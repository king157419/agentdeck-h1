"""Offline overlay checks: no Tk instance, Windows focus, or device access."""
from copy import deepcopy
import ctypes
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

import agentdeck_theme as theme
from hub_overlay import (COLORS, FOREGROUND, BACKGROUND, TRANSLUCENT_ALPHA, OPAQUE_ALPHA,
                         NoActivateWindow, Overlay, POLL_MS, display_model)


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

    def test_gate_labels_and_buttons_include_critical_without_native_lock(self):
        for risk in ("low", "high", "critical"):
            for armed in (False, True):
                with self.subTest(risk=risk, armed=armed):
                    pending = {"id": "gate", "summary": "command", "risk": risk,
                               "gate": True, "status": "pending", "armed": armed}
                    state = {"displayed_request_id": "gate", "pending": [pending]}
                    before = deepcopy(state)
                    detail = display_model(state)["request"]
                    expected = "GATE · " + risk.upper()
                    if armed and risk in ("high", "critical"):
                        expected += " · press again"
                    self.assertEqual(detail["label"], expected)
                    self.assertTrue(detail["can_approve"])
                    self.assertTrue(detail["can_deny"])
                    self.assertEqual(state, before)

    def test_gate_confirmation_marker_preserves_permission_button_policy(self):
        for risk in ("low", "high", "critical"):
            with self.subTest(risk=risk):
                pending = {"id": "permission", "risk": risk, "gate_confirmed": True}
                detail = display_model({"displayed_request_id": "permission",
                                        "pending": [pending]})["request"]
                self.assertIn("已在闸门确认", detail["label"])
                self.assertNotIn("GATE", detail["label"])
                self.assertEqual(detail["can_approve"], risk != "critical")
                self.assertEqual(detail["can_deny"], risk != "critical")


class OverlayActionsTests(unittest.TestCase):
    def setUp(self):
        self.hub = Mock()
        self.hub.action.return_value = {"status": "allowed"}
        self.hub.monotonic.return_value = 100.0
        self.window = Mock()
        self.overlay = Overlay(self.hub, window=self.window)

    def test_callbacks_share_action_path_and_capture_stale_id(self):
        self.overlay.model = display_model({"displayed_request_id": "old", "pending": [{"id": "old"}]})
        self.overlay._decision_press(None, "approve")
        self.overlay.model = display_model({"displayed_request_id": "new", "pending": [{"id": "new"}]})
        self.overlay._decision_release("approve")
        self.hub.action.assert_called_once_with({"action": "approve", "request_id": "old", "nonce": None}, source="overlay", received_at=100.0)
        self.assertEqual(self.window.restore.call_count, 2)
        self.window.remember.assert_called_once_with()
        self.assertEqual(self.overlay.message, "allowed")

    def test_nonce_is_captured_at_press_before_refresh(self):
        self.overlay.model = display_model({"displayed_request_id": "a", "pending": [
            {"id": "a", "nonce": 0x1234abcd}]})
        self.assertEqual(self.overlay.model["request"]["label"], "LOW · #abcd")
        self.overlay._decision_press(None, "deny")
        self.overlay.model = display_model({"displayed_request_id": "b", "pending": [
            {"id": "b", "nonce": 12}]})
        self.overlay._decision_release("deny")
        self.hub.action.assert_called_once_with(
            {"action": "deny", "request_id": "a", "nonce": 0x1234abcd}, source="overlay", received_at=100.0)

    def test_withdrawn_startup_does_not_acknowledge_invisible_render(self):
        self.overlay.root = Mock()
        self.overlay.root.state.return_value = "withdrawn"
        self.hub.state.return_value = {"displayed_request_id": "a", "pending": [
            {"id": "a", "nonce": 10}]}
        with patch.object(self.overlay, "_render"):
            self.overlay._poll()
        self.hub.record_rendered.assert_not_called()
        self.overlay.root.state.return_value = "normal"
        with patch.object(self.overlay, "_render"):
            self.overlay._poll()
        self.hub.record_rendered.assert_called_once_with("a", 10, source="overlay")

    def test_render_snapshot_recorded_only_after_successful_idle_update(self):
        self.overlay.root = Mock()
        self.overlay.note = Mock()
        self.hub.state.return_value = {"displayed_request_id": "old", "pending": [
            {"id": "old", "nonce": 10}]}
        with patch.object(self.overlay, "_render"):
            self.overlay._poll()
        self.hub.record_rendered.assert_called_once_with("old", 10, source="overlay")
        self.hub.record_rendered.reset_mock()
        self.overlay.root.update_idletasks.side_effect = RuntimeError("failed render")
        self.hub.state.return_value = {}
        with patch.object(self.overlay, "_render"), self.assertLogs("agentdeck.hub.overlay"):
            self.overlay._poll()
        self.hub.record_rendered.assert_not_called()
        self.assertEqual(self.overlay.model["request"]["id"], "old")
        self.overlay.root.update_idletasks.side_effect = None
        with patch.object(self.overlay, "_render"):
            self.overlay._poll()
        self.hub.record_rendered.assert_called_once_with(None, None, source="overlay")

    def test_empty_or_locked_display_cannot_decide(self):
        self.overlay.dispatch("approve")
        self.overlay._decision_release("deny")
        self.overlay.model = display_model({"displayed_request_id": "locked", "locked": [
            {"id": "locked", "risk": "critical"}]})
        self.overlay._decision_press(None, "approve")
        self.overlay._decision_release("approve")
        self.hub.action.assert_not_called()

    def test_critical_gate_buttons_dispatch_the_displayed_request(self):
        self.overlay.model = display_model({"displayed_request_id": "gate", "pending": [
            {"id": "gate", "gate": True, "risk": "critical", "status": "pending"}]})
        for action in ("approve", "deny"):
            with self.subTest(action=action):
                self.overlay._decision_press(None, action)
                self.overlay._decision_release(action)
                self.hub.action.assert_called_with({"action": action, "request_id": "gate", "nonce": None},
                                                  source="overlay", received_at=100.0)

    def test_gate_render_shows_title_and_keeps_both_buttons_enabled(self):
        self.overlay.rows = [(Mock(), Mock(), Mock(), Mock()) for _ in range(6)]
        for name in ("detail", "risk", "summary", "note", "decisions"):
            setattr(self.overlay, name, Mock())
        self.overlay.decision_buttons = {"approve": Mock(), "deny": Mock()}
        self.overlay.model = display_model({"displayed_request_id": "gate", "pending": [
            {"id": "gate", "gate": True, "risk": "critical", "armed": True}]})
        self.overlay._render()
        self.overlay.risk.configure.assert_called_once_with(text="GATE · CRITICAL · press again",
                                                           fg=COLORS["ERR"])
        self.overlay.decision_buttons["approve"].configure.assert_called_once_with(
            bg=COLORS["RUN"], fg=BACKGROUND, cursor="hand2")
        self.overlay.decision_buttons["deny"].configure.assert_called_once_with(
            bg=theme.RAISED, fg=COLORS["ERR"], cursor="hand2")

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


