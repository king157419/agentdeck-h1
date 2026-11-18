"""Append/remove AgentDeck relay hooks while preserving all existing integrations.

Schema: https://learn.chatgpt.com/docs/hooks and raw-tech.md sections 1.2/1.4.
Run with --dry-run to inspect unified diffs without creating directories/files.
"""
import argparse
import copy
from datetime import datetime
import difflib
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile


SCRIPT = Path(__file__).with_name("hub_relay.py").resolve().as_posix()
COMMON_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                 "PermissionRequest", "Stop", "SessionEnd")
EVENTS = {"cc": COMMON_EVENTS + ("Notification", "PostToolUseFailure"),
          "cx": COMMON_EVENTS + ("Interrupt",)}
TARGETS = {"cc": (".claude", "settings.json"), "cx": (".codex", "hooks.json")}


def validate_options(port, approve_timeout):
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer from 1 to 65535")
    if (isinstance(approve_timeout, bool) or not isinstance(approve_timeout, (int, float))
            or not math.isfinite(approve_timeout) or approve_timeout <= 0):
        raise ValueError("approve timeout must be positive and finite")


def command(agent, *, port=47800, approve_timeout=110, gate=False, python=None):
    validate_options(port, approve_timeout)
    executable = sys.executable if python is None else os.fspath(python)
    if not isinstance(executable, str) or not executable.strip() or "\0" in executable:
        raise ValueError("python executable must be a nonempty path without NUL characters")
    args = [executable, SCRIPT, "--agent", agent]
    if port != 47800:
        args.extend(("--port", str(port)))
    if approve_timeout != 110:
        args.extend(("--approve-timeout", str(approve_timeout)))
    if gate:
        args.append("--gate")
    return subprocess.list2cmdline(args) if sys.platform == "win32" else shlex.join(args)


def split_command(text):
    """Read the quoting used by hooks on the current platform."""
    if sys.platform == "win32":
        return [part.strip('"') for part in shlex.split(text, posix=False)]
    return shlex.split(text)


def is_ours(entry):
    """Recognize the executed relay script, never incidental text in other hooks."""
    if not isinstance(entry, dict) or entry.get("type") != "command":
        return False
    try:
        parts = split_command(entry.get("command", ""))
    except (TypeError, ValueError):
        return False
    return (len(parts) >= 4 and parts[1].replace("\\", "/").casefold() == SCRIPT.casefold()
            and parts[2] == "--agent" and parts[3] in EVENTS)


def is_gate(entry):
    return is_ours(entry) and "--gate" in split_command(entry["command"])


def updated(data, action, agent, *, port=47800, approve_timeout=110, gate=False, python=None):
    """Return a modified copy; retain foreign hooks, groups, and settings verbatim."""
    result = copy.deepcopy(data)
    if not isinstance(result, dict):
        raise ValueError("hook configuration must be a JSON object")
    if "hooks" not in result:
        if action == "uninstall":
            return result
        result["hooks"] = {}
    hooks = result["hooks"]
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be an object")
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            raise ValueError("event hooks must be lists")
        kept = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ValueError("each matcher group must contain a hooks list")
            own = [entry for entry in group["hooks"] if is_ours(entry)]
            if action == "uninstall" and own:
                group["hooks"] = [entry for entry in group["hooks"] if not is_ours(entry)]
                if not group["hooks"]:
                    continue
            kept.append(group)
        if action == "uninstall" and not kept and groups:
            del hooks[event]
        else:
            hooks[event] = kept
    if action == "install":
        for event in EVENTS[agent]:
            groups = hooks.setdefault(event, [])
            entry = {"type": "command", "command": command(agent, port=port,
                                                          approve_timeout=approve_timeout, python=python),
                     "timeout": 120 if event == "PermissionRequest" else 10}
            own = [handler for group in groups for handler in group["hooks"]
                   if is_ours(handler) and not is_gate(handler)]
            if own:
                for handler in own:
                    handler.update(entry)
            else:
                groups.append({"hooks": [entry]})
        groups = hooks["PreToolUse"]
        own_gates = [handler for group in groups for handler in group["hooks"] if is_gate(handler)]
        # Reinstalling regular hooks preserves an explicitly installed gate.
        if gate or own_gates:
            entry = {"type": "command", "command": command(agent, port=port,
                     approve_timeout=approve_timeout, gate=True, python=python), "timeout": 120}
            if own_gates:
                for handler in own_gates:
                    handler.update(entry)
            else:
                group = {"hooks": [entry]}
                if agent == "cc":
                    group["matcher"] = "Bash|Edit|Write|mcp__.*"
                groups.append(group)
    elif action != "uninstall":
        raise ValueError("unknown action")
    if action == "uninstall" and not hooks and data.get("hooks"):
        result.pop("hooks")
    return result


def apply(action, *, home=None, agents=("cc", "cx"), dry_run=False, output=None,
          port=47800, approve_timeout=110, gate=False, python=None):
    """Prepare every config first, back up existing files, then atomically replace."""
    validate_options(port, approve_timeout)
    home = Path.home() if home is None else Path(home)
    output = sys.stdout if output is None else output
    plans = []
    for agent in agents:
        path = home.joinpath(*TARGETS[agent])
        before = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        data = json.loads(before) if before else {}
        after_data = updated(data, action, agent, port=port, approve_timeout=approve_timeout,
                             gate=gate, python=python)
        if after_data == data:
            continue
        after = json.dumps(after_data, indent=2, ensure_ascii=False) + "\n"
        plans.append((path, before, after))
    for path, before, after in plans:
        if dry_run:
            output.write("".join(difflib.unified_diff(before.splitlines(keepends=True),
                                                    after.splitlines(keepends=True),
                                                    fromfile=str(path), tofile=str(path))))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            shutil.copy2(path, str(path) + ".bak-agentdeck-" + stamp)
        descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".agentdeck-",
                                                 suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(after)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        output.write("%s: %s (%s)\n" % (agent_for_path(path), action, path))
    return [path for path, _, _ in plans]


def agent_for_path(path):
    return "cc" if path.parent.name == ".claude" else "cx"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("agents", nargs="*", choices=("cc", "cx", "codex"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--python", help="Python executable for relay hooks (default: current interpreter)")
    parser.add_argument("--port", type=int, default=47800)
    parser.add_argument("--approve-timeout", type=float, default=110)
    parser.add_argument("--gate", action="store_true", help="also install the blocking PreToolUse gate")
    args = parser.parse_args(argv)
    agents = tuple(dict.fromkeys("cx" if name == "codex" else name for name in args.agents))
    try:
        apply(args.action, home=args.home, agents=agents or ("cc", "cx"),
              dry_run=args.dry_run, port=args.port, approve_timeout=args.approve_timeout,
              gate=args.gate, python=args.python)
    except (OSError, ValueError) as error:
        print("AgentDeck hooks: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
