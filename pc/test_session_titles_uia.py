"""Offline titles, recency, sidebar switching and Alt-release integration."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import hub
from hub_desktop import DesktopEffects
from hub_overlay import Overlay, display_model
from hub_window_switch import WindowSwitcher
from session_titles import TAIL_BYTES, event_title, session_label, transcript_title


class TitleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "transcript.jsonl"

    def write(self, records):
        self.path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records), encoding="utf-8")

    def test_latest_title_wins_without_trailing_newline(self):
        self.write([{"type": "custom-title", "customTitle": "旧标题"},
                    {"type": "user", "content": "hello"},
                    {"type": "custom-title", "customTitle": "现状与前景讨论"}])
        self.assertEqual(transcript_title(self.path), "现状与前景讨论")

    def test_no_title_missing_unreadable_and_malformed_files(self):
        self.assertEqual(transcript_title(self.path), "")
        self.assertEqual(transcript_title(self.path.parent), "")
        self.write([{"type": "user"}, {"type": "custom-title", "customTitle": None}])
        with self.path.open("ab") as stream:
            stream.write(b'\n{"type":"custom-title" invalid}\n\xff')
        self.assertEqual(transcript_title(self.path), "")
        self.assertEqual(event_title({"transcript_path": 42}), "")

    def test_searches_earlier_chunks_and_keeps_split_unicode_records(self):
        title = {"type": "custom-title", "customTitle": "中文标题"}
        self.write([title, {"type": "user", "content": "x" * (TAIL_BYTES + 20)}])
        self.assertEqual(transcript_title(self.path), "中文标题")
        record = json.dumps(title, ensure_ascii=False).encode("utf-8")
        # A complete title spans the 256 KB read boundary (including UTF-8).
        self.path.write_bytes(record + b"\n" + b"x" * (TAIL_BYTES - len(record) // 2))
        self.assertEqual(transcript_title(self.path), "中文标题")

    def test_payload_title_has_priority_without_opening_transcript(self):
        with patch("builtins.open", side_effect=AssertionError("must not read transcript")):
            self.assertEqual(event_title({"session_title": " Payload 标题 ", "transcript_path": self.path}), "Payload 标题")

    def test_label_prefers_title_and_bounds_display_text(self):
        self.assertEqual(session_label({"title": "中文\n标题", "name": "h1"}), "中文 标题")
        self.assertEqual(session_label({"name": "h1"}), "h1")
        self.assertEqual(session_label({"title": "x" * 80}, 10), "x" * 9 + "…")


class Windows:
    def __init__(self):
        self.items = [(11, "claude.exe", "Claude"), (22, "codex.exe", "Codex")]
        self.foreground = self.items[0]
        self.activated = []

    def __call__(self):
        return self.foreground

    def windows(self):
        return self.items

    def activate(self, hwnd):
        self.activated.append(hwnd)
        self.foreground = next(item for item in self.items if item[0] == hwnd)
        return True


class HubTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.clock = 1000.0
        self.windows = Windows()
        self.uia = Mock()
        self.uia.list.return_value = {"ok": True, "current_title": "old", "sessions": []}
        self.uia.invoke.return_value = {"ok": True, "matches": 1}
        self.effects = DesktopEffects(self.windows, claude_uia=self.uia,
                                      monotonic=lambda: self.clock, sleeper=lambda seconds: None)
        self.path = self.home / "sessions.json"
        self.engine = hub.Hub(home=self.home, desktop=self.effects, lcd_enabled=False,
                              monotonic=lambda: self.clock, wall_time=lambda: self.clock,
                              sessions_path=self.path, window_alive=lambda hwnd: True)
        self.addCleanup(self.engine.close)

    def event(self, sid, title=None, agent="cc", name="SessionStart", **fields):
        event = dict(hook_event_name=name, session_id=sid, cwd="D:/project/h1",
                     agentdeck_window={"hwnd": 11 if agent == "cc" else 22,
                                       "exe": "claude.exe" if agent == "cc" else "codex.exe"}, **fields)
        if title is not None:
            event["session_title"] = title
        self.engine.event(agent, event)

    def test_title_persists_across_events_restart_and_recent_ended(self):
        self.event("alpha", "现状与前景讨论")
        self.event("alpha", name="PostToolUse")
        self.engine.maintain()
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["title"], "现状与前景讨论")
        restored = hub.Hub(home=self.home, lcd_enabled=False, desktop_enabled=False,
                           sessions_path=self.path, wall_time=lambda: self.clock,
                           window_alive=lambda hwnd: True)
        self.assertEqual(restored.state()["sessions"][0]["title"], "现状与前景讨论")
        restored.close()
        self.event("alpha", name="SessionEnd")
        self.assertEqual(self.engine.state()["recent_ended"][0]["title"], "现状与前景讨论")

    def test_transcript_title_and_read_failure_do_not_drop_event(self):
        transcript = self.home / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "custom-title", "customTitle": "文件里的标题"}), encoding="utf-8")
        self.event("alpha", transcript_path=str(transcript))
        self.assertEqual(self.engine.state()["sessions"][0]["title"], "文件里的标题")
        self.event("alpha", name="PostToolUse", transcript_path=str(self.home / "missing"))
        self.assertEqual(self.engine.sessions[("cc", "alpha")]["last_event"], "PostToolUse")

    def test_cycle_and_overlay_use_recency_without_changing_slots_or_promoting_wait(self):
        self.event("older", "Old", name="Notification", notification_type="permission_prompt")
        self.clock += 1
        self.event("middle", "Middle")
        self.clock += 1
        self.event("newest", "New")
        model = display_model(self.engine.state())
        self.assertEqual(model["display_order"], [3, 2, 1])
        self.assertEqual(model["slots"][0]["name"], "Old")
        self.assertTrue(model["slots"][0]["needs_input"])
        self.uia.list.return_value = None
        self.engine.action({"action": "slot 3"})
        self.assertEqual(self.engine.action({"action": "cycle +1"})["slot"], 2)
        self.assertEqual(self.engine.action({"action": "cycle +1"})["slot"], 1)
        self.assertEqual(self.engine.action({"action": "cycle -1"})["slot"], 2)
        self.assertEqual({s["session_id"]: s["slot"] for s in self.engine.state()["sessions"]},
                         {"older": 1, "middle": 2, "newest": 3})
        overlay = Overlay(self.engine, window=Mock())
        overlay.model = model
        self.assertEqual([overlay._dot_slot(x) for x in (0, 14, 28)], [3, 2, 1])

    def test_24h_expiry_removes_candidates_and_persistence_on_load_and_maintenance(self):
        self.event("alpha", "Alpha")
        self.clock += 23 * 60 * 60
        self.assertEqual(len(self.engine.state()["sessions"]), 1)
        self.engine.maintain()
        self.clock += 60 * 60 + 1
        restored = hub.Hub(home=self.home, lcd_enabled=False, desktop_enabled=False,
                           sessions_path=self.path, wall_time=lambda: self.clock)
        self.assertEqual(restored.state()["sessions"], [])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), [])
        restored.close()
        self.engine.maintain()
        self.assertEqual(self.engine.state()["sessions"], [])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), [])

    def test_cycle_reads_current_title_asynchronously_once_per_burst_without_polling(self):
        self.event("alpha", "Alpha")
        self.clock += 1
        self.event("beta", "Beta")
        self.clock += 1
        self.event("gamma", "Gamma")
        self.uia.list.return_value["current_title"] = "Beta"
        self.assertEqual(self.engine.action({"action": "cycle +1"})["slot"], 3)
        self.engine.cycle_reader.join(timeout=1)
        self.assertFalse(self.engine.cycle_reader.is_alive())
        self.assertEqual(self.engine.state()["selected_slot"], 2)
        self.assertEqual(self.engine.action({"action": "cycle +1"})["slot"], 1)
        self.uia.list.assert_called_once_with(hwnd=11)
        self.engine.maintain()
        self.engine.state()
        self.uia.list.assert_called_once()
        self.clock += hub.CYCLE_BURST_SECONDS + 0.1
        self.assertEqual(self.engine.action({"action": "cycle -1"})["slot"], 2)
        self.engine.cycle_reader.join(timeout=1)
        self.assertEqual(self.uia.list.call_count, 2)

    def test_show_activates_invokes_and_confirms_target(self):
        self.event("alpha", "现状与前景讨论")
        self.uia.list.return_value["current_title"] = "现状与前景讨论"
        result = self.engine.action({"action": "show"})
        self.assertEqual(self.windows.activated, [11])
        self.uia.invoke.assert_called_once_with("现状与前景讨论", index=0, hwnd=11)
        self.assertTrue(result["switched"])
        self.assertEqual(hub.describe_input("show", result)[0], "已切到：现状与前景讨论")

    def test_missing_button_timeout_exception_and_failed_confirmation_keep_window_active(self):
        self.event("alpha", "Alpha")
        for invoke in (None, {"ok": True, "matches": 1}):
            with self.subTest(invoke=invoke):
                self.uia.invoke.return_value = invoke
                result = self.engine.action({"action": "show"})
                self.assertFalse(result["switched"])
                self.assertEqual(result["window"], "focused")
                self.assertEqual(hub.describe_input("show", result), ("Claude 侧栏里没找到：Alpha", False, None))
        self.uia.invoke.side_effect = OSError("bridge failed")
        with self.assertLogs("agentdeck.hub", "WARNING"):
            self.assertFalse(self.engine.action({"action": "show"})["switched"])
        self.assertEqual(self.windows.foreground[0], 11)

    def test_duplicate_title_uses_first_and_logs(self):
        self.event("alpha", "Alpha")
        self.uia.invoke.return_value["matches"] = 2
        self.uia.list.return_value["current_title"] = "Alpha"
        with self.assertLogs("agentdeck.hub", "WARNING") as logs:
            self.assertTrue(self.engine.action({"action": "show"})["switched"])
        self.assertIn("using first", " ".join(logs.output))
        self.uia.invoke.assert_called_once_with("Alpha", index=0, hwnd=11)

    def test_codex_only_activates_window_and_uia_does_not_hold_state_lock(self):
        self.event("codex", "ignored", agent="cx")
        result = self.engine.action({"action": "show"})
        self.assertEqual(result["window"], "focused")
        self.uia.invoke.assert_not_called()
        self.uia.list.assert_not_called()
        self.event("alpha", "Alpha")
        self.engine.action({"action": "slot 2"})
        def invoke(*args, **kwargs):
            self.assertFalse(self.engine.lock._is_owned())
            return None
        self.uia.invoke.side_effect = invoke
        self.engine.action({"action": "show"})

    def test_other_action_releases_alt_before_effect_and_hub_close_releases(self):
        events = []
        switcher = WindowSwitcher(self.windows, monotonic=lambda: self.clock,
                                  sender=lambda changes: events.extend(changes) or len(changes),
                                  timer_factory=lambda delay, callback: Mock())
        self.effects._window_switcher = switcher
        self.engine.action({"action": "window next"})
        self.event("alpha", "Alpha")
        self.uia.invoke.side_effect = lambda *args, **kwargs: events.append("invoke")
        self.engine.action({"action": "show"})
        self.assertLess(events.index((0x12, 2)), events.index("invoke"))
        self.engine.action({"action": "window prev"})
        self.engine.close()
        self.assertEqual(events[-1], (0x12, 2))
        self.uia.close.assert_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
