"""Regression tests for the 2026-11-19 field findings (H1-H7, F1, F6 wiring).

Only temporary homes, loopback HTTP and child processes of this interpreter are
real. Nothing touches ~/.claude, ~/.codex, the serial port or the keyboard.
"""
import http.client
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hub  # noqa: E402
import hub_doctor  # noqa: E402
import hub_install  # noqa: E402
import hub_relay  # noqa: E402

LONE = "\ud83d"  # half an emoji, as agents emit after cutting a string by UTF-16 units
PYTHON = sys.executable


class Desktop:
    def __init__(self, delay=0.0):
        self.calls = []
        self.voice_active = False
        self.delay = delay

    def focus(self, session, sessions):
        self.calls.append(("focus", session["session_id"]))
        time.sleep(self.delay)
        return (1, "app.exe", "project")

    def prompt(self, session, sessions, text):
        self.calls.append(("prompt", session["session_id"], text))
        time.sleep(self.delay)
        return True

    def close(self):
        pass


def make_hub(home, **options):
    options.setdefault("desktop", Desktop())
    return hub.Hub(sender=lambda *args, **kwargs: None, lcd_enabled=False,
                   hold_path=Path(home) / "hold", home=home, approve_timeout=5, **options)


def wait_for(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.01)


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.engine = make_hub(self.home)
        self.addCleanup(self.engine.close)
        self.token = hub.load_token(self.home)
        self.server = hub.HubServer(self.engine, self.token, 0)
        self.port = self.server.server_port
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, path, raw):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request("POST", path, body=raw, headers={
                "Content-Type": "application/json", "X-AgentDeck-Token": self.token})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def relay_main(self, payload, *args):
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        code = hub_relay.main(["--agent", "cc", "--home", str(self.home), "--port", str(self.port), *args],
                              stdin=io.BytesIO(payload), stdout=stdout)
        stdout.flush()
        return code, stdout.buffer.getvalue()


class SurrogateTests(ServerCase):
    """H3: lone surrogates must neither crash the relay nor the hub."""

    def test_relay_forwards_permission_with_lone_surrogate_and_chinese(self):
        payload = ('{"hook_event_name":"PermissionRequest","session_id":"s1","cwd":"D:/项目/后面",'
                   '"tool_name":"Bash","tool_input":{"command":"echo 找不到后面的文件 \\ud83d"}}').encode("utf-8")
        result = []
        worker = threading.Thread(target=lambda: result.append(self.relay_main(payload)))
        worker.start()
        wait_for(lambda: self.engine.state()["pending"])
        state = self.engine.state()
        self.assertIn("\ufffd", state["pending"][0]["summary"])
        self.assertEqual(state["sessions"][0]["cwd"], "D:/项目/后面")
        time.sleep(0.35)  # switch guard
        self.assertEqual(self.engine.action({"action": "approve"})["status"], "allowed")
        worker.join(5)
        code, output = result[0]
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["hookSpecificOutput"]["decision"], {"behavior": "allow"})
        records = self.engine.audit.recent(5)
        self.assertEqual(records[-1]["decision"], "allow")

    def test_ordinary_event_with_cut_emoji_and_huge_output_reaches_hub(self):
        event = {"hook_event_name": "PostToolUse", "session_id": "s2", "cwd": "D:/面板",
                 "tool_name": "Bash", "tool_input": {"command": "type 大文件.txt"},
                 "tool_response": {"stdout": "后" * 700_000 + LONE}}
        payload = json.dumps(event, ensure_ascii=False).encode("utf-8", "surrogatepass")
        self.assertGreater(len(payload), 2 * 1024 * 1024)
        code, output = self.relay_main(payload)
        self.assertEqual((code, json.loads(output)), (0, {}))
        self.assertEqual(self.engine.state()["sessions"][0]["cwd"], "D:/面板")

    def test_hub_accepts_lone_surrogate_posted_directly(self):
        raw = ('{"hook_event_name":"PermissionRequest","session_id":"s3","tool_name":"Bash",'
               '"tool_input":{"command":"rm x \\ud83d"}}').encode("ascii")
        result = []
        worker = threading.Thread(target=lambda: result.append(self.post("/event?agent=cc", raw)))
        worker.start()
        wait_for(lambda: self.engine.state()["pending"])
        self.assertEqual(self.engine.action({"action": "deny"})["status"], "denied")
        worker.join(5)
        self.assertEqual(result[0][0], 200)

    def test_hash_is_shared_and_ascii_safe(self):
        self.assertIs(hub.tool_input_hash, hub_relay.tool_input_hash)
        self.assertEqual(len(hub.tool_input_hash({"command": "x" + LONE})), 64)
        self.assertEqual(hub_relay.scrub_surrogates({"a": ["b" + LONE, "\ud83d\ude00"]}),
                         {"a": ["b\ufffd", "\U0001f600"]})


