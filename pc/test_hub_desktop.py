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
        self.held = []
        self.released = []
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

    def hold_combo(self, keys, expected):
        assert self.foreground == expected
        self.held.extend(keys)
        return self.input_ok

    def release_combo(self):
        if not self.held:
            return True
        if not self.input_ok:
            return False
        self.released.extend(reversed(self.held))
        self.held.clear()
        return True


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

    def test_hold_only_presses_and_release_is_reversed_and_idempotent(self):
        native, calls = self.make_native()
        self.assertTrue(native.hold_combo((0x11, 0xA5), WINDOW))
        self.assertEqual(calls, [[(0x11, 0), (0xA5, 1)]])
        self.assertTrue(native.release_combo())
        self.assertEqual(calls[1], [(0xA5, 3), (0x11, 2)])
        self.assertTrue(native.release_combo())
        self.assertEqual(len(calls), 2)

    def test_hold_partial_send_releases_only_inserted_keys(self):
        native, calls = self.make_native(sent=1)
        self.assertFalse(native.hold_combo((0x11, 0xA5), WINDOW))
        self.assertEqual(calls, [[(0x11, 0), (0xA5, 1)], [(0x11, 2)]])
        self.assertEqual(native._held_keys, [])

    def test_hold_rejects_physical_modifiers_without_releasing_them(self):
        native, calls = self.make_native(held=(0xA5,))
        self.assertFalse(native.hold_combo((0xA5,), WINDOW))
        self.assertTrue(native.release_combo())
        self.assertEqual(calls, [])

    def test_hold_rechecks_foreground_after_key_state_queries(self):
        native, calls = self.make_native(foreground=(99, "", "other"))
        self.assertFalse(native.hold_combo((0xA5,), WINDOW))
        self.assertEqual(calls, [])

    def test_native_exception_after_insertion_releases_owned_keys(self):
        native, calls = self.make_native()
        send = native.user.SendInput

        def fail(count, events, size):
            send(count, events, size)
            if len(calls) == 1:
                raise OSError("native input failed")
            return count

        native.user.SendInput = fail
        with self.assertRaisesRegex(OSError, "native input failed"):
            native.hold_combo((0x11, 0xA5), WINDOW)
        self.assertEqual(calls[1], [(0xA5, 3), (0x11, 2)])
        self.assertEqual(native._held_keys, [])

    def test_partial_and_failed_releases_retry_without_new_key_downs(self):
        native, calls = self.make_native()
        send = native.user.SendInput
        counts = iter((2, 1, 0, 1))

        def partial(count, events, size):
            send(count, events, size)
            return next(counts)

        native.user.SendInput = partial
        self.assertTrue(native.hold_combo((0x11, 0xA5), WINDOW))
        self.assertFalse(native.release_combo())
        self.assertEqual(native._held_keys, [0x11])
        self.assertTrue(native.release_combo())
        self.assertEqual(calls[1:], [[(0xA5, 3), (0x11, 2)], [(0x11, 2)], [(0x11, 2)]])

    def test_release_retries_an_exception_and_works_without_target_focus(self):
        native, calls = self.make_native()
        self.assertTrue(native.hold_combo((0xA5,), WINDOW))
        send = native.user.SendInput

        def fail_once(count, events, size):
            send(count, events, size)
            if len(calls) == 2:
                raise OSError("release failed")
            return count

        native.user.SendInput = fail_once
        # No foreground or key-state query is allowed on emergency key-up.
        native.user.GetAsyncKeyState = lambda key: self.fail("key-state query during release")
        with patch.object(type(native), "__call__", side_effect=AssertionError("foreground query")):
            self.assertTrue(native.release_combo())
        self.assertEqual(calls[1:], [[(0xA5, 3)], [(0xA5, 3)]])


