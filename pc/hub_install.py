"""Append/remove AgentDeck relay hooks while preserving all existing integrations.

Schema: https://learn.chatgpt.com/docs/hooks and raw-tech.md sections 1.2/1.4.
Run with --dry-run to inspect unified diffs without creating directories/files.
Use --project DIR to manage only that directory's local hook configuration.
"""
import argparse
import copy
from datetime import datetime
import difflib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


PYTHON = "D:/conda/miniconda3/python.exe"
SCRIPT = Path(__file__).with_name("hub_relay.py").resolve().as_posix()
COMMON_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                 "PermissionRequest", "Stop", "SessionEnd")
EVENTS = {"cc": COMMON_EVENTS + ("Notification", "PostToolUseFailure"),
          "cx": COMMON_EVENTS + ("Interrupt",)}
TARGETS = {"cc": (".claude", "settings.json"), "cx": (".codex", "hooks.json")}
PROJECT_TARGETS = {"cc": (".claude", "settings.local.json"), "cx": (".codex", "hooks.json")}
CODEX_PROJECT_MATCHER = "Bash|apply_patch|Edit|Write|mcp__.*"


def validate_options(port, approve_timeout):
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer from 1 to 65535")
    if (isinstance(approve_timeout, bool) or not isinstance(approve_timeout, (int, float))
            or not math.isfinite(approve_timeout) or approve_timeout <= 0):
        raise ValueError("approve timeout must be positive and finite")


def command(agent, *, port=47800, approve_timeout=110, gate=False, python=None, project=False):
    validate_options(port, approve_timeout)
    if getattr(sys, "frozen", False):
        # The bundled relay shares the application's onedir, not its _internal directory.
        args = [str(Path(sys.executable).resolve().with_name("AgentDeck-relay.exe")), "--agent", agent]
    else:
        args = _source_command(agent, python=python, project=project)
    if port != 47800:
        args.extend(("--port", str(port)))
    if approve_timeout != 110:
        args.extend(("--approve-timeout", str(approve_timeout)))
    if gate:
        args.append("--gate")
    return subprocess.list2cmdline(args) if sys.platform == "win32" else shlex.join(args)


def _source_command(agent, *, python=None, project=False):
    # Keep existing Windows global hooks stable across interpreter changes.
    default_python = PYTHON if sys.platform == "win32" and not project else sys.executable
    executable = default_python if python is None else os.fspath(python)
    if not isinstance(executable, str) or not executable.strip() or "\0" in executable:
        raise ValueError("python executable must be a nonempty path without NUL characters")
    if project:
        executable = Path(executable).resolve().as_posix()
    elif sys.platform == "win32":
        executable = Path(executable).as_posix()
    return [executable, SCRIPT, "--agent", agent]


def split_command(text):
    """Read the quoting used by hooks on the current platform."""
    if sys.platform == "win32":
        return [part.strip('"') for part in shlex.split(text, posix=False)]
    return shlex.split(text)


def relay_info(entry):
    """Identify an executed relay, including old locations after a folder move."""
    if not isinstance(entry, dict) or entry.get("type") != "command":
        return None
    try:
        parts = split_command(entry.get("command", ""))
    except (TypeError, ValueError):
        return None
    basename = lambda path: path.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if len(parts) >= 3 and basename(parts[0]) == "agentdeck-relay.exe" and parts[1] == "--agent":
        return {"agent": parts[2], "paths": [parts[0]]} if parts[2] in EVENTS else None
    if (len(parts) >= 4 and basename(parts[1]) == "hub_relay.py"
            and parts[2] == "--agent" and parts[3] in EVENTS
            and (parts[1].replace("\\", "/").casefold() == SCRIPT.casefold()
                 or re.fullmatch(r"python(?:w|[23](?:\.\d+)?)?(?:\.exe)?", basename(parts[0])))):
        return {"agent": parts[3], "paths": parts[:2]}
    return None


