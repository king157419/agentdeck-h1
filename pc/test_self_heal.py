"""Offline coverage for AgentDeck recovery and diagnostics."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from queue import SimpleQueue
from unittest.mock import Mock, patch

import agentdeck_app as app
import hub
import hub_relay as relay


TURN = {"hook_event_name": "Stop"}
GATE = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
        "tool_input": {"command": "git push --force origin main"}}


@unittest.skipUnless(sys.platform == "win32", "Windows task recovery")
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.directory = self.home / ".agentdeck"
        self.directory.mkdir()
        (self.directory / "token").write_text("test", encoding="utf-8")
        self.marker = self.directory / "hub.json"
        self.marker.write_text(json.dumps({"pid": os.getpid(), "port": 47800, "created": 1}))
        created = patch.object(relay, "process_created", return_value=2)
        self.created = created.start()
        self.addCleanup(created.stop)
        runner = patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0))
        self.run_task = runner.start()
        self.addCleanup(runner.stop)
        window = patch.object(relay, "find_agent_window", return_value=None)
        window.start()
        self.addCleanup(window.stop)

    def send(self, event=TURN, **kwargs):
        return relay.relay(event, "cc", home=self.home, **kwargs)

    def test_reused_pid_restarts_and_persists_cooldown(self):
        self.assertEqual(relay.hub_status(self.home, 47800), "down")

        def run(*args, **kwargs):
            stamp = json.loads((self.directory / "relay_restart.json").read_text())
            attempted_at, = stamp["attempts"]
            self.assertLess(time.time() - attempted_at, 3)
            return subprocess.CompletedProcess([], 0)

        self.run_task.side_effect = run
        self.assertIsNone(self.send())
        self.assertIsNone(self.send())
        self.run_task.assert_called_once()
        command, = self.run_task.call_args.args
        self.assertEqual(Path(command[0]).name.lower(), "schtasks.exe")
        self.assertEqual(command[1:], ["/Run", "/TN", "AgentDeck"])
        self.assertEqual(self.run_task.call_args.kwargs,
                         {"creationflags": subprocess.CREATE_NO_WINDOW, "timeout": 3, "capture_output": True})
        self.assertIn("已请计划任务启动 AgentDeck", (self.directory / "relay.log").read_text(encoding="utf-8"))

    def test_fourth_restart_is_skipped_and_logged_once_per_pause(self):
        message = "15 分钟内已尝试 3 次仍未起来，暂停自动启动"
        with patch.object(relay.time, "time", return_value=1000) as clock:
            for now in (1000, 1060, 1120, 1180):
                clock.return_value = now
                self.send()
            self.assertEqual(self.run_task.call_count, 3)
            log = self.directory / "relay.log"
            self.assertEqual(log.read_text(encoding="utf-8").count(message), 1)
            clock.return_value = 1899
            self.send()
            self.assertEqual(self.run_task.call_count, 3)
            self.assertEqual(log.read_text(encoding="utf-8").count(message), 1)

    def test_restart_resumes_when_oldest_attempt_leaves_window(self):
        path = self.directory / "relay_restart.json"
        path.write_text(json.dumps({"attempts": [1000, 1100, 1160], "pause_logged": True}))
        with patch.object(relay.time, "time", return_value=1901) as clock:
            self.send()
            self.run_task.assert_called_once()
            self.assertEqual(json.loads(path.read_text())["attempts"], [1100, 1160, 1901])
            clock.return_value = 1961
            self.send()
            self.run_task.assert_called_once()
        self.assertIn("15 分钟内已尝试 3 次仍未起来，暂停自动启动",
                      (self.directory / "relay.log").read_text(encoding="utf-8"))

    def test_legacy_restart_stamp_counts_toward_cooldown_and_window(self):
        path = self.directory / "relay_restart.json"
        path.write_text('{"attempted_at": 1000}')
        with patch.object(relay.time, "time", return_value=1059) as clock:
            self.send()
            self.run_task.assert_not_called()
            for now in (1060, 1120, 1180):
                clock.return_value = now
                self.send()
        self.assertEqual(self.run_task.call_count, 2)
        self.assertEqual(json.loads(path.read_text())["attempts"], [1000, 1060, 1120])

    def test_quit_and_fresh_maintenance_suppress_recovery(self):
        prefs = self.directory / "app.json"
        prefs.write_text('{"quit_by_user":true}')
        self.assertIsNone(self.send())
        prefs.unlink()
        marker = self.directory / "maintenance"
        marker.touch()
        self.assertIsNone(self.send())
        self.run_task.assert_not_called()
        old = time.time() - 901
        os.utime(marker, (old, old))
        self.assertIsNone(self.send())
        self.run_task.assert_called_once()

    def test_scheduler_failure_preserves_gate_result(self):
        self.run_task.return_value = subprocess.CompletedProcess([], 1, b"", b"Task not found")
        expected = relay.gate_failure(GATE, "cc", self.home, "hub not running")
        self.assertEqual(self.send(GATE, gate=True), expected)
        self.assertIsNone(self.send())
        self.run_task.assert_called_once()
        self.assertIn("Task not found", (self.directory / "relay.log").read_text(encoding="utf-8"))

    def test_scheduler_timeout_preserves_hook_result(self):
        self.run_task.side_effect = subprocess.TimeoutExpired("schtasks.exe", 3)
        self.assertIsNone(self.send())
        self.run_task.assert_called_once()
        self.assertIn("TimeoutExpired", (self.directory / "relay.log").read_text(encoding="utf-8"))

    def test_live_hub_with_refused_connection_does_not_restart(self):
        self.created.return_value = 1
        transport = Mock()
        transport.connect.side_effect = ConnectionRefusedError("busy")
        with patch("http.client.HTTPConnection", return_value=transport):
            self.assertIsNone(self.send())
        self.run_task.assert_not_called()

    def test_connect_failure_rechecks_process_identity(self):
        for error in (ConnectionRefusedError, TimeoutError):
            with self.subTest(error=error), patch.object(relay, "hub_status", side_effect=["up", "down"]), \
                    patch("http.client.HTTPConnection") as transport:
                transport.return_value.connect.side_effect = error("gone")
                self.assertIsNone(self.send())
                (self.directory / "relay_restart.json").unlink()
        self.assertEqual(self.run_task.call_count, 2)

    def test_live_legacy_marker_uses_pid_only(self):
        self.marker.write_text(json.dumps({"pid": os.getpid(), "port": 47800}))
        self.assertEqual(relay.hub_status(self.home, 47800), "up")
        self.created.assert_not_called()


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)

    def test_marker_records_creation_time(self):
        with patch.object(hub, "process_created", return_value=123) as created:
            path = hub.write_hub_marker(self.home, 47800)
        created.assert_called_once_with(os.getpid())
        self.assertEqual(json.loads(path.read_text()), {"pid": os.getpid(), "port": 47800, "created": 123})

    def test_menu_quit_persists_before_stop_and_startup_clears_flag(self):
        prefs = app.Preferences(self.home)
        tray = app.TrayApplication(Mock(home=self.home), commands=SimpleQueue(), prefs=prefs,
                                   keys_path=None, autostart=Mock(), overlay=Mock())
        tray.overlay.stop.side_effect = lambda: self.assertIs(app.Preferences(self.home).values["quit_by_user"], True)
        with self.assertLogs(app.log) as logs:
            tray.dispatch("quit")
        tray.overlay.stop.assert_called_once()
        self.assertIn("菜单退出", "\n".join(logs.output))
        with patch.object(app, "SingleInstance"), patch.object(hub, "main", return_value=0), \
                patch.object(app, "repair_global_hooks"):
            self.assertEqual(app.main(["--home", str(self.home)]), 0)
        self.assertIs(app.Preferences(self.home).values["quit_by_user"], False)
        log_text = (app.data_dir(self.home) / "logs" / "app.log").read_text(encoding="utf-8")
        self.assertIn("AgentDeck 启动：pid=", log_text)
        self.assertIn("主循环结束", log_text)

    def test_hooks_log_tracebacks_and_crash_file_stays_open(self):
        (app.data_dir(self.home) / "logs").mkdir(parents=True)
        original = (sys.excepthook, threading.excepthook)
        with patch.object(app.faulthandler, "enable") as enable, patch.object(app.faulthandler, "disable"), \
                self.assertLogs(app.log, level="ERROR") as logs, app.crash_diagnostics(self.home):
            self.assertIsNot(sys.excepthook, original[0])
            self.assertIsNot(threading.excepthook, original[1])
            crash_file = enable.call_args.kwargs["file"]
            self.assertFalse(crash_file.closed)
            try:
                raise RuntimeError("test exception")
            except RuntimeError:
                details = sys.exc_info()
                sys.excepthook(*details)
                threading.excepthook(threading.ExceptHookArgs((*details, threading.current_thread())))
        self.assertEqual((sys.excepthook, threading.excepthook), original)
        self.assertTrue(crash_file.closed)
        self.assertEqual(sum("RuntimeError: test exception" in entry for entry in logs.output), 2)

    def test_startup_failure_logs_reason_and_error(self):
        from tkinter import messagebox

        with patch.object(app, "SingleInstance"), patch.object(messagebox, "showerror") as dialog, \
                patch.object(app, "prepare_configs", side_effect=ValueError("invalid key map")):
            self.assertEqual(app.main(["--home", str(self.home)]), 1)
        dialog.assert_called_once()
        log_text = (app.data_dir(self.home) / "logs" / "app.log").read_text(encoding="utf-8")
        self.assertIn("启动失败", log_text)
        self.assertIn("ValueError: invalid key map", log_text)

    def test_heartbeat_uses_existing_snapshot_every_thirty_minutes(self):
        engine, overlay = Mock(home=self.home), Mock()
        overlay.state = {"input_reader": "usb", "sessions": []}
        with patch.object(app.time, "monotonic", return_value=10) as clock:
            tray = app.TrayApplication(engine, commands=SimpleQueue(), prefs=app.Preferences(self.home),
                                       keys_path=None, autostart=Mock(), overlay=overlay)
            tray._background_enabled = True
            tray.icon = Mock()
            with self.assertLogs(app.log) as logs:
                for now in (1809, 1810, 1811, 3609, 3610):
                    clock.return_value = now
                    tray.pump()
        engine.state.assert_not_called()
        self.assertEqual(sum("运行中：读键方式=usb，会话=0" in entry for entry in logs.output), 2)


if __name__ == "__main__":
    unittest.main()
