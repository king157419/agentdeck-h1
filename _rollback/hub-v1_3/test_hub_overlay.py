"""Offline overlay checks: no Tk instance, Windows focus, or device access."""
from copy import deepcopy
import ctypes
import sys
import types
import unittest
from unittest.mock import Mock, patch

from hub_overlay import COLORS, NoActivateWindow, Overlay, POLL_MS, display_model


class OverlayModelTests(unittest.TestCase):
    def test_six_slots_preserve_numbers_selection_and_source(self):
        state = {"sessions": [{"slot": 6, "name": "last", "state": "tool"},
                              {"slot": 2, "name": "app", "state": "wait"}],
                 "selected_slot": 6}
        before = deepcopy(state)
        model = display_model(state)
        self.assertEqual([slot["number"] for slot in model["slots"]], list(range(1, 7)))
        self.assertEqual(model["slots"][1]["name"], "app")
        self.assertEqual(model["slots"][5]["name"], "last")
        self.assertTrue(model["slots"][5]["selected"])
        self.assertFalse(model["slots"][0]["occupied"])
        self.assertEqual(state, before)

    def test_state_labels_and_colors(self):
        for state, expected in (("think", "RUN"), ("tool", "RUN"), ("wait", "ASK"),
                                ("locked", "ASK"), ("done", "DONE"), ("error", "ERR"),
                                ("idle", "IDLE"), ("unknown", "IDLE")):
            with self.subTest(state=state):
                slot = display_model({"sessions": [{"slot": 1, "state": state}]})["slots"][0]
                self.assertEqual((slot["label"], slot["color"]), (expected, COLORS[expected]))

    def test_only_displayed_request_appears_and_summary_is_at_most_80(self):
        model = display_model({"displayed_request_id": "shown", "pending": [
            {"id": "other", "summary": "other"},
            {"id": "shown", "summary": "中" * 100 + "\n next", "risk": "high"}]})
        self.assertEqual(model["request"]["id"], "shown")
        self.assertEqual(len(model["request"]["summary"]), 80)
        self.assertEqual(model["request"]["color"], COLORS["ERR"])
        self.assertTrue(model["request"]["can_approve"])
        self.assertIsNone(display_model({"pending": [{"id": "other"}]})["request"])
        self.assertIsNone(display_model({"displayed_request_id": "gone", "pending": []})["request"])

    def test_summary_whitespace_armed_high_and_critical_lock(self):
        pending = {"id": "a", "summary": "echo\n   hello", "risk": "high", "armed": True}
        result = display_model({"displayed_request_id": "a", "pending": [pending]})["request"]
        self.assertEqual(result["summary"], "echo hello")
        self.assertEqual(result["label"], "HIGH · press again")
        pending.update(risk="critical", status="locked")
        result = display_model({"displayed_request_id": "a", "locked": [pending]})["request"]
        self.assertEqual(result["label"], "LOCKED: use terminal")
        self.assertFalse(result["can_approve"])
        self.assertFalse(result["can_deny"])