class AppSwitchTests(unittest.TestCase):
    CLAUDE = (24, "C:/Program Files/Claude/claude.exe", "Claude")

    def setUp(self):
        self.windows = Windows()
        self.windows.items.append(self.CLAUDE)
        self.effects = DesktopEffects(self.windows)

    def test_directions_activate_claude_without_changing_selected_session(self):
        session = dict(SESSION)
        for direction, key in (("next", 0xDD), ("prev", 0xDB)):
            self.assertTrue(self.effects.app(session, [session], direction))
            self.assertEqual(self.windows.combos[-1], (0x11, 0x10, key))
        self.assertEqual(self.windows.activated, [24, 24])
        self.assertEqual(session, SESSION)

    def test_selected_claude_handle_precedes_main_window(self):
        selected = (31, "CLAUDE.EXE", "Working session")
        self.windows.items.append(selected)
        session = dict(SESSION, hwnd=31, window_exe="C:/app/Claude.exe")
        self.effects.app(session, [session], "next")
        self.assertEqual(self.windows.activated, [31])

    def test_wrong_exe_reused_and_missing_handles_fall_back_to_main_window(self):
        for session in (None, dict(SESSION, hwnd=12, window_exe="WindowsTerminal.exe"),
                        dict(SESSION, hwnd=12, window_exe="claude.exe"),
                        dict(SESSION, hwnd=99, window_exe="claude.exe")):
            with self.subTest(session=session):
                self.effects.app(session, [session] if session else [], "prev")
                self.assertEqual(self.windows.activated[-1], 24)

    def test_fallback_rejects_terminal_titles_and_non_main_claude_windows(self):
        self.windows.items = [WINDOW, (31, "claude.exe", "Settings"),
                              (32, "other.exe", "Claude")]
        with self.assertRaisesRegex(RuntimeError, "没找到 Claude 桌面版窗口"):
            self.effects.app(SESSION, [SESSION], "next")
        self.assertEqual(self.windows.activated, [])
        self.assertEqual(self.windows.combos, [])

    def test_activation_failure_and_focus_change_never_send_shortcut(self):
        self.windows.activate_ok = False
        with self.assertRaisesRegex(RuntimeError, "could not activate"):
            self.effects.app(None, [], "next")
        self.windows.activate = lambda hwnd: True  # reports success without changing foreground
        with self.assertRaisesRegex(RuntimeError, "could not activate"):
            self.effects.app(None, [], "prev")
        self.assertEqual(self.windows.combos, [])

    def test_voice_and_invalid_direction_reject_before_window_access(self):
        self.effects._voice = SimpleNamespace(closed=False)
        with self.assertRaisesRegex(RuntimeError, "release voice"):
            self.effects.app(None, [], "next")
        self.assertEqual(self.windows.activated, [])
        with self.assertRaises(ValueError):
            self.effects.app(None, [], "sideways")

    def native_effects(self, **kwargs):
        native, calls = ComboTests().make_native(foreground=self.CLAUDE, **kwargs)
        native.windows = lambda: [self.CLAUDE]
        native.activate = lambda hwnd: hwnd == self.CLAUDE[0]
        return DesktopEffects(native), calls

    def test_native_shortcuts_press_ctrl_shift_bracket_and_release_in_reverse(self):
        for direction, bracket in (("next", 0xDD), ("prev", 0xDB)):
            with self.subTest(direction=direction):
                effects, calls = self.native_effects()
                effects.app(None, [], direction)
                self.assertEqual(calls, [[(0x11, 0), (0x10, 0), (bracket, 0),
                                          (bracket, 2), (0x10, 2), (0x11, 2)]])

    def test_partial_shortcuts_release_every_inserted_key(self):
        releases = ([], [(0x11, 2)], [(0x10, 2), (0x11, 2)],
                    [(0xDD, 2), (0x10, 2), (0x11, 2)],
                    [(0x10, 2), (0x11, 2)], [(0x11, 2)])
        for sent, cleanup in enumerate(releases):
            with self.subTest(sent=sent):
                effects, calls = self.native_effects(sent=sent)
                with self.assertRaisesRegex(RuntimeError, "combination failed"):
                    effects.app(None, [], "next")
                self.assertEqual(calls[1:], [cleanup] if cleanup else [])
                self.assertEqual(effects.windows._held_keys, [])

    def test_native_exception_releases_ctrl_shift_and_bracket(self):
        effects, calls = self.native_effects()
        send = effects.windows.user.SendInput

        def interrupted(count, events, size):
            send(count, events, size)
            if len(calls) == 1:
                raise OSError("interrupted input")
            return count

        effects.windows.user.SendInput = interrupted
        with self.assertRaisesRegex(OSError, "interrupted input"):
            effects.app(None, [], "prev")
        self.assertEqual(calls[1], [(0xDB, 2), (0x10, 2), (0x11, 2)])
        self.assertEqual(effects.windows._held_keys, [])


