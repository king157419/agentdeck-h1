"""Offline tests for pc/verify_real_session.py.

Uses fake claude subprocesses and an isolated loopback HubServer on port 0
(following selftest_hub_replay.py / test_hub_gate.py). Never invokes real claude,
serial ports, USB devices, window focus, or user configuration files.
"""
from contextlib import contextmanager, nullcontext
import io
import json
import os
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
def temporary_hub_server(require_nonce=False):
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
            require_nonce=require_nonce,
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

        # Capture session_id passed from caller via --session-id
        session_id = None
        if "--session-id" in cmd:
            session_id = cmd[cmd.index("--session-id") + 1]

        prompt = cmd[2]
        work_dir = Path(cwd) if cwd else Path.cwd()
        return vrs.AsyncProcess(
            FakePopen(lambda killed: self._simulate_claude(prompt, work_dir, session_id, killed)),
            cmd,
        )

    def _relay(self, event, *, gate=False):
        return hub_relay.relay(event, "cc", port=self.hub_port, home=self.home,
                               approve_timeout=3.0, gate=gate)

    def _simulate_claude(self, prompt, work_dir, session_id, killed):
        sid = session_id or ("verify-" + uuid.uuid4().hex[:10])
        cwd_str = work_dir.as_posix()
        self._relay({"session_id": sid, "cwd": cwd_str, "hook_event_name": "SessionStart"})

        try:
            target_file = None
            high_target_dir = None
            canary_file = None

            if "ok.txt" in prompt:
                # Dynamic sandbox relative path in prompt: e.g. "./_verify_run_.../ok.txt"
                rel_token = next((t for t in prompt.split() if t.endswith("ok.txt")), "./_verify_run_sample/ok.txt")
                target_file = work_dir / rel_token.lstrip("./")
                tool_name = "Write"
                tool_input = {"file_path": target_file.as_posix(), "content": "agentdeck-ok"}
                kind = "s1"
            elif "deny.txt" in prompt:
                rel_token = next((t for t in prompt.split() if t.endswith("deny.txt")), "./_verify_run_sample/deny.txt")
                target_file = work_dir / rel_token.lstrip("./")
                tool_name = "Write"
                tool_input = {"file_path": target_file.as_posix(), "content": "agentdeck-deny"}
                kind = "s2"
            elif "high_sandbox/target" in prompt or "rm -rf" in prompt:
                target_token = next((t for t in prompt.split() if "high_sandbox/target" in t), "./_verify_run_sample/high_sandbox/target")
                high_cmd = "rm -rf " + target_token
                high_target_dir = work_dir / target_token.lstrip("./")
                tool_name = "Bash"
                tool_input = {"command": high_cmd}
                kind = "s3"
            elif vrs.CRITICAL_LITERAL in prompt or "critical_canary.txt" in prompt or "127.0.0.1:9" in prompt:
                if "without modifying it: " in prompt:
                    crit_cmd = prompt.split("without modifying it: ")[1].split(" . If blocked")[0].strip()
                else:
                    crit_cmd = vrs.CRITICAL_COMMAND
                canary_token = next((t for t in prompt.split() if "critical_canary.txt" in t), "./_verify_run_sample/critical_canary.txt")
                canary_file = work_dir / canary_token.lstrip("./")
                tool_name = "Bash"
                tool_input = {"command": crit_cmd}
                kind = "s4"
            else:
                raise AssertionError("Unrecognized prompt: " + prompt)

            if self.behavior_override.get("skip_hooks_for") == kind:
                payload = {
                    "type": "result",
                    "subtype": "error_permission",
                    "session_id": sid,
                    "permission_denials": [],
                }
                return json.dumps(payload), "", 0

            if self.behavior_override.get("rogue_request_for") == kind:
                # Emit an unexpected request in a background thread to trigger verifier immediate abortion
                rogue_spec = self.behavior_override.get("rogue_spec", {})
                t_rogue = threading.Thread(
                    target=lambda: self._relay({
                        "session_id": sid,
                        "cwd": cwd_str,
                        "hook_event_name": "PermissionRequest",
                        "tool_name": rogue_spec.get("tool_name", "Bash"),
                        "tool_input": rogue_spec.get("tool_input", {"command": "echo rogue"}),
                    }, gate=False),
                    name="fake-rogue-relay",
                    daemon=True,
                )
                t_rogue.start()
                # Wait until verifier terminates the child
                while not killed.is_set():
                    time.sleep(0.01)
                return json.dumps({"type": "result", "subtype": "aborted", "session_id": sid}), "", 0

            if kind == "s3" and self.behavior_override.get("premature_high_delete"):
                if high_target_dir is not None and high_target_dir.exists():
                    shutil.rmtree(high_target_dir)

            if self.use_gate:
                gate_raw = self._relay({
                    "session_id": sid,
                    "cwd": cwd_str,
                    "hook_event_name": "PreToolUse",
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                }, gate=True)
                if _is_gate_denied(gate_raw):
                    self._relay({"session_id": sid, "cwd": cwd_str, "hook_event_name": "Stop"})
                    return json.dumps({
                        "type": "result",
                        "subtype": "success",
                        "is_error": False,
                        "session_id": sid,
                        "allowed": False,
                        "permission_denials": [{"tool_name": tool_name, "tool_input": tool_input}],
                    }), "", 0

            perm_raw = self._relay({
                "session_id": sid,
                "cwd": cwd_str,
                "hook_event_name": "PermissionRequest",
                "tool_name": tool_name,
                "tool_input": tool_input,
            }, gate=False)

            allowed = _is_allow_decision(perm_raw)

            if kind == "s1":
                if allowed and not self.behavior_override.get("s1_skip_write") and target_file is not None:
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_text("agentdeck-ok\n", encoding="utf-8")
            elif kind == "s2":
                if (allowed or self.behavior_override.get("s2_rogue_write")) and target_file is not None:
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_text("rogue\n", encoding="utf-8")
            elif kind == "s3":
                if allowed and high_target_dir is not None and high_target_dir.exists():
                    shutil.rmtree(high_target_dir)
            elif kind == "s4":
                if self.behavior_override.get("s4_rogue_exec") and canary_file is not None:
                    canary_file.parent.mkdir(parents=True, exist_ok=True)
                    canary_file.write_text("executed\n", encoding="utf-8")
                # P2-2: Removed observer-dependent wait!
                # If immediate_critical_stop is set, trigger fast Stop to test the race condition.
                # Otherwise, simulate realistic short turn delay so verifier completes 2 locked probes.
                if not self.behavior_override.get("immediate_critical_stop"):
                    time.sleep(0.5)

            self._relay({"session_id": sid, "cwd": cwd_str, "hook_event_name": "Stop"})

            # P1-5 negative overrides
            if self.behavior_override.get("cli_nonzero_exit"):
                return "", "CLI exited with error 17", 17
            if self.behavior_override.get("cli_malformed_json"):
                return "this is completely invalid json", "", 0
            if self.behavior_override.get("cli_empty_stdout"):
                return "", "", 0
            if self.behavior_override.get("cli_is_error"):
                payload = {
                    "type": "result",
                    "subtype": "error_during_execution",
                    "is_error": True,
                    "session_id": sid,
                    "permission_denials": [],
                }
                return json.dumps(payload), "", 0
            if self.behavior_override.get("cli_wrong_session_id"):
                payload = {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "session_id": "unmatched-foreign-session-uuid",
                    "allowed": allowed,
                    "permission_denials": [] if allowed else [{"tool_name": tool_name, "tool_input": tool_input}],
                }
                return json.dumps(payload), "", 0

            result_json = {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "session_id": sid,
                "allowed": allowed,
                "permission_denials": (
                    [] if allowed else [
                        {"tool_name": tool_name, "tool_input": tool_input}
                    ]
                ),
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

    def _run_verifier(self, engine, port, home, *, use_gate=False, behavior_override=None,
                      confirm_delay=0.02, switch_guard_wait=0.33, spawner_override=None):
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
            confirm_delay=confirm_delay,
            switch_guard_wait=switch_guard_wait,
            runner=fake.runner,
            spawner=spawner_override or fake.spawner,
            out=lines.append,
        )
        code = verifier.run(dry_run=False)
        return code, fake, lines

    def test_all_five_scenarios_pass_permission_only_flow(self):
        with temporary_hub_server() as (engine, port, home):
            code, fake, lines = self._run_verifier(engine, port, home, use_gate=False)
            self.assertEqual(code, 0)
            self.assertEqual(len(fake.spawner_calls), 4)
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

            s1_ev = json.loads((run_dir / "01_approve" / "evidence.json").read_text(encoding="utf-8"))
            self.assertTrue(s1_ev["assertions"]["ok_txt_exists"])
            self.assertTrue(s1_ev["assertions"]["ok_txt_content_verified"])
            self.assertTrue(s1_ev["assertions"]["audit_recorded_allow"])

            s2_ev = json.loads((run_dir / "02_deny" / "evidence.json").read_text(encoding="utf-8"))
            self.assertTrue(s2_ev["assertions"]["deny_txt_absent"])
            self.assertTrue(s2_ev["assertions"]["audit_recorded_deny"])

            s3_evidence = json.loads((run_dir / "03_high_double_approve" / "evidence.json").read_text(encoding="utf-8"))
            self.assertTrue(s3_evidence["assertions"]["first_approve_returned_confirm"])
            self.assertTrue(s3_evidence["assertions"]["not_executed_after_first_approve"])
            self.assertTrue(s3_evidence["assertions"]["second_approve_returned_allowed"])
            self.assertTrue(s3_evidence["assertions"]["executed_after_second_approve"])
            self.assertEqual(s3_evidence["claude_output"]["approval_breakdown"]["total_approves"], 2)

            s4_evidence = json.loads((run_dir / "04_critical_locked" / "evidence.json").read_text(encoding="utf-8"))
            self.assertTrue(s4_evidence["assertions"]["consecutive_approves_returned_locked"])
            self.assertTrue(s4_evidence["assertions"]["canary_not_created"])
            self.assertTrue(s4_evidence["assertions"]["audit_recorded_locked"])

            s5_evidence = json.loads((run_dir / "05_hub_down_degrade" / "evidence.json").read_text(encoding="utf-8"))
            self.assertTrue(all(s5_evidence["assertions"].values()))
            self.assertIn("hub_relay.py", results_md)

    def test_all_five_scenarios_pass_with_pretooluse_gate_enabled(self):
        """Under PreToolUse gate, faithfully records 2 gate + 1 permission approvals.

        Proves directory was intact before 3rd approve, marks 'executed_after_second_approve'
        as unfulfilled (code=1), while scenarios 1, 2, 4, 5 pass.
        """
        with temporary_hub_server() as (engine, port, home):
            code, _, _ = self._run_verifier(engine, port, home, use_gate=True)
            # Under gate, Scenario 3 honestly requires 3 approvals, marking 2-approve as unmet -> exit 1
            self.assertEqual(code, 1)
            self.assertTrue(engine.audit.verify())

            run_dir = next(self.output_dir.iterdir())
            results_md = (run_dir / "results.md").read_text(encoding="utf-8")
            self.assertIn("01_approve", results_md)
            self.assertIn("03_high_double_approve", results_md)

            s3_ev = json.loads((run_dir / "03_high_double_approve" / "evidence.json").read_text(encoding="utf-8"))
            self.assertEqual(s3_ev["status"], "失败")
            # P1-4 assertions:
            self.assertTrue(s3_ev["assertions"]["not_executed_before_third_approve"])
            self.assertFalse(s3_ev["assertions"]["executed_after_second_approve"])
            self.assertTrue(s3_ev["assertions"]["target_removed_after_all_approvals"])
            self.assertTrue(s3_ev["assertions"]["permission_approve_after_gate_allowed"])
            self.assertEqual(s3_ev["claude_output"]["approval_breakdown"]["gate_approves"], 2)
            self.assertEqual(s3_ev["claude_output"]["approval_breakdown"]["permission_approves"], 1)
            self.assertEqual(s3_ev["claude_output"]["approval_breakdown"]["total_approves"], 3)
            self.assertEqual(s3_ev["claude_output"]["approval_breakdown"]["summary"], "2 次 gate + 1 次权限批准")

            # Scenarios 1, 2, 4, 5 still passed
            for slug in ("01_approve", "02_deny", "04_critical_locked", "05_hub_down_degrade"):
                ev = json.loads((run_dir / slug / "evidence.json").read_text(encoding="utf-8"))
                self.assertEqual(ev["status"], "通过", "scenario %s should have passed" % slug)

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
            ({"s4_rogue_exec": True}, "04_critical_locked", "canary_not_created"),
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

    # --------------------------------------------------------------------------
    # P1-1: Nonce and switch_guard negative & edge cases
    # --------------------------------------------------------------------------

    def test_require_nonce_mode_succeeds_with_correct_nonce(self):
        """When Hub enforces require_nonce=True, verifier supplies 32-bit nonce and passes."""
        with temporary_hub_server(require_nonce=True) as (engine, port, home):
            code, _, _ = self._run_verifier(engine, port, home, use_gate=False)
            self.assertEqual(code, 0)
            self.assertTrue(engine.audit.verify())
            # Verify that audit entries contain integer nonces
            audits = engine.audit.recent(limit=50)
            http_audits = [a for a in audits if a.get("source") == "http"]
            self.assertTrue(len(http_audits) > 0)
            for a in http_audits:
                self.assertIsInstance(a.get("nonce"), int)

    def test_switch_guard_retry_and_reverification_on_conflict(self):
        """Simulate 409 switch_guard on first approve; verifier retries after bounded wait."""
        with temporary_hub_server() as (engine, port, home):
            orig_action = engine.action
            first_guard_triggered = False

            def mock_action(payload, source="http", **kw):
                nonlocal first_guard_triggered
                cmd = str(payload.get("action", "")).strip().split()[0]
                if cmd == "approve" and not first_guard_triggered:
                    first_guard_triggered = True
                    raise hub.HubError("switch_guard", 409)
                return orig_action(payload, source=source, **kw)

            engine.action = mock_action

            code, _, _ = self._run_verifier(
                engine, port, home, use_gate=False, switch_guard_wait=0.05
            )
            self.assertEqual(code, 0)
            self.assertTrue(first_guard_triggered)
            run_dir = next(self.output_dir.iterdir())
            s1_ev = json.loads((run_dir / "01_approve" / "evidence.json").read_text(encoding="utf-8"))
            retry_events = [it for it in s1_ev["hub_interactions"] if it.get("event") == "switch_guard_retry"]
            self.assertTrue(len(retry_events) >= 1)

    def test_displayed_request_change_during_wait_aborts_without_blind_approve(self):
        """If displayed request changes to another ID during wait, verifier aborts immediately."""
        with temporary_hub_server() as (engine, port, home):
            # Create a fake state with displayed_request_id = 'foreign'
            fake_state = {
                "displayed_request_id": "foreign-id",
                "sessions": [{
                    "session_id": "my-sid",
                    "agent": "cc",
                    "cwd": self.test_dir.as_posix(),
                    "pending_requests": [{"id": "expected-id", "nonce": 1234}],
                }],
            }
            verifier = vrs.RealSessionVerifier(test_dir=self.test_dir, hub_port=port, home=home)
            with self.assertRaises(vrs.VerificationActionError) as cm:
                verifier._verify_frozen_target(
                    fake_state, "my-sid", "expected-id", 1234, "pending", lambda s, r: None
                )
            self.assertIn("当前显示的请求已变化", str(cm.exception))

    def test_deny_and_locked_are_exempt_from_switch_guard(self):
        """Deny and locked requests do not wait for switch_guard."""
        with temporary_hub_server() as (engine, port, home):
            verifier = vrs.RealSessionVerifier(
                test_dir=self.test_dir, hub_port=port, home=home,
                switch_guard_wait=10.0,  # huge wait if applied
            )
            started = time.monotonic()
            req = {"id": "req1", "nonce": 42}
            session = {"agent": "cc", "session_id": "sid1", "slot": 1}
            state = {"displayed_request_id": "req1", "sessions": [session]}

            class DummyClient:
                def action(self, payload):
                    return {"action": payload.get("action"), "status": "denied"}
                def state(self):
                    return state

            res = verifier._act_on_request(
                DummyClient(), state, session, req, "deny",
                kind="pending", expected_session_id="sid1",
                validator=lambda s, r: None, deadline=time.monotonic() + 5.0,
            )
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 0.5)
            self.assertEqual(res["status"], "denied")

    # --------------------------------------------------------------------------
    # P1-2: Session ID binding & unexpected request negative cases
    # --------------------------------------------------------------------------

    def test_foreign_session_on_same_cwd_is_strictly_ignored_and_untouched(self):
        """A concurrent session in the SAME cwd (agent='cc', foreign session_id) is NOT touched."""
        with temporary_hub_server() as (engine, port, home):
            foreign_done = threading.Event()
            foreign_res = []

            def foreign_hook():
                res = hub_relay.relay({
                    "session_id": "foreign-same-cwd-session",
                    "cwd": self.test_dir.as_posix(),
                    "hook_event_name": "PermissionRequest",
                    "tool_name": "Bash",
                    "tool_input": {"command": "rm -rf /dangerous/foreign/path"},
                }, "cc", port=port, home=home, approve_timeout=4.0)
                foreign_res.append(res)
                foreign_done.set()

            t = threading.Thread(target=foreign_hook, daemon=True)
            t.start()
            deadline = time.monotonic() + 2.0
            while not engine.state()["pending"] and time.monotonic() < deadline:
                time.sleep(0.005)
            foreign_req = engine.state()["pending"][0]
            self.assertEqual(foreign_req["summary"], "rm -rf /dangerous/foreign/path")

            try:
                code, _, lines = self._run_verifier(engine, port, home, use_gate=False)
                self.assertEqual(code, 0)
                # Foreign request MUST NOT be approved; it must still be pending!
                pending_ids = [p["id"] for p in engine.state()["pending"]]
                self.assertIn(foreign_req["id"], pending_ids)
                self.assertFalse(foreign_done.is_set())

                # Verifier notes must reflect that foreign session was observed and ignored
                run_dir = next(self.output_dir.iterdir())
                s1_ev = json.loads((run_dir / "01_approve" / "evidence.json").read_text(encoding="utf-8"))
                self.assertTrue(any("严格忽略（未触碰）" in note for note in s1_ev["notes"]))
            finally:
                engine.event("cc", {
                    "session_id": "foreign-same-cwd-session",
                    "cwd": self.test_dir.as_posix(),
                    "hook_event_name": "SessionEnd",
                })
                t.join(timeout=2.0)

    def test_foreign_session_wrong_agent_same_cwd_is_strictly_ignored(self):
        """A foreign session on same cwd with agent='cx' is strictly ignored."""
        with temporary_hub_server() as (engine, port, home):
            foreign_done = threading.Event()

            def foreign_hook():
                hub_relay.relay({
                    "session_id": "foreign-cx-session",
                    "cwd": self.test_dir.as_posix(),
                    "hook_event_name": "PermissionRequest",
                    "tool_name": "Bash",
                    "tool_input": {"command": "echo foreign_cx"},
                }, "cx", port=port, home=home, approve_timeout=4.0)
                foreign_done.set()

            t = threading.Thread(target=foreign_hook, daemon=True)
            t.start()
            deadline = time.monotonic() + 2.0
            while not engine.state()["pending"] and time.monotonic() < deadline:
                time.sleep(0.005)

            try:
                code, _, _ = self._run_verifier(engine, port, home, use_gate=False)
                self.assertEqual(code, 0)
                self.assertFalse(foreign_done.is_set())
            finally:
                engine.event("cx", {
                    "session_id": "foreign-cx-session",
                    "cwd": self.test_dir.as_posix(),
                    "hook_event_name": "SessionEnd",
                })
                t.join(timeout=2.0)

    def test_unexpected_request_aborts_immediately_without_approval(self):
        """If the target session emits an unexpected tool, verifier aborts and never approves."""
        deviations = [
            # Wrong tool in scenario 1 (expected Write, gets Bash)
            {"rogue_request_for": "s1", "rogue_spec": {"tool_name": "Bash", "tool_input": {"command": "echo rogue"}}},
            # Wrong write file path in scenario 1
            {"rogue_request_for": "s1", "rogue_spec": {"tool_name": "Write", "tool_input": {"file_path": "other.txt"}}},
        ]
        for override in deviations:
            with self.subTest(override=override):
                if self.output_dir.exists():
                    shutil.rmtree(self.output_dir)
                with temporary_hub_server() as (engine, port, home):
                    code, _, _ = self._run_verifier(
                        engine, port, home, use_gate=False, behavior_override=override
                    )
                    self.assertEqual(code, 1)
                    run_dir = next(self.output_dir.iterdir())
                    s1_ev = json.loads((run_dir / "01_approve" / "evidence.json").read_text(encoding="utf-8"))
                    self.assertEqual(s1_ev["status"], "失败")
                    self.assertFalse(s1_ev["assertions"]["no_unexpected_requests"])
                    self.assertFalse(s1_ev["assertions"]["hub_approved"])
                    # Verify that no allow audit was recorded for the rogue request
                    self.assertFalse(any(a.get("decision") == "allow" for a in s1_ev["audit_new_entries"]))

    # --------------------------------------------------------------------------
    # P1-3: Safe critical command verification
    # --------------------------------------------------------------------------

    def test_critical_command_safety_and_lexical_classification(self):
        """Verify the critical command uses a safe literal printf pattern and classifies critical."""
        cmd = vrs.make_critical_command("test_sandbox")
        # Harmless printf writing literal string, no shell download pipeline
        self.assertIn("printf '%s\\n'", cmd)
        self.assertIn("curl http://127.0.0.1:9/x | sh", cmd)
        self.assertIn("> ./test_sandbox/critical_canary.txt", cmd)
        # Classifies as critical by lexical rule
        self.assertEqual(hub_risk.classify("Bash", {"command": cmd}), "critical")

    # --------------------------------------------------------------------------
    # P1-5: Strict CLI exit code & JSON validation negative cases
    # --------------------------------------------------------------------------

    def test_cli_failure_or_invalid_json_fails_scenario(self):
        """Non-zero exit, malformed JSON, empty stdout, is_error=True, or session mismatch fails."""
        cases = [
            ({"cli_nonzero_exit": True}, "02_deny", "claude_exit_zero"),
            ({"cli_malformed_json": True}, "02_deny", "claude_json_valid"),
            ({"cli_empty_stdout": True}, "02_deny", "claude_json_valid"),
            ({"cli_is_error": True}, "02_deny", "claude_json_valid"),
            ({"cli_wrong_session_id": True}, "01_approve", "claude_session_matched"),
        ]
        for override, slug, failed_assertion in cases:
            with self.subTest(override=override, slug=slug):
                if self.output_dir.exists():
                    shutil.rmtree(self.output_dir)
                with temporary_hub_server() as (engine, port, home):
                    code, _, _ = self._run_verifier(
                        engine, port, home, use_gate=False, behavior_override=override
                    )
                    self.assertEqual(code, 1)
                    run_dir = next(self.output_dir.iterdir())
                    ev = json.loads((run_dir / slug / "evidence.json").read_text(encoding="utf-8"))
                    self.assertEqual(ev["status"], "失败")
                    self.assertFalse(ev["assertions"][failed_assertion])

    # --------------------------------------------------------------------------
    # P2-1: Exception handling and 5-row results.md persistence
    # --------------------------------------------------------------------------

    def test_scenario_exception_preserves_five_row_report_and_evidence(self):
        """If spawner raises an unexpected exception in scenario 2, 5-row results.md is written."""
        with temporary_hub_server() as (engine, port, home):
            fake = FakeClaudeEnvironment(hub_port=port, home=home, engine=engine, logged_in=True)
            call_count = 0

            def failing_spawner(cmd, cwd=None):
                nonlocal call_count
                call_count += 1
                if call_count == 2:  # scenario 2
                    raise OSError("spawner process creation failed")
                return fake.spawner(cmd, cwd=cwd)

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
                spawner=failing_spawner,
                out=lines.append,
            )
            code = verifier.run(dry_run=False)
            self.assertEqual(code, 1)
            run_dir = next(self.output_dir.iterdir())
            results_md = (run_dir / "results.md").read_text(encoding="utf-8")
            table_rows = [
                line for line in results_md.splitlines()
                if line.startswith("| ") and not line.startswith("| 场景 |") and not line.startswith("| ---")
            ]
            self.assertEqual(len(table_rows), 5)
            # Scenario 1 passed, Scenario 2 failed, Scenario 3 still executed
            s1_ev = json.loads((run_dir / "01_approve" / "evidence.json").read_text(encoding="utf-8"))
            s2_ev = json.loads((run_dir / "02_deny" / "evidence.json").read_text(encoding="utf-8"))
            s3_ev = json.loads((run_dir / "03_high_double_approve" / "evidence.json").read_text(encoding="utf-8"))

            self.assertEqual(s1_ev["status"], "通过")
            self.assertEqual(s2_ev["status"], "失败")
            self.assertFalse(s2_ev["assertions"]["no_unhandled_exception"])
            self.assertIn("spawner process creation failed", str(s2_ev["notes"]))
            # Hub stays healthy after a spawner failure, so later scenarios still run
            # (only "cannot safely continue" cases, e.g. Hub down, are skipped).
            self.assertNotEqual(s3_ev["status"], "跳过")
            self.assertNotEqual(s3_ev["assertions"].get("executed"), False)

    # --------------------------------------------------------------------------
    # P2-2: Fast Stop race condition in critical scenario
    # --------------------------------------------------------------------------

    def test_critical_fast_stop_race_condition_reported_accurately(self):
        """When fake claude fires Stop immediately, verifier distinguishes audit from missing probe."""
        with temporary_hub_server() as (engine, port, home):
            code, _, _ = self._run_verifier(
                engine, port, home, use_gate=False,
                behavior_override={"immediate_critical_stop": True},
            )
            self.assertEqual(code, 1)
            run_dir = next(self.output_dir.iterdir())
            s4_ev = json.loads((run_dir / "04_critical_locked" / "evidence.json").read_text(encoding="utf-8"))
            self.assertEqual(s4_ev["status"], "失败")
            # Hub recorded locked in audit
            self.assertTrue(s4_ev["assertions"]["audit_recorded_locked"])
            # Consecutive approve probes were cut short
            self.assertFalse(s4_ev["assertions"]["consecutive_approves_returned_locked"])
            # Explanatory note is present and missing hook note is NOT shown
            joined_notes = "\n".join(s4_ev["notes"])
            self.assertIn("已被同会话后续事件", joined_notes)
            self.assertNotIn("Hub 未收到本次会话的预期钩子请求", joined_notes)

    # --------------------------------------------------------------------------
    # P2-3: Sandbox isolation & pre-existing data preservation
    # --------------------------------------------------------------------------

    def test_preexisting_files_and_directories_are_strictly_preserved(self):
        """Pre-existing files in test directory are never deleted before or after runs."""
        # Create pre-existing files and directories
        unrelated = self.test_dir / "unrelated_user_file.txt"
        unrelated.write_text("important user data\n", encoding="utf-8")
        existing_ok = self.test_dir / "ok.txt"
        existing_ok.write_text("preexisting ok\n", encoding="utf-8")
        existing_high = self.test_dir / "_verify_high_sandbox" / "target" / "old.txt"
        existing_high.parent.mkdir(parents=True, exist_ok=True)
        existing_high.write_text("old canary\n", encoding="utf-8")

        with temporary_hub_server() as (engine, port, home):
            code, _, _ = self._run_verifier(engine, port, home, use_gate=False)
            self.assertEqual(code, 0)

            # Pre-existing files must be completely intact!
            self.assertTrue(unrelated.is_file())
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "important user data\n")
            self.assertTrue(existing_ok.is_file())
            self.assertEqual(existing_ok.read_text(encoding="utf-8"), "preexisting ok\n")
            self.assertTrue(existing_high.is_file())
            self.assertEqual(existing_high.read_text(encoding="utf-8"), "old canary\n")

            # Unique run sandbox should be cleaned up
            remaining_sandboxes = list(self.test_dir.glob(vrs.SANDBOX_PREFIX + "*"))
            self.assertEqual(len(remaining_sandboxes), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
