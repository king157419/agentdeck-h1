"""V9 desktop actions use fakes exclusively: no windows, UIA or SendInput."""
import ctypes
import threading
import unittest
from unittest.mock import Mock, patch

from claude_uia import ClaudeUIA
from hub_desktop import DesktopEffects, smooth_wheel_events
from hub_scroll import PaneSelection, SmoothScroll, valid_panes
from test_claude_uia import Process


class Windows:
    def __init__(self):
        self.current = (11, "claude.exe", "Claude")
        self.items = [self.current, (12, "Codex.exe", "Codex"), (13, "chrome.exe", "Browser")]
        self.actions = []

    def __call__(self):
        return self.current

    def windows(self):
        return self.items

    def is_terminal(self, hwnd):
        return False

    def activate(self, hwnd):
        self.actions.append(("activate", hwnd))
        self.current = next(item for item in self.items if item[0] == hwnd)
        return True

    def send_key(self, key, expected):
        assert expected[0] == self.current[0]
        self.actions.append(("key", key))
        return True

    def send_combo(self, keys, expected):
        assert expected[0] == self.current[0]
        self.actions.append(("combo", keys))
        return True

    def rectangle(self, hwnd):
        return (0, 0, 1200, 900)

    def wheel_delta(self, expected, point, delta):
        self.actions.append(("wheel", point, delta))
        return True


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.clock = 10.0
        self.windows, self.uia = Windows(), Mock()
        self.uia.prompt_text.return_value = ""
        self.uia.focus_prompt.return_value = {"ok": True}
        self.uia.click.return_value = {"ok": True}
        self.uia.focused_editable.return_value = False
        self.uia.panes.return_value = None
        self.clipboard = []
        self.effects = DesktopEffects(self.windows, claude_uia=self.uia, clipboard=self.clipboard.append,
                                      monotonic=lambda: self.clock, sleeper=lambda seconds: None)
        self.addCleanup(self.effects.close)

    def test_send_empty_does_not_focus_or_inject(self):
        self.assertEqual(self.effects.send(None, []), {"noop": "输入框是空的"})
        self.uia.focus_prompt.assert_not_called()
        self.assertEqual(self.windows.actions, [])

    def test_send_nonempty_focuses_prompt_then_enter(self):
        self.uia.prompt_text.return_value = "你好"
        self.assertTrue(self.effects.send(None, []))
        self.uia.focus_prompt.assert_called_once_with(hwnd=11)
        self.assertEqual(self.windows.actions, [("key", 0x0D)])

    def test_send_other_layer_is_plain_enter(self):
        self.effects.send(None, [], layer="browser")
        self.uia.prompt_text.assert_not_called()
        self.assertEqual(self.windows.actions, [("key", 0x0D)])

    def test_send_probes_named_button_and_never_duplicates_with_enter(self):
        self.uia.prompt_text.return_value = "你好"
        self.uia.list.return_value = {"buttons": ["Stop", "Send message"]}
        self.effects.send(None, [])
        self.uia.click.assert_called_once_with("Send message", hwnd=11)
        self.assertEqual(self.windows.actions, [])

    def test_send_failed_named_button_does_not_fall_back_to_enter(self):
        self.uia.prompt_text.return_value = "你好"
        self.uia.list.return_value = {"buttons": ["Send"]}
        self.uia.click.return_value = None
        with self.assertRaisesRegex(RuntimeError, "发送按钮操作失败"):
            self.effects.send(None, [])
        self.assertEqual(self.windows.actions, [])

    def test_interrupt_missing_stop_is_noop_other_layer_is_escape(self):
        self.uia.click.return_value = None
        self.assertEqual(self.effects.interrupt(None, [], layer="agent"), {"noop": "没有在跑的任务"})
        self.assertEqual(self.windows.actions, [])
        self.effects.interrupt(None, [], layer="default")
        self.assertEqual(self.windows.actions, [("key", 0x1B)])

    def test_interrupt_stop_invokes_exact_name(self):
        self.assertTrue(self.effects.interrupt(None, [], layer="agent"))
        self.uia.click.assert_called_once_with("Stop", hwnd=11)
        self.assertEqual(self.windows.actions, [])

    def test_clear_requires_editable_focus(self):
        self.assertEqual(self.effects.clear(None, []), {"noop": "这里不是输入框"})
        self.assertEqual(self.windows.actions, [])
        self.uia.focused_editable.return_value = True
        self.effects.clear(None, [])
        self.assertEqual(self.windows.actions, [("combo", (0x11, 0x41)), ("key", 0x2E)])

    def test_template_protects_existing_text_and_pending_permission(self):
        self.assertEqual(self.effects.prompt({"_permission_pending": True}, [], "继续"), {"noop": "会话正在等批准"})
        self.uia.prompt_text.assert_not_called()
        self.uia.prompt_text.return_value = "draft"
        self.assertEqual(self.effects.prompt(None, [], "继续"), {"noop": "输入框里已有内容"})
        self.assertEqual(self.windows.actions, [])
        self.assertEqual(self.clipboard, [])

    def test_template_empty_prompt_pastes_unicode_and_sends(self):
        self.assertTrue(self.effects.prompt(None, [], "继续"))
        self.assertEqual(self.clipboard, ["继续"])
        self.assertEqual(self.windows.actions, [("combo", (0x11, 0x56)), ("key", 0x0D)])

    def test_lost_foreground_after_prompt_read_blocks_input(self):
        def read(**kwargs):
            self.windows.current = self.windows.items[-1]
            return "text"
        self.uia.prompt_text.side_effect = read
        with self.assertRaises(RuntimeError):
            self.effects.send(None, [])
        self.uia.focus_prompt.assert_not_called()
        self.assertEqual(self.windows.actions, [])

    def test_copy_and_paste_target_foreground_without_activation(self):
        self.effects.copy(None, [])
        self.effects.paste(None, [])
        self.assertEqual(self.windows.actions, [("combo", (0x11, 0x43)), ("combo", (0x11, 0x56))])

    def test_context_bindings_and_deferred_chat_actions(self):
        self.assertEqual(self.effects.context(None, [], "chat", 1), {"noop": "这一步还没做"})
        self.assertEqual(self.effects.context_list(None, [], "chat", "next"), {"noop": "这一步还没做"})
        self.assertEqual(self.windows.actions, [])
        self.effects.context(None, [], "browser", 1)
        self.effects.context(None, [], "video", 4)
        self.effects.context_list(None, [], "browser", "prev")
        self.assertEqual(self.windows.actions, [("combo", (0x12, 0x25)), ("key", 0x46), ("combo", (0x11, 0x21))])

    def test_context_press_uses_guarded_enter_and_video_space(self):
        for layer, exe, key in (("agent", "claude.exe", 0x0D), ("agent", "Codex.exe", 0x0D),
                                ("chat", "WeChat.exe", 0x0D), ("chat", "Feishu.exe", 0x0D),
                                ("browser", "chrome.exe", 0x0D), ("default", "notepad.exe", 0x0D),
                                ("video", "msedge.exe", 0x20)):
            with self.subTest(layer=layer, exe=exe):
                self.windows.actions.clear()
                self.windows.current = (11, exe, "Foreground")
                self.assertTrue(self.effects.context_list(None, [], layer, "enter"))
                self.assertEqual(self.windows.actions, [("key", key)])
        self.uia.prompt_text.assert_not_called()
        self.uia.click.assert_not_called()

    def test_context_enter_blocks_when_foreground_changes_before_input(self):
        for layer in ("agent", "chat"):
            with self.subTest(layer=layer):
                with patch.object(self.effects, "foreground", return_value=(999, "claude.exe", "Old")):
                    with self.assertRaisesRegex(RuntimeError, "foreground changed"):
                        self.effects.context_list(None, [], layer, "enter")
                self.assertEqual(self.windows.actions, [])

    def test_chat_received_never_sends_enter(self):
        self.uia.focused_editable.return_value = True
        self.effects.context(None, [], "chat", 3)
        self.assertEqual(self.clipboard, ["收到"])
        self.assertEqual(self.windows.actions, [("combo", (0x11, 0x56))])

    def test_question_uses_named_option_and_missing_option_is_noop(self):
        session = {"needs_answer": True, "question_options": ["选择 A", "选择 B"]}
        self.effects.context(session, [], "agent", 2)
        self.uia.click.assert_called_once_with("选择 B", hwnd=11)
        self.assertIn("noop", self.effects.context(session, [], "agent", 4))
        self.assertEqual(self.windows.actions, [])

    def test_app_key_alternates_agent_desktops_and_browser_uses_recency(self):
        self.effects.app(None, [], "claude")
        self.assertEqual(self.windows.current[0], 12)
        self.effects.app(None, [], "claude")
        self.assertEqual(self.windows.current[0], 11)
        self.windows.items.append((14, "firefox.exe", "Firefox"))
        self.effects._app_recency[14] = 3
        self.effects.app(None, [], "browser")
        self.assertEqual(self.windows.current[0], 14)

    def test_missing_app_reports_error_without_input(self):
        with self.assertRaisesRegex(RuntimeError, "没找到微信窗口"):
            self.effects.app(None, [], "wechat")
        self.assertEqual(self.windows.actions, [])

    def test_scroll_uses_current_pane_and_never_activates_session(self):
        panes, smooth = Mock(), Mock()
        panes.snapshot.return_value = {"panes": [{"rect": [100, 40, 1000, 840]}], "selected": 0}
        self.effects._pane_selection, self.effects._smooth_scroll = panes, smooth
        self.effects.scroll({"hwnd": 999}, [], 1)
        smooth.pulse.assert_called_once_with(1, self.windows.current, (984, 440))
        self.assertEqual(self.windows.actions, [])

    def test_scroll_logs_direction_pane_point_and_only_first_40_title_characters(self):
        panes, smooth = Mock(), Mock()
        panes.snapshot.return_value = {"panes": [{"rect": [100, 40, 1000, 840]}], "selected": 0}
        self.effects._pane_selection, self.effects._smooth_scroll = panes, smooth
        self.windows.current = (11, r"C:\Apps\claude.exe", "T" * 40 + "PRIVATE_TITLE_SUFFIX")
        for notches in (1, -1):
            with self.subTest(notches=notches):
                with self.assertLogs("agentdeck.hub.scroll", level="INFO") as captured:
                    self.effects.scroll({"draft": "PRIVATE_INPUT_CONTENT"}, [], notches)
                self.assertEqual(len(captured.output), 1)
                line = captured.output[0]
                self.assertIn("notches=%+d" % notches, line)
                self.assertIn("exe=claude.exe", line)
                self.assertIn("title=" + repr("T" * 40), line)
                self.assertIn("rect=[100, 40, 1000, 840]", line)
                self.assertIn("point=(984, 440)", line)
                self.assertNotIn("PRIVATE", line)
                self.assertNotIn(r"C:\Apps", line)