class BackgroundOverlayTests(unittest.TestCase):
    def setUp(self):
        self.lock = threading.RLock()
        self.hub = Mock(lock=self.lock)
        self.hub.state.return_value = {"sessions": []}
        self.hub.monotonic.return_value = 100.
        self.overlay = Overlay(self.hub, window=Mock())
        self.overlay.root = Mock()
        self.overlay._render = Mock()
        self.overlay._start_background()
        self.addCleanup(self.overlay._stop_background)

    def test_poll_does_not_wait_for_hub_state_or_its_lock(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def slow_state():
            with self.lock:
                entered.set()
                release.wait(2)
            return {"sessions": []}

        self.hub.state.side_effect = slow_state
        self.overlay._poll()
        self.assertTrue(entered.wait(1))
        self.hub.record_rendered.reset_mock()
        before = time.monotonic()
        self.overlay._poll()
        self.assertLess(time.monotonic() - before, .2)
        self.hub.record_rendered.assert_not_called()
        self.overlay.hide()
        self.hub.hide_display.assert_not_called()
        release.set()

    def test_slow_action_keeps_captured_request_and_completes_on_tk_poll(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        caller = threading.get_ident()
        workers = []

        def slow_action(payload, **kwargs):
            workers.append(threading.get_ident())
            entered.set()
            release.wait(2)
            return {"status": "allowed"}

        self.hub.action.side_effect = slow_action
        before = time.monotonic()
        self.overlay.dispatch("approve", "old", 71, received_at=100.)
        self.assertLess(time.monotonic() - before, .2)
        self.assertTrue(entered.wait(1))
        self.overlay.model = display_model({"displayed_request_id": "new", "pending": [{"id": "new"}]})
        release.set()
        deadline = time.monotonic() + 2
        while self.overlay.message != "allowed" and time.monotonic() < deadline:
            self.overlay._poll()
            time.sleep(.01)
        self.assertEqual(self.overlay.message, "allowed")
        self.assertNotEqual(workers, [caller])
        self.hub.action.assert_called_once_with(
            {"action": "approve", "request_id": "old", "nonce": 71},
            source="overlay", received_at=100.)


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


class OverlayVisibilityAndReappearTests(unittest.TestCase):
    def setUp(self):
        self.hub = Mock()
        self.hub.action.return_value = {"status": "allowed"}
        self.window = Mock()
        self.overlay = Overlay(self.hub, window=self.window)

    def test_hide_withdraws_root_without_stopping_hub(self):
        root = self.overlay.root = Mock()
        self.overlay.hide()
        self.assertTrue(self.overlay.hidden)
        self.assertFalse(self.overlay.stopped.is_set())
        root.withdraw.assert_called_once_with()
        self.window.restore.assert_called_once_with()

    def test_hide_deactivates_only_overlay_source(self):
        self.hub.rendered_source = "overlay"
        self.overlay.root = Mock()
        self.overlay.hide()
        self.hub.hide_display.assert_called_once_with('overlay')
        self.hub.record_rendered.assert_not_called()

    def test_hidden_overlay_reappears_on_new_request(self):
        root = self.overlay.root = Mock()
        root.state.return_value = "withdrawn"
        self.overlay.hidden = True
        self.overlay._dismissed_requests = {"req-1"}
        # Same request does not unhide
        self.hub.state.return_value = {"displayed_request_id": "req-1", "pending": [{"id": "req-1"}]}
        with patch.object(self.overlay, "_render"):
            self.overlay._poll()
        self.assertTrue(self.overlay.hidden)
        root.deiconify.assert_not_called()

        # New request arrives
        self.hub.state.return_value = {"displayed_request_id": "req-2",
                                       "pending": [{"id": "req-1"}, {"id": "req-2"}]}
        with patch.object(self.overlay, "_render"):
            self.overlay._poll()
        self.assertFalse(self.overlay.hidden)
        root.deiconify.assert_called_once_with()
        self.window.show.assert_called_once_with()


class OverlayViewAndPrefsTests(unittest.TestCase):
    def setUp(self):
        self.hub = Mock()
        self.window = Mock()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "overlay.json"
        self.overlay = Overlay(self.hub, window=self.window, state_path=self.state_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_display_model_summary_and_expanded_flag(self):
        idle_model = display_model({"sessions": [{"slot": 1, "name": "app", "state": "idle"}]})
        self.assertEqual(idle_model["session_count"], 1)
        self.assertEqual(idle_model["pending_count"], 0)
        self.assertEqual(idle_model["summary_text"], "1 个会话")
        self.assertFalse(idle_model["expanded"])

        pending_model = display_model({
            "sessions": [{"slot": 1, "name": "app", "state": "wait"},
                         {"slot": 2, "name": "backend", "state": "think"}],
            "pending": [{"id": "p1", "summary": "rm -rf", "risk": "high"}],
            "displayed_request_id": "p1",
        })
        self.assertEqual(pending_model["session_count"], 2)
        self.assertEqual(pending_model["pending_count"], 1)
        self.assertEqual(pending_model["summary_text"], "1 待批")
        self.assertTrue(pending_model["expanded"])

    def test_render_collapses_body_when_not_expanded(self):
        self.overlay.body = Mock()
        self.overlay.status_label = Mock()
        self.overlay.alpha_button = Mock()
        self.overlay.rows = []
        self.overlay.model = display_model({"sessions": [{"slot": 1, "name": "app"}]})
        self.overlay._render()
        self.overlay.body.grid_remove.assert_called_once_with()
        self.overlay.status_label.configure.assert_called_with(text="1 个会话", fg=FOREGROUND)

        self.overlay.body.reset_mock()
        self.overlay.model = display_model({
            "pending": [{"id": "p1", "summary": "git push", "risk": "low"}],
            "displayed_request_id": "p1",
        })
        self.overlay.detail = Mock()
        self.overlay.risk = Mock()
        self.overlay.summary = Mock()
        self.overlay.decision_buttons = {"approve": Mock(), "deny": Mock()}
        self.overlay._render()
        self.overlay.body.grid.assert_called_once_with()
        self.overlay.status_label.configure.assert_called_with(text="1 待批", fg=COLORS["ASK"])

    def test_prefs_save_and_load_position_and_translucency(self):
        self.assertTrue(self.overlay.translucent)
        self.overlay._pos = (210, 320)
        self.overlay._save_prefs()
        self.assertTrue(self.state_path.exists())
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(data, {"translucent": True, "x": 210, "y": 320})

        another = Overlay(self.hub, state_path=self.state_path)
        another._load_prefs()
        self.assertEqual(another._pos, (210, 320))
        self.assertTrue(another.translucent)

    def test_toggle_translucent_flips_alpha_and_saves_state(self):
        self.overlay.root = Mock()
        self.overlay.alpha_button = Mock()
        self.overlay.toggle_translucent()
        self.assertFalse(self.overlay.translucent)
        self.overlay.root.attributes.assert_called_with("-alpha", 1.0)
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertFalse(saved["translucent"])

        self.overlay.toggle_translucent()
        self.assertTrue(self.overlay.translucent)
        self.overlay.root.attributes.assert_called_with("-alpha", 0.85)
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertTrue(saved["translucent"])

    def test_drag_motion_updates_position_and_saves_on_release(self):
        self.overlay.root = Mock()
        self.overlay.root.winfo_x.return_value = 100
        self.overlay.root.winfo_y.return_value = 200
        self.overlay._height = 40
        press = Mock(x_root=120, y_root=210)
        self.overlay._start_drag(press)
        self.assertEqual(self.overlay._drag, (20, 10))

        move = Mock(x_root=160, y_root=270)
        self.overlay._move(move)
        self.overlay.root.geometry.assert_called_with("+140+260")
        self.assertEqual(self.overlay._pos, (140, 260))
        self.assertEqual(self.overlay._anchor_bottom, 300)

        self.overlay._end_drag()
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["x"], 140)
        self.assertEqual(saved["y"], 260)


class KeyBindingsAndNextWaitTests(unittest.TestCase):
    def test_hub_keys_bindings_contain_all_idle_keys(self):
        keys_path = Path(__file__).resolve().parent / "hub_keys.json"
        data = json.loads(keys_path.read_text(encoding="utf-8"))
        bindings = data["bindings"]

        # 6 idle keys from brief
        self.assertEqual(bindings.get("hid:0x10"), "prompt continue")
        self.assertEqual(bindings.get("ctrl+hid:0x17"), "prompt tests")
        self.assertEqual(bindings.get("ctrl+hid:0x07"), "prompt summary")
        self.assertEqual(bindings.get("hid:0x18"), "prompt commit")
        self.assertEqual(bindings.get("hid:0x1B"), "cycle +1")
        self.assertEqual(bindings.get("hid:0x2B"), "next_wait")

        # Ctrl+C and Ctrl+V left empty
        self.assertNotIn("ctrl+hid:0x06", bindings)
        self.assertNotIn("ctrl+hid:0x19", bindings)

        # Old bindings preserved
        self.assertEqual(bindings.get("hid:0x14"), "prompt tests")
        self.assertEqual(bindings.get("hid:0x19"), "prompt summary")
        self.assertEqual(bindings.get("ctrl+hid:0x27"), "prompt continue")

    def test_next_wait_action_cycles_waiting_sessions_and_reports_no_wait(self):
        import hub
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = hub.Hub(home=temp_dir, lcd_enabled=False, desktop_enabled=False)
            try:
                engine.sessions = {
                    ("cc", "s1"): {"agent": "cc", "session_id": "s1", "slot": 1, "state": "think", "name": "s1", "key": "cc-s1"},
                    ("cc", "s2"): {"agent": "cc", "session_id": "s2", "slot": 2, "state": "wait", "name": "s2", "key": "cc-s2"},
                    ("cc", "s3"): {"agent": "cc", "session_id": "s3", "slot": 3, "state": "wait", "name": "s3", "key": "cc-s3"},
                }
                for session in engine.sessions.values():
                    session["last_updated"] = engine.wall_time()
                engine.selected = ("cc", "s1")

                res1 = engine.action({"action": "next_wait"})
                self.assertEqual(res1["status"], "selected")
                self.assertEqual(res1["slot"], 2)
                self.assertEqual(engine.selected, ("cc", "s2"))

                res2 = engine.action({"action": "next_wait"})
                self.assertEqual(res2["status"], "selected")
                self.assertEqual(res2["slot"], 3)
                self.assertEqual(engine.selected, ("cc", "s3"))

                res3 = engine.action({"action": "next_wait"})
                self.assertEqual(res3["status"], "selected")
                self.assertEqual(res3["slot"], 2)
                self.assertEqual(engine.selected, ("cc", "s2"))

                engine.sessions[("cc", "s2")]["state"] = "think"
                engine.sessions[("cc", "s3")]["state"] = "done"
                res4 = engine.action({"action": "next_wait"})
                self.assertEqual(res4["status"], "no_waiting_session")
                self.assertIsNone(res4["slot"])
            finally:
                engine.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