class RightModifierTests(unittest.TestCase):
    def test_modifier_scans_and_extended_flags_apply_to_press_and_release(self):
        for key, scan, extended in ((0xA5, 0x38, 1), (0xA3, 0x1D, 1),
                                    (0x5C, 0x5C, 1), (0xA1, 0x36, 0),
                                    (0xA4, 0x38, 0), (0xA2, 0x1D, 0)):
            with self.subTest(key=key):
                events = HubWindowControl._events([(key, 0), (key, 2)])
                self.assertEqual([(event.ki.wVk, event.ki.wScan, event.ki.dwFlags) for event in events],
                                 [(key, scan, extended), (key, scan, extended | 2)])

    def test_typeless_right_alt_hold_config_and_native_input(self):
        config = {"key_codes": [165], "modifiers": [], "mode": "hold"}
        native, calls = ComboTests().make_native()
        native.windows = lambda: [WINDOW]
        native.activate = lambda hwnd: hwnd == WINDOW[0]
        native.exists = lambda hwnd: hwnd == WINDOW[0]
        effects = DesktopEffects(native, dictation_shortcut=config)
        self.addCleanup(effects.close)
        self.assertEqual(effects.dictation_shortcut, config)
        effects.voice_down(SESSION, [SESSION])
        effects.voice_up()
        self.assertEqual(calls, [[(165, 1)], [(165, 3)]])
        self.assertEqual(native._held_keys, [])

    def test_native_recording_pipeline_keeps_right_alt_as_165(self):
        from agentdeck_app import ShortcutRecorder
        from voice_shortcut_capture import ShortcutCapture
        for code in (0x12, 0xA5):
            with self.subTest(code=code):
                recorder = ShortcutRecorder()
                pressed = ShortcutCapture.event(SimpleNamespace(vkCode=code, scanCode=0x38, flags=1))
                released = ShortcutCapture.event(SimpleNamespace(vkCode=code, scanCode=0x38, flags=0x81))
                recorder.press(pressed)
                shortcut = dict(recorder.release(released), mode="hold")
                self.assertEqual(shortcut, {"key_codes": [165], "modifiers": [], "mode": "hold"})
                self.assertEqual(DesktopEffects._shortcut(shortcut), shortcut)


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

    def test_missing_window_stops_without_toggling_unrelated_foreground(self):
        self.start()
        self.windows.items = []
        self.windows.foreground = (99, "other.exe", "other")
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            self.ticks.permits.release()
            self.assertTrue(self.completed.wait(1))
        result = self.completions[0]
        self.assertTrue(self.effects.voice_active)
        self.assertFalse(result["closed"])
        self.assertEqual(self.windows.combos, [(0x5B, 0x48)])
        self.assertEqual(result["reason"], "window_lost")
        self.assertEqual(result["restores"], 0)
        self.assertEqual(self.windows.activated, [12])
        self.windows.items, self.windows.foreground = [WINDOW], WINDOW
        self.assertTrue(self.effects.voice_up()["closed"])
        self.assertFalse(self.effects.voice_active)

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
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            self.ticks.permits.release()
            self.assertTrue(self.completed.wait(1))
        self.assertEqual(self.completions[0]["reason"], "focus_failed")
        self.assertTrue(self.effects.voice_active)
        self.assertFalse(self.completions[0]["closed"])
        self.assertEqual(self.windows.combos, [(0x5B, 0x48)])
        self.windows.foreground, self.windows.activate_ok = WINDOW, True
        self.assertTrue(self.effects.voice_up()["closed"])
        self.assertFalse(self.effects.voice_active)

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


