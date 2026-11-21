"""Offline Claude Desktop catalog checks using synthetic temporary files."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from claude_sessions import recent_sessions


class ClaudeSessionsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, sid, *, directory="account/org", mtime=100, **fields):
        path = self.root / directory / ("local_" + sid + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"sessionId": "local_" + sid, "cliSessionId": sid,
                  "title": "Title " + sid, "cwd": "D:/project/h1", "lastActivityAt": 1000}
        record.update(fields)
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def test_filters_and_projects_only_required_fields(self):
        self.write("keep", title=" 中文会话 ", spawnedFrom="parent")
        self.write("archived", isArchived=True)
        self.write("task", scheduledTaskId="task-1")
        for sid, title in (("empty", ""), ("spaces", "   "), ("null", None)):
            self.write(sid, title=title)
        self.assertEqual(recent_sessions(root=self.root), [
            {"session_id": "local_keep", "cli_session_id": "keep", "title": "中文会话",
             "cwd": "D:/project/h1", "last_activity": 1000}])

    def test_selects_directory_with_newest_file_mtime_including_archived(self):
        self.write("old", directory="old/org", mtime=500, lastActivityAt=9000)
        self.write("current", directory="new/org", mtime=200, lastActivityAt=1000)
        self.write("newest", directory="new/org", mtime=600, isArchived=True)
        # A non-session file and a session at the wrong depth cannot pick an account.
        (self.root / "old/org/other.json").write_text("{}", encoding="utf-8")
        self.write("wrong-depth", directory="ignored", mtime=900)
        self.assertEqual([item["cli_session_id"] for item in recent_sessions(root=self.root)], ["current"])

    def test_orders_by_activity_and_defaults_to_twelve_with_custom_limit(self):
        for index in range(16):
            self.write(str(index), lastActivityAt=index * 1000)
        sessions = recent_sessions(root=self.root)
        self.assertEqual(len(sessions), 12)
        self.assertEqual([item["last_activity"] for item in sessions], list(range(15000, 3000, -1000)))
        self.assertEqual(len(recent_sessions(3, root=self.root)), 3)
        self.assertEqual(recent_sessions(0, root=self.root), [])
        self.assertEqual(recent_sessions(-1, root=self.root), [])

    def test_cache_reuses_json_and_rereads_only_changed_files(self):
        first = self.write("first")
        second = self.write("second")
        real_read = Path.read_text
        reads = []

        def read(path, *args, **kwargs):
            reads.append(path)
            return real_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", read):
            result = recent_sessions(root=self.root)
            self.assertCountEqual(reads, [first, second])
            reads.clear()
            result[0]["title"] = "caller mutation"
            self.assertNotIn("caller mutation", [item["title"] for item in recent_sessions(root=self.root)])
            self.assertEqual(reads, [])
            # Size change alone invalidates a cached file even with its mtime restored.
            self.write("first", title="A longer changed title")
            recent_sessions(root=self.root)
            self.assertEqual(reads, [first])
            reads.clear()
            # Mtime change alone also invalidates the cache.
            os.utime(second, (101, 101))
            recent_sessions(root=self.root)
            self.assertEqual(reads, [second])
            reads.clear()
            first.unlink()
            self.assertEqual([item["cli_session_id"] for item in recent_sessions(root=self.root)], ["second"])
            self.assertEqual(reads, [])

    def test_newest_account_change_does_not_reuse_old_account_records(self):
        self.write("one", directory="one/org", mtime=100)
        self.write("two", directory="two/org", mtime=200)
        self.assertEqual(recent_sessions(root=self.root)[0]["cli_session_id"], "two")
        self.write("one", directory="one/org", mtime=300)
        self.assertEqual(recent_sessions(root=self.root)[0]["cli_session_id"], "one")

    def test_default_appdata_path_and_missing_catalog(self):
        self.write("one", directory="Claude/claude-code-sessions/account/org")
        with patch.dict(os.environ, {"APPDATA": str(self.root)}):
            self.assertEqual(recent_sessions()[0]["cli_session_id"], "one")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(recent_sessions(), [])
        self.assertEqual(recent_sessions(root=self.root / "missing"), [])

    def test_malformed_json_or_io_failure_returns_empty_list_without_writes(self):
        path = self.write("one")
        path.write_text("{invalid", encoding="utf-8")
        self.assertEqual(recent_sessions(root=self.root), [])
        self.write("one")
        with patch.object(Path, "read_text", side_effect=PermissionError("read denied")):
            self.assertEqual(recent_sessions(root=self.root), [])
        with patch.object(Path, "stat", side_effect=OSError("stat denied")):
            self.assertEqual(recent_sessions(root=self.root), [])
        with patch.object(Path, "write_text", side_effect=AssertionError("must be read-only")):
            self.assertEqual(recent_sessions(root=self.root)[0]["cli_session_id"], "one")


if __name__ == "__main__":
    unittest.main(verbosity=2)
