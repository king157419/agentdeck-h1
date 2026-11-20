"""Daily-fix integration regressions; no desktop, device or user profile access."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import hub
from hub_desktop import DesktopEffects


class DailyFixTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.clock = 100.0
        self.desktop = Mock(voice_active=False)
        self.desktop.release_window_switch.return_value = True
        self.desktop.current_session_title.return_value = None
        self.engine = hub.Hub(home=self.home, lcd_enabled=False, desktop=self.desktop,
                              monotonic=lambda: self.clock, wall_time=lambda: self.clock)
        self.addCleanup(self.engine.close)

    def event(self, sid, name="SessionStart"):
        self.engine.event("cc", {"hook_event_name": name, "session_id": sid,
                                 "session_title": sid.title(), "cwd": "D:/project",
                                 "agentdeck_window": {"hwnd": 11, "exe": "claude.exe"}})

    def sessions(self):
        for sid in ("alpha", "beta", "gamma"):
            self.event(sid)
            self.clock += 1

    def join_reader(self):
        reader = self.engine.cycle_reader
        self.assertIsNotNone(reader)
        reader.join(timeout=1)
        self.assertFalse(reader.is_alive())

    def test_cycle_never_activates_or_invokes_but_press_still_does(self):
        self.sessions()
        result = self.engine.action({"action": "cycle +1"})
        self.join_reader()
        self.assertEqual(result["status"], "selected")
        self.assertNotIn("window", result)
        self.desktop.focus.assert_not_called()
        self.desktop.show_session.assert_not_called()
        self.engine.action({"action": "show"})
        self.desktop.show_session.assert_called_once()

    def test_blocked_read_does_not_block_first_step_and_late_read_anchors(self):
        self.sessions()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def title(_):
            entered.set()
            release.wait(2)
            return "Beta"
        self.desktop.current_session_title.side_effect = title
        completed = threading.Event()
        action = threading.Thread(target=lambda: (self.engine.action({"action": "cycle +1"}), completed.set()), daemon=True)
        action.start()
        self.assertTrue(entered.wait(0.5))
        self.assertTrue(completed.wait(0.5), "first step waited for UI Automation")
        release.set()
        self.join_reader()
        self.assertEqual(self.engine.selected, ("cc", "beta"))
        self.desktop.focus.assert_not_called()

    def test_second_step_or_other_action_invalidates_late_read(self):
        for followup in ("cycle +1", "slot 1"):
            with self.subTest(followup=followup):
                self.sessions()
                entered, release = threading.Event(), threading.Event()
                self.addCleanup(release.set)
                def title(_):
                    entered.set()
                    release.wait(2)
                    return "Beta"
                self.desktop.current_session_title.side_effect = title
                self.engine.action({"action": "cycle +1"})
                self.assertTrue(entered.wait(0.5))
                self.engine.action({"action": followup})
                selected = self.engine.selected
                release.set()
                self.join_reader()
                self.assertEqual(self.engine.selected, selected)
                self.clock += 6

    def test_rotation_and_overlay_share_frozen_order_until_five_second_pause(self):
        self.sessions()
        self.engine.action({"action": "cycle +1"})
        self.join_reader()
        order = self.engine.state()["display_order"]
        self.assertEqual(order, [3, 2, 1])
        self.clock += 0.2
        self.event("alpha", "UserPromptSubmit")
        self.assertEqual(self.engine.state()["display_order"], order)
        selected = self.engine.state()["selected_slot"]
        result = self.engine.action({"action": "cycle +1"})
        self.assertEqual(result["slot"], order[(order.index(selected) + 1) % 3])
        self.clock += 5
        self.assertEqual(self.engine.state()["display_order"], [1, 3, 2])

    def test_new_sessions_keep_their_positions_during_rotation(self):
        self.sessions()
        self.engine.action({"action": "cycle +1"})
        self.join_reader()
        self.event("delta")
        self.assertEqual(self.engine.state()["display_order"], [3, 2, 1, 4])
        self.clock += .1
        self.event("epsilon")
        order = self.engine.state()["display_order"]
        self.assertEqual(order, [3, 2, 1, 4, 5])
        self.clock += .1
        self.event("delta", "UserPromptSubmit")
        self.assertEqual(self.engine.state()["display_order"], order)

    def test_shutdown_during_background_read_never_creates_uia_after_close(self):
        self.sessions()
        entered, release, desktop_closed = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def foreground():
            entered.set()
            release.wait(2)
            return (11, "claude.exe", "Claude")
        effects = DesktopEffects(windows=foreground)
        original_close = effects.close
        def close():
            original_close()
            desktop_closed.set()
        effects.close = close
        self.engine.desktop = effects
        with patch("claude_uia.ClaudeUIA") as uia:
            self.engine.action({"action": "cycle +1"})
            self.assertTrue(entered.wait(.5))
            shutdown = threading.Thread(target=self.engine.close, daemon=True)
            shutdown.start()
            self.assertTrue(desktop_closed.wait(.5))
            release.set()
            shutdown.join(timeout=1)
            self.assertFalse(shutdown.is_alive())
            self.join_reader()
            uia.assert_not_called()

    def test_closed_hub_cannot_lazily_create_desktop_effects(self):
        self.engine.desktop = None
        self.engine.close()
        with patch("hub_desktop.DesktopEffects") as desktop, self.assertRaises(hub.HubError):
            self.engine._desktop()
        desktop.assert_not_called()

    def test_overlay_actions_need_no_session_or_desktop(self):
        self.assertFalse(self.engine.state()["overlay_pinned"])
        self.assertTrue(self.engine.action({"action": "overlay toggle"})["pinned"])
        self.assertFalse(self.engine.action({"action": "overlay toggle"})["pinned"])
        for number in range(1, 5):
            self.engine.action({"action": "overlay corner"})
            self.assertEqual(self.engine.state()["overlay_corner_requests"], number)
        with self.assertRaises(hub.HubError):
            self.engine.action({"action": "overlay unknown"})
        self.desktop.focus.assert_not_called()

    def test_empty_approval_and_blocked_navigation_publish_compact_feedback(self):
        keys = hub.USBKeys(self.engine, {"bindings": {}})
        for command in ("approve", "deny"):
            self.assertTrue(keys._dispatch("hid:0x0A", command, {}, self.clock))
            feedback = self.engine.state()["last_input"]
            self.assertEqual(feedback["text"], "现在没有要批准的请求")
            self.assertTrue(feedback["compact"])
        self.event("alpha")
        self.assertFalse(keys._dispatch("hid:0x0F", "nav up", {}, self.clock))
        feedback = self.engine.state()["last_input"]
        self.assertEqual(feedback["text"], "只有 agent 提问时才能用")
        self.assertTrue(feedback["compact"])

    def test_hotkeys_publish_the_same_compact_and_cycle_metadata(self):
        from hub_hotkey import HotkeyKeys
        keys = HotkeyKeys(self.engine)
        keys._note("approve", {"status": "no_request"})
        feedback = self.engine.state()["last_input"]
        self.assertTrue(feedback["compact"])
        self.assertEqual(feedback["text"], "现在没有要批准的请求")
        keys._note("nav up", error=hub.HubError("nav up/down works only while the agent asks a question"))
        self.assertTrue(self.engine.state()["last_input"]["compact"])
        keys._note("cycle +1", {"status": "selected", "slot": 1})
        self.assertEqual(self.engine.state()["last_input"]["action"], "cycle +1")

    def test_usb_filter_is_applied_to_real_dispatch_and_leaves_buttons_alone(self):
        engine = Mock(monotonic=lambda: self.clock)
        engine.input_snapshot.return_value = {}
        keys = hub.USBKeys(engine, {"bindings": {"hid:0x15": "cycle +1", "hid:0x13": "cycle -1",
                                                "hid:0x14": "show"}}, knob_divider={"2": 2})
        def press(usage, seconds):
            self.clock += seconds
            keys({"down": True, "usage": usage, "keys": ["hid:0x%02X" % usage],
                  "pressed": [usage], "t": self.clock})
        press(0x15, 0)
        engine.action.assert_not_called()
        press(0x15, 0.02)
        self.assertEqual(engine.action.call_args.args[0], {"action": "cycle +1"})
        press(0x13, 0.02)
        self.assertEqual(engine.action.call_count, 1)
        press(0x14, 0.01)
        self.assertEqual(engine.action.call_args.args[0], {"action": "show"})

    def test_config_passes_release_timeout_and_knob_divider_to_runtime(self):
        config = self.home / ".agentdeck/config.json"
        config.parent.mkdir()
        config.write_text(json.dumps({"knob_divider": {"1": 2}, "window_switch_release_ms": 1500}), encoding="utf-8")
        with patch("hub.HubServer") as server, patch("hub.Hub"), patch("hub.USBKeys") as keys, patch(
                "hub_keyboard.KeyboardInput"), patch("hub_desktop.DesktopEffects") as effects, patch(
                "hub.load_token", return_value="token"):
            server.return_value.serve_forever.side_effect = KeyboardInterrupt
            self.assertEqual(hub.main(["--home", str(self.home), "--no-lcd", "--backend", "usb"]), 0)
        self.assertEqual(keys.call_args.kwargs["knob_divider"], {"1": 2})
        self.assertEqual(effects.call_args.kwargs["window_switch_release_ms"], 1500)
        effects = DesktopEffects(windows=Mock(), window_switch_release_ms=1700)
        with patch("hub_window_switch.WindowSwitcher") as switcher:
            effects.window(None, [], "prev")
        self.assertEqual(switcher.call_args.kwargs["release_ms"], 1700)


if __name__ == "__main__":
    unittest.main(verbosity=2)
