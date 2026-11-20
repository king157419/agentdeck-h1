"""Daily-use overlay regressions; clocks and desktop are offline substitutes."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from hub_overlay import COLORS, Overlay, display_model, plain_text


class DailyOverlayTests(unittest.TestCase):
    def setUp(self):
        self.hub = Mock()
        self.hub.state.return_value = {}
        self.overlay = Overlay(self.hub, window=Mock())
        self.overlay.root = Mock()
        self.overlay._render = Mock()
        self.now = 100.

    def poll(self, state):
        self.hub.state.return_value = state
        with patch('hub_overlay.time.time', return_value=self.now):
            self.overlay._poll()

    def test_default_hidden_and_pending_stays_until_resolved(self):
        self.assertTrue(self.overlay.hidden)
        self.poll({})
        self.overlay.root.deiconify.assert_not_called()
        pending = {'pending': [{'id': 'p'}], 'displayed_request_id': 'p'}
        self.poll(pending)
        self.assertFalse(self.overlay.hidden)
        self.now += 100
        self.poll(pending)
        self.assertFalse(self.overlay.hidden)
        self.overlay.root.deiconify.assert_called_once()
        self.poll({})
        self.assertTrue(self.overlay.hidden)

    def test_startup_never_shows_empty_panel_and_styles_pending_before_show(self):
        for pending in (False, True):
            with self.subTest(pending=pending):
                engine, native, root = Mock(), Mock(), Mock()
                engine.state.return_value = ({'pending': [{'id': 'p'}],
                                              'displayed_request_id': 'p'} if pending else {})
                root.winfo_id.return_value = 101
                root.winfo_reqheight.return_value = 200
                root.winfo_screenwidth.return_value = 1920
                root.winfo_screenheight.return_value = 1080
                root.state.return_value = 'withdrawn'
                events = []
                native.apply.side_effect = lambda hwnd: events.append('style')
                root.deiconify.side_effect = lambda: events.append('show')
                overlay = Overlay(engine, window=native)
                with patch.dict('sys.modules', {'tkinter': types.SimpleNamespace(Tk=lambda: root)}), \
                        patch.object(overlay, '_build'), patch.object(overlay, '_render'), \
                        patch.object(overlay, '_start_background'):
                    overlay.run()
                self.assertEqual(events, ['style', 'show'] if pending else ['style'])

    def test_error_done_and_feedback_expire_after_three_seconds(self):
        for kind in ('error', 'done', 'feedback'):
            with self.subTest(kind=kind):
                self.now = 100.
                self.overlay.hidden = True
                state = ({'last_input': {'at': 100., 'text': '已按键'}} if kind == 'feedback' else
                         {'sessions': [{'slot': 1, 'state': kind, 'last_updated': 100.}]})
                self.poll(state)
                self.assertFalse(self.overlay.hidden)
                self.now = 102.99
                self.poll(state)
                self.assertFalse(self.overlay.hidden)
                self.now = 103.
                self.poll(state)
                self.assertTrue(self.overlay.hidden)

    def test_cycle_feedback_uses_two_seconds_instead_of_three(self):
        state = {'last_cycle_age': 0., 'last_input': {'at': 100., 'text': '已选槽位 2',
                                                    'action': 'cycle +1'}}
        self.poll(state)
        self.assertFalse(self.overlay.hidden)
        self.now = 102.
        self.poll(dict(state, last_cycle_age=2.))
        self.assertTrue(self.overlay.hidden)

    def test_pinned_toggle_and_corner_counter(self):
        self.poll({'overlay_pinned': True})
        self.assertFalse(self.overlay.hidden)
        self.now += 30
        self.poll({'overlay_pinned': True})
        self.assertFalse(self.overlay.hidden)
        self.poll({'overlay_pinned': False})
        self.assertTrue(self.overlay.hidden)

    def test_manual_show_is_transient_and_corner_counter_is_consumed_once(self):
        with patch('hub_overlay.time.time', return_value=self.now):
            self.overlay.show()
        self.poll({})
        self.assertFalse(self.overlay.hidden)
        self.now += 3
        self.poll({})
        self.assertTrue(self.overlay.hidden)
        self.overlay.next_corner = Mock()
        self.poll({'overlay_corner_requests': 1})
        self.poll({'overlay_corner_requests': 1})
        self.overlay.next_corner.assert_called_once()

    def test_compact_feedback_preserves_geometry_and_uses_existing_header(self):
        self.overlay._render = Overlay._render.__get__(self.overlay)
        self.overlay._height = 200
        self.overlay.root.winfo_reqheight.return_value = 250
        self.overlay.status_label = Mock()
        self.overlay.feedback_label = Mock()
        for text in ('现在没有要批准的请求', '只有 agent 提问时才能用'):
            self.poll({'last_input': {'at': self.now, 'text': text, 'compact': True}})
            self.overlay.status_label.configure.assert_called_with(text=text, fg=COLORS['ASK'])
        self.overlay.root.geometry.assert_not_called()
        self.overlay.feedback_label.grid.assert_not_called()
        self.overlay.root.deiconify.assert_called_once()

    def test_four_visible_sessions_keep_selected_and_follow_frozen_order(self):
        state = {'sessions': [{'slot': n, 'last_updated': n} for n in range(1, 7)],
                 'selected_slot': 2, 'display_order': [1, 2, 3, 4, 5, 6]}
        model = display_model(state)
        self.assertEqual(model['display_order'], [1, 2, 3, 4, 5, 6])
        self.assertEqual(model['visible_order'], [1, 2, 3, 4])
        state['selected_slot'] = 6
        model = display_model(state)
        self.assertEqual(model['visible_order'], [3, 4, 5, 6])

    def test_markdown_preview_is_plain_text_with_code_content_preserved(self):
        markdown = '# 标题\n> **回复** [文档](https://example.com)\n- `命令`\n1. 项目\n```python\n# keep comment\nx = 2 ** 3\n```'
        expected = '标题\n回复 文档\n命令\n项目\n# keep comment\nx = 2 ** 3'
        self.assertEqual(plain_text(markdown), expected)
        model = display_model({'sessions': [{'slot': 1, 'last_text': markdown}], 'selected_slot': 1})
        self.assertEqual('\n'.join(model['preview']['lines']), expected)


class DailyGeometryTests(unittest.TestCase):
    def test_width_is_at_most_twenty_two_percent_of_primary_screen(self):
        overlay = Overlay(Mock())
        overlay.root = Mock()
        overlay.root.winfo_screenwidth.return_value = 1280
        overlay.root.winfo_screenheight.return_value = 720
        overlay._place(100, 100, 200)
        self.assertLessEqual(overlay.width, int(1280 * .22))
        self.assertEqual(overlay.root.geometry.call_args.args[0], '281x200+100+100')

    def test_corner_rotation_and_restart_remember_position(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay = Overlay(Mock(), home=directory)
            overlay.root = Mock()
            overlay.root.winfo_screenwidth.return_value = 1920
            overlay.root.winfo_screenheight.return_value = 1080
            overlay._height = 200
            positions = []
            for _ in range(4):
                overlay.next_corner()
                positions.append(overlay._pos)
            self.assertEqual(positions, [(1536, 24), (24, 24), (24, 856), (1536, 856)])
            prefs = json.loads((Path(directory) / '.agentdeck' / 'overlay.json').read_text())
            self.assertEqual(prefs['corner'], 0)
            another = Overlay(Mock(), home=directory)
            another._load_prefs()
            self.assertEqual((another.corner, another._pos), (0, (1536, 856)))

    def test_top_corner_restart_keeps_top_edge_when_height_changes(self):
        for corner in (1, 2):
            with self.subTest(corner=corner), tempfile.TemporaryDirectory() as directory:
                engine, root = Mock(), Mock()
                engine.state.return_value = {}
                root.winfo_screenwidth.return_value = 1920
                root.winfo_screenheight.return_value = 1080
                root.winfo_reqheight.return_value = 200
                overlay = Overlay(engine, home=directory)
                overlay.root, overlay._height = root, 200
                for _ in range(corner):
                    overlay.next_corner()
                another = Overlay(engine, home=directory)
                another._load_prefs()
                self.assertTrue(another._corner_anchored)
                another.root = root
                another._render = Mock()
                another._place(*another._pos, 200)
                root.winfo_reqheight.return_value = 350
                another._poll()
                self.assertEqual(another._pos[1], 24)
                self.assertEqual(another._height, 350)

    def test_drag_clears_persisted_corner_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Mock()
            root.winfo_screenwidth.return_value = 1920
            root.winfo_screenheight.return_value = 1080
            root.winfo_x.return_value = 100
            root.winfo_y.return_value = 100
            overlay = Overlay(Mock(), home=directory)
            overlay.root, overlay._height = root, 200
            overlay.next_corner()
            overlay._start_drag(types.SimpleNamespace(x_root=100, y_root=100))
            overlay._move(types.SimpleNamespace(x_root=200, y_root=200))
            overlay._end_drag()
            another = Overlay(Mock(), home=directory)
            another._load_prefs()
            self.assertFalse(another._corner_anchored)


if __name__ == '__main__':
    unittest.main(verbosity=2)
