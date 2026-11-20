"""Hold/passthrough regression tests; only temporary files and loopback are real."""
from contextlib import nullcontext
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

import hub


class Clock:
    def __init__(self, value=100000.0):
        self.value = value

    def __call__(self):
        return self.value


class HoldCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hub-hold-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.clock = Clock()
        self.lines = []
        self.engine = self.make_hub()

    def make_hub(self, **options):
        defaults = dict(home=self.home, monotonic=self.clock, wall_time=self.clock,
                        sender=lambda lines, **kwargs: self.lines.extend(lines),
                        focus_guard=lambda **kwargs: nullcontext(), hold_path=self.home / "hold",
                        desktop_enabled=False, lcd_enabled=False, approve_timeout=10)
        defaults.update(options)
        engine = hub.Hub(**defaults)
        self.addCleanup(engine.close)
        return engine

    def event(self, name, sid="hold-session", *, engine=None, gate=False, **fields):
        return (engine or self.engine).event("cc", dict(
            hook_event_name=name, session_id=sid, cwd="C:/work/project", **fields), gate=gate)

    def session(self, sid="hold-session", engine=None):
        return (engine or self.engine).sessions[("cc", sid)]

    def wait_for(self, condition, timeout=2):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() >= deadline:
                self.fail("background request did not reach the expected state")
            time.sleep(0.002)

    def pending(self, sid="hold-session", *, agent_id="", gate=False, command="echo ok"):
        before = set(self.engine.pending)
        results, errors = [], []

        def run():
            try:
                results.append(self.event("PreToolUse" if gate else "PermissionRequest", sid,
                                          gate=gate, agent_id=agent_id, tool_name="Bash",
                                          tool_input={"command": command}))
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(lambda: thread.join(2))
        self.addCleanup(self.engine.close)
        self.wait_for(lambda: set(self.engine.pending) - before or errors)
        self.assertEqual(errors, [])
        request_id = next(iter(set(self.engine.pending) - before))
        return self.engine.pending[request_id], thread, results


