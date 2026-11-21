"""Knob cards use the active monitor and legible content without desktop I/O."""
import ctypes
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import agentdeck_theme as theme
from hub_overlay import NoActivateWindow, Overlay, display_model, paint_card, paint_strip
from test_hub_keymap_v9_overlay import Canvas, Native, sessions


class CardNative(Native):
    def __init__(self):
        super().__init__(((-1440, -120, 0, 2440), (0, 40, 2560, 1400)))
        self.primary_area = self.areas[1]
        self.foreground = 10
        self.rects = {10: (-1400, 100, -100, 1500), 20: (100, 100, 2400, 1300)}
        self.foreground_reads = 0

    def foreground_window(self):
        self.foreground_reads += 1
        return self.foreground

    def window_rect(self, hwnd):
        return self.rects.get(hwnd)

    def _is_overlay(self, hwnd):
        return hwnd == 99


class CardPlacementTests(unittest.TestCase):
    def setUp(self):
        self.native = CardNative()
        self.hub = Mock()
        self.overlay = Overlay(self.hub, window=self.native)
        self.overlay.root = Mock()
        self.overlay._strip_canvas = Canvas()
        self.overlay._v9_windows = {kind: (Mock(), Canvas(), None) for kind in ("card", "feedback")}
        self.placed = {}
        self.overlay._popup_place = lambda popup, *bounds: self.placed.update(
            {next(kind for kind, value in self.overlay._v9_windows.items() if value is popup): bounds})

    def render(self, mode="sessions", **extra):
        state = {"layer": "agent", "sessions": sessions(),
                 "session_card": {"open": mode == "sessions"},
                 "list_card": {"open": mode == "list", "items": ["one", "two"]}, **extra}
        self.overlay._v9_state, self.overlay._v9_now = state, 100
        self.overlay.model = display_model(state, 100)
        self.overlay._render_v9()

    def assert_centered(self, area):
        x, y, width, height = self.placed["card"]
        left, top, right, bottom = area
        self.assertLessEqual(abs((x + width / 2) - (left + right) / 2), .5)
        self.assertEqual(y, top + int((bottom - top) * .22))
        self.assertTrue(left <= x < x + width <= right)
        self.assertLessEqual(y + height, bottom)

    def test_sessions_and_list_center_on_foreground_monitor(self):
        for mode in ("sessions", "list"):
            for hwnd, area in ((10, self.native.areas[0]), (20, self.native.areas[1])):
                with self.subTest(mode=mode, hwnd=hwnd):
                    self.render(None)
                    self.native.foreground = hwnd
                    self.render(mode)
                    self.assert_centered(area)

    def test_window_center_selects_monitor_even_when_top_left_is_on_other_monitor(self):
        self.native.rects[10] = (-100, 100, 2300, 1200)
        self.render()
        self.assert_centered(self.native.areas[1])

    def test_foreground_failures_fall_back_to_claude_then_primary(self):
        self.native.foreground = 0
        self.hub.desktop.windows.windows.return_value = [(20, r"C:\App\Claude.exe", "Claude")]
        self.render()
        self.assert_centered(self.native.areas[1])
        self.render(None)
        self.hub.desktop.windows.windows.return_value = [(10, "claude.exe", "Claude")]
        self.render()
        self.assert_centered(self.native.areas[0])
        self.render(None)
        self.native.foreground = 30  # GetWindowRect failed
        self.hub.desktop.windows.windows.side_effect = OSError("unavailable")
        self.render()
        self.assert_centered(self.native.primary_area)

    def test_open_card_freezes_monitor_and_overlay_foreground_reuses_last_monitor(self):
        self.render()
        self.assert_centered(self.native.areas[0])
        self.native.foreground = 20
        self.render()
        self.assert_centered(self.native.areas[0])
        self.assertEqual(self.native.foreground_reads, 1)
        self.render(None)
        self.native.foreground = 99
        self.render()
        self.assert_centered(self.native.areas[0])
        self.render(None)
        self.native.foreground = 20
        self.render()
        self.assert_centered(self.native.areas[1])

    def test_approval_keeps_existing_strip_anchor(self):
        self.render("approval", displayed_request_id="a", pending=[{"id": "a", "nonce": 1}])
        strip_x, strip_y, strip_width, _ = self.native.bounds[-1]
        x, y, width, height = self.placed["card"]
        area = next(area for area in self.native.areas if area[0] <= strip_x < area[2])
        expected_x = strip_x - width - 6 if strip_x > (area[0] + area[2]) // 2 else strip_x + strip_width + 6
        self.assertEqual((width, height), (340, 116))
        self.assertEqual((x, y), (max(area[0], min(expected_x, area[2] - width)),
                                 max(area[1], min(strip_y, area[3] - height))))
        self.assertEqual(self.native.foreground_reads, 0)

    def test_reopening_between_polls_selects_new_monitor_but_rotation_keeps_it(self):
        for mode, field in (("sessions", "session_card"), ("list", "list_card")):
            with self.subTest(mode=mode):
                self.render(None)
                card = {"open": True, "generation": 1, "items": ["one", "two"]}
                self.native.foreground = 10
                self.render(mode, **{field: card})
                self.assert_centered(self.native.areas[0])
                self.native.foreground = 20
                self.render(mode, **{field: dict(card, selected=1)})
                self.assert_centered(self.native.areas[0])
                self.render(mode, **{field: dict(card, generation=2)})
                self.assert_centered(self.native.areas[1])

    def test_help_covering_open_card_does_not_change_its_monitor(self):
        self.render()
        self.native.foreground = 20
        self.render(overlay_help=True)
        self.render()
        self.assert_centered(self.native.areas[0])

    def test_list_keeps_its_monitor_while_covered_by_session_card(self):
        list_card = {"open": True, "generation": 1, "items": ["one", "two"]}
        self.render("list", list_card=list_card)
        self.assert_centered(self.native.areas[0])
        self.native.foreground = 20
        self.render("sessions", list_card=list_card)
        self.assert_centered(self.native.areas[1])
        self.render("list", list_card=list_card)
        self.assert_centered(self.native.areas[0])

    def test_open_result_feedback_uses_card_location_after_focus_changes(self):
        self.native.foreground = 20
        self.render()
        card_x, card_y, _, _ = self.placed["card"]
        for kind, text in (("success", "已打开：项目"), ("error", "打开会话失败：项目")):
            with self.subTest(kind=kind):
                self.native.foreground = 10
                self.render(None, last_input={"at": 100, "kind": kind, "text": text})
                x, y, _, _ = self.placed["feedback"]
                self.assertEqual((x, y), (card_x, card_y))


