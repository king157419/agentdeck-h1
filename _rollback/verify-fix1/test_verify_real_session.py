"""Offline tests for pc/verify_real_session.py.

Uses fake claude subprocesses and an isolated loopback HubServer on port 0
(following selftest_hub_replay.py / test_hub_gate.py). Never invokes real claude,
serial ports, USB devices, window focus, or user configuration files.
"""
from contextlib import contextmanager, nullcontext
import io
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
import uuid

PC_DIR = Path(__file__).resolve().parent
if str(PC_DIR) not in sys.path:
    sys.path.insert(0, str(PC_DIR))

import hub
import hub_relay
import hub_risk
import verify_real_session as vrs


@contextmanager
def temporary_hub_server():
    """Isolated loopback Hub HTTP server on an ephemeral port (no LCD/desktop)."""
    with tempfile.TemporaryDirectory(prefix="agentdeck-verify-test-") as temp:
        home = Path(temp) / "home"
        home.mkdir(parents=True, exist_ok=True)
        token = hub.load_token(home)
        engine = hub.Hub(
            home=home,
            approve_timeout=5.0,
            lcd_enabled=False,
            desktop_enabled=False,
            sender=lambda lines, **kw: None,
            focus_guard=lambda **kw: nullcontext(),
            hold_path=home / "hold",
        )
        server = hub.HubServer(engine, token, port=0)
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01),
            name="test-hub-http",
            daemon=True,
        )
        thread.start()
        try:
            yield engine, server.server_port, home
        finally:
            engine.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)


def _is_allow_decision(raw_bytes):
    if not raw_bytes:
        return False
    data = json.loads(raw_bytes.decode("utf-8"))
    return (
        data.get("hookSpecificOutput", {})
        .get("decision", {})
        .get("behavior") == "allow"
    )


def _is_gate_denied(raw_bytes):
    if not raw_bytes:
        return False
    data = json.loads(raw_bytes.decode("utf-8"))
    return data.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


class FakePopen:
    """In-process substitute for subprocess.Popen running a callable in communicate()."""

    def __init__(self, target):
        self._target = target
        self.returncode = None
        self.killed = threading.Event()

    def communicate(self):
        out, err, code = self._target(self.killed)
        self.returncode = code
        return out, err

    def terminate(self):
        self.killed.set()

    def kill(self):
        self.killed.set()


