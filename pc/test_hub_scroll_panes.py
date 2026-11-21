"""Pane targeting regressions; windows, UIA and wheel delivery are all fakes."""
import unittest
from unittest.mock import Mock, patch

from hub_desktop import DesktopEffects
from hub_scroll import PaneSelection, valid_panes


CLAUDE = (11, r"C:\Apps\Claude.exe", "Claude")
WINDOW_RECT = (10, 20, 1210, 920)


class PaneSelectionTests(unittest.TestCase):
    def selector(self, panes, window=CLAUDE):
        reader = Mock(return_value={"panes": panes})
        selector = PaneSelection(reader, lambda hwnd: WINDOW_RECT)
        self.addCleanup(selector.close)
        selector._read(window)
        return selector, reader

    def test_valid_panes_keeps_chat_attached_after_sorting(self):
        panes = valid_panes([{"rect": [600, 0, 900, 800], "chat": False},
                             {"rect": [0, 0, 500, 800], "chat": True}], WINDOW_RECT)
        self.assertEqual([(pane["rect"][0], pane.get("chat")) for pane in panes],
                         [(0, True), (600, False)])

    def test_claude_prefers_left_chat_over_larger_right_pane(self):
        selector, _ = self.selector([{"rect": [600, 0, 1200, 900], "chat": False},
                                     {"rect": [0, 0, 500, 900], "chat": True}])
        snapshot = selector.snapshot(CLAUDE)
        self.assertEqual(snapshot["selected"], 0)
        self.assertIs(snapshot["panes"][0]["chat"], True)

    def test_claude_without_chat_chooses_largest_pane(self):
        selector, _ = self.selector([{"rect": [0, 0, 600, 900]},
                                     {"rect": [700, 0, 1000, 900]}])
        self.assertEqual(selector.snapshot(CLAUDE)["selected"], 0)

    def test_claude_largest_pane_can_be_rightmost(self):
        selector, _ = self.selector([{"rect": [0, 0, 200, 900]},
                                     {"rect": [300, 0, 500, 900]},
                                     {"rect": [600, 0, 1200, 900]}])
        self.assertEqual(selector.snapshot(CLAUDE)["selected"], 2)

    def test_other_program_still_defaults_to_first_pane(self):
        window = (12, "chrome.exe", "Browser")
        selector, _ = self.selector([{"rect": [0, 0, 200, 900]},
                                     {"rect": [300, 0, 1200, 900], "chat": True}], window)
        self.assertEqual(selector.snapshot(window)["selected"], 0)

    def test_manual_selection_survives_refresh_with_same_count(self):
        selector, reader = self.selector([{"rect": [0, 0, 500, 900], "chat": True},
                                          {"rect": [600, 0, 1200, 900]}])
        self.assertEqual(selector.snapshot(CLAUDE, advance=True)["selected"], 1)
        reader.return_value = {"panes": [{"rect": [0, 0, 400, 900], "chat": True},
                                          {"rect": [500, 0, 1200, 900]}]}
        selector._read(CLAUDE)
        self.assertEqual(selector.snapshot(CLAUDE)["selected"], 1)

    def test_uncached_window_keeps_same_process_manual_selection(self):
        for advance in (False, True):
            with self.subTest(advance=advance):
                panes = [{"rect": [0, 0, 500, 900], "chat": True},
                         {"rect": [600, 0, 1200, 900]}]
                selector, _ = self.selector(panes)
                self.assertEqual(selector.snapshot(CLAUDE, advance=True)["selected"], 1)
                other = (22, CLAUDE[1], "Another Claude window")
                # No refresh: examining the fallback must not start a UIA thread.
                self.assertEqual(selector.snapshot(other, advance=advance)["selected"], 0)
                selector._read(other)
                self.assertEqual(selector.snapshot(other)["selected"], 1)
                self.assertEqual(selector.snapshot(CLAUDE)["selected"], 1)

    def test_changed_count_resets_still_in_range_manual_index(self):
        selector, reader = self.selector([{"rect": [0, 0, 500, 900], "chat": True},
                                          {"rect": [600, 0, 1200, 900]}])
        self.assertEqual(selector.snapshot(CLAUDE, advance=True)["selected"], 1)
        reader.return_value = {"panes": [{"rect": [0, 0, 300, 900], "chat": True},
                                          {"rect": [400, 0, 700, 900]},
                                          {"rect": [800, 0, 1200, 900]}]}
        selector._read(CLAUDE)
        self.assertEqual(selector.snapshot(CLAUDE)["selected"], 0)

    def test_changed_count_does_not_restore_old_index_when_layout_returns(self):
        original = [{"rect": [0, 0, 500, 900], "chat": True},
                    {"rect": [600, 0, 1200, 900]}]
        selector, reader = self.selector(original)
        self.assertEqual(selector.snapshot(CLAUDE, advance=True)["selected"], 1)
        reader.return_value = {"panes": original + [{"rect": [1300, 0, 1600, 900]}]}
        selector._read(CLAUDE)
        reader.return_value = {"panes": original}
        selector._read(CLAUDE)
        self.assertEqual(selector.snapshot(CLAUDE)["selected"], 0)


class ScrollPointTests(unittest.TestCase):
    def effects(self):
        windows = Mock(return_value=CLAUDE)
        windows.rectangle.return_value = WINDOW_RECT
        effects = DesktopEffects(windows, claude_uia=Mock())
        effects._smooth_scroll = Mock()
        self.addCleanup(effects.close)
        return effects, windows

    def test_no_cached_panes_scrolls_at_window_center(self):
        effects, windows = self.effects()
        with patch("hub_scroll.threading.Thread"):
            self.assertTrue(effects.scroll(None, [], 1))
        effects._smooth_scroll.pulse.assert_called_once_with(1, CLAUDE, (610, 470))
        windows.wheel_delta.assert_not_called()
        windows.activate.assert_not_called()

    def test_empty_uia_result_still_scrolls_at_window_center(self):
        effects, windows = self.effects()
        selector = effects._panes()
        selector.reader = Mock(return_value={"panes": []})
        selector._read(CLAUDE)
        with patch("hub_scroll.threading.Thread"):
            self.assertTrue(effects.scroll(None, [], 1))
        effects._smooth_scroll.pulse.assert_called_once_with(1, CLAUDE, (610, 470))
        windows.wheel_delta.assert_not_called()
        windows.activate.assert_not_called()

    def test_cached_real_pane_keeps_right_inset_point(self):
        effects, windows = self.effects()
        selector = effects._panes()
        selector.reader = Mock(return_value={"panes": [{"rect": [100, 40, 1000, 840], "chat": True}]})
        selector._read(CLAUDE)
        with patch("hub_scroll.threading.Thread"):
            self.assertTrue(effects.scroll(None, [], -1))
        effects._smooth_scroll.pulse.assert_called_once_with(-1, CLAUDE, (984, 440))
        windows.wheel_delta.assert_not_called()
        windows.activate.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