class ShortcutTests(unittest.TestCase):
    def native_effects(self, counts):
        native, calls = ComboTests().make_native()
        send = native.user.SendInput
        remaining = iter(counts)
        native.listening, native.pressed = False, set()
        def partial(count, events, size):
            send(count, events, size)
            inserted = next(remaining, count)
            for event in events[:inserted]:
                key, flags = event.ki.wVk, event.ki.dwFlags
                if flags & 2:
                    native.pressed.discard(key)
                else:
                    if key == 0x48 and 0x5B in native.pressed:
                        native.listening = not native.listening
                    native.pressed.add(key)
            return inserted
        native.user.SendInput = partial
        native.windows = lambda: [WINDOW]
        native.activate = lambda handle: handle == WINDOW[0]
        native.exists = lambda handle: handle == WINDOW[0]
        effects = DesktopEffects(native)
        self.addCleanup(effects.close)
        return effects, calls

    def test_toggle_retry_releases_stranded_modifier_before_closing(self):
        effects, calls = self.native_effects([4, 1, 0, 0, 1, 4])
        effects.voice_down(SESSION, [SESSION])
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "combination failed"):
                effects.voice_up()
        self.assertTrue(effects.voice_active)
        self.assertEqual(effects.windows._held_keys, [0x5B])
        self.assertTrue(effects.voice_up()["closed"])
        self.assertEqual(calls[4], [(0x5B, 3)])
        self.assertEqual(effects.windows._held_keys, [])
        self.assertFalse(effects.voice_active)

    def test_failed_toggle_start_keeps_partial_key_cleanup_retryable(self):
        effects, calls = self.native_effects([1, 0, 0, 0, 0, 1])
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "combination failed"):
                effects.voice_down(SESSION, [SESSION])
        self.assertTrue(effects.voice_active)
        self.assertEqual(effects.windows._held_keys, [0x5B])
        self.assertTrue(effects.voice_up()["closed"])
        self.assertEqual(calls[-1], [(0x5B, 3)])
        self.assertEqual(len(calls), 6)
        self.assertFalse(effects.voice_active)

    def test_partial_start_that_pressed_main_key_is_closed_after_release_retry(self):
        effects, calls = self.native_effects([2, 0, 0, 0, 0, 2, 4])
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "combination failed"):
                effects.voice_down(SESSION, [SESSION])
        self.assertTrue(effects.windows.listening)
        self.assertTrue(effects.voice_active)
        self.assertTrue(effects.voice_up()["closed"])
        self.assertFalse(effects.windows.listening)
        self.assertEqual(effects.windows.pressed, set())
        self.assertEqual(len(calls), 7)

    def test_partial_start_with_successful_key_cleanup_still_stops_started_dictation(self):
        effects, calls = self.native_effects([2, 2, 4])
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "combination failed"):
                effects.voice_down(SESSION, [SESSION])
        self.assertFalse(effects.windows.listening)
        self.assertFalse(effects.voice_active)
        self.assertEqual(effects.windows.pressed, set())
        self.assertEqual(len(calls), 3)

    def test_partial_close_retry_only_releases_keys_without_reopening_dictation(self):
        effects, calls = self.native_effects([4, 2, 0, 0, 2])
        effects.voice_down(SESSION, [SESSION])
        self.assertTrue(effects.windows.listening)
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "combination failed"):
                effects.voice_up()
        self.assertFalse(effects.windows.listening)
        self.assertTrue(effects.voice_active)
        self.assertTrue(effects.voice_up()["closed"])
        self.assertFalse(effects.windows.listening)
        self.assertEqual(effects.windows.pressed, set())
        self.assertEqual(len(calls), 5)

    def test_unknown_native_delivery_releases_keys_but_keeps_input_blocked(self):
        effects, calls = self.native_effects([])
        effects.voice_down(SESSION, [SESSION])
        send = effects.windows.user.SendInput
        def interrupted(count, events, size):
            inserted = send(count, events, size)
            if len(calls) == 2:
                raise OSError("native call interrupted")
            return inserted
        effects.windows.user.SendInput = interrupted
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "native call interrupted"):
                effects.voice_up()
        self.assertEqual(effects.windows.pressed, set())
        self.assertTrue(effects.voice_active)
        before = len(calls)
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "delivery is unknown"):
                effects.voice_up()
        self.assertEqual(len(calls), before)
        # Model an operator ending dictation separately before fixture teardown.
        effects._voice.cleanup_only = True
        effects.voice_up()

    def test_outer_foreground_rejection_does_not_reuse_previous_delivery(self):
        effects, calls = self.native_effects([])
        effects.voice(SESSION, [SESSION])
        self.assertTrue(effects.windows._combo_triggered)
        with patch.object(type(effects.windows), "__call__", return_value=(99, "", "other")):
            with self.assertRaisesRegex(RuntimeError, "foreground changed"):
                effects._voice_shortcut(WINDOW)
        self.assertFalse(effects.windows._combo_triggered)
        self.assertEqual(len(calls), 2)

    def test_default_and_old_config_keep_win_h_toggle(self):
        for config in (None, {"key_codes": [0x48], "modifiers": ["command"]}):
            with self.subTest(config=config):
                effects = DesktopEffects(Windows(), dictation_shortcut=config)
                self.assertEqual(effects.dictation_shortcut,
                                 {"key_codes": [0x48], "modifiers": ["command"], "mode": "toggle"})
                effects.voice(SESSION, [SESSION])
                self.assertEqual(effects.windows.combos, [(0x5B, 0x48)] * 2)

    def test_custom_toggle_and_live_update(self):
        config = {"key_codes": [0x20], "modifiers": ["control", "option"]}
        effects = DesktopEffects(Windows(), dictation_shortcut=config)
        config["key_codes"][0] = 0x0D
        effects.voice(SESSION, [SESSION])
        self.assertEqual(effects.windows.combos, [(0x11, 0x12, 0x20)] * 2)
        effects.set_dictation_shortcut({"key_codes": [0xA5]})
        effects.voice(SESSION, [SESSION])
        self.assertEqual(effects.windows.combos[-2:], [(0xA5,)] * 2)

    def test_invalid_config_is_rejected_without_native_access(self):
        invalid = ["Win+H", {}, {"key_codes": []}, {"key_codes": [True]},
                   {"key_codes": [0]}, {"key_codes": [255]}, {"key_codes": ["H"]},
                   {"key_codes": [72] * 5}, {"key_codes": [72, 72]},
                   {"key_codes": [72], "modifiers": "control"},
                   {"key_codes": [72], "modifiers": ["ctrl"]},
                   {"key_codes": [72], "modifiers": [[], "control"]},
                   {"key_codes": [72], "modifiers": ["control", "control"]},
                   {"key_codes": [0xA5], "modifiers": ["option"]},
                   {"key_codes": [72], "mode": "press"},
                   {"key_codes": [72], "script": "arbitrary"}]
        with patch("hub_desktop.HubWindowControl", side_effect=AssertionError("native access")):
            for config in invalid:
                with self.subTest(config=config), self.assertRaises(ValueError):
                    DesktopEffects(dictation_shortcut=config)


