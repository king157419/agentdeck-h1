"""Offline app/window dispatch, measured feedback and keymap migration."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import agentdeck_app as app
from deck_usb import ReportState
import hub
from hub_overlay import Overlay, display_model, WIDTH


class AppSwitchTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.desktop = Mock(voice_active=False)
        self.desktop.app.return_value = True
        self.desktop.window.return_value = True
        self.engine = hub.Hub(desktop=self.desktop, home=Path(folder.name), lcd_enabled=False)
        self.addCleanup(self.engine.close)

    def start(self, sid):
        self.engine.event("cc", {"hook_event_name": "SessionStart", "session_id": sid,
                                 "cwd": "D:/project/" + sid})

    def test_next_prev_preserve_selected_slot_and_dispatch_snapshot(self):
        self.start("a")
        self.start("b")
        self.engine.action({"action": "slot 2"})
        selected = self.engine.selected
        for direction in ("next", "prev"):
            result = self.engine.action({"action": "app " + direction})
            self.assertEqual(result, {"action": "app", "status": "sent"})
            session, sessions, sent_direction = self.desktop.app.call_args.args
            self.assertEqual((session["session_id"], len(sessions), sent_direction), ("b", 2, direction))
            self.assertEqual(self.engine.selected, selected)
            self.assertEqual(self.engine.state()["selected_slot"], 2)

    def test_no_sessions_still_dispatches_for_desktop_window_fallback(self):
        self.engine.action({"action": "app next"})
        self.desktop.app.assert_called_once_with(None, [], "next")
        self.assertIsNone(self.engine.selected)

    def test_invalid_arguments_and_active_voice_do_not_dispatch(self):
        for action in ("app", "app forward", "app next extra"):
            with self.subTest(action=action), self.assertRaisesRegex(hub.HubError, "app needs next or prev"):
                self.engine.action({"action": action})
        self.desktop.voice_active = True
        for action in ("app next", "app prev"):
            with self.assertRaisesRegex(hub.HubError, "release voice"):
                self.engine.action({"action": action})
        self.desktop.app.assert_not_called()

    def test_usb_knob_reports_dispatch_window_and_name_both_directions(self):
        clock = [self.engine.monotonic()]
        self.engine.monotonic = lambda: clock[0]
        keys = hub.USBKeys(self.engine)
        for usage, direction, name in ((0x09, "next", "顺时针"), (0x16, "prev", "逆时针")):
            clock[0] += .5  # Rest: v9 clears the accumulator, so each direction is a fresh first step.
            event = next(iter(ReportState().feed(bytes([0, 0, usage, 0, 0, 0, 0, 0]))))
            calls = len(self.desktop.window.call_args_list)
            # One pulse is one step: the CXT encoder emits one pulse per notch.
            with self.assertLogs("agentdeck.hub", "INFO") as logs:
                keys(dict(event, t=self.engine.monotonic()))
            # v9: a successful window switch shows no toast; only failures are reported.
            self.assertIsNone(self.engine.state()["last_input"])
            self.assertIn("旋钮 1 " + name, "\n".join(logs.output))
            self.assertEqual(len(self.desktop.window.call_args_list), calls + 1)
            self.assertEqual(self.desktop.window.call_args.args[-1], direction)
        # A failed switch is still reported and names the physical control.
        self.desktop.window.return_value = False
        clock[0] += .5
        event = next(iter(ReportState().feed(bytes([0, 0, 0x09, 0, 0, 0, 0, 0]))))
        keys(dict(event, t=self.engine.monotonic()))
        last = self.engine.state()["last_input"]
        self.assertEqual(last["text"], "旋钮 1 顺时针 → 此操作不可用")
        self.assertEqual((last["action"], last["kind"]), ("window next", "noop"), last)

    def test_window_dispatch_without_sessions_preserves_selection(self):
        for direction in ("next", "prev"):
            result = self.engine.action({"action": "window " + direction})
            self.assertEqual(result, {"action": "window", "status": "sent"})
            self.desktop.window.assert_called_with(None, [], direction)
            self.assertIsNone(self.engine.selected)

    def test_window_invalid_arguments_and_voice_are_rejected(self):
        for action in ("window", "window forward", "window next extra"):
            with self.subTest(action=action), self.assertRaisesRegex(hub.HubError, "window needs next or prev"):
                self.engine.action({"action": action})
        self.desktop.voice_active = True
        for action in ("window next", "window prev"):
            with self.assertRaisesRegex(hub.HubError, "release voice"):
                self.engine.action({"action": action})
        self.desktop.window.assert_not_called()

    def test_raw_input_refuses_both_app_directions_and_names_control(self):
        keys = hub.USBKeys(self.engine)
        for binding, direction in (("hid:0x09", "next"), ("hid:0x16", "prev")):
            self.assertFalse(keys._dispatch(binding, "app " + direction, {}, self.engine.monotonic(), "Raw Input"))
            last = self.engine.state()["last_input"]
            self.assertEqual(last["text"], hub.control_name(binding) + " → " + hub.LEAK_TEXT)
            self.assertFalse(last["ok"], last)
        self.desktop.app.assert_not_called()

    def test_raw_input_refuses_both_window_directions(self):
        keys = hub.USBKeys(self.engine)
        for binding, direction in (("hid:0x09", "next"), ("hid:0x16", "prev")):
            self.assertFalse(keys._dispatch(binding, "window " + direction, {}, self.engine.monotonic(), "Raw Input"))
            last = self.engine.state()["last_input"]
            self.assertEqual(last["text"], hub.control_name(binding) + " → " + hub.LEAK_TEXT)
            self.assertFalse(last["ok"], last)
        self.desktop.window.assert_not_called()

    def test_missing_window_error_uses_requested_feedback(self):
        self.desktop.app.side_effect = RuntimeError("没找到 Claude 桌面版窗口")
        keys = hub.USBKeys(self.engine)
        self.assertFalse(keys._dispatch("hid:0x09", "app next", {}, self.engine.monotonic()))
        self.assertEqual(self.engine.state()["last_input"]["text"], "旋钮 1 顺时针 → 没找到 Claude 桌面版窗口")

    def test_feedback_names_approval_voice_and_shared_controls(self):
        self.assertEqual(hub.control_name("hid:0x13"), "第 5 排第 4 颗 / 旋钮 2 逆时针")
        self.assertEqual(hub.control_name("hid:0x0F"), "第 3 排第 1 颗 / 旋钮 1 按下")
        self.assertEqual(hub.control_name("ctrl+hid:0x09"), "第 2 排第 2 颗")
        self.assertEqual(hub.control_name("ctrl+hid:0x19"), "第 5 排第 3 颗")
        self.assertEqual(hub.control_name("hid:0x19"), "旋钮 3 按下")
        self.assertEqual(hub.control_name("hid:0x68"), "F13")
        keys = hub.USBKeys(self.engine)
        keys._note("hid:0x0A", "approve", {"status": "allowed"})
        self.assertEqual(self.engine.state()["last_input"]["text"], "第 2 排第 1 颗 → 已批准")
        for action, text in (("voice_down", "开始说话"), ("voice_up", "停止说话")):
            keys._note("hid:0x0B", action, {"status": "sent"})
            self.assertEqual(self.engine.state()["last_input"]["text"], "第 2 排第 3 颗 → " + text)
        keys._note("hid:0x13", "cycle -1", {"status": "selected", "slot": 2})
        self.assertEqual(self.engine.state()["last_input"]["text"],
                         "第 5 排第 4 颗 / 旋钮 2 逆时针 → 已选槽位 2")


class FeedbackLayoutTests(unittest.TestCase):
    def test_long_shared_control_feedback_is_clipped_to_one_fixed_line_toast(self):
        # v9 replaced the wrapping header label with a fixed 220x28 one-line toast
        # beside the strip: a long physical-control name must be clipped there and
        # must not resize or move the strip.
        from unittest.mock import patch
        from hub_overlay import FEEDBACK_HEIGHT, FEEDBACK_WIDTH, _clip_columns, _text_width
        from test_hub_keymap_v9_overlay import Canvas, Native, sessions
        fake = Mock()
        native = Native()
        overlay = Overlay(fake, window=native)
        overlay.root = Mock()
        overlay._v9_ready = True
        overlay._strip_canvas = Canvas()
        overlay._new_v9_window = lambda **kwargs: (Mock(), Canvas(), None)
        overlay._v9_windows = {kind: (Mock(), Canvas(), None) for kind in ("card", "feedback")}
        text = hub.control_name("hid:0x13") + " → " + hub.describe_input(
            "cycle -1", {"status": "selected", "slot": 2, "shared_window": True})[0]
        self.assertGreater(_text_width(text), 29)
        def render(state):
            fake.state.return_value = dict({"layer": "agent", "sessions": sessions()}, **state)
            with patch("hub_overlay.time.time", return_value=100):
                overlay._poll_v9()
        render({})
        bounds = list(native.bounds)
        render({"last_input": {"at": 100, "kind": "success", "text": text}})
        self.assertEqual(native.bounds, bounds)
        popup, canvas, _ = overlay._v9_windows["feedback"]
        popup.deiconify.assert_called_once()
        self.assertEqual((canvas.options["width"], canvas.options["height"]),
                         (FEEDBACK_WIDTH, FEEDBACK_HEIGHT))
        texts = [item[2]["text"] for item in canvas.shapes if item[0] == "text"]
        self.assertEqual(texts, [_clip_columns(text, 29)])
        self.assertTrue(texts[0].endswith("…"))
        self.assertLessEqual(_text_width(texts[0]), 29)
        self.assertIsNone(overlay.feedback_label)  # no wrapping header label in v9


def old_default_bindings(version):
    """The shipped bindings of an earlier keymap: v8 baseline patched per version (v9 moved most keys)."""
    return {key: value for key, value in dict(app.V8_BINDINGS, **app.OLD_DEFAULTS[version]).items()
            if value is not None}


def old_keymap(shipped, version):
    old = dict(shipped, version=version, bindings=old_default_bindings(version))
    old.pop("layers", None)  # no earlier default had layers
    return old


class V8MigrationTests(unittest.TestCase):
    def test_v7_untouched_upgrade_keeps_original_backup_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = app.data_dir(home) / "hub_keys.json"
            target.parent.mkdir()
            shipped = hub.load_json(app.resource_dir() / "hub_keys.json")
            original = json.dumps(old_keymap(shipped, 7), indent=3).encode("utf-8")
            target.write_bytes(original)
            app.prepare_configs(home)
            self.assertEqual(hub.load_json(target), shipped)
            self.assertEqual(shipped["version"], 9)
            backup = target.with_name("hub_keys.json.bak-v7")
            self.assertEqual(backup.read_bytes(), original)
            app.prepare_configs(home)
            self.assertEqual(backup.read_bytes(), original)
            self.assertFalse(app.upgrade_keymap(target, app.resource_dir() / "hub_keys.json"))

    def test_custom_v7_bindings_hotkeys_and_profiles_stay_byte_identical(self):
        source = app.resource_dir() / "hub_keys.json"
        for section in ("bindings", "hotkey", "v2_emulation"):
            with self.subTest(section=section), tempfile.TemporaryDirectory() as directory:
                old = old_keymap(hub.load_json(source), 7)
                if section == "v2_emulation":
                    old[section]["bindings"]["hid:0x08"] = "slot 6"
                else:
                    old[section]["hid:0x08" if section == "bindings" else "F13"] = "slot 6"
                original = json.dumps(old, indent=3).encode("utf-8")
                target = Path(directory) / "hub_keys.json"
                target.write_bytes(original)
                self.assertFalse(app.upgrade_keymap(target, source))
                self.assertEqual(target.read_bytes(), original)
                self.assertFalse(target.with_name("hub_keys.json.bak-v7").exists())

    def test_v6_untouched_upgrade_backup_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = app.data_dir(home) / "hub_keys.json"
            target.parent.mkdir()
            shipped = hub.load_json(app.resource_dir() / "hub_keys.json")
            original = json.dumps(old_keymap(shipped, 6), indent=3).encode("utf-8")
            target.write_bytes(original)
            app.prepare_configs(home)
            self.assertEqual(hub.load_json(target), shipped)
            backup = target.with_name("hub_keys.json.bak-v6")
            self.assertEqual(backup.read_bytes(), original)
            app.prepare_configs(home)
            self.assertEqual(backup.read_bytes(), original)
            self.assertFalse(app.upgrade_keymap(target, app.resource_dir() / "hub_keys.json"))

    def test_custom_v6_bindings_hotkeys_and_profiles_stay_byte_identical(self):
        source = app.resource_dir() / "hub_keys.json"
        for section in ("bindings", "hotkey", "v2_emulation"):
            with self.subTest(section=section), tempfile.TemporaryDirectory() as directory:
                old = old_keymap(hub.load_json(source), 6)
                if section == "v2_emulation":
                    old[section]["bindings"]["hid:0x08"] = "slot 6"
                else:
                    old[section]["hid:0x08" if section == "bindings" else "F13"] = "slot 6"
                original = json.dumps(old, indent=3).encode("utf-8")
                target = Path(directory) / "hub_keys.json"
                target.write_bytes(original)
                self.assertFalse(app.upgrade_keymap(target, source))
                self.assertEqual(target.read_bytes(), original)
                self.assertFalse(target.with_name("hub_keys.json.bak-v6").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
