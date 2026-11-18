"""Offline Hub desktop checks: fake windows, clipboard and capture only."""
from datetime import datetime
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hub_desktop import DesktopEffects, HubWindowControl, capture_screen


SESSION = {"key": "cc-abcdef", "name": "app", "state": "think"}
WINDOW = (12, "WindowsTerminal.exe", "app - Claude")


class Windows:
    def __init__(self):
        self.foreground = WINDOW
        self.items = [WINDOW]
        self.keys = []
        self.combos = []
        self.activated = []
        self.activate_ok = True
        self.input_ok = True

    def __call__(self):
        return self.foreground

    def windows(self):
        return self.items

    def activate(self, handle):
        self.activated.append(handle)
        if self.activate_ok:
            self.foreground = next((window for window in self.items if window[0] == handle),
                                   self.foreground)
        return self.activate_ok

    def send_key(self, key, expected):
        assert self.foreground == expected
        self.keys.append(key)
        return self.input_ok

    def send_combo(self, keys, expected):
        assert self.foreground == expected
        self.combos.append(keys)
        return self.input_ok


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.windows = Windows()
        self.clipboard = []
        self.effects = DesktopEffects(self.windows, clipboard=self.clipboard.append,
                                      sleeper=lambda seconds: None)

    def test_native_adapter_is_lazy(self):
        with patch("hub_desktop.HubWindowControl", side_effect=AssertionError("native call")):
            DesktopEffects()

    def test_focus_uses_project_and_tool_matching(self):
        self.assertEqual(self.effects.focus(SESSION, [SESSION]), WINDOW)
        self.assertEqual(self.windows.activated, [12])
        self.windows.items = [(13, "WindowsTerminal.exe", "app - Codex")]
        with self.assertRaisesRegex(RuntimeError, "no matching window"):
            self.effects.focus(SESSION, [SESSION])

    def test_focus_rejects_ambiguity_and_activation_failure(self):
        self.windows.items.append((14, "WindowsTerminal.exe", "app - Claude"))
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            self.effects.focus(SESSION, [SESSION])
        self.windows.items = [WINDOW]
        self.windows.activate_ok = False
        with self.assertRaisesRegex(RuntimeError, "could not activate"):
            self.effects.voice(SESSION, [SESSION])
        self.assertEqual(self.windows.combos, [])

    def test_interrupt_sends_one_escape(self):
        self.assertTrue(self.effects.interrupt(SESSION, [SESSION]))
        self.assertEqual(self.windows.keys, [0x1B])

    def test_voice_sends_win_h(self):
        self.assertTrue(self.effects.voice(SESSION, [SESSION]))
        self.assertEqual(self.windows.combos, [(0x5B, 0x48)] * 2)
        self.assertEqual(self.windows.keys, [])
        self.assertFalse(self.effects.voice_active)

    def test_prompt_pastes_unicode_then_enter(self):
        text = "跑测试 / run tests"
        self.assertTrue(self.effects.prompt(SESSION, [SESSION], text))
        self.assertEqual(self.clipboard, [text])
        self.assertEqual(self.windows.combos, [(0x11, 0x56)])
        self.assertEqual(self.windows.keys, [0x0D])

    def test_screenshot_saves_path_and_never_sends_enter(self):
        saved = []

        def save(path, format):
            self.assertEqual(format, "PNG")
            saved.append(path)
            path.write_bytes(b"fake capture")

        with tempfile.TemporaryDirectory() as directory:
            self.effects.shots_dir = Path(directory) / "shots"
            self.effects.capture = lambda: SimpleNamespace(save=save)
            self.effects.now = lambda: datetime(2026, 11, 17, 12, 34, 56)
            first = self.effects.screenshot(SESSION, [SESSION])
            second = self.effects.screenshot(SESSION, [SESSION])
            self.assertTrue(Path(first).is_file())
            self.assertNotEqual(first, second)
            self.assertTrue(Path(first).name.startswith("20261117-123456"))
            self.assertEqual(self.clipboard, [first, second])
            self.assertEqual(len(saved), 2)
        self.assertEqual(self.windows.keys, [])
        self.assertEqual(self.windows.combos, [(0x11, 0x56)] * 2)

    def test_foreground_change_after_clipboard_never_pastes(self):
        self.effects.clipboard = lambda text: setattr(self.windows, "foreground", (99, "", "other"))
        with self.assertRaisesRegex(RuntimeError, "foreground changed"):
            self.effects.prompt(SESSION, [SESSION], "continue")
        self.assertEqual(self.windows.combos, [])
        self.assertEqual(self.windows.keys, [])

    def test_failed_paste_never_sends_enter(self):
        self.windows.input_ok = False
        with self.assertRaises(RuntimeError):
            self.effects.prompt(SESSION, [SESSION], "continue")
        self.assertEqual(self.windows.keys, [])

    def test_focus_change_after_paste_never_sends_enter(self):
        self.effects.sleep = lambda seconds: setattr(self.windows, "foreground", (99, "", "other"))
        with self.assertRaisesRegex(RuntimeError, "foreground changed"):
            self.effects.prompt(SESSION, [SESSION], "continue")
        self.assertEqual(self.windows.keys, [])

    def test_default_capture_requests_all_screens(self):
        with patch("PIL.ImageGrab.grab", return_value="fake image") as grab:
            self.assertEqual(capture_screen(), "fake image")
            grab.assert_called_once_with(all_screens=True)


