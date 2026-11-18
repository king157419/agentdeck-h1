"""Gate acceptance checks: temporary homes, fake LCD, and loopback HTTP only."""
from contextlib import nullcontext
import json
import http.client
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import hub
import hub_relay


class Clock:
    value = 100.0

    def __call__(self):
        return self.value


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.lines = []
        self.engine = hub.Hub(home=self.temp.name, monotonic=self.clock, approve_timeout=5,
                              sender=lambda lines, **kw: self.lines.extend(lines),
                              focus_guard=lambda **kw: nullcontext(), desktop_enabled=False,
                              hold_path=Path(self.temp.name) / "hold")
        self.addCleanup(self.engine.close)

    def event(self, command="git push origin main", name="PreToolUse", sid="first", **fields):
        return dict(hook_event_name=name, session_id=sid, cwd="C:/work/project",
                    tool_name="Bash", tool_input={"command": command}, **fields)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate():
            self.assertLess(time.monotonic(), deadline, "background request did not arrive")
            time.sleep(0.001)

    def start(self, event=None, *, gate=True, agent="cc"):
        result, errors = [], []
        event = self.event() if event is None else event

        def run():
            try:
                result.append(self.engine.event(agent, event, gate=gate))
            except Exception as error:
                errors.append(error)

        before = set(self.engine.pending)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(lambda: thread.join(1))
        self.addCleanup(self.engine.close)
        self.wait_for(lambda: bool({p["id"] for p in self.engine.state()["pending"]} - before) or bool(errors))
        self.assertEqual(errors, [])
        request = next(p for key, p in self.engine.pending.items() if key not in before)
        return thread, result, request

    def decide(self, action="approve", request=None, source="key"):
        payload = {"action": action}
        if request:
            payload["request_id"] = request.id
        return self.engine.action(payload, source=source)

    def pass_gate(self, event=None, agent="cc"):
        thread, result, request = self.start(event, agent=agent)
        self.assertEqual(self.decide(request=request)["status"], "confirm")
        self.assertTrue(thread.is_alive())
        self.assertEqual(result, [])
        self.clock.value += 0.1
        self.assertEqual(self.decide(request=request)["status"], "allowed")
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [{}])
        return request

    def assert_denial(self, result, reason=None):
        output = result["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertTrue(output["permissionDecisionReason"].startswith("Blocked by AgentDeck gate: "))
        if reason:
            self.assertIn(reason, output["permissionDecisionReason"])
        self.assertNotIn("decision", output)

    def test_low_returns_empty_in_under_50ms_without_wait_or_lcd(self):
        with patch.object(self.engine, "_send", side_effect=AssertionError("LCD on bypass")), patch.object(
                threading.Event, "wait", side_effect=AssertionError("wait on bypass")):
            start = time.perf_counter()
            self.assertEqual(self.engine.event("cc", self.event("git status"), gate=True), {})
            elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.05)
        self.assertEqual(self.engine.state()["pending"], [])
        self.assertEqual(self.engine.sessions, {})

    def test_high_and_critical_both_need_two_presses_and_never_return_allow(self):
        for agent, command in (("cc", "git push origin main"), ("cx", "rm -rf /")):
            with self.subTest(agent=agent):
                request = self.pass_gate(self.event(command), agent)
                self.assertEqual(request.risk, "critical" if agent == "cx" else "high")
                self.assertEqual(self.engine.state()["locked"], [])
        self.assertEqual([(r["decision"], r["source"]) for r in self.engine.audit.recent()],
                         [("allow", "gate"), ("allow", "gate")])

    def test_deny_and_interrupt_return_pretooluse_reason_and_audit_gate(self):
        for command in ("deny", "interrupt"):
            thread, result, request = self.start()
            self.assertEqual(self.decide(command, request, "overlay")["status"], "denied")
            thread.join(1)
            self.assert_denial(result[0], "denied by user")
            self.assertEqual(self.engine.audit.recent()[-1]["source"], "gate")
        self.assertEqual(self.engine.gate_passed, {})

    def test_real_wait_timeout_denies_instead_of_falling_back(self):
        self.engine.approve_timeout = 0.015
        self.assert_denial(self.engine.event("cx", self.event(), gate=True), "timed out")
        self.assertEqual(self.engine.audit.recent()[-1]["decision"], "timeout")
        self.assertEqual(self.engine.audit.recent()[-1]["source"], "gate")

    def test_session_end_stop_interrupt_and_shutdown_deny_waiting_gates(self):
        for event_name in ("Stop", "Interrupt", "SessionEnd"):
            thread, result, _ = self.start()
            self.engine.event("cc", self.event(name=event_name))
            thread.join(1)
            self.assert_denial(result[0], "cancelled")
        thread, result, _ = self.start()
        self.engine.close()
        thread.join(1)
        self.assert_denial(result[0])
        self.assert_denial(self.engine.event("cc", self.event(), gate=True), "shutting down")

    def test_confirmation_expires_and_is_bound_to_same_request(self):
        thread, result, first = self.start()
        self.decide(request=first)
        self.clock.value += 1.501
        self.assertEqual(self.decide(request=first)["status"], "confirm")
        self.assertEqual(result, [])
        self.decide("deny", first)
        thread.join(1)
        thread, result, second = self.start(self.event(sid="second"))
        with self.assertRaisesRegex(hub.HubError, "displayed request changed"):
            self.decide(request=first)
        self.assertEqual(self.decide(request=second)["status"], "confirm")
        self.decide("deny", second)
        thread.join(1)

    def test_repeated_gate_commands_still_require_new_double_confirmation(self):
        self.pass_gate()
        thread, result, request = self.start()
        self.assertEqual(self.decide(request=request)["status"], "confirm")
        self.assertEqual(result, [])
        self.decide("deny")
        thread.join(1)

    def test_gate_confirmation_marks_permission_but_still_requires_one_key(self):
        event = self.event()
        event["tool_input"]["extra"] = {"a": 1, "b": 2}
        self.pass_gate(event)
        permission = dict(event, hook_event_name="PermissionRequest",
                          tool_input={"extra": {"b": 2, "a": 1}, "command": "git push origin main"})
        thread, result, request = self.start(permission, gate=False)
        self.assertTrue(request.public()["gate_confirmed"])
        self.assertEqual(request.public()["gate_confirmed_message"], "已在闸门确认")
        self.assertEqual(result, [])
        self.assertTrue(thread.is_alive())
        self.assertEqual(self.decide(request=request)["status"], "allowed")
        thread.join(1)
        self.assertEqual(result, [{"hookSpecificOutput": {
            "hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}])
        self.assertEqual(self.engine.audit.recent()[-1]["source"], "key")

    def test_marker_is_scoped_to_agent_session_and_complete_tool_input(self):
        self.pass_gate()
        cases = [("cc", self.event(sid="other")), ("cx", self.event()),
                 ("cc", self.event("git push origin master"))]
        for agent, event in cases:
            thread, result, request = self.start(dict(event, hook_event_name="PermissionRequest"),
                                                  gate=False, agent=agent)
            self.assertFalse(request.gate_confirmed)
            self.assertEqual(self.decide(request=request)["status"], "confirm")
            self.decide("deny", request)
            thread.join(1)

    def test_marker_expires_at_30_seconds_and_session_end_clears_it(self):
        self.pass_gate()
        self.clock.value += hub.GATE_CONFIRMED_SECONDS
        thread, result, request = self.start(self.event(name="PermissionRequest"), gate=False)
        self.assertFalse(request.gate_confirmed)
        self.decide("deny")
        thread.join(1)
        self.pass_gate()
        self.engine.event("cc", self.event(name="SessionEnd"))
        self.assertEqual(self.engine.gate_passed, {})

    def test_critical_permission_stays_locked_after_gate_confirmation(self):
        event = self.event("rm -rf /")
        self.pass_gate(event)
        self.assertEqual(self.engine.event("cc", dict(event, hook_event_name="PermissionRequest")), {})
        request = self.engine.state()["locked"][0]
        self.assertTrue(request["gate_confirmed"])
        self.assertEqual(self.decide()["status"], "locked")

    def test_low_and_off_modes(self):
        self.engine.gate_mode = "off"
        self.assertEqual(self.engine.event("cc", self.event("rm -rf /"), gate=True), {})
        self.engine.gate_mode = "low"
        thread, result, request = self.start(self.event("echo hello"))
        self.assertEqual(request.risk, "low")
        self.assertEqual(self.decide(request=request)["status"], "allowed")
        thread.join(1)
        self.assertEqual(result, [{}])

    def test_audit_failure_never_releases_gate_and_timeout_still_denies(self):
        thread, result, request = self.start()
        self.decide(request=request)
        with patch.object(self.engine.audit, "append", side_effect=OSError("disk full")):
            with self.assertLogs("agentdeck.hub", level="ERROR"):
                with self.assertRaises(hub.HubError):
                    self.decide(request=request)
                self.assertEqual(result, [])
                self.assertEqual(self.engine.gate_passed, {})
                self.clock.value += 6
                self.engine.maintain()
                thread.join(1)
        self.assert_denial(result[0])

    def test_gate_banner_uses_existing_firmware_protocol(self):
        from test_ui import make_ui
        thread, result, request = self.start()
        ui, lcd, _ = make_ui()
        for line in self.lines:
            self.assertTrue(ui.handle(line, 0).startswith("ok "), line)
        ui.render(0)
        self.assertIn(b"GATE:", lcd.rows[1])
        self.decide(request=request)
        self.assertIn("GATE! press again", self.lines[-2])
        self.decide("deny")
        thread.join(1)

    def test_validation_before_pending_creation(self):
        for event in (self.event(name="PermissionRequest"), dict(self.event(), tool_name=[])):
            with self.assertRaises(hub.HubError):
                self.engine.event("cc", event, gate=True)
        for options in ({"gate_mode": "bad"}, {"production_hosts": "prod"},
                        {"mcp_write_tools": [None]}, {"protected_branches": {"main": True}}):
            with self.assertRaises(ValueError):
                hub.Hub(home=self.temp.name, **options)


class GateRiskTests(unittest.TestCase):
    def test_complete_default_gate_rule_categories(self):
        commands = ["git push origin main", 'git -C repo push origin "master"',
                    "git push origin HEAD:release/v1.4", "git push origin HEAD:refs/heads/main",
                    "git push origin feature --force", "git push origin +main", "git push origin +refs/heads/main",
                    "git push --all origin", "git push --mirror origin", "git push origin 'refs/heads/*:refs/heads/*'",
                    "git reset --hard HEAD", "rm -rf build",
                    "gh pr merge 123 --squash", "kubectl --context prod apply -f deployment.yml",
                    "kubectl delete pod example", "kubectl exec example -- sh",
                    "terraform apply plan", "terraform destroy", "helm upgrade app chart",
                    "DROP DATABASE app", "DROP USER fred", "ALTER ROLE fred SUPERUSER",
                    "DELETE FROM users WHERE id=1", "UPDATE users SET admin=1",
                    "UPDATE users\nSET admin=1", "ALTER TABLE users ADD flag bool",
                    "npx prisma migrate deploy", "alembic upgrade head", "python manage.py migrate", "php artisan migrate",
                    "rake db:migrate", "knex migrate:latest", "dotnet ef database update",
                    "echo x > .env.production", "cp x ~/.ssh/config", "echo x > private.pem"]
        for command in commands:
            with self.subTest(command=command):
                self.assertIn(hub.classify("Bash", {"command": command}), ("high", "critical"))
        for path in (".env", "C:/work/.env.local", "~/.ssh/id_ed25519", "C:/work/private.key",
                     "C:/work/credentials.json", "C:/work/secret.p12"):
            with self.subTest(path=path):
                self.assertIn(hub.classify("Write", {"file_path": path, "content": "x"}), ("high", "critical"))
        for command in ("git status", "git push origin feature", "SELECT * FROM users", "cat private.pem"):
            self.assertEqual(hub.classify("Bash", {"command": command}), "low")

    def test_production_hosts_protected_branches_and_mcp_write_allowlist(self):
        for command in ("ssh prod", "ssh deploy@prod", "ssh -p 2222 -i key deploy@prod uname",
                        'ssh -o "StrictHostKeyChecking=yes" PROd', "ssh -- deploy@prod",
                        "ssh -o HostName=prod alias", "ssh -oHostName=prod alias"):
            with self.subTest(command=command):
                self.assertEqual(hub.classify("Bash", {"command": command}, production_hosts=["prod"]), "high")
        self.assertEqual(hub.classify("Bash", {"command": "ssh dev"}, production_hosts=["prod"]), "low")
        self.assertEqual(hub.classify("Bash", {"command": "ssh prod"}), "low")
        self.assertEqual(hub.classify("Bash", {"command": "ssh user@[2001:db8::1]"},
                                      production_hosts=["2001:db8::1"]), "high")
        self.assertEqual(hub.classify("Bash", {"command": "git push origin stable"},
                                      protected_branches=["stable"]), "high")
        self.assertEqual(hub.classify("mcp__db__write", {}, mcp_write_tools=["mcp__db__write"]), "high")
        self.assertEqual(hub.classify("mcp__db__read", {}, mcp_write_tools=["mcp__db__write"]), "low")


class GateIntegrationTests(unittest.TestCase):
    def test_real_relay_http_gate_then_permission_and_timeout(self):
        with tempfile.TemporaryDirectory() as home:
            hub.load_token(home)
            engine = hub.Hub(home=home, lcd_enabled=False, desktop_enabled=False, approve_timeout=2)
            server = hub.HubServer(engine, hub.load_token(home), port=0)
            listener = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
            listener.start()
            worker = None
            try:
                for agent in ("cc", "cx"):
                    result = []
                    event = dict(hook_event_name="PreToolUse", session_id=agent + "-real", cwd="C:/work/app",
                                 tool_name="Bash", tool_input={"command": "git push origin main"})
                    worker = threading.Thread(target=lambda: result.append(hub_relay.relay(
                        event, agent, port=server.server_port, home=home, gate=True)), daemon=True)
                    worker.start()
                    deadline = time.monotonic() + 1
                    while not engine.state()["pending"]:
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.002)
                    self.assertEqual(engine.action({"action": "approve"})["status"], "confirm")
                    self.assertEqual(result, [])
                    engine.action({"action": "approve"})
                    worker.join(1)
                    self.assertEqual(json.loads(result[0]), {})
                    result = []
                    permission = dict(event, hook_event_name="PermissionRequest")
                    worker = threading.Thread(target=lambda: result.append(hub_relay.relay(
                        permission, agent, port=server.server_port, home=home)), daemon=True)
                    worker.start()
                    deadline = time.monotonic() + 1
                    while not engine.state()["pending"]:
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.002)
                    self.assertTrue(engine.state()["pending"][0]["gate_confirmed"])
                    self.assertEqual(result, [])
                    self.assertEqual(engine.action({"action": "approve"})["status"], "allowed")
                    worker.join(1)
                    self.assertEqual(json.loads(result[0]), {"hookSpecificOutput": {
                        "hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}})
                engine.approve_timeout = 0.01
                denied = hub_relay.relay(event, "cx", port=server.server_port, home=home, gate=True)
                self.assertEqual(json.loads(denied)["hookSpecificOutput"]["permissionDecision"], "deny")
                for query in ("gate=", "gate=0", "gate=2", "gate=1&gate=1"):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=1)
                    try:
                        connection.request("POST", "/event?agent=cx&" + query, body=json.dumps(event),
                                           headers={"X-AgentDeck-Token": hub.load_token(home)})
                        response = connection.getresponse()
                        self.assertEqual(response.status, 400)
                        response.read()
                    finally:
                        connection.close()
            finally:
                engine.close()
                server.shutdown()
                server.server_close()
                listener.join(1)
                if worker:
                    worker.join(1)

    def test_config_file_defaults_and_cli_override(self):
        with tempfile.TemporaryDirectory() as home:
            config = Path(home) / ".agentdeck" / "config.json"
            config.parent.mkdir()
            config.write_text(json.dumps({"gate_mode": "low", "production_hosts": ["prod"],
                                          "mcp_write_tools": ["mcp__db__write"]}), encoding="utf-8")
            with patch("hub.Hub") as engine, patch("hub.HubServer") as server, patch(
                    "hub.load_token", return_value="token"):
                server.return_value.serve_forever.side_effect = KeyboardInterrupt
                self.assertEqual(hub.main(["--home", home, "--no-lcd", "--no-desktop"]), 0)
                self.assertEqual(engine.call_args.kwargs["gate_mode"], "low")
                self.assertEqual(engine.call_args.kwargs["production_hosts"], ["prod"])
                self.assertEqual(hub.main(["--home", home, "--config", str(config), "--gate-mode", "off",
                                           "--no-lcd", "--no-desktop"]), 0)
                self.assertEqual(engine.call_args.kwargs["gate_mode"], "off")


if __name__ == "__main__":
    unittest.main(verbosity=2)