class CardContentTests(unittest.TestCase):
    def test_help_explains_plain_enter_and_list_confirmation_with_video_exception(self):
        for layer in ("agent", "chat", "browser", "default", "video"):
            with self.subTest(layer=layer):
                canvas = Canvas()
                _, height = paint_card(canvas, display_model({"layer": layer, "overlay_help": True}))
                texts = [options["text"] for kind, _, options in canvas.shapes if kind == "text"]
                key = "播放/暂停" if layer == "video" else "回车"
                self.assertIn("4 按下：" + key + "（列表开着时确认）", texts)
                self.assertIn("按住帮助转旋钮移动 · 松手保存", texts)
                self.assertGreater(height, 222)

    def model(self, entries, **extra):
        return display_model({"layer": "agent", "sessions": entries,
                              "session_card": {"open": True, "selected_slot": entries[-1]["slot"]}, **extra})

    def test_session_title_project_colors_and_hint_are_visible_without_changing_strip(self):
        entry = dict(sessions()[0], title="标题" * 20, cwd="D:\\work\\hardware\\")
        model = self.model([entry])
        self.assertEqual(model["strip_entries"][0]["title"], "标题" * 9 + "…")
        self.assertEqual(model["card_entries"][0]["title"], "标题" * 14 + "…")
        self.assertEqual(model["card_entries"][0]["project"], "hardware")
        canvas = Canvas()
        width, height = paint_card(canvas, model)
        self.assertTrue(460 <= width <= 720)
        self.assertGreater(height, 80)
        texts = [options for kind, _, options in canvas.shapes if kind == "text"]
        self.assertTrue(any(item.get("text") == "hardware" and item.get("fill") == theme.MUTED for item in texts))
        self.assertTrue(any(item.get("text") == "转动选择 · 按下打开" for item in texts))
        self.assertTrue(any(item["font"][1:] == (12, "bold") for item in texts))
        self.assertTrue(any(item["font"][1] == 14 for item in texts))
        self.assertTrue(any(kind == "rectangle" and options.get("fill") not in (None, "", theme.RAISED)
                            for kind, _, options in canvas.shapes))
        strip = Canvas()
        self.assertEqual(paint_strip(strip, model, dual=True), (340, 22))

    def test_project_basename_handles_posix_windows_missing_and_root_paths(self):
        for cwd, expected in (("/home/project/", "project"), (r"D:\work\h1", "h1"), (None, ""), ("/", "")):
            with self.subTest(cwd=cwd):
                self.assertEqual(self.model([dict(sessions()[0], cwd=cwd)])["card_entries"][0]["project"], expected)

    def test_card_width_grows_with_content_and_remains_bounded(self):
        widths = []
        for title in ("短", "标题" * 10, "标题" * 30):
            widths.append(paint_card(Canvas(), self.model([dict(sessions()[0], title=title, cwd="/work/project")]))[0])
        self.assertEqual(widths[0], 460)
        self.assertLess(widths[0], widths[-1])
        self.assertTrue(all(460 <= width <= 720 for width in widths))

    def test_session_and_list_scroll_seven_rows_with_correct_footer(self):
        entries = [dict(sessions()[0], slot=i, title="会话" + str(i)) for i in range(12)]
        model = self.model(entries, session_card={"open": True, "order": list(range(12)), "selected_slot": 10})
        self.assertEqual([entry["slot"] for entry in model["card_entries"]], list(range(4, 11)))
        self.assertTrue(model["card_entries"][-1]["selected"])
        canvas = Canvas()
        paint_card(canvas, display_model({"layer": "agent", "list_card": {
            "open": True, "title": "候选", "items": ["条目" + str(i) for i in range(12)], "selected": 10}}))
        labels = [options["text"] for kind, _, options in canvas.shapes if kind == "text"]
        self.assertEqual([text for text in labels if text.startswith("条目")], ["条目" + str(i) for i in range(4, 11)])
        self.assertIn("转动选择 · 按下确认", labels)