def is_ours(entry):
    """Recognize the executed relay, never incidental text in other hooks."""
    return relay_info(entry) is not None


def is_gate(entry):
    return is_ours(entry) and "--gate" in split_command(entry["command"])


def is_legacy(entry):
    """Only the old Python LCD hook invocation, not mentions inside another hook."""
    if not isinstance(entry, dict) or entry.get("type") != "command":
        return False
    if "args" in entry:
        # The original Claude installer writes an executable and argv separately;
        # its unquoted executable can legitimately contain spaces.
        args = entry["args"]
        command = entry.get("command")
        if (not isinstance(command, str) or not isinstance(args, list)
                or any(not isinstance(arg, str) for arg in args)):
            return False
        parts = [command, *args]
    else:
        try:
            parts = split_command(entry.get("command", ""))
        except (TypeError, ValueError):
            return False
    name = lambda value: value.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return (len(parts) >= 4 and re.fullmatch(r"python(?:w|[23](?:\.\d+)?)?(?:\.exe)?", name(parts[0]))
            is not None and name(parts[1]) == "agent_lcd.py" and parts[2] == "hook"
            and parts[3] in ("cc", "cx", "ds"))


def remove_legacy_hooks(*, home=None, confirmed=False):
    """Explicit user action only: back up each changed global file before replacing it."""
    if confirmed is not True:
        raise ValueError("removing legacy hooks requires explicit confirmation")
    root = Path.home() if home is None else Path(home)
    plans = []
    for folders in TARGETS.values():
        path = root.joinpath(*folders)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        after = copy.deepcopy(data)
        if not isinstance(after, dict) or not isinstance(after.get("hooks", {}), dict):
            raise ValueError("hook configuration must contain an object")
        hooks = after.get("hooks", {})
        for event, groups in list(hooks.items()):
            if not isinstance(groups, list):
                raise ValueError("event hooks must be lists")
            kept = []
            for group in groups:
                if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                    raise ValueError("each matcher group must contain a hooks list")
                entries = group["hooks"]
                remaining = [entry for entry in entries if not is_legacy(entry)]
                if remaining != entries:
                    group["hooks"] = remaining
                    if not remaining:
                        continue
                kept.append(group)
            if kept != groups:
                if kept:
                    hooks[event] = kept
                else:
                    del hooks[event]
        if after != data:
            plans.append((path, json.dumps(after, ensure_ascii=False, indent=2) + "\n"))
    # Prepare and validate every config before touching either one.
    for path, _ in plans:
        shutil.copy2(path, str(path) + ".bak-agentdeck-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    for path, content in plans:
        descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".agentdeck-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return [path for path, _ in plans]


def updated(data, action, agent, *, port=47800, approve_timeout=110, gate=False,
            python=None, project=False):
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
                     approve_timeout=approve_timeout, python=python, project=project),
                     "timeout": 120 if event == "PermissionRequest" else 10}
            own = [handler for group in groups for handler in group["hooks"]
                   if is_ours(handler) and not is_gate(handler)]
            if own:
                for handler in own:
                    handler.update(entry)
            else:
                groups.append({"hooks": [entry]})
        groups = hooks["PreToolUse"]
        if project and agent == "cx":
            for group in list(groups):
                gates = [handler for handler in group["hooks"] if is_gate(handler)]
                if not gates or group.get("matcher") == CODEX_PROJECT_MATCHER:
                    continue
                # Give our gate its matcher without changing a foreign handler's scope.
                if len(gates) < len(group["hooks"]):
                    group["hooks"] = [handler for handler in group["hooks"] if not is_gate(handler)]
                    gate_group = {**group, "hooks": gates, "matcher": CODEX_PROJECT_MATCHER}
                    groups.append(gate_group)
                else:
                    group["matcher"] = CODEX_PROJECT_MATCHER
        own_gates = [handler for group in groups for handler in group["hooks"] if is_gate(handler)]
        # Reinstalling regular hooks preserves an explicitly installed gate.
        if gate or own_gates:
            entry = {"type": "command", "command": command(agent, port=port,
                     approve_timeout=approve_timeout, gate=True, python=python,
                     project=project), "timeout": 120}
            if own_gates:
                for handler in own_gates:
                    handler.update(entry)
            else:
                group = {"hooks": [entry]}
                if agent == "cc":
                    group["matcher"] = "Bash|Edit|Write|mcp__.*"
                elif project:
                    group["matcher"] = CODEX_PROJECT_MATCHER
                groups.append(group)
    elif action != "uninstall":
        raise ValueError("unknown action")
    if action == "uninstall" and not hooks and data.get("hooks"):
        result.pop("hooks")
    return result


