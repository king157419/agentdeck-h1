"""Read-only Hub diagnostics; every external check can be substituted offline."""
import http.client
import json
import logging
import math
from pathlib import Path
import subprocess
import sys
import time

import hub_install


RECENT_SECONDS = 600
log = logging.getLogger("agentdeck.hub.doctor")
MAC_PERMISSION_ADVICE = "系统设置 → 隐私与安全性 → 辅助功能 / 自动化 / 屏幕录制 / 输入监控"


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
                    parts = hub_install.split_command(entry["command"])
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
    """Print read-only checks (two extra on macOS); return 0 only if healthy."""
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
    if sys.platform == "darwin":
        stdout.write("macOS permissions: %s\n" % MAC_PERMISSION_ADVICE)
        stdout.write('macOS dictation requires dictation_shortcut in the Hub config: '
                     '{"key_codes": [49], "modifiers": ["control", "option"]}; '
                     'enable Dictation in System Settings → Keyboard and set the same '
                     'Control+Option+Space shortcut. Without this config, voice is unavailable.\n')
        probes = (("macOS osascript", "return 1", "1"),
                  ("macOS accessibility", 'tell application "System Events" to get UI elements enabled', "true"))
        permission_hint_logged = False
        for label, script, expected in probes:
            detail = ""
            try:
                result = runner(["osascript", "-e", script], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=3, check=False)
                success = result.returncode == 0 and result.stdout.strip().casefold() == expected
                if not success:
                    detail = (getattr(result, "stderr", "") or "probe returned %r" % result.stdout).strip()
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                success, detail = False, str(error)
            if not success:
                log.warning("%s probe failed: %s", label, detail)
                if not permission_hint_logged:
                    log.warning("macOS permissions: %s", MAC_PERMISSION_ADVICE)
                    permission_hint_logged = True
            check(label, success, "available" if success else
                  "%s; check osascript and grant permissions in %s" % (detail, MAC_PERMISSION_ADVICE))
    return 1 if failures else 0
