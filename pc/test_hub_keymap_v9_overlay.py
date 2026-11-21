"""v9 overlay regressions: recording canvases, fake clocks, no desktop windows."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from hub_overlay import (CARD_WIDTH, COLORS, FEEDBACK_HEIGHT, FEEDBACK_WIDTH,
                         NoActivateWindow, Overlay, display_model, paint_card, paint_strip)
from test_hub_overlay import NativeFunction


class Canvas:
    def __init__(self, *args, **kwargs):
        self.options = dict(kwargs)
        self.shapes = []

    def configure(self, **kwargs):
        self.options.update(kwargs)

    def delete(self, what):
        self.shapes.clear()

    def _shape(self, kind, *args, **kwargs):
        self.shapes.append((kind, args, kwargs))

    def create_rectangle(self, *args, **kwargs):
        self._shape("rectangle", *args, **kwargs)

    def create_text(self, *args, **kwargs):
        self._shape("text", *args, **kwargs)

    def create_oval(self, *args, **kwargs):
        self._shape("oval", *args, **kwargs)

    def pack(self, **kwargs):
        pass


class Native:
    def __init__(self, areas=((0, 0, 1920, 1040),)):
        self.areas = areas
        self.bounds = []

    def work_areas(self):
        return self.areas

    def place(self, *bounds):
        self.bounds.append(bounds)

    def show(self):
        pass

    def restore(self):
        pass


def sessions():
    return [{"slot": n, "agent": "cc", "session_id": str(n), "name": "项目" + str(n),
             "state": state, "last_updated": n}
            for n, state in enumerate(("idle", "think", "done", "error", "wait", "locked"), 1)]


class V9ModelTests(unittest.TestCase):
    def test_idle_is_strip_only_and_six_status_characters(self):
        state = {"layer": "agent", "sessions": sessions()}
        before = deepcopy(state)
        model = display_model(state, 100)
        self.assertIsNone(model["card_mode"])
        self.assertEqual([item["word"] for item in model["strip_entries"]], list("批问错完跑闲"))
        self.assertEqual(state, before)
        canvas = Canvas()
        self.assertEqual(paint_strip(canvas, model), (28, 132))

    def test_only_four_authorized_triggers_expand_cards(self):
        base = {"layer": "agent", "sessions": sessions()[:2]}
        for addition in ({"last_input": {"at": 100, "text": "无效", "kind": "noop"}},
                         {"show_requests": 1}, {"last_cycle_age": .1}, {}):
            self.assertIsNone(display_model(dict(base, **addition), 100)["card_mode"])
        cases = [({"overlay_help": True}, "help"),
                 ({"session_card": {"open": True}}, "sessions"),
                 ({"list_card": {"open": True}}, "list"),
                 ({"pending": [{"id": "a"}], "displayed_request_id": "a"}, "approval"),
                 ({"sessions": [{"slot": 1, "needs_answer": "AskUserQuestion"}]}, "question")]
        for addition, mode in cases:
            self.assertEqual(display_model(dict(base, **addition), 100)["card_mode"], mode)

    def test_session_card_uses_frozen_order_and_opening_row(self):
        state = {"layer": "agent", "sessions": sessions(),
                 "session_card": {"open": True, "order": [2, 5, 1, 6, 3, 4],
                                  "selected_slot": 5, "opening_slot": 5}}
        model = display_model(state, 100)
        self.assertEqual([item["slot"] for item in model["card_entries"]], [2, 5, 1, 6, 3, 4])
        canvas = Canvas()
        self.assertEqual(paint_card(canvas, model), (460, 348))
        self.assertTrue(any(shape[2].get("text") == "正在打开…" for shape in canvas.shapes))

    def test_approval_text_includes_owner_tool_first_command_line_and_sixty_character_limit(self):
        state = {"layer": "agent", "sessions": sessions(), "displayed_request_id": "b",
                 "pending": [{"id": "a"}, {"id": "b", "agent": "cc", "session_id": "1",
                                          "tool": "Bash", "summary": "npm test\nsecret next line"}]}
        approval = display_model(state, 100)["approval"]
        self.assertEqual(approval["position"], "2/2")
        self.assertIn("Bash", approval["text"])
        self.assertIn("npm test", approval["text"])
        self.assertNotIn("secret", approval["text"])
        state["pending"][1]["summary"] = "长" * 100
        self.assertEqual(len(display_model(state, 100)["approval"]["text"]), 60)

    def test_feedback_expires_in_point_nine_seconds_and_layer_notice_in_one_second(self):
        state = {"layer": "chat", "layer_changed_at": 100,
                 "last_input": {"at": 100, "text": "这里不是输入框", "kind": "noop"}}
        self.assertEqual(display_model(state, 100.89)["feedback"]["kind"], "noop")
        self.assertIsNone(display_model(state, 100.91)["feedback"])
        self.assertTrue(display_model(state, 100.99)["layer_notice"])
        self.assertFalse(display_model(state, 101.01)["layer_notice"])

    def test_help_row_two_tracks_layer_or_question(self):
        self.assertEqual(display_model({"layer": "browser"})["help_rows"][1],
                         ("后退", "地址栏", "关标签", "刷新"))
        state = {"layer": "agent", "sessions": [{"slot": 1, "needs_answer": "AskUserQuestion"}]}
        self.assertEqual(display_model(state)["help_rows"][1], ("选项 1", "选项 2", "选项 3", "选项 4"))


class V9RenderTests(unittest.TestCase):
    def setUp(self):
        self.hub = Mock()
        self.native = Native()
        self.overlay = Overlay(self.hub, window=self.native)
        self.overlay.root = Mock()
        self.overlay._v9_ready = True
        self.overlay._strip_canvas = Canvas()
        self.overlay._new_v9_window = lambda **kwargs: (Mock(), Canvas(), None)
        self.overlay._v9_windows = {kind: (Mock(), Canvas(), None) for kind in ("card", "feedback")}

    def render(self, state, now=100):
        self.hub.state.return_value = dict({"layer": "agent"}, **state)
        with patch("hub_overlay.time.time", return_value=now):
            self.overlay._poll_v9()

    def test_feedback_uses_separate_220x28_window_and_preserves_main_geometry(self):
        self.render({"sessions": sessions()})
        bounds = list(self.native.bounds)
        self.overlay.root.geometry.reset_mock()
        self.render({"sessions": sessions(), "last_input": {"at": 100, "kind": "success", "text": "已发送：继续"}})
        self.assertEqual(self.native.bounds, bounds)
        self.overlay.root.geometry.assert_not_called()
        feedback_top, feedback_canvas, _ = self.overlay._v9_windows["feedback"]
        self.assertEqual((feedback_canvas.options["width"], feedback_canvas.options["height"]), (220, 28))
        self.assertTrue(any(item[2].get("fill") == COLORS["RUN"] for item in feedback_canvas.shapes))
        self.overlay._v9_windows["card"][0].deiconify.assert_not_called()

    def test_hidden_strip_shows_new_approval_for_only_three_seconds(self):
        state = {"overlay_visible": False, "displayed_request_id": "a",
                 "pending": [{"id": "a", "nonce": 42}]}
        self.render(state)
        card = self.overlay._v9_windows["card"][0]
        card.deiconify.assert_called_once()
        self.hub.record_rendered.assert_called_with("a", 42, source="overlay")
        self.render(state, 102.99)
        self.assertEqual(card.deiconify.call_count, 2)
        self.render(state, 103.01)
        self.assertEqual(card.deiconify.call_count, 2)
        card.withdraw.assert_called_once()
        self.hub.hide_display.assert_called_with("overlay")

    def test_noop_deduplication_and_color_do_not_expand_card(self):
        def state(at):
            return {"last_input": {"at": at, "kind": "noop", "text": "这一步还没做"}}
        self.render(state(100))
        top, canvas, _ = self.overlay._v9_windows["feedback"]
        self.assertEqual(top.deiconify.call_count, 1)
        self.render(state(101), 101)
        self.assertEqual(top.deiconify.call_count, 1)
        self.render(state(103.1), 103.1)
        self.assertEqual(top.deiconify.call_count, 2)
        self.hub.action.assert_not_called()
        self.overlay._v9_windows["card"][0].deiconify.assert_not_called()

    def test_six_docks_times_each_monitor_and_save_only_at_release(self):
        self.native.areas = ((0, 0, 1920, 1040), (-1600, -100, 0, 860))
        with tempfile.TemporaryDirectory() as directory:
            self.overlay.state_path = Path(directory) / "overlay.json"
            positions = []
            for number in range(1, 13):
                self.render({"overlay_move_requests": number})
                positions.append(self.overlay._pos)
            self.assertEqual(len(set(positions)), 12)
            self.assertFalse(self.overlay.state_path.exists())
            self.render({"overlay_move_requests": 12, "overlay_save_requests": 1})
            saved = json.loads(self.overlay.state_path.read_text())
            another = Overlay(self.hub, state_path=self.overlay.state_path)
            another._load_prefs()
            self.assertEqual(another._dock, saved["dock"])

    def test_dual_screen_defaults_to_secondary_top_right_list(self):
        self.native.areas = ((0, 0, 1920, 1040), (-1600, -100, 0, 860))
        self.render({"sessions": sessions()})
        self.assertEqual(self.native.bounds[-1], (-340, -100 + 56, 340, 132))  # below the title bar

    def test_pane_frames_expire_without_touching_windows(self):
        state = {"panes": {"items": [{"rect": [20, 40, 300, 400], "name": "左"},
                                     {"rect": [300, 40, 900, 400], "name": "中"}],
                           "selected": 1, "until": 101.2}}
        self.render(state)
        self.assertEqual(len(self.overlay._v9_outlines), 2)
        selected = self.overlay._v9_outlines[1]
        self.assertTrue(any(item[2].get("width") == 3 for item in selected[1].shapes))
        self.render(state, 101.21)
        selected[0].withdraw.assert_called_once()
        self.hub.action.assert_not_called()

    def test_v9_decisions_include_four_hundred_millisecond_guard(self):
        self.overlay.dispatch("approve", "a", 4)
        self.hub.action.assert_called_with({"action": "approve", "request_id": "a", "nonce": 4,
                                           "card_guard": True}, source="overlay")


class V9NativeTests(unittest.TestCase):
    def test_transparent_style_and_hit_test(self):
        changed = []
        user = types.SimpleNamespace(**{name: NativeFunction(callback) for name, callback in {
            "GetWindowLongPtrW": lambda *args: 0,
            "SetWindowLongPtrW": lambda *args: changed.append(args) or 0,
            "GetAncestor": lambda *args: 101,
            "GetForegroundWindow": lambda: 202,
            "SetForegroundWindow": lambda *args: True,
            "IsChild": lambda *args: False,
            "CallWindowProcW": lambda *args: 0,
            "SetWindowPos": lambda *args: True,
            "ShowWindow": lambda *args: True,
        }.items()})
        window = NoActivateWindow(user, transparent=True)
        window.apply(100)
        self.assertTrue(changed[0][2] & 0x20)
        self.assertTrue(changed[0][2] & 0x08000000)
        self.assertEqual(window._message(101, 0x84, 0, 0), -1)
        window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
