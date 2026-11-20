"""End-to-end relay check through the exact installed hook entries (replaces the
old ASCII-only, Python-pipe-only version that missed the UTF-8 and Git Bash bugs).

A temporary Hub runs in this process on a random port with a temporary home;
the relay child gets USERPROFILE/HOME pointing there, so the real ~/.agentdeck,
~/.claude and ~/.codex are never read or written. Payload files contain Chinese
(后面/面板), an emoji, a lone UTF-16 surrogate, Windows paths and a body over 1 MiB.

Modes per payload:
  cc-exec   Claude exec form (command + args, no shell) - what the installer writes
  cc-bash   Git Bash `cat payload | <command>` with the same command as one string
  cx-cmd    Codex command string through `cmd /c`
  cx-ps     Codex command string through `powershell -Command`

  python research/e2e_exe.py            # the built dist/AgentDeck/AgentDeck-relay.exe
  python research/e2e_exe.py --source   # python pc/hub_relay.py (before building)

Prints a PASS/FAIL table; exit code 1 on any failure.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pc"))

import hub  # noqa: E402
import hub_doctor  # noqa: E402
import hub_install  # noqa: E402

DIST = ROOT / "dist" / "AgentDeck" / "AgentDeck.exe"


def payloads(folder):
    long_chinese = "面板后面的文件找不到。" * 6000  # ~60 KB of Chinese text
    items = {
        "permission": {"hook_event_name": "PermissionRequest", "session_id": "e2e-perm",
                       "cwd": "D:\\工作\\后面的项目", "tool_name": "Bash",
                       "tool_input": {"command": "type \"C:\\Users\\用户\\面板.txt\" 😀"}},
        "lone-surrogate": None,  # written by hand below: JSON.stringify of a cut emoji
        "stop-60k": {"hook_event_name": "Stop", "session_id": "e2e-stop", "cwd": "D:\\面板",
                     "last_assistant_message": long_chinese},
        "post-1mib": {"hook_event_name": "PostToolUse", "session_id": "e2e-big", "cwd": "D:/w",
                      "tool_name": "Read", "tool_input": {"file_path": "C:\\大\\文件.log"},
                      "tool_response": {"content": "后" * 450_000}},
        "notification": {"hook_event_name": "Notification", "session_id": "e2e-note", "cwd": "D:/w",
                         "notification_type": "idle_prompt", "message": "Claude 在等你回答：后面怎么办？"},
    }
    paths = {}
    for name, event in items.items():
        path = folder / (name + ".json")
        if event is None:
            path.write_bytes(('{"hook_event_name":"PostToolUse","session_id":"e2e-cut","cwd":"D:/w",'
                              '"tool_name":"Bash","tool_input":{"command":"echo"},'
                              '"tool_response":{"stdout":"截断的表情 \\ud83d"}}').encode("utf-8"))
        else:
            path.write_bytes(json.dumps(event, ensure_ascii=False).encode("utf-8"))
        paths[name] = path
    assert paths["post-1mib"].stat().st_size > 1024 * 1024
    return paths


def entries(port, source):
    """The cc entry and cx command the installer writes, but pointed at our port."""
    if source:
        with patch.object(hub_install.sys, "platform", "win32"):
            cc = hub_install.hook_fields("cc", port=port, python=sys.executable, project=True)
            cx = hub_install.command("cx", port=port, python=sys.executable, project=True)
        cc = {"command": hub_install.split_command(cc["command"])[0],
              "args": hub_install.split_command(cc["command"])[1:]}
    else:
        with patch.multiple(sys, frozen=True, executable=str(DIST), create=True):
            cc = hub_install.hook_fields("cc", port=port)
            cx = hub_install.command("cx", port=port)
    return cc, cx


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", action="store_true", help="test pc/hub_relay.py instead of the exe")
    args = parser.parse_args(argv)
    if not args.source and not DIST.with_name("AgentDeck-relay.exe").exists():
        print("missing %s; run build_exe.bat or use --source" % DIST.with_name("AgentDeck-relay.exe"))
        return 2
    bash = hub_doctor.git_bash()
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory) / "home"
        (home / ".agentdeck").mkdir(parents=True)
        engine = hub.Hub(sender=lambda *a, **k: None, lcd_enabled=False, desktop_enabled=False,
                         home=home, hold_path=home / "hold", approve_timeout=20)
        statuses = []
        original_reply = hub.HubHandler._reply

        def reply(handler, status, body):
            if handler.path.startswith("/event"):
                statuses.append(status)
            return original_reply(handler, status, body)

        server = hub.HubServer(engine, hub.load_token(home), 0)
        port = server.server_port
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        env = dict(os.environ, USERPROFILE=str(home), HOME=str(home))
        files = payloads(Path(directory))
        cc, cx = entries(port, args.source)
        cc_string = subprocess.list2cmdline([cc["command"], *cc["args"]])
        modes = {"cc-exec": lambda path: ([cc["command"], *cc["args"]], path),
                 "cx-cmd": lambda path: (["cmd.exe", "/d", "/c", cx], path),
                 "cx-ps": lambda path: (["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cx], path)}
        if bash:
            modes["cc-bash"] = lambda path: ([bash, "-c", "cat '%s' | %s" % (Path(path).as_posix(), cc_string)], None)
        rows, failures = [], 0
        log = home / ".agentdeck" / "relay.log"
        with patch.object(hub.HubHandler, "_reply", reply):
            for mode, build in modes.items():
                for name, path in files.items():
                    command, stdin_path = build(path)
                    before = len(statuses)
                    log_before = log.stat().st_size if log.exists() else 0
                    approver = None
                    if name == "permission":
                        def approve():
                            deadline = time.monotonic() + 15
                            while not engine.state()["pending"] and time.monotonic() < deadline:
                                time.sleep(0.05)
                            time.sleep(0.35)  # switch guard
                            try:
                                engine.action({"action": "approve"})
                            except hub.HubError:
                                pass
                        approver = threading.Thread(target=approve, daemon=True)
                        approver.start()
                    started = time.monotonic()
                    stdin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
                    try:
                        process = subprocess.run(command, stdin=stdin, capture_output=True, env=env, timeout=60)
                    finally:
                        if stdin_path:
                            stdin.close()
                    elapsed = time.monotonic() - started
                    if approver is not None:
                        approver.join(20)
                    http = statuses[before:]
                    out = process.stdout.strip()
                    try:
                        decoded = json.loads(out) if out else None
                    except ValueError:
                        decoded = None
                    if name == "permission":
                        ok = (decoded or {}).get("hookSpecificOutput", {}).get("decision") == {"behavior": "allow"}
                    else:
                        ok = decoded == {}
                    ok = ok and process.returncode == 0 and http == [200]
                    grew = (log.stat().st_size if log.exists() else 0) > log_before
                    if grew:
                        ok = False
                    failures += not ok
                    rows.append((mode, name, "PASS" if ok else "FAIL", process.returncode, http,
                                 "%.2fs" % elapsed, (out[:60] or process.stderr.strip()[:60]).decode("utf-8", "replace"),
                                 "relay.log" if grew else ""))
        server.shutdown()
        server.server_close()
        engine.close()
        tail = log.read_text(encoding="utf-8", errors="replace")[-600:] if log.exists() else ""
    print("relay: %s" % ("source pc/hub_relay.py" if args.source else DIST.with_name("AgentDeck-relay.exe")))
    print("%-8s %-15s %-4s %3s %-7s %-6s %s" % ("mode", "payload", "res", "rc", "http", "time", "stdout/stderr"))
    for row in rows:
        print("%-8s %-15s %-4s %3s %-7s %-6s %s %s" % (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7]))
    if tail:
        print("relay.log tail:\n" + tail)
    if not bash:
        print("Git Bash not found: cc-bash skipped")
    print("%d/%d passed" % (len(rows) - failures, len(rows)))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
