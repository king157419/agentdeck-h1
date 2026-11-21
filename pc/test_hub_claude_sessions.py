"""Offline Claude catalog/card integration, with no native UI or hardware access."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import hub
from hub_overlay import display_model


def catalog(sid, activity, cli=None, title=None):
    return {"session_id": "local_" + sid, "cli_session_id": cli or sid,
            "title": title or sid.title(), "cwd": "D:/work/" + sid,
            "last_activity": activity * 1000}


class CardTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.clock = 100.
        self.source = []
        self.reader = Mock(side_effect=lambda: deepcopy(self.source))
        self.desktop = Mock(voice_active=False, _window_switcher=None)
        self.desktop.foreground.return_value = (11, "claude.exe", "Claude")
        self.desktop.current_session_title.return_value = None
        self.desktop.show_session.return_value = {"switched": True, "claude_sidebar": True}
        self.desktop.show_claude_session.return_value = {"switched": True, "claude_sidebar": True}
        self.engine = hub.Hub(home=Path(folder.name), desktop=self.desktop, lcd_enabled=False,
                              monotonic=lambda: self.clock, wall_time=lambda: self.clock,
                              claude_sessions_reader=self.reader)
        self.addCleanup(self.engine.close)
        self.join_catalog()

    def join_catalog(self):
        self.engine.controls.catalog_reader.join(timeout=1)
        self.assertFalse(self.engine.controls.catalog_reader.is_alive())

    def refresh(self):
        self.engine.controls.refresh_sessions(force=True)
        self.join_catalog()

    def action(self, text):
        return self.engine.action({"action": "session " + text})

    def known(self, sid, slot, activity, agent="cc", state="idle", **extra):
        item = {"agent": agent, "session_id": sid, "slot": slot, "state": state,
                "last_updated": activity, "title": sid.title(), "name": sid, "cwd": "D:/work/" + sid,
                "hwnd": 11, "window_exe": "claude.exe", "key": agent + "-" + sid,
                "read": False, **extra}
        self.engine.sessions[(agent, sid)] = item
        return item

    def open_card(self):
        self.action("next")
        self.engine.controls.origin_reader.join(timeout=1)
        return self.engine.state()["session_card"]

    def test_merge_deduplicates_cli_ids_uses_hub_state_and_mixes_codex_by_activity(self):
        self.source = [catalog("new", 99), catalog("match", 95, cli="hook"),
                       catalog("duplicate", 94, cli="hook")]
        self.refresh()
        self.known("hook", 1, 90, state="tool")
        self.known("codex", 2, 97, agent="cx", state="done")
        self.known("hook-only", 3, 91, state="wait")
        card = self.open_card()
        self.assertEqual(card["order"], ["claude:local_new", 2, 1, 3])
        self.assertEqual([s["title"] for s in card["entries"]], ["New", "Codex", "Match", "Hook-Only"])
        self.assertEqual([e["word"] for e in display_model(self.engine.state())["card_entries"]],
                         ["闲", "完", "跑", "问"])
        self.engine.sessions[("cc", "hook")]["state"] = "error"
        self.assertEqual(display_model(self.engine.state())["card_entries"][2]["word"], "错")

    def test_all_status_words_and_twelve_entry_cap(self):
        self.source = [catalog(str(i), 100 - i) for i in range(20)]
        self.refresh()
        for slot, state in enumerate(("idle", "wait", "tool", "done", "error", "locked"), 1):
            self.known(str(slot - 1), slot, 50, state=state)
        card = self.open_card()
        self.assertEqual(len(card["entries"]), 12)
        self.assertEqual([e["word"] for e in display_model(self.engine.state())["card_entries"]],
                         list("闲问跑完错批闲"))
        self.engine.sessions[("cc", "0")]["native_wait"] = True
        self.assertEqual(display_model(self.engine.state())["card_entries"][0]["word"], "批")
        self.engine.sessions[("cc", "0")]["native_wait"] = False
        self.engine.pending["p"] = SimpleNamespace(session=("cc", "0"),
            public=lambda: {"id": "p", "agent": "cc", "session_id": "0"})
        # Use Controls' snapshot directly: this pending stub is intentionally only presentation data.
        state = dict(self.engine.controls.snapshot(), sessions=list(self.engine.sessions.values()),
                     pending=[self.engine.pending.pop("p").public()])
        self.assertEqual(display_model(state)["card_entries"][0]["word"], "批")

    def test_origin_can_select_catalog_only_conversation_and_visible_window_follows_it(self):
        self.source = [catalog(str(i), 100 - i) for i in range(12)]
        self.refresh()
        self.desktop.current_session_title.return_value = "9"
        card = self.open_card()
        self.assertEqual(card["selected_slot"], "claude:local_9")
        before = deepcopy(self.engine.state())
        visible = display_model(before)["card_entries"]
        self.assertEqual(len(visible), 7)
        self.assertTrue(any(e["selected"] and e["slot"] == "claude:local_9" for e in visible))
        self.assertEqual(before, self.engine.state())
        for direction in ["next"] * 4 + ["prev"] * 14:
            self.action(direction)
            entries = display_model(self.engine.state())["card_entries"]
            self.assertEqual(sum(bool(e["selected"]) for e in entries), 1)
        self.desktop.show_session.assert_not_called()
        self.desktop.show_claude_session.assert_not_called()

    def test_origin_prefers_selected_session_when_titles_match(self):
        self.source = [catalog("newer", 100, cli="new-hook", title="Same"),
                       catalog("older", 90, cli="old-hook", title="Same")]
        self.refresh()
        self.known("new-hook", 1, 95)
        self.known("old-hook", 2, 85)
        self.engine.selected = ("cc", "old-hook")
        self.desktop.current_session_title.return_value = "Same"
        card = self.open_card()
        self.assertEqual(card["order"], [1, 2])
        self.assertEqual(card["selected_slot"], 2)

    def test_origin_uses_latest_duplicate_when_selected_does_not_match(self):
        self.source = [catalog("newer", 100, title="Same"),
                       catalog("older", 90, title="Same")]
        self.refresh()
        self.known("other", 1, 110, agent="cx", title="Other")
        self.desktop.current_session_title.return_value = "Same"
        for selected in (None, ("cx", "other")):
            with self.subTest(selected=selected):
                self.engine.selected = selected
                self.engine.controls.session_card["open"] = False
                card = self.open_card()
                self.assertEqual(card["selected_slot"], "claude:local_newer")

    def test_card_press_uses_catalog_title_and_cwd_without_changing_hub_record(self):
        self.source = [catalog("external", 100, cli="X", title="New")]
        self.refresh()
        known = self.known("X", 1, 90, title="Old", cwd="D:/old")
        for title in ("Old", ""):
            with self.subTest(title=title):
                known.update(title=title, read=False)
                before = deepcopy(known)
                self.open_card()
                result = self.action("select")
                chosen, _ = self.desktop.show_session.call_args.args
                self.assertEqual((chosen["title"], chosen["cwd"]), ("New", "D:/work/external"))
                self.assertEqual(result, {"status": "sent", "message": "已打开：New"})
                self.assertEqual(known, dict(before, read=True))
                self.assertIsNot(chosen, known)
        self.desktop.show_claude_session.assert_not_called()

    def test_card_press_routes_known_and_catalog_only_and_reports_failure(self):
        self.source = [catalog("known", 100, cli="hook"), catalog("external", 99)]
        self.refresh()
        self.known("hook", 1, 90)
        self.open_card()
        with patch.object(self.engine.controls, "_show_session", return_value={"status": "sent"}) as show:
            self.action("select")
            show.assert_called_once_with(("cc", "hook"),
                                         session_override={"title": "Known", "cwd": "D:/work/known"})
        self.desktop.show_claude_session.assert_not_called()
        self.engine.controls.session_card["open"] = False
        self.open_card()
        self.action("next")
        result = self.action("select")
        self.assertEqual(result, {"status": "sent", "message": "已打开：External"})
        chosen, _ = self.desktop.show_claude_session.call_args.args
        self.assertEqual((chosen["title"], chosen["cwd"]), ("External", "D:/work/external"))
        self.assertFalse(self.engine.controls.session_card["open"])
        for failed in (False, RuntimeError("missing Claude")):
            self.open_card()
            self.action("next")
            self.desktop.show_claude_session.side_effect = failed if isinstance(failed, Exception) else None
            self.desktop.show_claude_session.return_value = {"switched": False}
            self.assertEqual(self.action("select"), {"status": "error", "message": "打开会话失败：External"})
            self.assertNotIn("opening_slot", self.engine.controls.session_card)

    def test_closed_card_select_keeps_waiting_session_behavior(self):
        self.source = [catalog("external", 100)]
        self.refresh()
        self.known("running", 1, 99, state="tool")
        self.known("waiting", 2, 98, state="wait")
        with patch.object(self.engine.controls, "_show_session", return_value={"status": "sent"}) as show:
            self.action("select")
            show.assert_called_once_with(("cc", "waiting"))
        self.desktop.show_claude_session.assert_not_called()

    def test_hidden_claude_hub_sessions_are_not_merged_into_cards(self):
        self.source = ([catalog("visible", 95), catalog("duplicate", 96, cli="scheduled")],
                       {"scheduled", "archived"})
        self.refresh()
        scheduled = self.known("scheduled", 1, 100, state="wait")
        archived = self.known("archived", 2, 99, state="locked")
        self.known("visible", 3, 94)
        self.known("hook-only", 4, 93, state="wait")
        self.known("scheduled", 5, 98, agent="cx", state="wait")
        before = deepcopy(self.engine.sessions)
        card = self.open_card()
        self.assertEqual(card["order"], [5, 3, 4])
        self.assertEqual(self.engine.sessions, before)
        self.assertIs(self.engine.sessions[("cc", "scheduled")], scheduled)
        self.assertIs(self.engine.sessions[("cc", "archived")], archived)

    def test_closed_card_skips_hidden_sessions_and_cycles_visible_waits(self):
        self.source = ([], {"scheduled", "archived"})
        self.refresh()
        self.known("scheduled", 1, 100, state="wait", native_wait=True)
        self.known("archived", 2, 99, state="error")
        self.known("visible", 3, 98, state="wait")
        self.known("scheduled", 4, 97, agent="cx", state="locked")
        self.engine.controls.wait_cursor = ("cc", "scheduled")
        with patch.object(self.engine.controls, "_show_session", return_value={"status": "sent"}) as show:
            for expected in (("cc", "visible"), ("cx", "scheduled"), ("cc", "visible")):
                self.action("select")
                self.assertEqual(show.call_args.args, (expected,))
        self.assertFalse(self.engine.controls.session_card["open"])

    def test_closed_card_with_only_hidden_waits_does_not_open_a_session(self):
        self.source = ([], {"scheduled"})
        self.refresh()
        self.known("scheduled", 1, 100, state="wait")
        with patch.object(self.engine.controls, "_show_session") as show:
            self.assertEqual(self.action("select"), {"status": "noop", "noop": "没有等你的会话"})
            show.assert_not_called()

    def test_catalog_failure_or_empty_result_restores_hub_card_and_wait_candidates(self):
        self.known("scheduled", 1, 100, state="wait")
        for result in (RuntimeError("catalog unavailable"), [], ([], set())):
            with self.subTest(result=result):
                self.source = ([], {"scheduled"})
                self.refresh()
                self.assertEqual(self.engine.controls._card_sessions(), [])
                if isinstance(result, Exception):
                    self.reader.side_effect = result
                else:
                    self.source = result
                self.refresh()
                self.assertEqual([s["slot"] for s in self.engine.controls._card_sessions()], [1])
                with patch.object(self.engine.controls, "_show_session", return_value={"status": "sent"}) as show:
                    self.action("select")
                    show.assert_called_once_with(("cc", "scheduled"))
                self.reader.side_effect = lambda: deepcopy(self.source)

    def test_strip_keeps_hub_sessions_when_card_only_contains_catalog_entries(self):
        self.source = [catalog(str(i), 100 - i) for i in range(12)]
        self.refresh()
        self.known("older", 1, 50, agent="cx", state="tool")
        self.open_card()
        for opened in (True, False):
            self.engine.controls.session_card["open"] = opened
            model = display_model(self.engine.state())
            self.assertEqual([entry["slot"] for entry in model["strip_entries"]], [1])

    def test_catalog_entry_gains_live_hook_status_and_known_open_path_without_moving(self):
        self.source = [catalog("external", 100, cli="hook")]
        self.refresh()
        self.open_card()
        self.known("hook", 1, 99, state="tool")
        card = self.engine.state()["session_card"]
        self.assertEqual(card["order"], ["claude:local_external"])
        self.assertEqual(card["entries"][0]["slot"], "claude:local_external")
        self.assertEqual(display_model(self.engine.state())["card_entries"][0]["word"], "跑")
        with patch.object(self.engine.controls, "_show_session", return_value={"status": "sent"}) as show:
            self.action("select")
            show.assert_called_once_with(("cc", "hook"),
                                         session_override={"title": "External", "cwd": "D:/work/external"})
        self.desktop.show_claude_session.assert_not_called()

        self.assertEqual(self.action("select")["status"], "sent")
        model = display_model(self.engine.state())
        self.assertTrue(model["strip_entries"][0]["selected"])
        self.assertFalse(self.engine.controls.session_card["open"])

    def test_startup_periodic_and_open_refresh_are_async_and_use_cached_frozen_entries(self):
        self.assertEqual(self.reader.call_count, 1)
        self.engine.maintain()
        self.assertEqual(self.reader.call_count, 1)
        self.clock += 10
        self.engine.maintain()
        self.join_catalog()
        self.assertEqual(self.reader.call_count, 2)
        self.source = [catalog("cached", 100)]
        self.refresh()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def slow():
            self.assertFalse(self.engine.lock._is_owned())
            entered.set()
            release.wait(2)
            return [catalog("fresh", 100)]

        self.reader.side_effect = slow
        before = time.monotonic()
        card = self.open_card()
        self.assertLess(time.monotonic() - before, .5)
        self.assertTrue(entered.wait(1))
        self.assertEqual(card["order"], ["claude:local_cached"])
        self.assertTrue(self.engine.lock.acquire(timeout=.2))
        self.engine.lock.release()
        self.action("next")
        release.set()
        self.join_catalog()
        self.assertEqual(self.engine.state()["session_card"]["order"], card["order"])
        self.engine.controls.session_card["open"] = False
        self.assertEqual(self.open_card()["order"], ["claude:local_fresh"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
