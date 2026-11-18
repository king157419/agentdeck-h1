"""Offline Hub desktop checks: fake windows, clipboard and capture only."""
from datetime import datetime
from pathlib import Path
import tempfile
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
        self.assertEqual(self.windows.combos, [(0x5B, 0x48)])
        self.assertEqual(self.windows.keys, [])

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