class ScrollTests(unittest.TestCase):
    def test_panes_filter_bad_rectangles_sort_and_fallback(self):
        panes = valid_panes([{"rect": [600, 0, 900, 800]}, {"rect": [0, 0, 300, 800]},
                             {"rect": [0, 0, 0, 1]}, {"rect": [0, 0, float("nan"), 4]}], (0, 0, 100, 100))
        self.assertEqual([pane["rect"][0] for pane in panes], [0, 600])
        self.assertEqual(valid_panes([], (0, 0, 100, 100))[0]["rect"], (0, 0, 100, 100))

    def test_per_process_selection_largest_default_and_wrap(self):
        selector = PaneSelection(Mock(), lambda hwnd: (0, 0, 900, 900))
        self.addCleanup(selector.close)
        selector.cache[11] = valid_panes([{"rect": [i * 300, 0, (i + 1) * 300, 900]} for i in range(3)], ())
        window = (11, "claude.exe", "Claude")
        self.assertEqual(selector.snapshot(window)["selected"], 0)
        self.assertEqual(selector.snapshot(window, advance=True)["selected"], 1)
        self.assertEqual(selector.snapshot((11, "chrome.exe", "Chrome"))["selected"], 0)
        self.assertEqual(selector.snapshot(window)["selected"], 1)
        self.assertEqual(selector.snapshot(window, advance=True)["selected"], 2)
        self.assertEqual(selector.snapshot(window, advance=True)["selected"], 0)

    def test_async_panes_read_is_cached_for_500ms(self):
        clock = [1.0]
        ready, release = threading.Event(), threading.Event()
        calls = []
        def read(hwnd):
            calls.append(hwnd)
            ready.set()
            release.wait(1)
            return None
        selector = PaneSelection(read, lambda hwnd: (0, 0, 900, 900), monotonic=lambda: clock[0])
        self.addCleanup(selector.close)
        self.addCleanup(release.set)
        selector.snapshot((11, "claude.exe", "Claude"), refresh=True)
        self.assertTrue(ready.wait(.5))
        selector.snapshot((11, "claude.exe", "Claude"), refresh=True)
        self.assertEqual(calls, [11])

    def sequence(self, pulses):
        clock = [0.0]
        window = (1, "test.exe", "Test")
        output = []
        wheel = SmoothScroll(lambda expected, point, delta: output.append(delta) or True,
                             lambda: window, monotonic=lambda: clock[0], automatic=False)
        for tick in range(240):
            clock[0] = tick / 120
            if tick in pulses:
                wheel.pulse(1, window, (50, 50))
            wheel.tick()
        return output, wheel

    def test_momentum_small_deltas_decay_and_accelerate(self):
        slow, wheel = self.sequence({0})
        fast, _ = self.sequence({0, 3, 6})
        self.assertTrue(slow)
        self.assertTrue(all(10 <= delta <= 30 for delta in slow + fast))
        self.assertGreater(sum(fast), sum(slow) * 3)
        self.assertLess(abs(wheel.velocity), .001)
        self.assertLess(abs(wheel.remainder), 10)

    def test_foreground_change_cancels_inertia(self):
        clock, hwnd, output = [0.0], [1], []
        wheel = SmoothScroll(lambda *args: output.append(args) or True, lambda: (hwnd[0], "", ""),
                             monotonic=lambda: clock[0], automatic=False)
        wheel.pulse(1, (1, "", ""), (0, 0))
        hwnd[0], clock[0] = 2, .02
        self.assertIsNone(wheel.tick())
        self.assertEqual(output, [])

    def test_first_pulse_after_idle_starts_a_fresh_timebase(self):
        clock, output = [0.0], []
        window = (1, "test.exe", "Test")
        wheel = SmoothScroll(lambda expected, point, delta: output.append(delta) or True,
                             lambda: window, monotonic=lambda: clock[0], automatic=False)
        wheel.pulse(1, window, (0, 0))
        clock[0] = 5.0
        wheel.pulse(1, window, (0, 0))
        self.assertIsNone(wheel.tick())
        self.assertEqual(output, [])
        clock[0] += .02
        self.assertIsNotNone(wheel.tick())

    def test_native_batch_leaves_cursor_in_pane(self):
        events = smooth_wheel_events((100, 200), 20, (0, 0, 1920, 1080))
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].mi.dwFlags, 0x0001 | 0x8000 | 0x4000)
        self.assertEqual(ctypes.c_int32(events[1].mi.mouseData).value, -20)
        self.assertEqual(events[1].mi.dwFlags, 0x0800)


