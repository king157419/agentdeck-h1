"""Offline app dispatch, measured control feedback and v6 migration regressions."""
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

    def test_usb_knob_reports_dispatch_app_and_name_both_directions(self):
        keys = hub.USBKeys(self.engine)
        for usage, direction, name in ((0x09, "next", "顺时针"), (0x16, "prev", "逆时针")):
            event = next(iter(ReportState().feed(bytes([0, 0, usage, 0, 0, 0, 0, 0]))))
            with self.assertLogs("agentdeck.hub", "INFO") as logs:
                keys(dict(event, t=self.engine.monotonic()))
            text = "旋钮 1 %s → Claude：%s一个会话" % (name, "下" if direction == "next" else "上")
            self.assertEqual(self.engine.state()["last_input"]["text"], text)
            self.assertIn("旋钮 1 " + name, "\n".join(logs.output))
            self.assertEqual(self.desktop.app.call_args.args[-1], direction)

    def test_raw_input_refuses_both_app_directions_and_names_control(self):
        keys = hub.USBKeys(self.engine)
        for binding, direction in (("hid:0x09", "next"), ("hid:0x16", "prev")):
            self.assertFalse(keys._dispatch(binding, "app " + direction, {}, self.engine.monotonic(), "Raw Input"))
            last = self.engine.state()["last_input"]
            self.assertEqual(last["text"], hub.control_name(binding) + " → " + hub.LEAK_TEXT)
            self.assertFalse(last["ok"])
        self.desktop.app.assert_not_called()

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
    def test_long_shared_control_feedback_wraps_and_keeps_header_buttons_visible(self):
        import tkinter as tk
        from test_hub_ui_live import FakeHub
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        overlay = Overlay(FakeHub())
        overlay.root = root
        overlay._build()
        state = {"sessions": [{"slot": i, "name": "session", "state": "idle"} for i in range(1, 7)]}
        overlay.model = display_model(state)
        text = hub.control_name("hid:0x13") + " → " + hub.describe_input(
            "cycle -1", {"status": "selected", "slot": 2, "shared_window": True})[0]
        overlay.model["feedback"] = {"text": text, "ok": True}
        overlay._render()
        root.geometry("%dx480+60+60" % WIDTH)
        root.deiconify()
        root.update()
        self.assertTrue(all(widget.winfo_ismapped() for widget in overlay.header.winfo_children()))
        self.assertEqual(overlay.status_label.cget("text"), "6 个会话")
        self.assertEqual(overlay.feedback_label.cget("text"), text)
        self.assertGreaterEqual(overlay.feedback_label.winfo_width(), overlay.feedback_label.winfo_reqwidth())
        self.assertGreater(overlay.feedback_label.winfo_height(), overlay.status_label.winfo_height())
        overlay.model = display_model(state)
        overlay._render()
        root.update_idletasks()
        self.assertFalse(overlay.feedback_label.winfo_ismapped())


class V7MigrationTests(unittest.TestCase):
    def test_v6_untouched_upgrade_backup_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = app.data_dir(home) / "hub_keys.json"
            target.parent.mkdir()
            shipped = hub.load_json(app.resource_dir() / "hub_keys.json")
            original = json.dumps(dict(shipped, version=6,
                                       bindings=dict(shipped["bindings"], **app.V6_CHANGED)), indent=3).encode("utf-8")
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
                old = hub.load_json(source)
                old["version"] = 6
                old["bindings"].update(app.V6_CHANGED)
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
