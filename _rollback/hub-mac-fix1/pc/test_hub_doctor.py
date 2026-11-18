"""Offline doctor checks; no real hooks, credentials, network, or CLI calls."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hub_doctor
import hub_install


class DoctorTests(unittest.TestCase):
    def setUp(self):
        platform = patch.object(hub_doctor.sys, "platform", "win32")
        platform.start()
        self.addCleanup(platform.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.output = io.StringIO()
        self.calls = []
        self.commands = []
        self.responses = {"/health": (200, {"ok": True}),
                          "/state": (200, {"agents_seen": {"cc": 950, "cx": 1000}})}
        self.auth_result = SimpleNamespace(returncode=0, stdout='{"loggedIn":true}')
        self.mac_results = {"return 1": SimpleNamespace(returncode=0, stdout="1\n", stderr=""),
                            'tell application "System Events" to get UI elements enabled':
                            SimpleNamespace(returncode=0, stdout="true\n", stderr="")}
        token = self.home / ".agentdeck" / "token"
        token.parent.mkdir()
        token.write_text("test-token\n", encoding="utf-8")
        for agent, folders in hub_install.TARGETS.items():
            path = self.home.joinpath(*folders)
            path.parent.mkdir()
            data = {"hooks": {"SessionStart": [{"hooks": [
                {"type": "command", "command": hub_install.command(agent)}]}]}}
            path.write_text(json.dumps(data), encoding="utf-8")

    def connection(self, host, port, timeout):
        self.assertEqual((host, port, timeout), ("127.0.0.1", 47900, 2))
        test = self

        class Connection:
            def request(self, method, path, headers):
                test.calls.append((method, path, headers))
                self.path = path

            def getresponse(self):
                result = test.responses[self.path]
                if isinstance(result, Exception):
                    raise result
                status, body = result
                raw = json.dumps(body).encode()
                return SimpleNamespace(status=status, read=lambda size: raw)

            def close(self):
                self.closed = True

        return Connection()

    def runner(self, command, **options):
        self.commands.append((command, options))
        if command[0] == "osascript":
            result = self.mac_results[command[2]]
            if isinstance(result, Exception):
                raise result
            return result
        if isinstance(self.auth_result, Exception):
            raise self.auth_result
        return self.auth_result

    def run_doctor(self):
        return hub_doctor.doctor(port=47900, home=self.home, stdout=self.output,
                                 connection_factory=self.connection, runner=self.runner,
                                 wall_time=lambda: 1000)

    def test_macos_adds_two_harmless_bounded_probes(self):
        with patch.object(hub_doctor.sys, "platform", "darwin"):
            self.assertEqual(self.run_doctor(), 0)
        self.assertEqual(self.output.getvalue().count("✓"), 9)
        self.assertEqual([command for command, _ in self.commands[1:]], [
            ["osascript", "-e", "return 1"],
            ["osascript", "-e", 'tell application "System Events" to get UI elements enabled']])
        for _, options in self.commands[1:]:
            self.assertEqual(options["timeout"], 3)
            self.assertTrue(options["capture_output"])
            self.assertFalse(options["check"])

    def test_macos_missing_osascript_logs_and_reports_without_raising(self):
        self.mac_results = {script: FileNotFoundError("osascript unavailable")
                            for script in self.mac_results}
        with patch.object(hub_doctor.sys, "platform", "darwin"), self.assertLogs(hub_doctor.log, "WARNING") as logs:
            self.assertEqual(self.run_doctor(), 1)
        self.assertEqual(self.output.getvalue().count("✗"), 2)
        self.assertIn("macOS osascript", self.output.getvalue())
        self.assertIn("辅助功能 / 自动化", self.output.getvalue())
        self.assertEqual(sum("macOS permissions:" in message for message in logs.output), 1)

    def test_macos_accessibility_denied_or_timeout_has_permission_guidance(self):
        script = 'tell application "System Events" to get UI elements enabled'
        for result in (SimpleNamespace(returncode=0, stdout="false\n", stderr=""),
                       SimpleNamespace(returncode=1, stdout="", stderr="not authorized (-1743)"),
                       subprocess.TimeoutExpired("osascript", 3)):
            with self.subTest(result=result):
                self.mac_results[script] = result
                self.output = io.StringIO()
                with patch.object(hub_doctor.sys, "platform", "darwin"), self.assertLogs(hub_doctor.log, "WARNING"):
                    self.assertEqual(self.run_doctor(), 1)
                self.assertEqual(self.output.getvalue().count("✗"), 1)
                self.assertIn("✗ macOS accessibility", self.output.getvalue())
                self.assertIn("系统设置", self.output.getvalue())

    def test_macos_relay_detection_understands_posix_quoted_paths(self):
        with patch.object(hub_doctor.sys, "platform", "darwin"), patch.object(
                hub_install, "SCRIPT", "/Users/test/Hub's workspace/pc/hub_relay.py"):
            for agent, folders in hub_install.TARGETS.items():
                data = {"hooks": {"SessionStart": [{"hooks": [{"type": "command",
                    "command": hub_install.command(agent, python="/Users/test/My env/bin/python3")}]}]}}
                self.home.joinpath(*folders).write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(self.run_doctor(), 0)
        self.assertNotIn("✗", self.output.getvalue())

    def test_all_checks_pass_and_state_is_authenticated(self):
        before = {path.relative_to(self.home): path.read_bytes()
                  for path in self.home.rglob("*") if path.is_file()}
        self.assertEqual(self.run_doctor(), 0)
        self.assertEqual(self.output.getvalue().count("✓"), 7)
        self.assertNotIn("✗", self.output.getvalue())
        self.assertEqual(self.calls, [("GET", "/health", {}),
                                     ("GET", "/state", {"X-AgentDeck-Token": "test-token"})])
        self.assertEqual(self.commands[0][0], ["claude", "auth", "status"])
        self.assertEqual(self.commands[0][1]["timeout"], 5)
        self.assertFalse(self.commands[0][1]["check"])
        self.assertEqual(before, {path.relative_to(self.home): path.read_bytes()
                                 for path in self.home.rglob("*") if path.is_file()})

    def test_empty_home_advice_without_creating_files_or_logging_in(self):
        self.home = self.home / "missing home"
        self.responses["/health"] = OSError("offline")
        self.auth_result = FileNotFoundError("claude")
        self.assertEqual(self.run_doctor(), 1)
        self.assertFalse(self.home.exists())
        self.assertEqual(self.output.getvalue().count("✗"), 7)
        for advice in ("start python pc/hub.py", "nonempty token", "install cc", "install cx",
                       "在 Codex 里输入 /hooks 信任 AgentDeck 钩子", "运行 claude 登录"):
            self.assertIn(advice, self.output.getvalue())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.commands), 1)

    def test_stale_missing_future_and_invalid_agent_timestamps(self):
        for stamp in (None, 399, 1001, "950", True, float("nan"), float("inf")):
            with self.subTest(stamp=stamp):
                self.output = io.StringIO()
                self.responses["/state"] = (200, {"agents_seen": {"cc": stamp, "cx": stamp}})
                self.assertEqual(self.run_doctor(), 1)
                self.assertIn("✗ cc event", self.output.getvalue())
                self.assertIn("在 Codex 里输入 /hooks 信任 AgentDeck 钩子", self.output.getvalue())
        self.output = io.StringIO()
        self.responses["/state"] = (200, {"agents_seen": {"cc": 400, "cx": 400}})
        self.assertEqual(self.run_doctor(), 0)

    def test_health_and_protected_state_failures_print_guidance(self):
        for route, result in (("/health", (503, {})), ("/health", (200, {"ok": False})),
                              ("/health", (200, [])), ("/state", (401, {})),
                              ("/state", OSError("timeout")), ("/state", (200, [])),
                              ("/state", (200, {"agents_seen": []}))):
            with self.subTest(route=route, result=result):
                self.responses = {"/health": (200, {"ok": True}),
                                  "/state": (200, {"agents_seen": {"cc": 950, "cx": 1000}})}
                self.responses[route] = result
                self.output = io.StringIO()
                self.assertEqual(self.run_doctor(), 1)
                self.assertIn("ensure Hub is running", self.output.getvalue())

    def test_token_empty_or_unreadable_does_not_make_protected_request(self):
        path = self.home / ".agentdeck" / "token"
        for data in (b"\n", b"\xff"):
            path.write_bytes(data)
            self.output = io.StringIO()
            self.calls.clear()
            self.assertEqual(self.run_doctor(), 1)
            self.assertIn("✗ Token file", self.output.getvalue())
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(path.read_bytes(), data)

    def test_hook_detection_requires_executed_relay_and_correct_agent(self):
        path = self.home.joinpath(*hub_install.TARGETS["cx"])
        invalid = ["{bad", "[]", '{"hooks":[]}',
                   json.dumps({"note": "hub_relay.py"}),
                   json.dumps({"hooks": {"Stop": [{"hooks": [
                       {"type": "command", "command": 'python other.py --note "hub_relay.py"'}]}]}}),
                   json.dumps({"hooks": {"Stop": [{"hooks": [
                       {"type": "command", "command": hub_install.command("cc")}]}]}})]
        for data in invalid:
            with self.subTest(data=data):
                path.write_text(data, encoding="utf-8")
                self.output = io.StringIO()
                self.assertEqual(self.run_doctor(), 1)
                self.assertIn("✗ cx hub_relay hook", self.output.getvalue())
                self.assertIn("install cx", self.output.getvalue())

    def test_auth_timeout_missing_login_unknown_and_text_status(self):
        failed = [subprocess.TimeoutExpired(["claude", "auth", "status"], 5),
                  FileNotFoundError("claude"),
                  SimpleNamespace(returncode=1, stdout='{"loggedIn":true}'),
                  SimpleNamespace(returncode=0, stdout='{"loggedIn":false}'),
                  SimpleNamespace(returncode=0, stdout='{"authMethod":"none"}'),
                  SimpleNamespace(returncode=0, stdout="not logged in"),
                  SimpleNamespace(returncode=0, stdout="")]
        for result in failed:
            with self.subTest(result=result):
                self.auth_result = result
                self.output = io.StringIO()
                self.assertEqual(self.run_doctor(), 1)
                self.assertIn("✗ Claude login: 运行 claude 登录", self.output.getvalue())
        for text in ("Logged in as user@example.test", "Logged in using API key"):
            self.auth_result = SimpleNamespace(returncode=0, stdout=text)
            self.output = io.StringIO()
            self.assertEqual(self.run_doctor(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