class UIABridgeTests(unittest.TestCase):
    def test_new_commands_use_persistent_fake_bridge(self):
        responses = {"panes": {"panes": [{"rect": [0, 0, 100, 200]}]},
                     "prompt_text": {"text": "你好"}, "focused_editable": {"editable": True}}
        process = Process(lambda request: dict(ok=True, **responses.get(request["command"], {})))
        bridge = ClaudeUIA(popen=lambda *args, **kwargs: process)
        self.addCleanup(bridge.close)
        self.assertEqual(bridge.panes(11)["panes"][0]["rect"], [0, 0, 100, 200])
        self.assertEqual(bridge.prompt_text(11), "你好")
        self.assertTrue(bridge.focus_prompt(11))
        self.assertTrue(bridge.click("Stop", 11))
        self.assertTrue(bridge.focused_editable(11))
        self.assertEqual([request["command"] for request in process.requests],
                         ["panes", "prompt_text", "focus_prompt", "click", "focused_editable"])

    def test_malformed_panes_and_text_fail_closed(self):
        process = Process(lambda request: {"ok": True, "text": 1, "panes": [{"rect": [1, 2, 0, 0]}]})
        bridge = ClaudeUIA(popen=lambda *args, **kwargs: process)
        self.addCleanup(bridge.close)
        self.assertIsNone(bridge.panes(11))
        self.assertIsNone(bridge.prompt_text(11))


if __name__ == "__main__":
    unittest.main(verbosity=2)
