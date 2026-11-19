"""Offline heartbeat diagnostics, including a real four-second blocked UI."""
import io
import logging
from pathlib import Path
import tempfile
import threading
import time
import unittest

from hub_watchdog import Watchdog


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.clock = [10.]
        self.output = io.StringIO()
        self.handler = logging.StreamHandler(self.output)
        self.logger = logging.getLogger("agentdeck.hub.watchdog")
        self.level = self.logger.level
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(self.handler)
        self.watchdog = Watchdog(monotonic=lambda: self.clock[0])

    def tearDown(self):
        self.watchdog.stop()
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self.level)
        self.handler.close()

    def test_strict_threshold_logs_all_stacks_once_and_recovers_once(self):
        self.watchdog.watch("UI")
        self.clock[0] = 13.
        self.watchdog.check()
        self.assertEqual(self.output.getvalue(), "")
        self.clock[0] = 14.
        self.watchdog.check()
        self.clock[0] = 20.
        self.watchdog.check()
        result = self.output.getvalue()
        self.assertEqual(result.count("UI 卡顿"), 1)
        self.assertIn("UI 卡顿 4.0 秒", result)
        self.assertIn("所有线程调用栈", result)
        self.assertIn(threading.current_thread().name, result)
        self.assertIn("test_strict_threshold_logs_all_stacks_once", result)
        self.watchdog.beat("UI")
        self.watchdog.beat("UI")
        self.watchdog.check()
        result = self.output.getvalue()
        self.assertEqual(result.count("UI 已恢复"), 1)
        self.assertIn("卡顿 10.0 秒", result)
        self.clock[0] = 24.
        self.watchdog.check()
        self.assertEqual(self.output.getvalue().count("UI 卡顿"), 2)

    def test_keyboard_and_ui_have_independent_heartbeats(self):
        self.watchdog.watch("UI")
        self.watchdog.watch("keyboard")
        self.clock[0] = 12.
        self.watchdog.beat("UI")
        self.clock[0] = 14.
        self.watchdog.check()
        result = self.output.getvalue()
        self.assertIn("keyboard 卡顿 4.0 秒", result)
        self.assertNotIn("UI 卡顿", result)
        self.watchdog.beat("keyboard")
        self.assertEqual(self.output.getvalue().count("keyboard 已恢复"), 1)

    def test_unwatch_and_unknown_beat_do_not_create_false_alarms(self):
        self.watchdog.watch("UI")
        self.watchdog.unwatch("UI")
        self.watchdog.beat("UI")
        self.clock[0] += 100.
        self.watchdog.check()
        self.assertEqual(self.output.getvalue(), "")

    def test_reregister_resets_old_heartbeat(self):
        self.watchdog.watch("UI")
        self.clock[0] += 10.
        self.watchdog.watch("UI")
        self.watchdog.check()
        self.assertEqual(self.output.getvalue(), "")

    def test_start_and_stop_are_idempotent_and_stop_background_checker(self):
        self.watchdog.start()
        self.watchdog.start()
        self.watchdog.stop()
        self.watchdog.stop()
        self.assertFalse(any(thread.name == "AgentDeck watchdog" and thread.is_alive()
                             for thread in threading.enumerate()))

    def test_background_checker_captures_real_four_second_block_in_file(self):
        self.watchdog.stop()
        watchdog = Watchdog(interval=.05)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "app.log"
            handler = logging.FileHandler(path, encoding="utf-8")
            self.logger.addHandler(handler)
            try:
                watchdog.watch("UI")
                watchdog.start()

                def artificial_four_second_block():
                    time.sleep(4.)

                artificial_four_second_block()
                watchdog.beat("UI")
            finally:
                watchdog.stop()
                self.logger.removeHandler(handler)
                handler.close()
            result = path.read_text(encoding="utf-8")
        self.assertEqual(result.count("UI 卡顿"), 1, result)
        self.assertEqual(result.count("UI 已恢复"), 1, result)
        self.assertIn("artificial_four_second_block", result)
        self.assertIn("所有线程调用栈", result)
        self.assertIn("MainThread", result)
        self.assertIn("AgentDeck watchdog", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