class AbandonTests(ServerCase):
    """H4: a request whose hook client is gone must not stay pending."""

    def test_killed_client_drops_pending_and_audits_abandoned(self):
        body = json.dumps({"hook_event_name": "PermissionRequest", "session_id": "gone",
                           "tool_name": "Bash", "tool_input": {"command": "echo hi"}}).encode()
        client = socket.create_connection(("127.0.0.1", self.port))
        client.sendall(b"POST /event?agent=cc HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                       b"X-AgentDeck-Token: " + self.token.encode() + b"\r\nContent-Length: "
                       + str(len(body)).encode() + b"\r\n\r\n" + body)
        wait_for(lambda: self.engine.state()["pending"])
        client.close()
        started = time.monotonic()
        wait_for(lambda: not self.engine.state()["pending"], timeout=2)
        self.assertLess(time.monotonic() - started, 1.5)
        session = self.engine.state()["sessions"][0]
        self.assertNotEqual(session["state"], "wait")
        self.assertEqual(self.engine.audit.recent(1)[0]["decision"], "abandoned")
        self.assertEqual(self.engine.action({"action": "deny"})["status"], "no_request")


class MovedOnTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = make_hub(self.temp.name)
        self.addCleanup(self.engine.close)

    def permission(self, sid="s", command="echo 1", gate=False):
        result = []
        name = "PreToolUse" if gate else "PermissionRequest"
        worker = threading.Thread(target=lambda: result.append(self.engine.event(
            "cc", {"hook_event_name": name, "session_id": sid, "tool_name": "Bash",
                   "tool_input": {"command": command}}, gate=gate)), daemon=True)
        worker.start()
        wait_for(lambda: any(p["session_id"] == sid for p in self.engine.state()["pending"]))
        return worker, result

    def event(self, name, sid="s", **fields):
        return self.engine.event("cc", dict(hook_event_name=name, session_id=sid, **fields))

    def test_same_subagent_progress_or_new_prompt_clears_pending(self):
        for name in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
            with self.subTest(event=name):
                worker, result = self.permission(command="echo 1")
                # Tool identity/input may differ after the native permission UI.
                self.event(name, tool_name="Read", tool_input={"path": "other"})
                worker.join(2)
                self.assertEqual(result, [{}])
                self.assertEqual(self.engine.state()["pending"], [])
                self.assertEqual(self.engine.audit.recent(1)[0]["decision"], "abandoned")
        worker, result = self.permission(command="echo 2")
        self.event("UserPromptSubmit")
        worker.join(2)
        self.assertEqual(result, [{}])

    def test_gate_requests_are_not_cleared_by_telemetry(self):
        worker, result = self.permission(command="git push --force origin main", gate=True)
        self.event("PreToolUse", tool_name="Bash", tool_input={"command": "git push --force origin main"})
        self.event("UserPromptSubmit")
        self.assertEqual(len(self.engine.state()["pending"]), 1)
        self.engine.action({"action": "deny"})
        worker.join(2)


