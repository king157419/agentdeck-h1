"""Read-only Hub diagnostics; every external check can be substituted offline."""
import http.client
import json
import math
from pathlib import Path
import shlex
import subprocess
import sys
import time

import hub_install


RECENT_SECONDS = 600


def _get_json(path, port, token, connection_factory):
    connection = connection_factory("127.0.0.1", port, timeout=2)
    try:
        headers = {"X-AgentDeck-Token": token} if token else {}
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("HTTP %s" % response.status)
        result = json.loads(response.read(1024 * 1024))
        if not isinstance(result, dict):
            raise ValueError("response is not an object")
        return result
    finally:
        connection.close()


def _has_relay(path, agent):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    if not isinstance(hooks, dict):
        return False
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            entries = group.get("hooks", []) if isinstance(group, dict) else []
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if hub_install.is_ours(entry):
                    parts = [part.strip('"') for part in shlex.split(entry["command"], posix=False)]
                    if parts[3] == agent:
                        return True
    return False


def _logged_in(result):
    if result.returncode != 0:
        return False
    try:
        data = json.loads(result.stdout)
    except (TypeError, ValueError):
        # Older CLI versions may print a human-readable status instead of JSON.
        text = (result.stdout or "").strip().casefold()
        return text.startswith("logged in as ") or text.startswith("logged in using ")
    return isinstance(data, dict) and data.get("loggedIn") is True


def doctor(*, port=47800, home=None, stdout=None, connection_factory=None,
           runner=None, wall_time=None):
    """Print seven checks and return 0 if healthy, otherwise 1; never repair."""
    home = Path.home() if home is None else Path(home)
    if stdout is None:
        stdout = sys.stdout
        if hasattr(stdout, "reconfigure"):
            stdout.reconfigure(encoding="utf-8")
    connection_factory = http.client.HTTPConnection if connection_factory is None else connection_factory
    runner = subprocess.run if runner is None else runner
    now = time.time() if wall_time is None else wall_time()
    failures = 0

    def check(label, success, detail=""):
        nonlocal failures
        failures += not success
        stdout.write("%s %s%s\n" % ("✓" if success else "✗", label,
                                   ": " + detail if detail else ""))

    try:
        health = _get_json("/health", port, None, connection_factory)
        running = health.get("ok") is True
    except (OSError, ValueError, http.client.HTTPException):
        running = False
    check("Hub /health", running,
          "http://127.0.0.1:%s" % port if running else
          "start python pc/hub.py --backend none --port %s" % port)

    path = home / ".agentdeck" / "token"
    try:
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        token = ""
    check("Token file", bool(token), str(path) if token else
          "start Hub to create a nonempty token at %s" % path)

    for agent, folders in hub_install.TARGETS.items():
        path = home.joinpath(*folders)
        try:
            present = _has_relay(path, agent)
        except (OSError, ValueError, UnicodeError):
            present = False
        check("%s hub_relay hook" % agent, present, str(path) if present else
              "check %s; run python pc/hub_install.py install %s" % (path, agent))

    seen = {}
    if running and token:
        try:
            seen = _get_json("/state", port, token, connection_factory).get("agents_seen", {})
            if not isinstance(seen, dict):
                seen = {}
        except (OSError, ValueError, http.client.HTTPException):
            pass
    for agent in ("cc", "cx"):
        stamp = seen.get(agent)
        recent = (isinstance(stamp, (int, float)) and not isinstance(stamp, bool)
                  and math.isfinite(stamp) and 0 <= now - stamp <= RECENT_SECONDS)
        advice = ("trigger a Claude Code event and check the relay/Hub token" if agent == "cc" else
                  "在 Codex 里输入 /hooks 信任 AgentDeck 钩子")
        check("%s event in last 10 minutes" % agent, recent,
              "last event %.0fs ago" % (now - stamp) if recent else
              advice + "; ensure Hub is running and /state accepts the token")

    try:
        result = runner(["claude", "auth", "status"], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=5, check=False)
        authenticated = _logged_in(result)
    except (OSError, subprocess.SubprocessError, ValueError):
        authenticated = False
    check("Claude login", authenticated, "logged in" if authenticated else "运行 claude 登录")
    return 1 if failures else 0
