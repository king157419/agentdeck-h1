"""Momentum diagnostics use fake time and never send native input."""
import ctypes
import unittest

from hub_desktop import smooth_wheel_events
from hub_scroll import SmoothScroll


class Clock:
    value = 0.0

    def __call__(self):
        return self.value


class TickStop:
    """Advance one frame per wait so the real run loop needs no thread or sleep."""
    def __init__(self, clock):
        self.clock = clock
        self.stopped = False
        self.waits = 0

    def wait(self, interval):
        self.waits += 1
        if self.waits > 1000:
            raise AssertionError("scroll run did not settle")
        self.clock.value += interval
        return self.stopped

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True


class ScrollDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.window = (1, "claude.exe", "conversation")
        self.foreground = self.window
        self.output = []
        self.fail_emit = False

        def emit(window, point, delta):
            if self.fail_emit:
                return False
            events = smooth_wheel_events(point, delta, (0, 0, 1920, 1080))
            self.output.append((delta, ctypes.c_int32(events[1].mi.mouseData).value))
            return True

        self.scroll = SmoothScroll(emit, lambda: self.foreground,
                                   monotonic=self.clock, automatic=False)
        self.scroll._stop = TickStop(self.clock)
        self.addCleanup(self.scroll.close)

    def pulse(self, direction=1, window=None):
        self.assertTrue(self.scroll.pulse(direction, window or self.window, (50, 60)))

    def tick(self):
        self.clock.value += .02
        return self.scroll.tick()

    def assert_summary(self, record, output, reason):
        self.assertEqual(record.levelname, "INFO")
        self.assertIn("reason=" + reason, record.getMessage())
        self.assertIn("logical_delta_total=%+d" % sum(item[0] for item in output), record.getMessage())
        self.assertIn("wheel_total=%+d" % sum(item[1] for item in output), record.getMessage())
        self.assertIn("count=%d" % len(output), record.getMessage())

    def test_decay_logs_one_signed_native_summary_per_round(self):
        for direction in (1, -1):
            with self.subTest(direction=direction):
                start = len(self.output)
                with self.assertLogs("agentdeck.hub.scroll", "INFO") as logs:
                    self.pulse(direction)
                    self.scroll._run()
                    self.scroll._run()  # an already settled round is not logged twice
                emitted = self.output[start:]
                self.assertTrue(emitted)
                self.assertTrue(all(delta * direction > 0 and native * direction < 0
                                    for delta, native in emitted))
                self.assertEqual(len(logs.records), 1)
                self.assert_summary(logs.records[0], emitted, "decayed")

    def test_reversal_keeps_each_direction_in_its_own_summary(self):
        with self.assertLogs("agentdeck.hub.scroll", "INFO") as logs:
            self.pulse(1)
            self.tick()
            boundary = len(self.output)
            self.pulse(-1)
            self.scroll._run()
        self.assertEqual(len(logs.records), 2)
        self.assert_summary(logs.records[0], self.output[:boundary], "reversed")
        self.assert_summary(logs.records[1], self.output[boundary:], "decayed")

    def test_foreground_cancellation_does_not_mix_into_next_round(self):
        with self.assertLogs("agentdeck.hub.scroll", "INFO") as logs:
            self.pulse(1)
            self.tick()
            boundary = len(self.output)
            self.foreground = (2, "other.exe", "other")
            self.scroll._run()
            self.pulse(-1, self.foreground)
            self.scroll._run()
        self.assertEqual(len(logs.records), 2)
        self.assert_summary(logs.records[0], self.output[:boundary], "foreground_changed")
        self.assert_summary(logs.records[1], self.output[boundary:], "decayed")

    def test_failed_emit_is_not_in_successful_output_total(self):
        with self.assertLogs("agentdeck.hub.scroll", "INFO") as logs:
            self.pulse(1)
            self.tick()
            self.fail_emit = True
            self.scroll._run()
        self.assertEqual(len(logs.records), 1)
        self.assert_summary(logs.records[0], self.output, "emit_failed")
        self.assertEqual(len(self.output), 1)

    def test_window_replacement_splits_round_before_new_output(self):
        with self.assertLogs("agentdeck.hub.scroll", "INFO") as logs:
            self.pulse(1)
            self.tick()
            boundary = len(self.output)
            self.foreground = (2, "other.exe", "other")
            self.pulse(-1, self.foreground)
            self.scroll._run()
        self.assertEqual(len(logs.records), 2)
        self.assert_summary(logs.records[0], self.output[:boundary], "window_changed")
        self.assert_summary(logs.records[1], self.output[boundary:], "decayed")

    def test_idle_reset_splits_round_and_preserves_fresh_timebase(self):
        with self.assertLogs("agentdeck.hub.scroll", "INFO") as logs:
            self.pulse(1)
            self.tick()
            boundary = len(self.output)
            self.clock.value += 1
            self.pulse(-1)
            self.assertIsNone(self.scroll.tick())
            self.scroll._run()
        self.assertEqual(len(logs.records), 2)
        self.assert_summary(logs.records[0], self.output[:boundary], "idle_reset")
        self.assert_summary(logs.records[1], self.output[boundary:], "decayed")


if __name__ == "__main__":
    unittest.main()