class LockTests(unittest.TestCase):
    """H5: desktop effects run without the Hub lock."""

    def test_events_are_not_blocked_by_slow_focus_or_prompt(self):
        with tempfile.TemporaryDirectory() as home:
            desktop = Desktop(delay=1.0)
            engine = make_hub(home, desktop=desktop, prompts={"tests": "跑测试"})
            self.addCleanup(engine.close)
            engine.event("cc", {"hook_event_name": "SessionStart", "session_id": "a", "cwd": "D:/a"})
            for action in ("slot 1", "prompt tests"):
                with self.subTest(action=action):
                    worker = threading.Thread(target=engine.action, args=({"action": action},))
                    worker.start()
                    wait_for(lambda: len(desktop.calls) and desktop.calls[-1][0] in ("focus", "prompt"))
                    started = time.monotonic()
                    engine.event("cc", {"hook_event_name": "PreToolUse", "session_id": "b", "tool_name": "Read"})
                    self.assertLess(time.monotonic() - started, 0.3)
                    worker.join(3)
                    desktop.calls.clear()

    def test_deadline_counts_from_http_receipt(self):
        with tempfile.TemporaryDirectory() as home:
            engine = make_hub(home)
            self.addCleanup(engine.close)
            received = time.monotonic() - 4.0
            worker = threading.Thread(target=engine.event, args=("cc", {
                "hook_event_name": "PermissionRequest", "session_id": "late", "tool_name": "Bash",
                "tool_input": {"command": "echo"}}), kwargs={"received_at": received}, daemon=True)
            worker.start()
            wait_for(lambda: engine.pending)
            request = next(iter(engine.pending.values()))
            self.assertAlmostEqual(request.deadline, received + engine.approve_timeout, places=3)
            worker.join(3)
            self.assertFalse(engine.pending)

    def test_relay_read_timeout_uses_one_budget_from_hook_start(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("t", encoding="utf-8")
            connection = Mock()
            connection.getresponse.return_value = Mock(status=200, read=Mock(return_value=b"{}"))
            hub_relay.relay({"hook_event_name": "PermissionRequest"}, "cc", home=home,
                            connection_factory=lambda *args, **kwargs: connection,
                            started=time.monotonic() - 3)
            timeout = connection.sock.settimeout.call_args.args[0]
            self.assertLess(timeout, 112.1)
            self.assertGreater(timeout, 111.5)


class AnswerTests(unittest.TestCase):
    """H6: questions and plans go to the native UI; approve focuses that window."""

    def test_ask_user_question_is_native_and_approve_focuses(self):
        with tempfile.TemporaryDirectory() as home:
            desktop = Desktop()
            engine = make_hub(home, desktop=desktop)
            self.addCleanup(engine.close)
            started = time.monotonic()
            result = engine.event("cc", {"hook_event_name": "PermissionRequest", "session_id": "q",
                                         "cwd": "D:/demo", "tool_name": "AskUserQuestion",
                                         "tool_input": {"questions": [{"question": "选哪个？"}]}})
            self.assertEqual(result, {})
            self.assertLess(time.monotonic() - started, 0.5)
            state = engine.state()
            self.assertEqual(state["pending"], [])
            self.assertEqual(state["sessions"][0]["state"], "wait")
            self.assertEqual(state["sessions"][0]["needs_answer"], "AskUserQuestion")
            self.assertTrue(engine._display_label(engine.sessions[("cc", "q")]).startswith("ANSWER: "))
            reply = engine.action({"action": "approve"}, source="key")
            self.assertEqual((reply["status"], reply["slot"]), ("focus", 1))
            self.assertEqual(desktop.calls, [("focus", "q")])
            engine.event("cc", {"hook_event_name": "PostToolUse", "session_id": "q", "tool_name": "AskUserQuestion"})
            self.assertNotIn("needs_answer", engine.state()["sessions"][0])
            self.assertEqual(engine.action({"action": "approve"}, source="key")["status"], "no_request")


class FeedbackTests(unittest.TestCase):
    """F1: every key press is visible (state for the overlay, LCD for failures)."""

    def test_failed_and_successful_keys_publish_last_input(self):
        with tempfile.TemporaryDirectory() as home:
            lines = []
            engine = hub.Hub(sender=lambda batch, **kwargs: lines.extend(batch), desktop=Desktop(),
                             hold_path=Path(home) / "hold", home=home, focus_guard=lambda timeout: _Null())
            self.addCleanup(engine.close)
            keys = hub.USBKeys(engine, {"bindings": {"hid:0x08": "slot 1", "hid:0x05": "slot 2"}})
            keys._dispatch("hid:0x08", "slot 1", {}, engine.monotonic())
            last = engine.state()["last_input"]
            self.assertEqual((last["text"], last["ok"]), ("第 1 排第 1 颗 → 槽位 1 没有会话", False))
            engine.event("cc", {"hook_event_name": "SessionStart", "session_id": "a", "cwd": "D:/a"})
            keys._dispatch("hid:0x08", "slot 1", {}, engine.monotonic())
            self.assertEqual(engine.state()["last_input"]["text"], "第 1 排第 1 颗 → 已选槽位 1")
            keys._dispatch("hid:0x05", "slot 2", {}, engine.monotonic())
            self.assertTrue(any("KEY: Slot 2 empty" in line for line in lines))
            self.assertGreater(engine.state()["last_input"]["seq"], 2)

    def test_describe_input_texts(self):
        self.assertEqual(hub.describe_input("approve", {"status": "no_request"})[0], "没有待批请求")
        self.assertEqual(hub.describe_input("approve", error=hub.HubError("switch_guard"))[:2],
                         ("请求刚切换，稍后再按", False))
        self.assertEqual(hub.describe_input("slot 3", {"status": "selected", "slot": 3, "window": "x"})[0],
                         "已选槽位 3（没找到窗口）")

    def test_show_key_and_reader_mode_in_state(self):
        with tempfile.TemporaryDirectory() as home:
            engine = make_hub(home)
            self.addCleanup(engine.close)
            engine.input_reader = lambda: "raw"
            self.assertEqual(engine.state()["input_reader"], "raw")
            before = engine.state()["show_requests"]
            self.assertEqual(engine.action({"action": "show"})["status"], "shown")
            self.assertEqual(engine.state()["show_requests"], before + 1)


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class RelayStartTests(unittest.TestCase):
    """H7 and launch probes: fast exit when the hub is down, never exit code 2."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / ".agentdeck").mkdir()
        (self.home / ".agentdeck" / "token").write_text("t", encoding="utf-8")

    def dead_pid(self):
        process = subprocess.Popen([PYTHON, "-c", "pass"])
        process.wait(10)
        return process.pid

    def test_dead_hub_marker_skips_connect(self):
        (self.home / ".agentdeck" / "hub.json").write_text(
            json.dumps({"pid": self.dead_pid(), "port": 47999}), encoding="utf-8")
        self.assertEqual(hub_relay.hub_status(self.home, 47999), "down")
        event = {"hook_event_name": "PreToolUse", "session_id": "x", "tool_name": "Bash",
                 "tool_input": {"command": "git push --force origin main"}}
        with patch("http.client.HTTPConnection", side_effect=AssertionError("must not connect")):
            started = time.perf_counter()
            self.assertIsNone(hub_relay.relay(dict(event, hook_event_name="Stop"), "cc",
                                              port=47999, home=self.home))
            self.assertLess(time.perf_counter() - started, 0.2)
            denied = json.loads(hub_relay.relay(event, "cc", port=47999, home=self.home, gate=True))
            self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_marker_states(self):
        marker = self.home / ".agentdeck" / "hub.json"
        self.assertEqual(hub_relay.hub_status(self.home, 1), "unknown")
        marker.write_text(json.dumps({"pid": os.getpid(), "port": 5}), encoding="utf-8")
        self.assertEqual(hub_relay.hub_status(self.home, 5), "up")
        self.assertEqual(hub_relay.hub_status(self.home, 6), "unknown")
        path = hub.write_hub_marker(self.home, 4321)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"pid": os.getpid(), "port": 4321})
        hub.remove_hub_marker(path)
        self.assertFalse(path.exists())

    def test_closed_port_without_marker_returns_fast(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()
        started = time.perf_counter()
        self.assertIsNone(hub_relay.relay({"hook_event_name": "Stop", "session_id": "x"}, "cc",
                                          port=port, home=self.home))
        self.assertLess(time.perf_counter() - started, 0.5)  # was ~0.7 s (0.5 s connect timeout)

    def test_probe_and_bad_arguments_exit_zero_silently(self):
        for argv, stdin in ((["--agent", "cc", "--home", str(self.home)], b""),
                            (["--agent", "cc", "--home", str(self.home)], b"  \r\n"),
                            (["--bogus"], b"{}"), ([], b"{}")):
            with self.subTest(argv=argv, stdin=stdin):
                stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
                with patch("sys.stderr", io.StringIO()):
                    self.assertEqual(hub_relay.main(argv, stdin=io.BytesIO(stdin), stdout=stdout), 0)
                stdout.flush()
                self.assertEqual(stdout.buffer.getvalue(), b"")
        self.assertFalse((self.home / ".agentdeck" / "relay.log").exists())

    def test_ordinary_events_are_slimmed(self):
        connection = Mock()
        connection.getresponse.return_value = Mock(status=200, read=Mock(return_value=b"{}"))
        event = {"hook_event_name": "PostToolUse", "session_id": "x", "cwd": "D:/a", "tool_name": "Read",
                 "tool_input": {"file_path": "a"}, "tool_response": {"content": "x" * 3_000_000},
                 "transcript_path": "C:/t.jsonl"}
        hub_relay.relay(event, "cc", home=self.home, connection_factory=lambda *args, **kwargs: connection)
        body = json.loads(connection.request.call_args.kwargs["body"])
        self.assertEqual(body, {"hook_event_name": "PostToolUse", "session_id": "x", "cwd": "D:/a",
                                "tool_name": "Read", "transcript_path": "C:/t.jsonl",
                                "tool_input_hash": hub.tool_input_hash({"file_path": "a"})})


class InstallFormTests(unittest.TestCase):
    """H1: the bundled Claude relay hook uses exec form; Codex stays byte-identical."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.home.mkdir()
        self.exe = Path(self.temp.name) / "AgentDeck" / "AgentDeck.exe"
        self.exe.parent.mkdir()
        self.exe.with_name("AgentDeck-relay.exe").touch()

    def frozen(self):
        return patch.multiple(sys, frozen=True, executable=str(self.exe), create=True)

    def entries(self, agent):
        data = json.loads(self.home.joinpath(*hub_install.TARGETS[agent]).read_text(encoding="utf-8"))
        return [entry for groups in data["hooks"].values() for group in groups for entry in group["hooks"]]

    def test_frozen_install_writes_exec_form_for_cc_only(self):
        relay = self.exe.with_name("AgentDeck-relay.exe").resolve()
        with self.frozen():
            hub_install.apply("install", home=self.home, output=io.StringIO())
            for entry in self.entries("cc"):
                self.assertEqual(entry["command"], relay.as_posix())
                self.assertEqual(entry["args"], ["--agent", "cc"])
                self.assertNotIn("\\", entry["command"])
            for entry in self.entries("cx"):
                self.assertNotIn("args", entry)
                self.assertEqual(entry["command"], subprocess.list2cmdline([str(relay), "--agent", "cx"]))
            status = hub_install.global_status(home=self.home)
            self.assertEqual((status["enabled"], status["needs_repair"], status["shell_form"]), (True, False, False))
            self.assertEqual(hub_install.apply("install", home=self.home, output=io.StringIO()), [])

    def test_broken_shell_form_is_repaired_without_duplicates(self):
        relay = self.exe.with_name("AgentDeck-relay.exe").resolve()
        broken = {"type": "command", "command": "%s --agent cc" % relay, "timeout": 10}
        path = self.home.joinpath(*hub_install.TARGETS["cc"])
        path.parent.mkdir()
        path.write_text(json.dumps({"hooks": {event: [{"hooks": [dict(broken)]}]
                                              for event in hub_install.EVENTS["cc"]}}), encoding="utf-8")
        with self.frozen():
            hub_install.apply("install", home=self.home, agents=("cx",), output=io.StringIO())
            status = hub_install.global_status(home=self.home)
            self.assertTrue(status["needs_repair"])
            self.assertTrue(status["shell_form"])
            hub_install.apply("install", home=self.home, output=io.StringIO())
            entries = self.entries("cc")
            self.assertEqual(len(entries), len(hub_install.EVENTS["cc"]))
            self.assertTrue(all(entry.get("args") == ["--agent", "cc"] for entry in entries))
            self.assertFalse(hub_install.global_status(home=self.home)["needs_repair"])
            hub_install.apply("uninstall", home=self.home, output=io.StringIO())
            self.assertFalse(hub_install.global_status(home=self.home)["enabled"])

    @unittest.skipUnless(hub_doctor.git_bash(), "Git Bash not installed")
    def test_git_bash_eats_backslashes_but_exec_form_runs(self):
        bash = hub_doctor.git_bash()
        windows_path = str(Path(PYTHON).resolve())
        self.assertIn("\\", windows_path)
        shell = subprocess.run([bash, "-c", windows_path + " -c pass"], capture_output=True, timeout=30)
        self.assertEqual(shell.returncode, 127)
        exec_form = subprocess.run([Path(windows_path).as_posix(), "-c", "pass"], capture_output=True, timeout=30)
        self.assertEqual(exec_form.returncode, 0)

    def test_doctor_launch_probe_flags_exit_127_and_uses_exec_form(self):
        relay = self.exe.with_name("AgentDeck-relay.exe").resolve()
        path = self.home.joinpath(*hub_install.TARGETS["cc"])
        path.parent.mkdir()
        shell = {"type": "command", "command": "%s --agent cc" % relay}
        path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [shell]}]}}), encoding="utf-8")
        calls = []

        def runner(argv, **options):
            calls.append(argv)
            return Mock(returncode=127, stderr="command not found")

        result = hub_doctor.hook_launch(self.home, runner, bash="C:/Git/bin/bash.exe")
        self.assertFalse(result["ok"])
        self.assertIn("127", result["detail"])
        self.assertEqual(calls[-1], ["C:/Git/bin/bash.exe", "-c", shell["command"]])
        self.assertEqual(calls and runner.__name__, "runner")
        exec_entry = {"type": "command", "command": relay.as_posix(), "args": ["--agent", "cc"]}
        path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [exec_entry]}]}}), encoding="utf-8")
        result = hub_doctor.hook_launch(self.home, lambda argv, **options: calls.append(argv) or Mock(returncode=0))
        self.assertTrue(result["ok"])
        self.assertEqual(calls[-1], [relay.as_posix(), "--agent", "cc"])

    def test_launch_probe_runs_real_source_relay_with_empty_stdin(self):
        path = self.home.joinpath(*hub_install.TARGETS["cc"])
        path.parent.mkdir()
        entry = {"type": "command", "command": Path(PYTHON).as_posix(),
                 "args": [str(Path(hub_relay.__file__).resolve()), "--agent", "cc", "--home", str(self.home)]}
        path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [entry]}]}}), encoding="utf-8")
        result = hub_doctor.hook_launch(self.home, subprocess.run)
        self.assertTrue(result["ok"], result)
        self.assertFalse((self.home / ".agentdeck" / "relay.log").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
