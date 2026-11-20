"""Single-tap dictation regressions; all desktop input and user data are isolated."""
import unittest
from unittest.mock import Mock, patch

import hub
from hub_desktop import DesktopEffects
import test_hub as hub_tests
import test_hub_desktop as desktop_tests


TAP = {"key_codes": [165], "modifiers": [], "mode": "tap"}


class TapDesktopTests(unittest.TestCase):
    def setUp(self):
        self.windows = desktop_tests.Windows()
        self.effects = DesktopEffects(self.windows, dictation_shortcut=TAP)
        self.addCleanup(self.effects.close)

    def test_validation_accepts_tap_and_copies_config(self):
        config = dict(TAP, key_codes=[165])
        result = DesktopEffects._shortcut(config)
        config["key_codes"][0] = 72
        self.assertEqual(result, TAP)

    def test_down_focuses_then_taps_once_without_state_guard_or_callback(self):
        self.windows.foreground = (99, "other.exe", "other")
        stopped = Mock()
        with patch("hub_desktop.threading.Thread", side_effect=AssertionError("tap guard")):
            result = self.effects.voice_down(desktop_tests.SESSION, [desktop_tests.SESSION],
                                             on_stop=stopped)
        self.assertEqual(self.windows.activated, [desktop_tests.WINDOW[0]])
        self.assertEqual(self.windows.combos, [(165,)])
        self.assertEqual(result, {"mode": "tap", "shortcut": "右 Alt"})
        self.assertFalse(self.effects.voice_active)
        self.assertIsNone(self.effects._voice)
        stopped.assert_not_called()
        self.assertIsNone(self.effects.voice_up())
        self.effects.close()
        self.assertEqual(self.windows.combos, [(165,)])
        self.assertEqual(self.windows.held, [])
        self.assertEqual(self.windows.released, [])

    def test_each_press_taps_again_including_before_a_release(self):
        for _ in range(2):
            self.effects.voice_down(desktop_tests.SESSION, [desktop_tests.SESSION])
            self.assertFalse(self.effects.voice_active)
        self.effects.voice_up()
        self.assertEqual(self.windows.combos, [(165,)] * 2)

    def test_focus_or_send_failure_never_creates_voice_state(self):
        for focus_ok, input_ok in ((False, True), (True, False)):
            with self.subTest(focus_ok=focus_ok, input_ok=input_ok):
                self.windows.activate_ok, self.windows.input_ok = focus_ok, input_ok
                with self.assertRaises(RuntimeError):
                    self.effects.voice_down(desktop_tests.SESSION, [desktop_tests.SESSION])
                self.assertIsNone(self.effects._voice)
                self.assertFalse(self.effects.voice_active)
                self.assertIsNone(self.effects.voice_up())

    def test_right_alt_native_tap_keeps_scan_and_extended_flags(self):
        native, calls = desktop_tests.ComboTests().make_native()
        native.windows = lambda: [desktop_tests.WINDOW]
        native.activate = lambda hwnd: hwnd == desktop_tests.WINDOW[0]
        effects = DesktopEffects(native, dictation_shortcut=TAP)
        self.addCleanup(effects.close)
        events = []
        send = native.user.SendInput

        def capture(count, inputs, size):
            events.extend((item.ki.wVk, item.ki.wScan, item.ki.dwFlags) for item in inputs)
            return send(count, inputs, size)

        native.user.SendInput = capture
        effects.voice_down(desktop_tests.SESSION, [desktop_tests.SESSION])
        effects.voice_up()
        self.assertEqual(calls, [[(165, 1), (165, 3)]])
        self.assertEqual(events, [(165, 0x38, 1), (165, 0x38, 3)])
        self.assertEqual(native._held_keys, [])

    def test_shortcut_feedback_uses_configured_keys(self):
        for config, expected in ((TAP, "右 Alt"),
                                 ({"key_codes": [72], "modifiers": ["command"], "mode": "tap"}, "Win+H"),
                                 ({"key_codes": [0xA3, 0x7B], "mode": "tap"}, "右 Ctrl+F12")):
            with self.subTest(config=config):
                self.effects.set_dictation_shortcut(config)
                result = self.effects.voice_down(desktop_tests.SESSION, [desktop_tests.SESSION])
                self.assertEqual(hub.describe_input("voice_down", dict(result, status="sent")),
                                 ("语音键：已点一下" + expected, True, None))


class TapHubTests(unittest.TestCase):
    def setUp(self):
        self.fixture = hub_tests.HubTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine = self.fixture.engine
        self.windows = desktop_tests.Windows()
        self.windows.items = [(12, "WindowsTerminal.exe", "project - Claude")]
        self.windows.foreground = self.windows.items[0]
        self.engine.desktop = DesktopEffects(self.windows, dictation_shortcut=TAP)
        self.fixture.event("SessionStart")

    def test_tap_keeps_selection_and_approval_available_before_release(self):
        self.engine.event("cc", {"hook_event_name": "SessionStart", "session_id": "second",
                                  "cwd": "C:/work/other"})
        self.windows.items.append((13, "WindowsTerminal.exe", "other - Claude"))
        thread, result = self.fixture.permission()
        self.fixture.clock.value += 1
        with patch("hub_desktop.threading.Thread", side_effect=AssertionError("tap guard")):
            sent = self.engine.action({"action": "voice_down"})
        self.assertEqual(hub.describe_input("voice_down", sent)[0], "语音键：已点一下右 Alt")
        self.assertFalse(self.engine.desktop.voice_active)
        self.assertIsNone(self.engine.voice_target)
        self.assertEqual(self.engine.action({"action": "slot 2"})["status"], "selected")
        self.engine.action({"action": "slot 1"})
        self.fixture.clock.value += 0.5
        self.assertEqual(self.engine.action({"action": "approve"})["status"], "allowed")
        thread.join(1)
        self.fixture.decision(result, "allow")
        self.engine.action({"action": "voice_up"})
        self.assertEqual(self.windows.combos, [(165,)])

    def test_usb_release_keeps_tap_feedback_and_sends_no_second_shortcut(self):
        notes = []
        self.engine.note_input = lambda text, ok=True, lcd=None: notes.append((text, ok))
        keys = hub.USBKeys(self.engine, {"bindings": {"hid:0x0B": {
            "down": "voice_down", "up": "voice_up"}}}, monotonic=self.fixture.clock)
        parser = hub_tests.ReportState()
        for report in ([0, 0, 0x0B, 0, 0, 0, 0, 0], [0] * 8):
            for event in parser.feed(bytes(report)):
                keys(dict(event, t=self.fixture.clock()))
        self.assertEqual(len(notes), 1)
        self.assertIn("语音键：已点一下右 Alt", notes[0][0])
        self.assertEqual(self.windows.combos, [(165,)])
        self.assertEqual(keys.held, {})

    def test_raw_input_tap_remains_blocked(self):
        notes = []
        self.engine.note_input = lambda text, ok=True, lcd=None: notes.append((text, ok))
        keys = hub.USBKeys(self.engine, {"bindings": {}})
        self.assertFalse(keys._dispatch("hid:0x0B", "voice_down", {},
                                        self.fixture.clock(), "Raw Input"))
        self.assertIn(hub.LEAK_TEXT, notes[0][0])
        self.assertFalse(notes[0][1])
        self.assertEqual(self.windows.combos, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
