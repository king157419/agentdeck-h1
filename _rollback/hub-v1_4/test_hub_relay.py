"""Relay tests inject HTTP transports and temporary homes; no live hub required."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hub_relay


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
            event = {"hook_event_name": "PreToolUse"}
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

    def test_gate_failure_denies_including_missing_token_and_invalid_event(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            cases = (({}, "cc", {}), ({"hook_event_name": "PreToolUse"}, "bad", {}),
                     (None, "cc", {}), ({"hook_event_name": "PreToolUse"}, "cc", {}),
                     ({"hook_event_name": "PreToolUse"}, "cc", {"approve_timeout": float("nan")}))
            for event, agent, options in cases:
                with self.subTest(event=event, agent=agent, options=options):
                    self.assert_gate_denial(hub_relay.relay(event, agent, home=home, gate=True,
                                                          **options))
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret", encoding="utf-8")
            def unavailable(*args, **kwargs):
                raise TimeoutError("offline")
            self.assert_gate_denial(hub_relay.relay({"hook_event_name": "PreToolUse"}, "cc",
                home=home, gate=True, connection_factory=unavailable))

    def test_gate_cli_passes_option_and_denies_malformed_input_or_exception(self):
        for input_text in ("{}", "bad json"):
            with self.subTest(input_text=input_text):
                output = io.StringIO()
                with patch.object(hub_relay, "relay", side_effect=TimeoutError) as relay:
                    self.assertEqual(hub_relay.main(["--agent", "cx", "--gate"],
                        stdin=io.StringIO(input_text), stdout=output), 0)
                    if input_text == "{}":
                        self.assertTrue(relay.call_args.kwargs["gate"])
                self.assert_gate_denial(output.getvalue())

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
        with patch.object(hub_relay, "relay", return_value=b'{ "a": 1 }\n'):
            self.assertEqual(hub_relay.main(["--agent", "cc"], stdin=io.StringIO("{}"),
                                           stdout=output), 0)
        self.assertEqual(output.getvalue(), '{ "a": 1 }\n')
        for value in ("bad json", "{}"):
            output = io.StringIO()
            with patch.object(hub_relay, "relay", side_effect=TimeoutError):
                self.assertEqual(hub_relay.main(["--agent", "cc"], stdin=io.StringIO(value),
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
            (home / ".agentdeck" / "token").write_text("secret")
            process = subprocess.run(["D:/conda/miniconda3/python.exe", str(Path(hub_relay.__file__)),
                                      "--agent", "cc", "--home", str(home), "--port", "0"],
                                     input="{}", capture_output=True, text=True, timeout=5)
            self.assertEqual((process.returncode, process.stdout, process.stderr), (0, "", ""))

    def test_missing_hub_process_gate_emits_deny_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret", encoding="utf-8")
            process = subprocess.run(["D:/conda/miniconda3/python.exe", str(Path(hub_relay.__file__)),
                "--agent", "cc", "--gate", "--home", str(home), "--port", "0"],
                input=json.dumps({"hook_event_name": "PreToolUse"}),
                capture_output=True, text=True, timeout=5)
            self.assertEqual((process.returncode, process.stderr), (0, ""))
            self.assert_gate_denial(process.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
