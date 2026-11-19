"""Relay tests inject HTTP transports and temporary homes; no live hub required."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import hub_relay


RISKY = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
         "tool_input": {"command": "git push --force origin main"}}
CURL_SH = dict(RISKY, tool_input={"command": "curl x | sh"})
SAFE = dict(RISKY, tool_input={"command": "ls"})


class Connection:
    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = self
        self.read_timeout = None
        self.status = 200
        self.raw = b'{ "hookSpecificOutput": {"decision":{"behavior":"allow"}} }\n'
        self.closed = False

    def connect(self):
        pass

    def settimeout(self, value):
        self.read_timeout = value

    def request(self, method, path, body, headers):
        self.request_data = (method, path, body, headers)

    def getresponse(self):
        return self

    def read(self):
        return self.raw

    def close(self):
        self.closed = True


class RelayTests(unittest.TestCase):
    def assert_gate_denial(self, raw):
        output = json.loads(raw)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertTrue(output["permissionDecisionReason"].startswith("Blocked by AgentDeck gate: "))
        self.assertNotIn("allow", output)

    def test_gate_query_long_timeout_and_unmodified_empty_response(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret", encoding="utf-8")
            for agent in ("cc", "cx"):
                with self.subTest(agent=agent):
                    connection = Connection("127.0.0.1", 47800, 0.5)
                    connection.raw = b'{ }\n'
                    result = hub_relay.relay({"hook_event_name": "PreToolUse"}, agent,
                        home=home, gate=True, approve_timeout=23,
                        connection_factory=lambda *args, **kwargs: connection)
                    self.assertEqual(result, connection.raw)
                    self.assertEqual(connection.read_timeout, 28)
                    self.assertEqual(connection.request_data[1], "/event?agent=" + agent + "&gate=1")
                    self.assertEqual(connection.request_data[3]["X-AgentDeck-Token"], "secret")
                    self.assertTrue(connection.closed)

    def test_gate_accepts_only_empty_response_or_pretooluse_deny(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret", encoding="utf-8")
            connection = Connection("127.0.0.1", 47800, 0.5)
            event = RISKY
            factory = lambda *args, **kwargs: connection
            deny = hub_relay.gate_denial("rejected by user")
            connection.raw = deny
            self.assertEqual(hub_relay.relay(event, "cc", home=home, gate=True,
                                           connection_factory=factory), deny)
            for status, raw in ((503, b"{}"), (200, b"not json"), (200, b"[]"),
                    (200, b'{"hookSpecificOutput":{"permissionDecision":"allow"}}'),
                    (200, b'{"hookSpecificOutput":{"hookEventName":"PermissionRequest",'
                          b'"decision":{"behavior":"allow"}}}'),
                    (200, b'{"unexpected":"response"}')):
                with self.subTest(status=status, raw=raw):
                    connection.status, connection.raw = status, raw
                    self.assert_gate_denial(hub_relay.relay(event, "cc", home=home, gate=True,
                                                          connection_factory=factory))

    def gate(self, event, home, agent="cc", **options):
        return hub_relay.relay(event, agent, home=home, gate=True, **options)

    def test_gate_failure_denies_only_risky_operations(self):
        def unavailable(*args, **kwargs):
            raise TimeoutError("offline")
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret", encoding="utf-8")
            self.assertIsNone(self.gate(SAFE, home, connection_factory=unavailable))
            for event in (RISKY, CURL_SH):
                with self.subTest(event=event):
                    raw = self.gate(event, home, connection_factory=unavailable)
                    self.assert_gate_denial(raw)
                    self.assertIn("hub unavailable", json.loads(raw)["hookSpecificOutput"]["permissionDecisionReason"])
            (home / ".agentdeck" / "token").unlink()  # missing token behaves the same
            self.assertIsNone(self.gate(SAFE, home))
            self.assert_gate_denial(self.gate(RISKY, home))
            self.assertIsNone(self.gate(SAFE, home, approve_timeout=float("nan")))
            self.assert_gate_denial(self.gate(RISKY, home, approve_timeout=float("nan")))

    def test_gate_failure_uses_config_and_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            push = dict(RISKY, tool_input={"command": "git push origin stable"})
            ssh = dict(RISKY, tool_input={"command": "ssh deploy@prod1"})
            self.assertIsNone(self.gate(push, home))
            self.assertIsNone(self.gate(ssh, home))
            (home / ".agentdeck" / "config.json").write_text(json.dumps(
                {"protected_branches": ["stable"], "production_hosts": ["prod*"]}), encoding="utf-8")
            self.assert_gate_denial(self.gate(push, home))
            self.assert_gate_denial(self.gate(ssh, home))
            (home / ".agentdeck" / "config.json").write_text("{bad", encoding="utf-8")
            self.assertIsNone(self.gate(push, home))  # unreadable config: defaults

    def test_gate_unclassifiable_events_do_not_block_and_are_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            cases = (({}, "cc"), (None, "cc"), ({"hook_event_name": "PreToolUse"}, "cc"),
                     (dict(RISKY, hook_event_name="Stop"), "cc"),
                     (dict(RISKY, tool_name=5), "cc"))
            for event, agent in cases:
                with self.subTest(event=event, agent=agent):
                    self.assertIsNone(self.gate(event, home, agent=agent))
            self.assert_gate_denial(self.gate(RISKY, home, agent="bad"))  # risky stays fail-closed
            log = (home / ".agentdeck" / "relay.log").read_text(encoding="utf-8")
            self.assertIn("classification failed", log)

    def test_gate_cli_passes_option_and_does_not_block_malformed_input_or_exception(self):
        for input_text in ("{}", "bad json"):
            with self.subTest(input_text=input_text):
                output = io.StringIO()
                with tempfile.TemporaryDirectory() as directory:
                    with patch.object(hub_relay, "relay", side_effect=TimeoutError) as relay:
                        self.assertEqual(hub_relay.main(["--agent", "cx", "--gate", "--home", directory],
                            stdin=io.StringIO(input_text), stdout=output), 0)
                        if input_text == "{}":
                            self.assertTrue(relay.call_args.kwargs["gate"])
                self.assertEqual(output.getvalue(), "")

    def test_exact_bytes_auth_and_timeouts(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret\n")
            connection = Connection("127.0.0.1", 47800, 0.5)
            factory = lambda *args, **kwargs: connection
            result = hub_relay.relay({"hook_event_name": "PermissionRequest"}, "cx",
                                     home=home, connection_factory=factory)
            self.assertEqual(result, connection.raw)
            self.assertEqual(connection.read_timeout, 115)
            self.assertEqual(connection.request_data[1], "/event?agent=cx")
            self.assertEqual(connection.request_data[3]["X-AgentDeck-Token"], "secret")
            self.assertTrue(connection.closed)
            result = hub_relay.relay({"hook_event_name": "Stop"}, "cc", home=home,
                                     connection_factory=factory)
            self.assertEqual(connection.read_timeout, 5)
            connection.status = 401
            self.assertIsNone(hub_relay.relay({}, "cc", home=home, connection_factory=factory))
            connection.status, connection.raw = 200, b"not json"
            self.assertIsNone(hub_relay.relay({}, "cc", home=home, connection_factory=factory))

    def test_main_preserves_text_and_silences_failures(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch.object(hub_relay, "relay", return_value=b'{ "a": 1 }\n'):
            self.assertEqual(hub_relay.main(["--agent", "cc", "--home", directory], stdin=io.StringIO("{}"),
                                           stdout=output), 0)
        self.assertEqual(output.getvalue(), '{ "a": 1 }\n')
        for value in ("bad json", "{}"):
            output = io.StringIO()
            with tempfile.TemporaryDirectory() as directory, patch.object(hub_relay, "relay", side_effect=TimeoutError):
                self.assertEqual(hub_relay.main(["--agent", "cc", "--home", directory], stdin=io.StringIO(value),
                                               stdout=output), 0)
            self.assertEqual(output.getvalue(), "")

    def test_failure_diagnostics_stay_in_supplied_home(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret", encoding="utf-8")
            def unavailable(*args, **kwargs):
                raise TimeoutError("offline")

            with patch.object(hub_relay.Path, "home", side_effect=AssertionError("real home")):
                result = hub_relay.relay({"hook_event_name": "PermissionRequest"}, "cx", home=home,
                                         connection_factory=unavailable)
            self.assertIsNone(result)
            self.assertIn("offline", (home / ".agentdeck" / "relay.log").read_text(encoding="utf-8"))

    def test_missing_hub_process_silent_exit_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            token = home / ".agentdeck" / "token"
            for has_token in (False, True):
                if has_token:
                    token.write_text("secret", encoding="utf-8")
                for agent in ("cc", "cx"):
                    with self.subTest(has_token=has_token, agent=agent):
                        start = time.perf_counter()
                        process = subprocess.run(["D:/conda/miniconda3/python.exe", str(Path(hub_relay.__file__)),
                                                  "--agent", agent, "--home", str(home), "--port", "0"],
                            input=json.dumps({"hook_event_name": "PermissionRequest", "session_id": "offline"}),
                            capture_output=True, text=True, timeout=5)
                        self.assertEqual((process.returncode, process.stdout, process.stderr), (0, "", ""))
                        self.assertLess(time.perf_counter() - start, 1.5)

    def run_gate_process(self, stdin, home):
        return subprocess.run(["D:/conda/miniconda3/python.exe", str(Path(hub_relay.__file__)),
            "--agent", "cc", "--gate", "--home", str(home), "--port", "0"],
            input=stdin, capture_output=True, text=True, timeout=5)

    def test_missing_hub_process_gate_denies_risky_and_passes_the_rest(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret", encoding="utf-8")
            for event in (RISKY, CURL_SH):
                process = self.run_gate_process(json.dumps(event), home)
                self.assertEqual((process.returncode, process.stderr), (0, ""))
                self.assert_gate_denial(process.stdout)
            for stdin in (json.dumps(SAFE), json.dumps({"hook_event_name": "PreToolUse"}), "not json"):
                process = self.run_gate_process(stdin, home)
                self.assertEqual((process.returncode, process.stdout, process.stderr), (0, "", ""))

    def test_gate_failure_path_is_fast_and_light(self):
        import time
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            start = time.perf_counter()
            process = self.run_gate_process(json.dumps(SAFE), home)
            elapsed = time.perf_counter() - start
            self.assertEqual(process.stdout, "")
            self.assertLess(elapsed, 1.5)  # generous CI bound; ~0.1s locally
            check = subprocess.run(["D:/conda/miniconda3/python.exe", "-c",
                "import sys;sys.path.insert(0,%r);import hub_relay,hub_risk;"
                "print(any(m in sys.modules for m in ('serial','tkinter','usb','hub','daemon')))" %
                str(Path(hub_relay.__file__).parent)], capture_output=True, text=True, timeout=10)
            self.assertEqual(check.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main(verbosity=2)