class HoldTests(HoldCase):
    def test_reader_presence_and_hold_modes(self):
        self.assertEqual(self.engine.hold_mode, "always")
        for reader, connected in ((None, False), ("absent", False), ("usb", True),
                                  ("raw", True), ("other", False)):
            self.engine.input_reader = lambda reader=reader: reader
            for mode in ("auto", "always", "never"):
                with self.subTest(reader=reader, mode=mode):
                    expected = mode == "always" or mode == "auto" and connected
                    self.assertEqual(self.engine.action({"action": "hold " + mode}),
                                     {"status": "ok", "hold_mode": mode})
                    self.assertEqual(self.engine.deck_connected(), connected)
                    self.assertEqual(self.engine.hold_active(), expected)
                    state = self.engine.state()
                    self.assertIs(state["deck_connected"], connected)
                    self.assertIs(state["hold_active"], expected)
                    self.assertEqual(state["hold_mode"], mode)
        self.engine.input_reader = None
        self.assertFalse(self.engine.deck_connected())
        self.engine.input_reader = lambda: (_ for _ in ()).throw(OSError("reader stopped"))
        self.engine.action({"action": "hold auto"})
        self.assertFalse(self.engine.deck_connected())
        self.assertFalse(self.engine.hold_active())

    def test_invalid_hold_mode_or_action_is_rejected(self):
        with self.assertRaises(ValueError):
            self.make_hub(hold_mode="sometimes")
        for action in ("hold", "hold yes", "hold auto extra", "hold ALWAYS"):
            with self.subTest(action=action), self.assertRaises(hub.HubError) as error:
                self.engine.action({"action": action})
            self.assertEqual(error.exception.status, 400)

    def test_permission_passthrough_including_critical_uses_native_ui(self):
        self.engine.action({"action": "hold never"})
        for command in ("echo hello", "rm -rf /"):
            with self.subTest(command=command):
                self.assertEqual(self.event("PermissionRequest", tool_name="Bash",
                                            tool_input={"command": command}), {})
                session = self.session()
                self.assertEqual(session["state"], "wait")
                self.assertTrue(session["native_wait"])
                self.assertEqual(session["label"], "在应用里批准")
                self.assertEqual(self.engine.pending, {})
                self.assertEqual(self.engine.locked, {})
                record = self.engine.audit.recent()[-1]
                self.assertEqual((record["decision"], record["source"]), ("passthrough", "hold"))
                self.assertEqual(self.engine._display_name(session), "APP: project")

    def test_gate_passthrough_is_audited_without_creating_wait(self):
        self.engine.action({"action": "hold never"})
        self.event("SessionStart")
        self.assertEqual(self.event("PreToolUse", gate=True, tool_name="Bash",
                                    tool_input={"command": "rm -rf /"}), {})
        self.assertEqual(self.session()["state"], "idle")
        self.assertNotIn("native_wait", self.session())
        self.assertFalse(self.engine.pending)
        self.assertFalse(self.engine.locked)
        record = self.engine.audit.recent()[-1]
        self.assertEqual((record["decision"], record["source"]), ("passthrough", "hold"))

    def test_new_held_permission_clears_previous_native_wait_label(self):
        self.engine.action({"action": "hold never"})
        self.event("PermissionRequest", tool_name="Bash", tool_input={"command": "echo native"})
        self.engine.action({"action": "hold always"})
        request, thread, results = self.pending()
        self.assertNotIn("native_wait", self.session())
        self.assertNotIn("label", self.session())
        self.assertEqual(self.engine._display_name(self.session()), "project")
        self.event("Stop")
        thread.join(2)
        self.assertEqual(results, [{}])

    def test_question_tools_keep_their_existing_native_answer_branch(self):
        self.engine.action({"action": "hold never"})
        for tool in hub.NEEDS_ANSWER_TOOLS:
            self.assertEqual(self.event("PermissionRequest", tool_name=tool, tool_input={}), {})
            self.assertEqual(self.session()["needs_answer"], tool)
            self.assertFalse(self.engine.pending)

    def test_switching_off_hold_releases_permissions_but_preserves_gate(self):
        permission, thread, results = self.pending()
        gate, gate_thread, _ = self.pending("gate-session", gate=True, command="rm -rf build")
        with self.assertLogs("agentdeck.hub", "INFO") as messages:
            self.engine.action({"action": "hold never"})
        thread.join(1)
        self.assertEqual(results, [{}])
        self.assertNotIn(permission.id, self.engine.pending)
        self.assertIn(gate.id, self.engine.pending)
        self.assertTrue(gate_thread.is_alive())
        self.assertTrue(self.session()["native_wait"])
        self.assertEqual(self.session()["label"], "在应用里批准")
        self.assertEqual(len(messages.records), 1)
        self.assertEqual(self.engine.audit.recent()[-1]["decision"], "passthrough")

    def test_auto_without_reader_releases_existing_permission(self):
        _, thread, results = self.pending()
        self.engine.input_reader = lambda: "absent"
        self.engine.action({"action": "hold auto"})
        thread.join(1)
        self.assertEqual(results, [{}])
        self.assertTrue(self.session()["native_wait"])

    def test_auto_disconnect_releases_a_held_permission_during_maintenance(self):
        self.engine.input_reader = lambda: "usb"
        self.engine.action({"action": "hold auto"})
        _, thread, results = self.pending()
        self.engine.input_reader = lambda: "absent"
        self.engine.maintain()  # starts the settle period; a reader switch may report none briefly
        self.clock.value += hub.UNHELD_SETTLE_SECONDS
        self.engine.maintain()
        thread.join(1)
        self.assertEqual(results, [{}])
        self.assertTrue(self.session()["native_wait"])
        self.assertEqual(self.engine.audit.recent()[-1]["decision"], "passthrough")

    def test_brief_reader_gap_does_not_release_a_held_permission(self):
        reader = ["usb"]
        self.engine.input_reader = lambda: reader[0]
        self.engine.action({"action": "hold auto"})
        request, thread, results = self.pending()
        for value in (None, "usb", None, "usb"):  # USB -> Raw Input switch reports None for a moment
            reader[0] = value
            self.engine.maintain()
            self.clock.value += hub.UNHELD_SETTLE_SECONDS * 0.6
        self.assertIn(request.id, self.engine.pending)
        self.assertTrue(thread.is_alive())
        self.engine.action({"action": "deny", "request_id": request.id})
        thread.join(1)
        self.assertEqual(results[0]["hookSpecificOutput"]["decision"]["behavior"], "deny")

    def test_low_risk_gate_is_not_audited_when_hold_is_disabled(self):
        self.engine.action({"action": "hold never"})
        self.event("SessionStart")
        before = len(self.engine.audit.recent(1000))
        self.assertEqual(self.event("PreToolUse", gate=True, tool_name="Read",
                                    tool_input={"file_path": "readme.txt"}), {})
        self.assertEqual(self.session()["state"], "idle")
        self.assertEqual(len(self.engine.audit.recent(1000)), before)

    def test_moved_on_events_release_permission_and_audit_once(self):
        for index, name in enumerate(("PreToolUse", "PostToolUse", "PostToolUseFailure",
                                      "UserPromptSubmit", "Stop", "StopFailure", "Interrupt",
                                      "SessionEnd")):
            sid = "moved-%d-session" % index
            with self.subTest(event=name):
                _, thread, results = self.pending(sid)
                with self.assertLogs("agentdeck.hub", "INFO") as messages:
                    self.event(name, sid, tool_name="DifferentTool", tool_input={"command": "other"},
                               error="rate_limit")
                thread.join(1)
                self.assertEqual(results, [{}])
                self.assertFalse(any(p.session == ("cc", sid) for p in self.engine.pending.values()))
                if name != "SessionEnd":
                    self.assertFalse(self.session(sid).get("native_wait"))
                    if name != "StopFailure":
                        self.assertNotIn("label", self.session(sid))
                record = self.engine.audit.recent()[-1]
                self.assertEqual((record["decision"], record["source"]), ("abandoned", "event"))
                self.assertIs(record["moved_on"], True)
                self.assertEqual(len(messages.records), 1)
                message = messages.records[0].getMessage()
                for fragment in (name, sid[:8], "1"):
                    self.assertIn(fragment, message)

    def test_one_event_releases_multiple_requests_with_one_log(self):
        _, first, one = self.pending()
        _, second, two = self.pending()
        with self.assertLogs("agentdeck.hub", "INFO") as messages:
            self.event("PostToolUse", tool_name="DifferentTool")
        first.join(1)
        second.join(1)
        self.assertEqual((one, two), ([{}], [{}]))
        self.assertEqual(len(messages.records), 1)
        self.assertIn("2", messages.records[0].getMessage())

    def test_tool_events_only_release_matching_subagent(self):
        for index, name in enumerate(("PreToolUse", "PostToolUse", "PostToolUseFailure")):
            sid = "agent-%d" % index
            own, first, one = self.pending(sid, agent_id="child-A")
            other, second, two = self.pending(sid, agent_id="child-B")
            self.assertEqual(own.agent_id, "child-A")
            self.event(name, sid, agent_id="child-A", tool_name="Unrelated")
            first.join(1)
            self.assertEqual(one, [{}])
            self.assertIn(other.id, self.engine.pending)
            self.assertTrue(second.is_alive())
            self.event("Stop", sid)
            second.join(1)
            self.assertEqual(two, [{}])

    def test_gate_survives_tool_and_prompt_events_but_stop_releases_it(self):
        request, thread, results = self.pending(gate=True, command="rm -rf build")
        for name in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "UserPromptSubmit"):
            self.event(name, tool_name="Bash", tool_input={"command": "rm -rf build"})
            self.assertIn(request.id, self.engine.pending)
            self.assertTrue(thread.is_alive())
        self.event("Stop")
        thread.join(1)
        self.assertEqual(results[0]["hookSpecificOutput"]["permissionDecision"], "deny")
        record = self.engine.audit.recent()[-1]
        self.assertEqual((record["decision"], record["source"]), ("abandoned", "event"))
        self.assertTrue(record["moved_on"])

    def test_notification_does_not_release_pending_or_force_idle(self):
        request, thread, _ = self.pending()
        self.event("Notification", notification_type="idle_prompt")
        self.assertIn(request.id, self.engine.pending)
        self.assertTrue(thread.is_alive())
        self.assertEqual(self.session()["state"], "wait")
        self.event("Stop")

    def test_idle_prompt_only_settles_tool_or_think(self):
        for name in ("UserPromptSubmit", "PreToolUse"):
            self.event(name, tool_name="Read")
            self.event("Notification", notification_type="idle_prompt")
            self.assertEqual(self.session()["state"], "idle")
        for name, expected in (("Stop", "done"), ("StopFailure", "error")):
            self.event(name, error="server_error")
            self.event("Notification", notification_type="idle_prompt")
            self.assertEqual(self.session()["state"], expected)
        self.event("PermissionRequest", tool_name="Bash", tool_input={"command": "rm -rf /"})
        self.event("Notification", notification_type="idle_prompt")
        self.assertEqual(self.session()["state"], "locked")

    def test_stop_failure_has_error_label_and_latest_error_text(self):
        message = "before" + "报错内容" * 1500
        error = "rate_limit" + "x" * 80
        self.event("StopFailure", error=error, error_details="upstream", last_assistant_message=message)
        session = self.session()
        self.assertEqual(session["state"], "error")
        self.assertEqual(session["label"], "出错：" + error[:40])
        self.assertEqual(session["last_text"], message[-hub.LAST_TEXT_LIMIT:])
        self.assertEqual(session["last_kind"], "错误")
        self.event("PreToolUse", tool_name="Read")
        self.assertNotIn("label", session)

    def test_unknown_events_warn_once_with_bounded_names(self):
        name = "unsupported-" + uuid.uuid4().hex + "x" * 100
        with self.assertLogs("agentdeck.hub", "WARNING") as messages:
            for _ in range(2):
                with self.assertRaises(hub.HubError) as error:
                    self.event(name)
                self.assertEqual(error.exception.status, 400)
        self.assertEqual(len(messages.records), 1)
        self.assertIn(name[:64], messages.records[0].getMessage())
        self.assertNotIn(name[:65], messages.records[0].getMessage())
        with self.assertLogs("agentdeck.hub", "WARNING") as messages:
            for index in range(300):
                with self.assertRaises(hub.HubError):
                    self.event("unsupported-%s-%d" % (name[:40], index))
        self.assertLessEqual(len(messages.records), 255)

    def test_apply_patch_delete_risk_covers_strings_and_known_input_fields(self):
        patches = (("*** Begin Patch\n*** Delete File: old.py\n*** End Patch", "high"),
                   ("*** Begin Patch\n*** Update File: old.py\n@@\n-x\n+y\n*** End Patch", "low"),
                   ("*** Begin Patch\n*** Add File: new.py\n+x\n*** End Patch", "low"))
        for text, expected in patches:
            for field in (None, "command", "patch", "input"):
                value = text if field is None else {field: text}
                with self.subTest(field=field, expected=expected):
                    self.assertEqual(hub.classify("apply_patch", value), expected)