@unittest.skipUnless(sys.platform == "win32", "Win32 adapter contract")
class NativeCardTests(unittest.TestCase):
    def setUp(self):
        self.hwnd = 0x123456789ABC
        self.user = SimpleNamespace(GetWindowLongPtrW=Mock(return_value=0),
                                    SetWindowLongPtrW=Mock(return_value=0),
                                    GetForegroundWindow=Mock(return_value=self.hwnd),
                                    GetWindowRect=Mock(side_effect=self.rectangle))
        self.window = NoActivateWindow(self.user)

    def rectangle(self, hwnd, pointer):
        self.assertEqual(hwnd, self.hwnd)
        rect = pointer._obj
        rect.left, rect.top, rect.right, rect.bottom = (-1440, -120, 0, 2440)
        return True

    def test_foreground_and_rectangle_preserve_pointer_and_signed_coordinates(self):
        self.assertEqual(self.window.foreground_window(), self.hwnd)
        self.assertEqual(self.window.window_rect(self.hwnd), (-1440, -120, 0, 2440))
        self.user.GetWindowRect.return_value = False
        self.user.GetWindowRect.side_effect = None
        self.assertIsNone(self.window.window_rect(self.hwnd))
        self.assertIsNone(self.window.window_rect(0))

    def test_monitor_primary_flag_handles_primary_work_area_without_origin(self):
        def monitors(dc, clip, callback, data):
            callback(10, None, None, data)
            callback(20, None, None, data)
            return True

        def info(monitor, pointer):
            value = pointer._obj
            bounds = (-1440, -120, 0, 2440) if monitor == 10 else (0, 40, 2560, 1400)
            rect = value.rcWork
            rect.left, rect.top, rect.right, rect.bottom = bounds
            value.dwFlags = 1 if monitor == 20 else 0
            return True

        self.user.EnumDisplayMonitors = Mock(side_effect=monitors)
        self.user.GetMonitorInfoW = Mock(side_effect=info)
        areas = self.window.work_areas()
        self.assertEqual(areas, [(-1440, -120, 0, 2440), (0, 40, 2560, 1400)])
        self.assertEqual(self.window.primary_area, areas[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
