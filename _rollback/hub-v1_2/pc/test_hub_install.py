"""Offline installer checks; all configuration writes stay in temporary homes."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import hub_install


class InstallTests(unittest.TestCase):
    def test_round_trip_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = {"theme": "dark", "hooks": {"PermissionRequest": [{"matcher": "Bash",
                      "hooks": [{"type": "command", "command": "python agent_lcd.py hook cc"},
                                {"type": "command", "command": "python another.py"}]}]}}
            for folders in hub_install.TARGETS.values():
                path = home.joinpath(*folders)
                path.parent.mkdir()
                path.write_text(json.dumps(source), encoding="utf-8")
            output = io.StringIO()
            changed = hub_install.apply("install", home=home, output=output)
            self.assertEqual(len(changed), 2)
            snapshots = {path: path.read_bytes() for path in changed}
            backups = sorted(home.rglob("*.bak-agentdeck-*"))
            self.assertEqual(len(backups), 2)
            self.assertEqual(hub_install.apply("install", home=home, output=output), [])
            self.assertEqual(sorted(home.rglob("*.bak-agentdeck-*")), backups)
            for path, content in snapshots.items():
                self.assertEqual(path.read_bytes(), content)
                data = json.loads(content)
                handlers = data["hooks"]["PermissionRequest"]
                self.assertEqual(handlers[0], source["hooks"]["PermissionRequest"][0])
                self.assertEqual(handlers[-1]["hooks"][0]["timeout"], 120)
                self.assertNotIn("async", handlers[-1]["hooks"][0])
            codex = json.loads(home.joinpath(*hub_install.TARGETS["cx"]).read_text())
            self.assertNotIn("Notification", codex["hooks"])
            hub_install.apply("uninstall", home=home, output=output)
            for folders in hub_install.TARGETS.values():
                self.assertEqual(json.loads(home.joinpath(*folders).read_text()), source)

    def test_mixed_group_only_removes_own_handler(self):
        own = {"type": "command", "command": hub_install.command("cc"), "timeout": 120}
        foreign = {"type": "command", "command": "python agent_lcd.py hook cc"}
        original = {"hooks": {"PermissionRequest": [{"matcher": "Bash", "hooks": [own, foreign]}]}}
        frozen = copy.deepcopy(original)
        result = hub_install.updated(original, "uninstall", "cc")
        self.assertEqual(original, frozen)
        self.assertEqual(result, {"hooks": {"PermissionRequest": [{"matcher": "Bash",
                                                                "hooks": [foreign]}]}})

    def test_reinstall_reconciles_options_without_duplicate_or_foreign_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            foreign = {"matcher": "Bash", "hooks": [
                {"type": "command", "command": "python agent_lcd.py hook cc", "timeout": 10}]}
            source = {"theme": "dark", "hooks": {"PermissionRequest": [foreign]}}
            for folders in hub_install.TARGETS.values():
                path = home.joinpath(*folders)
                path.parent.mkdir()
                path.write_text(json.dumps(source), encoding="utf-8")
            output = io.StringIO()
            hub_install.apply("install", home=home, output=output)
            self.assertEqual(len(hub_install.apply("install", home=home, output=output,
                                                  port=47910, approve_timeout=85)), 2)
            for agent, folders in hub_install.TARGETS.items():
                data = json.loads(home.joinpath(*folders).read_text())
                self.assertEqual(data["theme"], "dark")
                self.assertEqual(data["hooks"]["PermissionRequest"][0], foreign)
                for event, groups in data["hooks"].items():
                    own = [entry for group in groups for entry in group["hooks"]
                           if hub_install.is_ours(entry)]
                    self.assertEqual(len(own), 1)
                    self.assertEqual(own[0]["command"], hub_install.command(
                        agent, port=47910, approve_timeout=85))
                    self.assertEqual(own[0]["timeout"], 120 if event == "PermissionRequest" else 10)
            backups = sorted(home.rglob("*.bak-agentdeck-*"))
            self.assertEqual(hub_install.apply("install", home=home, output=output,
                                              port=47910, approve_timeout=85), [])
            self.assertEqual(sorted(home.rglob("*.bak-agentdeck-*")), backups)

    def test_invalid_options_are_rejected_without_writes(self):
        invalid = ([{"port": value} for value in (0, -1, 65536, True, 47800.5)] +
                   [{"approve_timeout": value} for value in (0, -1, float("nan"),
                                                            float("inf"), True)])
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "missing home"
            for options in invalid:
                with self.subTest(options=options), self.assertRaises(ValueError):
                    hub_install.apply("install", home=home, output=io.StringIO(), **options)
                self.assertFalse(home.exists())

    def test_ownership_is_executed_script_not_substring(self):
        self.assertFalse(hub_install.is_ours({"type": "command",
                         "command": 'python foreign.py --note "hub_relay.py"'}))
        self.assertFalse(hub_install.is_ours({"type": "command",
                         "command": 'python "' + hub_install.SCRIPT + '.backup" --agent cc'}))
        with patch.object(hub_install, "SCRIPT", "D:/a directory/pc/hub_relay.py"):
            self.assertTrue(hub_install.is_ours({"type": "command",
                                               "command": hub_install.command("cx")}))

    def test_dry_run_never_creates_home_or_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "missing home"
            output = io.StringIO()
            hub_install.apply("install", home=home, dry_run=True, output=output)
            self.assertFalse(home.exists())
            self.assertIn("+", output.getvalue())
            self.assertIn("PermissionRequest", output.getvalue())

    def test_uninstall_noop_preserves_empty_foreign_configuration(self):
        for source in ({}, {"hooks": {}}, {"hooks": {"Stop": []}}):
            self.assertEqual(hub_install.updated(source, "uninstall", "cc"), source)

    def test_all_files_are_validated_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home.joinpath(*hub_install.TARGETS["cx"])
            path.parent.mkdir()
            path.write_text("[invalid", encoding="utf-8")
            with self.assertRaises(ValueError):
                hub_install.apply("install", home=home, output=io.StringIO())
            self.assertFalse((home / ".claude").exists())

    def test_cli_with_default_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("sys.stdout", io.StringIO()):
                self.assertEqual(hub_install.main(["install", "--dry-run", "--home", directory]), 0)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