class PersistenceTests(HoldCase):

    def saved_session(self, sid="restored", slot=1, **values):
        row = dict(agent="cc", session_id=sid, slot=slot, cwd="C:/work/project", name="project",
                   state="think", hwnd=123, window_exe="terminal.exe", last_text="last line",
                   last_updated=self.clock.value, last_kind="回复", last_text_at=self.clock.value)
        row.update(values)
        return row

    def persisted_hub(self, rows):
        path = self.home / ".agentdeck" / "sessions.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(rows), encoding="utf-8")
        engine = self.make_hub(sessions_path=path, window_alive=lambda hwnd: hwnd == 123)
        return engine, path

    def test_restore_valid_rows_and_normalize_native_wait(self):
        engine, _ = self.persisted_hub([
            self.saved_session("thinking", 1), self.saved_session("waiting", 2, state="wait"),
            self.saved_session("locked", 3, state="locked"),
            self.saved_session("unknown", 4, state="future-state", hwnd=999)])
        sessions = {item["session_id"]: item for item in engine.state()["sessions"]}
        self.assertEqual(len(sessions), 4)
        self.assertEqual(sessions["thinking"]["state"], "think")
        self.assertEqual(sessions["thinking"]["hwnd"], 123)
        self.assertEqual(sessions["thinking"]["last_text"], "last line")
        for name in ("waiting", "locked"):
            self.assertEqual(sessions[name]["state"], "wait")
            self.assertTrue(sessions[name]["native_wait"])
        self.assertEqual(sessions["unknown"]["state"], "idle")
        self.assertFalse(sessions["unknown"].get("hwnd"))
        self.assertFalse(sessions["unknown"].get("window_exe"))
        self.assertFalse(engine.pending)
        self.assertFalse(engine.locked)

    def test_expired_duplicate_and_invalid_rows_do_not_occupy_slots(self):
        engine, _ = self.persisted_hub([
            self.saved_session("valid", 1), self.saved_session("duplicate-slot", 1),
            self.saved_session("expired", 2, last_updated=self.clock.value - hub.SESSION_IDLE_SECONDS - 1),
            self.saved_session("zero", 0), self.saved_session("seven", 7),
            self.saved_session("boolean", True), self.saved_session("string-slot", "2"),
            self.saved_session("wrong-agent", 2, agent="other"),
            self.saved_session("bad-cwd", 3, cwd=[]), {"session_id": "partial"}, None])
        sessions = engine.state()["sessions"]
        self.assertEqual([(row["session_id"], row["slot"]) for row in sessions], [("valid", 1)])
        self.event("SessionStart", "new", engine=engine)
        self.assertEqual(self.session("new", engine)["slot"], 2)

    def test_failed_window_check_keeps_session_without_handle(self):
        path = self.home / "sessions.json"
        path.write_text(json.dumps([self.saved_session()]), encoding="utf-8")
        engine = self.make_hub(sessions_path=path,
                               window_alive=lambda hwnd: (_ for _ in ()).throw(OSError("window gone")))
        session = engine.state()["sessions"][0]
        self.assertFalse(session.get("hwnd"))
        self.assertFalse(session.get("window_exe"))

    def test_missing_or_corrupt_file_warns_without_preventing_start(self):
        path = self.home / "sessions.json"
        for contents in (None, "not json", "{}", "null"):
            if contents is not None:
                path.write_text(contents, encoding="utf-8")
            with self.subTest(contents=contents), self.assertLogs("agentdeck.hub", "WARNING"):
                engine = self.make_hub(sessions_path=path)
            self.assertEqual(engine.state()["sessions"], [])

    def test_writes_are_atomic_throttled_and_skip_unchanged_content(self):
        engine, path = self.persisted_hub([])
        self.event("SessionStart", engine=engine)
        replace = os.replace
        writes = []

        def atomic(source, destination):
            self.assertFalse(engine.lock._is_owned(), "disk I/O held the Hub state lock")
            self.assertEqual(Path(source).parent, path.parent)
            self.assertEqual(Path(destination), path)
            writes.append(json.loads(Path(source).read_text(encoding="utf-8")))
            return replace(source, destination)

        with patch.object(hub.os, "replace", side_effect=atomic):
            engine.maintain()
            self.assertEqual(len(writes), 1)
            self.clock.value += 0.5
            self.event("UserPromptSubmit", engine=engine, prompt="new message")
            engine.maintain()
            self.assertEqual(len(writes), 1)
            self.clock.value += 1.5
            engine.maintain()
            self.assertEqual(len(writes), 2)
            self.clock.value += 10
            engine.maintain()
            self.assertEqual(len(writes), 2)
            self.event("Stop", engine=engine, last_assistant_message="finished")
            engine.close()
            self.assertEqual(len(writes), 3)
            engine.close()
            self.assertEqual(len(writes), 3)
        saved = json.loads(path.read_text(encoding="utf-8"))[0]
        required = {"agent", "session_id", "slot", "cwd", "name", "state", "hwnd", "window_exe",
                    "last_text", "last_updated"}
        self.assertTrue(required <= saved.keys())
        self.assertEqual(saved["last_text"], "finished")
        self.assertNotIn("hold_mode", saved)

    def test_unchanged_loaded_sessions_and_hold_setting_do_not_rewrite_file(self):
        engine, path = self.persisted_hub([self.saved_session()])
        before = path.read_bytes()
        with patch.object(hub.os, "replace", side_effect=AssertionError("unchanged sessions rewritten")) as replace:
            engine.maintain()
            engine.action({"action": "hold never"})
            self.clock.value += 2.1
            engine.maintain()
            engine.close()
        replace.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_repeated_disk_error_warns_once_and_close_still_returns(self):
        engine, _ = self.persisted_hub([])
        self.event("SessionStart", engine=engine)
        failures = [OSError(5, "disk unavailable", str(self.home / ("sessions-%d.tmp" % index)))
                    for index in range(4)]
        with patch.object(hub.os, "replace", side_effect=failures), self.assertLogs(
                "agentdeck.hub", "WARNING") as messages:
            for _ in range(3):
                engine.maintain()
                self.clock.value += 2.1
            engine.close()
        self.assertEqual(len(messages.records), 1)

    def test_close_releases_pending_and_persists_native_wait(self):
        path = self.home / "sessions.json"
        self.engine.sessions_path = path
        _, thread, results = self.pending()
        self.engine.close()
        thread.join(1)
        self.assertEqual(results, [{}])
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["state"], "wait")
        restored = self.make_hub(sessions_path=path)
        self.assertTrue(restored.state()["sessions"][0]["native_wait"])


class SocketRelayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hub-hold-socket-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.token = "hold-socket-only"
        self.engine = hub.Hub(home=self.home, hold_mode="auto", lcd_enabled=False,
                              desktop_enabled=False, approve_timeout=10)
        self.engine.input_reader = lambda: "absent"
        self.server = hub.HubServer(self.engine, self.token, port=0)
        self.server_thread = threading.Thread(target=self.server.serve_forever,
                                              kwargs={"poll_interval": 0.01}, daemon=True)
        self.server_thread.start()
        self.addCleanup(self.close)
        directory = self.home / ".agentdeck"
        directory.mkdir(exist_ok=True)
        (directory / "token").write_text(self.token, encoding="utf-8")
        (directory / "hub.json").write_text(json.dumps(
            {"pid": os.getpid(), "port": self.server.server_port}), encoding="utf-8")

    def close(self):
        self.engine.close()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(2)

    def request(self, method, path, body=None, token=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=json.dumps(body) if body is not None else None,
                               headers={"X-AgentDeck-Token": self.token if token is None else token})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def relay_command(self):
        return [sys.executable, "-X", "utf8", str(Path(__file__).with_name("hub_relay.py")),
                "--agent", "cc", "--port", str(self.server.server_port), "--home", str(self.home)]

    def test_real_relay_passthrough_and_ghost_cleanup(self):
        event = dict(hook_event_name="PermissionRequest", session_id="socket-session",
                     cwd="C:/work/project", tool_name="Bash", tool_input={"command": "echo hello"})
        started = time.perf_counter()
        result = subprocess.run(self.relay_command(), input=json.dumps(event).encode("utf-8"),
                                capture_output=True, timeout=3,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        passthrough_elapsed = time.perf_counter() - started
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"{}", b""))
        self.assertLess(passthrough_elapsed, 1.5)
        status, state = self.request("GET", "/state")
        self.assertEqual(status, 200)
        self.assertTrue(state["sessions"][0]["native_wait"])
        self.assertEqual(state["pending"], [])
        self.assertIn("passthrough", [row["decision"] for row in self.request("GET", "/audit")[1]])
        self.assertEqual(self.request("POST", "/action", {"action": "hold always"}),
                         (200, {"status": "ok", "hold_mode": "always"}))
        process = subprocess.Popen(self.relay_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            process.stdin.write(json.dumps(event).encode("utf-8"))
            process.stdin.close()
            process.stdin = None
            deadline = time.monotonic() + 2
            while not self.request("GET", "/state")[1]["pending"]:
                self.assertIsNone(process.poll(), "permission relay exited before being held")
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.005)
            started = time.perf_counter()
            moved = dict(event, hook_event_name="PostToolUse", tool_name="DifferentTool")
            self.assertEqual(self.request("POST", "/event?agent=cc", moved), (200, {}))
            output, error = process.communicate(timeout=1.5)
            ghost_elapsed = time.perf_counter() - started
            self.assertEqual((process.returncode, output, error), (0, b"{}", b""))
            self.assertLess(ghost_elapsed, 1.5)
            _, state = self.request("GET", "/state")
            self.assertEqual(state["pending"], [])
            self.assertFalse(state["sessions"][0].get("native_wait"))
            print("real relay: passthrough=%.3f s; ghost release=%.3f s" %
                  (passthrough_elapsed, ghost_elapsed), flush=True)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=2)

    def test_hold_http_action_requires_token_and_valid_argument(self):
        self.assertEqual(self.request("POST", "/action", {"action": "hold never"}, token="wrong")[0], 401)
        self.assertEqual(self.engine.hold_mode, "auto")
        for action in ("hold", "hold other", "hold never extra"):
            self.assertEqual(self.request("POST", "/action", {"action": action})[0], 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