class ComboTests(unittest.TestCase):
    def test_native_window_existence_uses_handle_even_when_not_visible(self):
        native = HubWindowControl.__new__(HubWindowControl)
        native.user = SimpleNamespace(IsWindow=lambda hwnd: hwnd == 12)
        self.assertTrue(native.exists(12))
        self.assertFalse(native.exists(99))

    def make_native(self, *, held=(), sent=None, foreground=WINDOW):
        calls = []

        def send(count, events, size):
            calls.append([(event.ki.wVk, event.ki.dwFlags) for event in events])
            return count if sent is None or len(calls) > 1 else sent

        class Native(HubWindowControl):
            def __init__(self):
                self.user = SimpleNamespace(
                    GetAsyncKeyState=lambda key: 0x8000 if key in held else 0,
                    SendInput=send)

            def __call__(self):
                return foreground

        return Native(), calls

    def test_combo_presses_in_order_releases_in_reverse(self):
        native, calls = self.make_native()
        self.assertTrue(native.send_combo((0x11, 0x56), WINDOW))
        self.assertEqual(calls, [[(0x11, 0), (0x56, 0), (0x56, 2), (0x11, 2)]])

    def test_partial_input_releases_only_inserted_down_keys(self):
        for sent, releases in ((1, [(0x11, 2)]),
                               (2, [(0x56, 2), (0x11, 2)]),
                               (3, [(0x11, 2)])):
            with self.subTest(sent=sent):
                native, calls = self.make_native(sent=sent)
                self.assertFalse(native.send_combo((0x11, 0x56), WINDOW))
                self.assertEqual(calls[1], releases)

    def test_held_modifiers_and_changed_foreground_prevent_input(self):
        native, calls = self.make_native(held=(0x12,))
        self.assertFalse(native.send_combo((0x11, 0x56), WINDOW))
        self.assertEqual(calls, [])
        native, calls = self.make_native(foreground=(99, "", "other"))
        self.assertFalse(native.send_combo((0x11, 0x56), WINDOW))
        self.assertEqual(calls, [])


class GuardTicks:
    """Advance one requested guard period without wall-clock timing assertions."""

    def __init__(self):
        self.entered = queue.Queue()
        self.permits = threading.Semaphore(0)

    def __call__(self, stop, seconds):
        self.entered.put(seconds)
        while not stop.is_set():
            if self.permits.acquire(timeout=0.005):
                return stop.is_set()
        return True