def apply(action, *, home=None, agents=("cc", "cx"), dry_run=False, output=None,
          port=47800, approve_timeout=110, gate=False, python=None, project=None):
    """Prepare every config first, back up existing files, then atomically replace."""
    validate_options(port, approve_timeout)
    if project is None:
        root = Path.home() if home is None else Path(home)
        targets = TARGETS
    else:
        root = Path(project).resolve()
        targets = PROJECT_TARGETS
        agents = tuple(dict.fromkeys("cx" if agent == "codex" else agent for agent in agents))
    output = sys.stdout if output is None else output
    plans = []
    for agent in agents:
        path = root.joinpath(*targets[agent])
        if project is not None and not path.resolve().is_relative_to(root):
            raise ValueError("project hook configuration points outside project directory: %s" % path)
        exists = path.exists()
        before = path.read_text(encoding="utf-8-sig") if exists else ""
        data = json.loads(before) if before or (project is not None and exists) else {}
        after_data = updated(data, action, agent, port=port, approve_timeout=approve_timeout,
                             gate=gate, python=python, project=project is not None)
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
    if project is not None and not dry_run:
        if not (root / ".git").exists():
            output.write("Warning: %s has no .git; Codex uses .git to find the project root "
                         "and may ignore .codex/hooks.json. Run git init there if appropriate.\n" % root)
        if action == "install":
            output.write("Next steps: restart open sessions in %s.\n" % root)
            if "cc" in agents:
                output.write("Start claude in %s and accept directory trust.\n" % root)
            if "cx" in agents:
                output.write("Start codex in %s, trust the directory, then run /hooks to review "
                             "and approve the hooks; approve again after changing hook options.\n" % root)
            if getattr(sys, "frozen", False):
                output.write("卸载：在 AgentDeck 托盘选择“从项目卸载…”，再选择 %s。\n" % root)
            else:
                rollback = [Path(sys.executable).resolve().as_posix(),
                            Path(__file__).resolve().as_posix(), "uninstall", *agents,
                            "--project", str(root)]
                output.write("Rollback: " + (subprocess.list2cmdline(rollback)
                             if sys.platform == "win32" else shlex.join(rollback)) + "\n")
    return [path for path, _, _ in plans]


def agent_for_path(path):
    return "cc" if path.parent.name == ".claude" else "cx"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("agents", nargs="*", choices=("cc", "cx", "codex"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--project", type=Path, help="manage only DIR's project hooks; ignores --home",
                        metavar="DIR")
    parser.add_argument("--python", help="Python executable for relay hooks (default: current interpreter; "
                        "Windows global hooks retain D:/conda/miniconda3/python.exe)")
    parser.add_argument("--port", type=int, default=47800)
    parser.add_argument("--approve-timeout", type=float, default=110)
    parser.add_argument("--gate", action="store_true", help="also install the blocking PreToolUse gate")
    args = parser.parse_args(argv)
    agents = tuple(dict.fromkeys("cx" if name == "codex" else name for name in args.agents))
    try:
        apply(args.action, home=args.home, agents=agents or ("cc", "cx"),
              dry_run=args.dry_run, port=args.port, approve_timeout=args.approve_timeout,
              gate=args.gate, python=args.python, project=args.project)
    except (OSError, ValueError) as error:
        print("AgentDeck hooks: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