class FakeClaudeEnvironment:
    """Simulates `claude auth status`, `claude -p`, and `hub_relay.py` offline."""

    def __init__(self, *, hub_port, home, engine=None, logged_in=True, auth_stdout=None,
                 auth_returncode=0, auth_raise=None, use_gate=False, behavior_override=None):
        self.hub_port = hub_port
        self.home = Path(home)
        self.engine = engine
        self.logged_in = logged_in
        self.auth_stdout = auth_stdout
        self.auth_returncode = auth_returncode
        self.auth_raise = auth_raise
        self.use_gate = use_gate
        self.behavior_override = behavior_override or {}
        self.runner_calls = []
        self.spawner_calls = []
        self.locked_approve_count = 0
        self.two_locked_approves = threading.Event()
        if engine is not None:
            orig_action = engine.action

            def tracked_action(payload, source="http"):
                res = orig_action(payload, source=source)
                if isinstance(res, dict) and res.get("action") == "approve" and res.get("status") == "locked":
                    self.locked_approve_count += 1
                    if self.locked_approve_count >= 2:
                        self.two_locked_approves.set()
                return res

            engine.action = tracked_action

    def runner(self, cmd, *, cwd=None, timeout=10.0, input_text=None):
        self.runner_calls.append((list(cmd), cwd, input_text))
        if cmd[:3] == ["claude", "auth", "status"]:
            if self.auth_raise is not None:
                raise self.auth_raise
            if self.auth_stdout is not None:
                stdout = self.auth_stdout
                code = self.auth_returncode
            elif self.logged_in:
                stdout = json.dumps({"loggedIn": True, "authMethod": "claude.ai"})
                code = 0
            else:
                stdout = json.dumps({"loggedIn": False})
                code = 1
            return vrs.CommandResult(list(cmd), code, stdout, "", 0.01, False)

        # Scenario 5 invokes hub_relay.py via runner with Hook JSON on stdin.
        if len(cmd) >= 2 and Path(cmd[1]).name == "hub_relay.py":
            if "relay_broken_allow_high" in self.behavior_override:
                return vrs.CommandResult(list(cmd), 0, "", "", 0.02, False)
            started = time.monotonic()
            out_buf = io.StringIO()
            code = hub_relay.main(
                [str(x) for x in cmd[2:]],
                stdin=io.StringIO(input_text or ""),
                stdout=out_buf,
            )
            elapsed = round(time.monotonic() - started, 4)
            return vrs.CommandResult(list(cmd), code, out_buf.getvalue(), "", elapsed, False)

        raise AssertionError("Unexpected synchronous command: %r" % (cmd,))

    def spawner(self, cmd, *, cwd=None):
        self.spawner_calls.append((list(cmd), Path(cwd) if cwd else None))
        assert cmd[0] == "claude" and cmd[1] == "-p", "unexpected spawner args: %r" % (cmd,)
        assert "--permission-mode" in cmd and cmd[cmd.index("--permission-mode") + 1] == "default"
        assert "--output-format" in cmd and cmd[cmd.index("--output-format") + 1] == "json"
        prompt = cmd[2]
        work_dir = Path(cwd)
        return vrs.AsyncProcess(FakePopen(lambda killed: self._simulate_claude(prompt, work_dir, killed)), cmd)

    def _relay(self, event, *, gate=False):
        return hub_relay.relay(event, "cc", port=self.hub_port, home=self.home,
                               approve_timeout=3.0, gate=gate)

    def _simulate_claude(self, prompt, work_dir, killed):
        sid = "verify-" + uuid.uuid4().hex[:10]
        cwd_str = work_dir.as_posix()
        self._relay({"session_id": sid, "cwd": cwd_str, "hook_event_name": "SessionStart"})

        try:
            if "ok.txt" in prompt:
                tool_name = "Write"
                tool_input = {"file_path": (work_dir / "ok.txt").as_posix(), "content": "agentdeck-ok"}
                kind = "s1"
            elif "deny.txt" in prompt:
                tool_name = "Write"
                tool_input = {"file_path": (work_dir / "deny.txt").as_posix(), "content": "agentdeck-deny"}
                kind = "s2"
            elif vrs.HIGH_COMMAND in prompt:
                tool_name = "Bash"
                tool_input = {"command": vrs.HIGH_COMMAND}
                kind = "s3"
            elif "127.0.0.1:9" in prompt:
                tool_name = "Bash"
                tool_input = {"command": vrs.CRITICAL_COMMAND}
                kind = "s4"
            else:
                raise AssertionError("Unrecognized prompt: " + prompt)

            if self.behavior_override.get("skip_hooks_for") == kind:
                payload = {"type": "result", "subtype": "error_permission", "session_id": sid}
                return json.dumps(payload), "", 0

            if kind == "s3" and self.behavior_override.get("premature_high_delete"):
                target = work_dir / vrs.HIGH_SANDBOX_DIR / "target"
                if target.exists():
                    shutil.rmtree(target)

            if self.use_gate:
                gate_raw = self._relay({
                    "session_id": sid,
                    "cwd": cwd_str,
                    "hook_event_name": "PreToolUse",
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                }, gate=True)
                if _is_gate_denied(gate_raw):
                    return json.dumps({"type": "result", "denied_by": "gate", "session_id": sid}), "", 0

            perm_raw = self._relay({
                "session_id": sid,
                "cwd": cwd_str,
                "hook_event_name": "PermissionRequest",
                "tool_name": tool_name,
                "tool_input": tool_input,
            }, gate=False)

            allowed = _is_allow_decision(perm_raw)

            if kind == "s1":
                if allowed and not self.behavior_override.get("s1_skip_write"):
                    (work_dir / "ok.txt").write_text("agentdeck-ok\n", encoding="utf-8")
            elif kind == "s2":
                if allowed or self.behavior_override.get("s2_rogue_write"):
                    (work_dir / "deny.txt").write_text("rogue\n", encoding="utf-8")
            elif kind == "s3":
                if allowed:
                    target = work_dir / vrs.HIGH_SANDBOX_DIR / "target"
                    if target.exists():
                        shutil.rmtree(target)
            elif kind == "s4":
                if self.behavior_override.get("s4_rogue_exec"):
                    (work_dir / vrs.CRITICAL_MARKER).write_text("executed\n", encoding="utf-8")
                # In real headless claude, after PermissionRequest returns {}, Claude makes a
                # final API turn before firing Stop/SessionEnd; wait until the verifier sends
                # its two consecutive approve probes (or 1.5s fallback) before clearing locked.
                deadline = time.monotonic() + 1.5
                while (not self.two_locked_approves.is_set()
                       and not killed.is_set()
                       and time.monotonic() < deadline):
                    time.sleep(0.005)

            self._relay({"session_id": sid, "cwd": cwd_str, "hook_event_name": "Stop"})
            result_json = {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "session_id": sid,
                "allowed": allowed,
            }
            return json.dumps(result_json), "", 0
        finally:
            self._relay({"session_id": sid, "cwd": cwd_str, "hook_event_name": "SessionEnd"})


class VerifyRealSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentdeck-vrs-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.test_dir = self.root / "agentdeck-test"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = self.root / "real-session"

    def test_risk_rules_match_chosen_commands(self):
        self.assertEqual(hub_risk.classify("Write", {"file_path": "ok.txt", "content": "ok"}), "low")
        self.assertEqual(hub_risk.classify("Write", {"file_path": "deny.txt", "content": "no"}), "low")
        self.assertEqual(hub_risk.classify("Bash", {"command": vrs.HIGH_COMMAND}), "high")
        self.assertEqual(hub_risk.classify("Bash", {"command": vrs.CRITICAL_COMMAND}), "critical")

    def test_dry_run_does_not_call_claude_or_hub(self):
        lines = []

        def forbidden(*args, **kwargs):
            raise AssertionError("dry-run must not invoke subprocesses")

        code = vrs.main(
            ["--dry-run", "--test-dir", str(self.test_dir), "--output-dir", str(self.output_dir)],
            runner=forbidden,
            spawner=forbidden,
            out=lines.append,
        )
        self.assertEqual(code, 0)
        joined = "\n".join(lines)
        for index in range(1, 6):
            self.assertIn("%d." % index, joined)
        self.assertIn("--permission-mode default", joined)
        self.assertIn("--output-format json", joined)
        self.assertFalse(self.output_dir.exists())

    def test_unauthenticated_exits_2_without_login_attempt(self):
        cases = [
            {"logged_in": False},
            {"auth_stdout": "Not logged in", "auth_returncode": 1},
            {"auth_raise": FileNotFoundError("claude not found")},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                lines = []
                fake = FakeClaudeEnvironment(hub_port=9, home=self.root, **kwargs)
                code = vrs.main(
                    ["--test-dir", str(self.test_dir), "--output-dir", str(self.output_dir)],
                    runner=fake.runner,
                    spawner=fake.spawner,
                    out=lines.append,
                )
                self.assertEqual(code, 2)
                self.assertEqual(len(fake.runner_calls), 1)
                self.assertEqual(fake.runner_calls[0][0], ["claude", "auth", "status"])
                self.assertEqual(fake.spawner_calls, [])
                self.assertTrue(any("未登录" in line for line in lines))

    def test_hub_unavailable_exits_3_with_start_bat_hint(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
        sock.close()

        lines = []
        fake = FakeClaudeEnvironment(hub_port=dead_port, home=self.root, logged_in=True)
        code = vrs.main(
            ["--hub-port", str(dead_port), "--home", str(self.root),
             "--test-dir", str(self.test_dir), "--output-dir", str(self.output_dir)],
            runner=fake.runner,
            spawner=fake.spawner,
            out=lines.append,
        )
        self.assertEqual(code, 3)
        self.assertEqual(fake.spawner_calls, [])
        self.assertTrue(any("start_agentdeck.bat" in line for line in lines))

        # Hub /health is up, but token file does not exist in --home -> still exit 3.
        with temporary_hub_server() as (_, port, _):
            empty_home = self.root / "empty-home"
            empty_home.mkdir()
            lines_missing_tok = []
            fake2 = FakeClaudeEnvironment(hub_port=port, home=empty_home, logged_in=True)
            code2 = vrs.main(
                ["--hub-port", str(port), "--home", str(empty_home),
                 "--test-dir", str(self.test_dir), "--output-dir", str(self.output_dir)],
                runner=fake2.runner,
                spawner=fake2.spawner,
                out=lines_missing_tok.append,
            )
            self.assertEqual(code2, 3)
            self.assertEqual(fake2.spawner_calls, [])
            self.assertTrue(any("start_agentdeck.bat" in line for line in lines_missing_tok))

    def _run_verifier(self, engine, port, home, *, use_gate=False, behavior_override=None):
        fake = FakeClaudeEnvironment(
            hub_port=port,
            home=home,
            engine=engine,
            logged_in=True,
            use_gate=use_gate,
            behavior_override=behavior_override,
        )
        lines = []
        verifier = vrs.RealSessionVerifier(
            test_dir=self.test_dir,
            output_dir=self.output_dir,
            hub_port=port,
            home=home,
            scenario_timeout=5.0,
            poll_interval=0.01,
            confirm_delay=0.02,
            runner=fake.runner,
            spawner=fake.spawner,
            out=lines.append,
        )
        code = verifier.run(dry_run=False)
        return code, fake, lines

    def test_all_five_scenarios_pass_permission_only_flow(self):
        with temporary_hub_server() as (engine, port, home):
            code, fake, _ = self._run_verifier(engine, port, home, use_gate=False)
            self.assertEqual(code, 0)
            self.assertEqual(len(fake.spawner_calls), 4)
            self.assertTrue((self.test_dir / "ok.txt").is_file())
            self.assertFalse((self.test_dir / "deny.txt").exists())
            self.assertFalse((self.test_dir / vrs.CRITICAL_MARKER).exists())
            self.assertTrue(engine.audit.verify())
            # Real home must not be polluted by Scenario 5's offline relay log.
            self.assertFalse((home / ".agentdeck" / "relay.log").exists())

            run_dirs = list(self.output_dir.iterdir())
            self.assertEqual(len(run_dirs), 1)
            run_dir = run_dirs[0]
            results_md = (run_dir / "results.md").read_text(encoding="utf-8")
            table_rows = [
                line for line in results_md.splitlines()
                if line.startswith("| ") and not line.startswith("| 场景 |") and not line.startswith("| ---")
            ]
            self.assertEqual(len(table_rows), 5)
            for row in table_rows:
                self.assertIn("| 通过 |", row)

            for spec in vrs.SCENARIOS:
                folder = run_dir / spec["slug"]
                for fname in ("evidence.json", "claude_output.json", "state_before.json",
                              "state_after.json", "audit_delta.json", "assertions.json"):
                    fpath = folder / fname
                    self.assertTrue(fpath.is_file(), "missing %s" % fpath)
                    json.loads(fpath.read_text(encoding="utf-8"))

            s3_evidence = json.loads((run_dir / "03_high_double_approve" / "evidence.json").read_text(encoding="utf-8"))
            self.assertTrue(s3_evidence["assertions"]["first_approve_returned_confirm"])
            self.assertTrue(s3_evidence["assertions"]["not_executed_after_first_approve"])
            self.assertTrue(s3_evidence["assertions"]["second_approve_returned_allowed"])
            self.assertTrue(s3_evidence["assertions"]["executed_after_second_approve"])

            s4_evidence = json.loads((run_dir / "04_critical_locked" / "evidence.json").read_text(encoding="utf-8"))
            self.assertTrue(s4_evidence["assertions"]["consecutive_approves_returned_locked"])
            self.assertTrue(s4_evidence["assertions"]["command_not_executed"])

            s5_evidence = json.loads((run_dir / "05_hub_down_degrade" / "evidence.json").read_text(encoding="utf-8"))
            self.assertTrue(all(s5_evidence["assertions"].values()))
            self.assertIn("hub_relay.py", results_md)

    def test_all_five_scenarios_pass_with_pretooluse_gate_enabled(self):
        with temporary_hub_server() as (engine, port, home):
            code, _, _ = self._run_verifier(engine, port, home, use_gate=True)
            self.assertEqual(code, 0)
            self.assertTrue(engine.audit.verify())

    def test_other_concurrent_session_on_hub_is_not_touched(self):
        with temporary_hub_server() as (engine, port, home):
            foreign_done = threading.Event()
            foreign_result = []

            def foreign_hook():
                res = hub_relay.relay({
                    "session_id": "foreign-session-01",
                    "cwd": "D:/other/unrelated-project",
                    "hook_event_name": "PermissionRequest",
                    "tool_name": "Bash",
                    "tool_input": {"command": "pytest"},
                }, "cc", port=port, home=home, approve_timeout=4.0)
                foreign_result.append(res)
                foreign_done.set()

            t = threading.Thread(target=foreign_hook, daemon=True)
            t.start()
            deadline = time.monotonic() + 2.0
            while not engine.state()["pending"] and time.monotonic() < deadline:
                time.sleep(0.005)
            foreign_req_id = engine.state()["pending"][0]["id"]

            try:
                code, _, _ = self._run_verifier(engine, port, home, use_gate=False)
                self.assertEqual(code, 0)
                # The unrelated session's pending request must still be waiting untouched!
                pending_ids = [p["id"] for p in engine.state()["pending"]]
                self.assertIn(foreign_req_id, pending_ids)
                self.assertFalse(foreign_done.is_set())
            finally:
                engine.event("cc", {"session_id": "foreign-session-01",
                                    "cwd": "D:/other/unrelated-project",
                                    "hook_event_name": "SessionEnd"})
                t.join(timeout=2.0)

    def test_judgment_logic_catches_failures_in_each_scenario(self):
        failure_modes = [
            ({"s1_skip_write": True}, "01_approve", "ok_txt_exists"),
            ({"s2_rogue_write": True}, "02_deny", "deny_txt_absent"),
            ({"premature_high_delete": True}, "03_high_double_approve", "not_executed_after_first_approve"),
            ({"s4_rogue_exec": True}, "04_critical_locked", "command_not_executed"),
            ({"skip_hooks_for": "s4"}, "04_critical_locked", "consecutive_approves_returned_locked"),
            ({"relay_broken_allow_high": True}, "05_hub_down_degrade", "high_risk_denied_locally"),
        ]
        for override, expected_failed_slug, expected_failed_assertion in failure_modes:
            with self.subTest(override=override):
                if self.output_dir.exists():
                    shutil.rmtree(self.output_dir)
                with temporary_hub_server() as (engine, port, home):
                    code, _, _ = self._run_verifier(
                        engine, port, home, use_gate=False, behavior_override=override
                    )
                    self.assertEqual(code, 1)
                    run_dir = next(self.output_dir.iterdir())
                    ev = json.loads((run_dir / expected_failed_slug / "evidence.json").read_text(encoding="utf-8"))
                    self.assertEqual(ev["status"], "失败")
                    self.assertFalse(ev["assertions"][expected_failed_assertion])


if __name__ == "__main__":
    unittest.main(verbosity=2)
