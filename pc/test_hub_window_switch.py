"""Alt+Tab ownership and timers, entirely through fake input and timers."""
import ctypes
from types import SimpleNamespace
import unittest

from hub_window_switch import ALT, SHIFT, TAB, ESC, RELEASE_SECONDS, WindowSwitcher


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
        self.assertEqual(self.events[0], [(ALT, 0), (TAB, 0), (TAB, 2)])
        self.assertTrue(self.switcher.release())
        self.assertEqual(self.events[-1], [(ALT, 2)])
        self.assertTrue(self.switcher.release())
        self.assertEqual(len(self.events), 2)

    def test_idle_timeout_is_700ms_and_early_callback_rearms(self):
        self.switcher.step("next")
        self.clock.value = .699
        self.timers[-1].callback()
        self.assertEqual(len(self.events), 1)
        self.assertAlmostEqual(self.timers[-1].seconds, 0.001)
        self.clock.value = .7
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
        self.clock.value = 2.001
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
        self.assertEqual(calls[-1], [(TAB, 2), (ALT, 2)])
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
        self.assertEqual(calls[-1], [(TAB, 2), (ALT, 2)])
        self.assertEqual(self.switcher._owned, [])

    def test_partial_later_reverse_releases_shift_and_owned_alt(self):
        self.switcher.step("next")
        calls = []

        def partial(events):
            calls.append(events)
            return 1 if len(calls) == 1 else len(events)

        self.switcher.sender = partial
        self.assertFalse(self.switcher.step("prev"))
        self.assertEqual(calls[-1], [(SHIFT, 2), (ALT, 2)])
        self.assertEqual(self.switcher._owned, [])

    def test_later_reverse_exception_releases_every_possible_key(self):
        self.switcher.step("next")
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

    def test_reverse_detents_after_first_use_shift_and_new_bursts_start_with_tab(self):
        self.switcher.step("prev")
        self.switcher.step("prev")
        self.assertEqual(self.events[-1], [(SHIFT, 0), (TAB, 0), (TAB, 2), (SHIFT, 2)])
        self.switcher.release()
        self.switcher.step("prev")
        self.assertEqual(self.events[-1], [(ALT, 0), (TAB, 0), (TAB, 2)])

    def test_release_delay_is_configurable(self):
        switcher = WindowSwitcher(None, monotonic=self.clock, timer_factory=FakeTimer,
                                  sender=lambda events: len(events), release_ms=1750)
        self.addCleanup(switcher.close)
        self.assertTrue(switcher.step("next"))
        self.assertEqual(switcher._timer.seconds, 1.75)
        self.clock.value = 1.749
        switcher._timer.callback()
        self.assertEqual(switcher._owned, [ALT])
        self.clock.value = 1.75
        switcher._timer.callback()
        self.assertEqual(switcher._owned, [])

    def test_release_delay_must_be_positive_and_finite(self):
        for value in (0, -1, True, "1200", float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "release_ms"):
                WindowSwitcher(None, sender=lambda events: len(events), release_ms=value)

    def test_position_clamps_at_original_and_last_window(self):
        self.switcher.windows = SimpleNamespace(windows=lambda: [(1, "a", "A"), (2, "b", "B"), (3, "c", "C")])
        self.assertTrue(self.switcher.step("prev"))
        self.assertEqual(self.switcher.position, 1)
        self.assertTrue(self.switcher.step("next"))
        self.assertEqual(self.switcher.position, 2)
        count = len(self.events)
        self.assertFalse(self.switcher.step("next"))
        self.assertEqual(len(self.events), count)
        self.assertTrue(self.switcher.step("prev"))
        self.assertTrue(self.switcher.step("prev"))
        self.assertEqual(self.switcher.position, 0)
        count = len(self.events)
        self.assertFalse(self.switcher.step("prev"))
        self.assertEqual(len(self.events), count)

    def test_press_confirms_or_performs_one_complete_previous_window(self):
        self.assertTrue(self.switcher.back())
        self.assertFalse(self.switcher.active)
        self.assertEqual(self.events, [[(ALT, 0), (TAB, 0), (TAB, 2)], [(ALT, 2)]])
        self.switcher.step("next")
        self.events.clear()
        self.assertTrue(self.switcher.back())
        self.assertEqual(self.events, [[(ALT, 2)]])

    def test_cancel_esc_precedes_alt_release(self):
        self.switcher.step("next")
        self.events.clear()
        self.assertTrue(self.switcher.cancel())
        self.assertEqual(self.events, [[(ESC, 0), (ESC, 2)], [(ALT, 2)]])
        self.assertFalse(self.switcher.active)

    def test_continuous_rotation_cannot_extend_five_second_watchdog(self):
        self.switcher.step("next")
        for step in range(1, 10):
            self.clock.value = step * .5
            self.assertTrue(self.switcher.step("next"))
        self.assertAlmostEqual(self.timers[-1].seconds, .5)
        self.clock.value = 5
        self.timers[-1].callback()
        self.assertFalse(self.switcher.active)
        self.assertEqual(self.events[-1], [(ALT, 2)])

    def test_late_step_also_enforces_watchdog_without_timer_callback(self):
        self.switcher.step("next")
        self.clock.value = 5
        self.assertFalse(self.switcher.step("next"))
        self.assertFalse(self.switcher.active)

    def test_no_second_window_means_no_injected_input(self):
        self.switcher.windows = SimpleNamespace(windows=lambda: [(1, "a", "A")])
        self.assertFalse(self.switcher.step("next"))
        self.assertEqual(self.events, [])

    def test_turning_at_boundary_renews_idle_without_wrapping(self):
        self.switcher.windows = SimpleNamespace(windows=lambda: [(1, "a", "A"), (2, "b", "B")])
        self.assertTrue(self.switcher.step("next"))
        self.clock.value = .6
        self.assertFalse(self.switcher.step("next"))
        self.assertEqual(len(self.events), 1)
        self.clock.value = .9
        self.timers[-1].callback()
        self.assertTrue(self.switcher.active)
        self.clock.value = 1.3
        self.timers[-1].callback()
        self.assertFalse(self.switcher.active)


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
