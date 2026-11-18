"""Relay tests inject HTTP transports and temporary homes; no live hub required."""
import io
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

    def test_missing_hub_process_silent_exit_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret")
            process = subprocess.run(["D:/conda/miniconda3/python.exe", str(Path(hub_relay.__file__)),
                                      "--agent", "cc", "--home", str(home), "--port", "0"],
                                     input="{}", capture_output=True, text=True, timeout=5)
            self.assertEqual((process.returncode, process.stdout, process.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
