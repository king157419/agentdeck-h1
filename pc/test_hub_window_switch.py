"""Alt+Tab ownership and timers, entirely through fake input and timers."""
import ctypes
from types import SimpleNamespace
import unittest

from hub_window_switch import ALT, SHIFT, TAB, RELEASE_SECONDS, WindowSwitcher


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class FakeTimer:
    def __init__(self, seconds, callback):
        self.seconds = seconds
        self.callback = callback
        self.cancelled = False
        self.started = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


class WindowSwitchTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.timers = []
        self.events = []

        def timer(seconds, callback):
            value = FakeTimer(seconds, callback)
            self.timers.append(value)
            return value

        def send(events):
            self.events.append(list(events))
            return len(events)

        self.switcher = WindowSwitcher(None, monotonic=self.clock, timer_factory=timer, sender=send)
        self.addCleanup(self.switcher.close)

    def test_first_and_later_detents_hold_one_alt_and_use_shift_only_for_prev(self):
        self.assertTrue(self.switcher.step("next"))
        self.assertTrue(self.switcher.step("next"))
        self.assertTrue(self.switcher.step("prev"))
        self.assertEqual(self.events, [[(ALT, 0), (TAB, 0), (TAB, 2)],
                                       [(TAB, 0), (TAB, 2)],
                                       [(SHIFT, 0), (TAB, 0), (TAB, 2), (SHIFT, 2)]])
        self.assertEqual(self.switcher._owned, [ALT])
        self.assertTrue(self.timers[0].cancelled)
        self.assertTrue(self.timers[-1].started)
        self.assertEqual(self.timers[-1].seconds, RELEASE_SECONDS)

    def test_prev_first_detent_and_repeated_release_are_balanced(self):
        self.switcher.step("prev")
        self.assertEqual(self.events[0], [(ALT, 0), (SHIFT, 0), (TAB, 0), (TAB, 2), (SHIFT, 2)])
        self.assertTrue(self.switcher.release())
        self.assertEqual(self.events[-1], [(ALT, 2)])
        self.assertTrue(self.switcher.release())
        self.assertEqual(len(self.events), 2)

    def test_idle_timeout_is_900ms_and_early_callback_rearms(self):
        self.switcher.step("next")
        self.clock.value = 0.899
        self.timers[-1].callback()
        self.assertEqual(len(self.events), 1)
        self.assertAlmostEqual(self.timers[-1].seconds, 0.001)
        self.clock.value = 0.9
        self.timers[-1].callback()
        self.assertEqual(self.events[-1], [(ALT, 2)])
        self.assertEqual(self.switcher._owned, [])

    def test_old_timer_cannot_release_a_new_burst(self):
        self.switcher.step("next")
        first = self.timers[-1]
        self.clock.value = 0.8
        self.switcher.step("next")
        self.clock.value = 0.9
        first.callback()
        self.assertEqual(self.switcher._owned, [ALT])
        self.clock.value = 1.701
        self.timers[-1].callback()
        self.assertEqual(self.switcher._owned, [])

    def test_release_before_another_action_cancels_timer_and_next_detent_reopens(self):
        self.switcher.step("next")
        first = self.timers[-1]
        self.assertTrue(self.switcher.release())
        self.assertTrue(first.cancelled)
        first.callback()
        self.assertEqual(self.events[-1], [(ALT, 2)])
        self.switcher.step("next")
        self.assertEqual(self.events[-1][0], (ALT, 0))

    def test_close_releases_alt_and_prevents_new_input(self):
        self.switcher.step("next")
        self.assertTrue(self.switcher.close())
        self.assertEqual(self.events[-1], [(ALT, 2)])
        self.assertTrue(self.timers[-1].cancelled)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.switcher.step("next")

    def test_partial_input_cleans_up_only_delivered_keys(self):
        calls = []

        def partial(events):
            calls.append(events)
            return 2 if len(calls) == 1 else len(events)

        self.switcher.sender = partial
        self.assertFalse(self.switcher.step("prev"))
        self.assertEqual(calls[-1], [(SHIFT, 2), (ALT, 2)])
        self.assertEqual(self.switcher._owned, [])
        self.assertEqual(self.timers, [])

    def test_input_exception_releases_all_keys_that_might_have_been_inserted(self):
        calls = []

        def interrupted(events):
            calls.append(events)
            if len(calls) == 1:
                raise OSError("input failed")
            return len(events)

        self.switcher.sender = interrupted
        with self.assertRaisesRegex(OSError, "input failed"):
            self.switcher.step("prev")
        self.assertEqual(calls[-1], [(TAB, 2), (SHIFT, 2), (ALT, 2)])
        self.assertEqual(self.switcher._owned, [])

    def test_timer_start_failure_releases_alt(self):
        def broken_timer(*args):
            raise RuntimeError("timer failed")

        self.switcher.timer_factory = broken_timer
        with self.assertRaisesRegex(RuntimeError, "timer failed"):
            self.switcher.step("next")
        self.assertEqual(self.events[-1], [(ALT, 2)])
        self.assertEqual(self.switcher._owned, [])

    def test_failed_release_retries_and_keeps_ownership_for_next_attempt(self):
        self.switcher.step("next")
        original = self.switcher.sender
        self.switcher.sender = lambda events: 0
        with self.assertLogs("agentdeck.hub.window", "ERROR"):
            self.assertFalse(self.switcher.release())
        self.assertEqual(self.switcher._owned, [ALT])
        self.switcher.sender = original
        self.assertTrue(self.switcher.release())
        self.assertEqual(self.switcher._owned, [])

    def test_invalid_direction_sends_nothing(self):
        with self.assertRaisesRegex(ValueError, "next or prev"):
            self.switcher.step("forward")
        self.assertEqual(self.events, [])


class NativeShapeTests(unittest.TestCase):
    def test_native_batch_uses_scan_codes_and_refuses_physical_modifiers(self):
        class Key(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_uint)]

        class Input(ctypes.Structure):
            _fields_ = [("ki", Key)]

        captured = []
        held = set()

        def send(count, events, size):
            captured.append([(event.ki.wVk, event.ki.wScan, event.ki.dwFlags) for event in events])
            self.assertEqual(size, ctypes.sizeof(Input))
            return count

        user = SimpleNamespace(SendInput=send, GetAsyncKeyState=lambda key: 0x8000 if key in held else 0)
        windows = SimpleNamespace(user=user, _events=lambda transitions: (Input * len(transitions))())
        switcher = WindowSwitcher(windows, timer_factory=FakeTimer)
        self.addCleanup(switcher.close)
        held.add(SHIFT)
        self.assertFalse(switcher.step("next"))
        self.assertEqual(captured, [])
        held.clear()
        self.assertTrue(switcher.step("next"))
        self.assertEqual(captured[0], [(0, 0x38, 8), (0, 0x0F, 8), (0, 0x0F, 10)])
        switcher.close()
        self.assertEqual(captured[-1], [(0, 0x38, 10)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