class OverlayActionsTests(unittest.TestCase):
    def setUp(self):
        self.hub = Mock()
        self.hub.action.return_value = {"status": "allowed"}
        self.window = Mock()
        self.overlay = Overlay(self.hub, window=self.window)

    def test_callbacks_share_action_path_and_capture_stale_id(self):
        self.overlay.model = display_model({"displayed_request_id": "old", "pending": [{"id": "old"}]})
        self.overlay._decision_press(None, "approve")
        self.overlay.model = display_model({"displayed_request_id": "new", "pending": [{"id": "new"}]})
        self.overlay._decision_release("approve")
        self.hub.action.assert_called_once_with({"action": "approve", "request_id": "old"}, source="overlay")
        self.assertEqual(self.window.restore.call_count, 2)
        self.window.remember.assert_called_once_with()
        self.assertEqual(self.overlay.message, "allowed")

    def test_empty_or_locked_display_cannot_decide(self):
        self.overlay.dispatch("approve")
        self.overlay._decision_release("deny")
        self.overlay.model = display_model({"displayed_request_id": "locked", "locked": [
            {"id": "locked", "risk": "critical"}]})
        self.overlay._decision_press(None, "approve")
        self.overlay._decision_release("approve")
        self.hub.action.assert_not_called()

    def test_slot_clicks_work_without_keyboard(self):
        self.overlay.model = display_model({"sessions": [{"slot": 4, "name": "app"}]})
        self.overlay._select(3)
        self.hub.action.assert_not_called()
        self.overlay._select(4)
        self.hub.action.assert_called_once_with({"action": "slot 4"}, source="overlay")

    def test_stale_error_is_reported_and_focus_restored(self):
        self.hub.action.side_effect = ValueError("displayed request changed")
        with self.assertLogs("agentdeck.hub.overlay", level="WARNING"):
            self.overlay.dispatch("deny", "old")
        self.assertEqual(self.overlay.message, "displayed request changed")
        self.assertEqual(self.window.restore.call_count, 2)

    def test_stop_is_only_a_signal_and_poll_quits_on_tk_thread(self):
        root = self.overlay.root = Mock()
        self.overlay.stop()
        root.quit.assert_not_called()
        self.window.close.assert_not_called()
        self.overlay._poll()
        root.quit.assert_called_once_with()
        root.after.assert_not_called()

    def test_poll_uses_safe_hub_snapshot_every_300_ms(self):
        self.hub.state.return_value = {"sessions": []}
        root = self.overlay.root = Mock()
        with patch.object(self.overlay, "_render") as render:
            self.overlay._poll()
        self.hub.state.assert_called_once_with()
        render.assert_called_once_with()
        root.after.assert_called_once_with(POLL_MS, self.overlay._poll)

    def test_poll_grows_for_a_new_request_without_moving_the_bottom_edge(self):
        self.overlay._height = 240
        root = self.overlay.root = Mock()
        root.winfo_reqheight.return_value = 340
        root.winfo_x.return_value = 900
        root.winfo_y.return_value = 600
        self.hub.state.return_value = {}
        with patch.object(self.overlay, "_render"):
            self.overlay._poll()
        root.geometry.assert_called_once_with("360x340+900+500")

    def test_render_keeps_decision_labels_during_refresh(self):
        self.overlay.rows = [(Mock(), Mock(), Mock(), Mock()) for _ in range(6)]
        for name in ("detail", "risk", "summary", "note", "decisions"):
            setattr(self.overlay, name, Mock())
        buttons = self.overlay.decision_buttons = {"approve": Mock(), "deny": Mock()}
        self.overlay.model = display_model({"displayed_request_id": "a", "pending": [{"id": "a"}]})
        with patch.object(self.overlay, "_button", side_effect=AssertionError("recreated button")):
            self.overlay._render()
            self.overlay._render()
        self.overlay.decisions.winfo_children.assert_not_called()
        self.assertIs(self.overlay.decision_buttons, buttons)
        self.assertEqual(buttons["approve"].configure.call_count, 2)

    def test_run_applies_noactivate_before_show_and_cleans_up(self):
        root = Mock()
        root.winfo_reqheight.return_value = 240
        root.winfo_screenwidth.return_value = 1600
        root.winfo_screenheight.return_value = 900
        root.winfo_id.return_value = 101
        events = []
        root.deiconify.side_effect = lambda: events.append("deiconify")
        root.mainloop.side_effect = lambda: events.append("mainloop")
        self.window.apply.side_effect = lambda hwnd: events.append(("apply", hwnd))
        self.window.show.side_effect = lambda: events.append("show")
        done = self.overlay.on_close = Mock()
        with patch.dict(sys.modules, {"tkinter": types.SimpleNamespace(Tk=lambda: root)}), \
                patch.object(self.overlay, "_build"), patch.object(self.overlay, "_poll"):
            self.overlay.run()
        self.assertEqual(events, [("apply", 101), "deiconify", "show", "mainloop"])
        root.withdraw.assert_called_once_with()
        self.window.close.assert_called_once_with()
        root.destroy.assert_called_once_with()
        done.assert_called_once_with()


class NativeFunction:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class NoActivateTests(unittest.TestCase):
    def setUp(self):
        self.hwnd = 2 ** 35 + 30
        self.foreground = 500
        self.style = 0x40000
        self.sets = []
        self.original_proc = 2 ** 35 + 99
        self.activations = []

        def set_long(hwnd, index, value):
            self.sets.append((hwnd, index, value))
            return self.style if index == -20 else self.original_proc

        def activate(hwnd):
            self.activations.append(hwnd)
            self.foreground = hwnd
            return True

        self.user = types.SimpleNamespace(**{name: NativeFunction(callback) for name, callback in {
            "GetAncestor": lambda hwnd, flag: self.hwnd,
            "GetWindowLongPtrW": lambda hwnd, index: self.style,
            "SetWindowLongPtrW": set_long,
            "GetForegroundWindow": lambda: self.foreground,
            "SetForegroundWindow": activate,
            "IsChild": lambda parent, child: child == 33,
            "CallWindowProcW": lambda *args: 42,
            "SetWindowPos": lambda *args: True,
            "ShowWindow": lambda *args: True,
        }.items()})
        self.window = NoActivateWindow(self.user)

    def test_pointer_safe_style_and_mouseactivate_handling(self):
        self.window.apply(30)
        hwnd, index, style = self.sets[0]
        self.assertEqual((hwnd, index), (self.hwnd, -20))
        self.assertTrue(style & 0x08000000)
        self.assertTrue(style & 0x80)
        self.assertFalse(style & 0x40000)
        self.assertIs(self.user.SetWindowLongPtrW.restype, ctypes.c_ssize_t)
        self.assertEqual(self.window._message(self.hwnd, 0x21, 0, 0), 3)
        self.assertEqual(self.window._message(self.hwnd, 123, 0, 0), 42)
        self.window.close()
        self.assertEqual(self.sets[-1], (self.hwnd, -4, self.original_proc))

    def test_restore_only_when_overlay_owns_foreground(self):
        self.window.apply(30)
        self.window.remember()
        self.foreground = self.hwnd
        self.window.restore()
        self.assertEqual(self.activations, [500])
        self.foreground = 600  # Slot action intentionally focused a different window.
        self.window.restore()
        self.assertEqual(self.activations, [500])
        self.window.remember()
        self.foreground = 33  # An overlay child stole focus.
        self.window.restore()
        self.assertEqual(self.activations, [500, 600])
        self.window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