class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.windows = Windows()
        self.ticks = GuardTicks()
        self.now = 100.0
        self.clipboard = []
        self.completions = []
        self.completed = threading.Event()
        self.effects = DesktopEffects(self.windows, clipboard=self.clipboard.append,
                                      monotonic=lambda: self.now, voice_wait=self.ticks)
        self.addCleanup(self.effects.close)

    def on_stop(self, result):
        self.completions.append(result)
        self.completed.set()

    def start(self, session=None):
        self.effects.voice_down(SESSION if session is None else session, [SESSION],
                                on_stop=self.on_stop)
        self.assertEqual(self.ticks.entered.get(timeout=1), 0.1)
        self.assertTrue(self.effects.voice_active)

    def tick(self):
        self.ticks.permits.release()
        self.assertEqual(self.ticks.entered.get(timeout=1), 0.1)

    def ended(self):
        self.assertTrue(self.completed.wait(1), "guard did not finish")
        self.effects._voice.thread.join(1)
        self.assertFalse(self.effects._voice.thread.is_alive())
        self.assertFalse(self.effects.voice_active)
        self.assertEqual(self.windows.combos, [(0x5B, 0x48)] * 2)
        self.assertEqual(self.windows.keys, [])
        self.assertEqual(self.clipboard, [])
        self.assertTrue(self.completions[0]["closed"])
        return self.completions[0]

    def test_first_100ms_tick_restores_target_and_release_joins_guard(self):
        self.start()
        self.windows.foreground = (99, "other.exe", "other")
        with self.assertLogs("agentdeck.hub.voice", level="INFO") as captured:
            self.tick()
        self.assertEqual(self.windows.foreground, WINDOW)
        self.assertTrue(any("restores=1" in line for line in captured.output))
        result = self.effects.voice_up()
        self.assertEqual(result, self.ended())
        self.assertEqual(result["reason"], "released")
        self.assertEqual(result["restores"], 1)
        self.assertEqual(self.effects.voice_up(), None)
        self.assertEqual(len(self.completions), 1)
        self.assertEqual(self.windows.combos, [(0x5B, 0x48)] * 2)

    def test_60_second_limit_closes_without_waiting_for_release(self):
        self.start()
        self.now = 159.999
        self.tick()
        self.assertTrue(self.effects.voice_active)
        self.now = 160.0
        self.ticks.permits.release()
        self.assertEqual(self.ended()["reason"], "timeout")
        self.assertIsNone(self.effects.voice_up())

    def test_missing_window_stops_on_next_tick_and_only_sends_global_close(self):
        self.start()
        self.windows.items = []
        self.windows.foreground = (99, "other.exe", "other")
        self.ticks.permits.release()
        result = self.ended()
        self.assertEqual(result["reason"], "window_lost")
        self.assertEqual(result["restores"], 0)
        self.assertEqual(self.windows.activated, [12])

    def test_release_notices_window_loss_before_next_tick(self):
        self.start()
        self.windows.items = []
        self.assertEqual(self.effects.voice_up()["reason"], "window_lost")
        self.ended()

    def test_duplicate_down_keeps_original_session_and_handle(self):
        original = dict(SESSION)
        self.start(original)
        original["name"] = "changed"
        other = {"key": "cx-other", "name": "other", "state": "idle"}
        self.effects.voice_down(other, [other], on_stop=lambda result: self.fail("retargeted"))
        self.assertEqual(len(self.windows.combos), 1)
        self.windows.foreground = (99, "other.exe", "other")
        self.tick()
        result = self.effects.voice_up()
        self.assertEqual(result["session"], SESSION)
        self.assertEqual(self.windows.foreground[0], 12)
        self.ended()

    def test_changing_target_title_preserves_handle_and_closes_successfully(self):
        self.start()
        changed = (12, "WindowsTerminal.exe", "new title")
        self.windows.items = [changed]
        self.windows.foreground = changed
        self.tick()
        result = self.effects.voice_up()
        self.assertEqual(result["restores"], 0)
        self.assertNotIn("error", result)
        self.ended()

    def test_existing_handle_is_kept_when_window_is_hidden_or_titleless(self):
        self.start()
        self.windows.exists = lambda hwnd: hwnd == 12
        self.windows.items = []  # EnumWindows adapter excludes hidden/titleless windows.
        self.tick()
        result = self.effects.voice_up()
        self.assertEqual(result["reason"], "released")
        self.ended()

    def test_failed_restore_ends_guard_without_typing_or_approval(self):
        self.start()
        self.windows.foreground = (99, "other.exe", "other")
        self.windows.activate_ok = False
        self.ticks.permits.release()
        self.assertEqual(self.ended()["reason"], "focus_failed")

    def test_window_query_error_still_attempts_owned_dictation_close(self):
        self.start()
        self.windows.windows = lambda: (_ for _ in ()).throw(OSError("window lookup failed"))
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            self.ticks.permits.release()
            result = self.ended()
        self.assertEqual(result["reason"], "error")
        self.assertIn("window lookup failed", result["error"])

    def test_failed_close_retains_ownership_until_explicit_retry_succeeds(self):
        self.start()
        self.addCleanup(setattr, self.windows, "input_ok", True)
        self.windows.input_ok = False
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "combination failed"):
                self.effects.voice_up()
        self.assertTrue(self.completed.wait(1))
        self.effects._voice.thread.join(1)
        self.assertFalse(self.effects._voice.thread.is_alive())
        self.assertTrue(self.effects.voice_active)
        self.assertFalse(self.completions[0]["closed"])
        self.assertIn("error", self.completions[0])
        other = {"key": "cx-other", "name": "other", "state": "idle"}
        self.effects.voice_down(other, [other])
        self.assertEqual(len(self.windows.combos), 2)
        self.windows.input_ok = True
        result = self.effects.voice_up()
        self.assertTrue(result["closed"])
        self.assertNotIn("error", result)
        self.assertFalse(self.effects.voice_active)
        self.assertEqual(len(self.completions), 2)
        self.assertIsNone(self.effects.voice_up())
        self.assertEqual(self.windows.combos, [(0x5B, 0x48)] * 3)
        self.assertEqual(self.windows.keys, [])

    def test_timeout_ends_thread_even_if_owned_dictation_cannot_close(self):
        self.start()
        self.addCleanup(setattr, self.windows, "input_ok", True)
        self.windows.input_ok = False
        self.now = 160.0
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            self.ticks.permits.release()
            self.assertTrue(self.completed.wait(1))
        self.effects._voice.thread.join(1)
        self.assertFalse(self.effects._voice.thread.is_alive())
        self.assertTrue(self.effects.voice_active)
        self.assertEqual(self.completions[0]["reason"], "timeout")
        self.assertFalse(self.completions[0]["closed"])
        self.windows.input_ok = True
        self.assertTrue(self.effects.voice_up()["closed"])
        self.assertFalse(self.effects.voice_active)

    def test_failed_thread_start_and_failed_close_keep_ownership_for_retry(self):
        self.addCleanup(setattr, self.windows, "input_ok", True)

        def fail_start():
            self.windows.input_ok = False
            raise RuntimeError("cannot start thread")

        with patch("hub_desktop.threading.Thread.start", side_effect=fail_start):
            with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
                with self.assertRaisesRegex(RuntimeError, "cannot start thread"):
                    self.effects.voice_down(SESSION, [SESSION], on_stop=self.on_stop)
        self.assertTrue(self.effects.voice_active)
        self.assertIsNone(self.effects._voice.thread.ident)
        self.assertFalse(self.completions[0]["closed"])
        self.effects.voice_down(SESSION, [SESSION])
        self.assertEqual(len(self.windows.combos), 2)
        self.windows.input_ok = True
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            result = self.effects.voice_up()
        self.assertTrue(result["closed"])
        self.assertEqual(result["error"], "cannot start thread")
        self.assertFalse(self.effects.voice_active)
        self.assertEqual(len(self.completions), 2)
        self.assertEqual(len(self.windows.combos), 3)

    def test_concurrent_releases_close_once_and_callback_once(self):
        self.start()
        ready = threading.Barrier(3)
        results = []

        def release():
            ready.wait()
            results.append(self.effects.voice_up())

        threads = [threading.Thread(target=release) for _ in range(2)]
        for thread in threads:
            thread.start()
        ready.wait()
        for thread in threads:
            thread.join(1)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.completions), 1)
        self.ended()

    def test_close_stops_active_voice_before_returning(self):
        self.start()
        self.assertEqual(self.effects.close()["reason"], "shutdown")
        self.ended()
        self.assertIsNone(self.effects.close())

    def test_failed_open_never_starts_guard_or_closes_unowned_dictation(self):
        self.windows.input_ok = False
        with self.assertRaisesRegex(RuntimeError, "combination failed"):
            self.effects.voice_down(SESSION, [SESSION], on_stop=self.on_stop)
        self.assertFalse(self.effects.voice_active)
        self.assertEqual(len(self.windows.combos), 1)
        self.assertEqual(self.completions, [])
        self.assertIsNone(self.effects.voice_up())


if __name__ == "__main__":
    unittest.main(verbosity=2)