class HoldVoiceTests(unittest.TestCase):
    def setUp(self):
        self.windows = Windows()
        self.ticks = GuardTicks()
        self.now = 100.0
        self.completed = threading.Event()
        self.results = []
        self.effects = DesktopEffects(self.windows, dictation_shortcut={
            "key_codes": [0x20], "modifiers": ["control", "option"], "mode": "hold"},
            monotonic=lambda: self.now, voice_wait=self.ticks)
        self.addCleanup(self.effects.close)
        self.addCleanup(setattr, self.windows, "input_ok", True)

    def start(self):
        def done(result):
            self.results.append(result)
            self.completed.set()
        self.effects.voice_down(SESSION, [SESSION], on_stop=done)
        self.assertEqual(self.ticks.entered.get(timeout=1), 0.1)
        self.assertTrue(self.effects.voice_active)

    def stopped(self):
        self.assertTrue(self.completed.wait(1), "guard did not finish")
        self.effects._voice.thread.join(1)
        self.assertFalse(self.effects._voice.thread.is_alive())
        self.assertFalse(self.effects.voice_active)
        self.assertEqual(self.windows.held, [])
        self.assertEqual(self.windows.released, [0x20, 0x12, 0x11])
        self.assertEqual(self.windows.combos, [])
        self.assertEqual(self.windows.keys, [])
        return self.results[-1]

    def test_hold_down_once_and_release_once_in_reverse(self):
        self.start()
        self.assertEqual(self.windows.held, [0x11, 0x12, 0x20])
        self.effects.voice_down(SESSION, [SESSION])
        self.assertEqual(self.windows.held, [0x11, 0x12, 0x20])
        self.effects.voice_up()
        self.assertEqual(self.stopped()["reason"], "released")
        self.assertIsNone(self.effects.voice_up())
        self.assertEqual(len(self.results), 1)

    def test_hold_times_out_and_releases_without_physical_up(self):
        self.start()
        self.now = 160.0
        self.ticks.permits.release()
        self.assertEqual(self.stopped()["reason"], "timeout")

    def test_missing_window_releases_owned_keys_without_new_presses(self):
        self.start()
        self.windows.items = []
        self.windows.foreground = (99, "other.exe", "other")
        self.ticks.permits.release()
        self.assertEqual(self.stopped()["reason"], "window_lost")

    def test_failed_focus_restore_still_releases(self):
        self.start()
        self.windows.foreground = (99, "other.exe", "other")
        self.windows.activate_ok = False
        self.ticks.permits.release()
        self.assertEqual(self.stopped()["reason"], "focus_failed")

    def test_query_error_still_releases(self):
        self.start()
        self.windows.windows = lambda: (_ for _ in ()).throw(OSError("lookup failed"))
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            self.ticks.permits.release()
            result = self.stopped()
        self.assertEqual(result["reason"], "error")

    def test_guard_wait_exception_still_releases(self):
        def fail_wait(stop, seconds):
            raise OSError("wait failed")
        self.effects.voice_wait = fail_wait
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            self.effects.voice_down(SESSION, [SESSION])
            self.effects._voice.thread.join(1)
        self.assertFalse(self.effects.voice_active)
        self.assertEqual(self.windows.held, [])
        self.assertEqual(self.windows.released, [0x20, 0x12, 0x11])

    def test_shutdown_releases_and_joins_guard(self):
        self.start()
        self.effects.close()
        self.assertEqual(self.stopped()["reason"], "shutdown")

    def test_thread_start_failure_releases_before_propagating(self):
        with patch("hub_desktop.threading.Thread.start", side_effect=RuntimeError("thread failed")):
            with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
                with self.assertRaisesRegex(RuntimeError, "thread failed"):
                    self.effects.voice_down(SESSION, [SESSION])
        self.assertFalse(self.effects.voice_active)
        self.assertEqual(self.windows.held, [])
        self.assertEqual(self.windows.released, [0x20, 0x12, 0x11])

    def test_exception_after_partial_down_releases_before_propagating(self):
        def partial(keys, expected):
            self.windows.held.append(keys[0])
            raise OSError("partial input")
        self.windows.hold_combo = partial
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            with self.assertRaisesRegex(OSError, "partial input"):
                self.effects.voice_down(SESSION, [SESSION])
        self.assertFalse(self.effects.voice_active)
        self.assertEqual(self.windows.held, [])
        self.assertEqual(self.windows.released, [0x11])

    def test_failed_release_keeps_ownership_and_blocks_reconfiguration_until_retry(self):
        self.start()
        self.windows.input_ok = False
        with self.assertLogs("agentdeck.hub.voice", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "key release failed"):
                self.effects.voice_up()
        self.assertTrue(self.effects.voice_active)
        self.assertEqual(self.windows.held, [0x11, 0x12, 0x20])
        with self.assertRaisesRegex(RuntimeError, "release voice"):
            self.effects.set_dictation_shortcut(None)
        self.windows.input_ok = True
        self.effects.voice_up()
        self.stopped()

    def test_live_setting_cannot_replace_the_owned_shortcut(self):
        self.start()
        with self.assertRaisesRegex(RuntimeError, "release voice"):
            self.effects.set_dictation_shortcut({"key_codes": [0xA5], "mode": "hold"})
        self.effects.voice_up()
        self.stopped()


if __name__ == "__main__":
    unittest.main(verbosity=2)
