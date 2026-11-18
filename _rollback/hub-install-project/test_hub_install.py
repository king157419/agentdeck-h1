"""Offline installer checks; all configuration writes stay in temporary homes."""
import copy
import io
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hub_install


class InstallTests(unittest.TestCase):
    def test_default_python_is_the_running_interpreter(self):
        with patch.object(hub_install.sys, "executable", "C:/active env/python.exe"):
            self.assertEqual(hub_install.split_command(hub_install.command("cc"))[0],
                             "C:/active env/python.exe")

    def test_macos_command_quotes_paths_and_options_for_a_posix_shell(self):
        executable = "/Users/test/My env's $python; literal/python3"
        script = "/Users/test/Hub's project; $HOME/pc/hub_relay.py"
        with patch.object(hub_install.sys, "platform", "darwin"), patch.object(hub_install, "SCRIPT", script):
            text = hub_install.command("cx", python=executable, port=47910,
                                       approve_timeout=85, gate=True)
            self.assertEqual(shlex.split(text), [executable, script, "--agent", "cx",
                             "--port", "47910", "--approve-timeout", "85", "--gate"])
            entry = {"type": "command", "command": text}
            self.assertTrue(hub_install.is_ours(entry))
            self.assertTrue(hub_install.is_gate(entry))
            source = {"hooks": {"PreToolUse": [{"hooks": [entry]}]}}
            self.assertEqual(hub_install.updated(source, "uninstall", "cx"), {})

    def test_windows_command_keeps_list2cmdline_quoting(self):
        executable = "C:/Python env/python.exe"
        script = "D:/Hub project/pc/hub_relay.py"
        with patch.object(hub_install.sys, "platform", "win32"), patch.object(hub_install, "SCRIPT", script):
            text = hub_install.command("cc", python=executable)
            self.assertEqual(text, subprocess.list2cmdline([executable, script, "--agent", "cc"]))
            self.assertTrue(hub_install.is_ours({"type": "command", "command": text}))

    def test_macos_cli_python_override_reaches_all_hook_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "isolated home"
            executable = "/Applications/Python env/bin/python3"
            with patch.object(hub_install.sys, "platform", "darwin"), patch("sys.stdout", io.StringIO()):
                self.assertEqual(hub_install.main(["install", "--gate", "--home", str(home),
                                                  "--python", executable]), 0)
                snapshots = {path: path.read_bytes() for path in home.rglob("*.json")}
                self.assertEqual(len(snapshots), 2)
                for raw in snapshots.values():
                    data = json.loads(raw)
                    for groups in data["hooks"].values():
                        for group in groups:
                            for entry in group["hooks"]:
                                self.assertEqual(shlex.split(entry["command"])[0], executable)
                                self.assertTrue(hub_install.is_ours(entry))
                self.assertEqual(hub_install.apply("install", home=home, gate=True,
                    python=executable, output=io.StringIO()), [])
                self.assertCountEqual(hub_install.apply("uninstall", home=home, output=io.StringIO()),
                                      snapshots)

    def test_invalid_python_override_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "missing home"
            for executable in ("", "  ", "python\0evil"):
                with self.subTest(executable=executable), self.assertRaises(ValueError):
                    hub_install.apply("install", home=home, python=executable, output=io.StringIO())
                self.assertFalse(home.exists())

    def test_gate_opt_in_separate_hooks_idempotent_and_clean_uninstall(self):
        for agent in ("cc", "cx"):
            with self.subTest(agent=agent):
                foreign = {"matcher": "Bash", "hooks": [
                    {"type": "command", "command": "python foreign.py", "timeout": 9}]}
                source = {"theme": "dark", "hooks": {"PreToolUse": [foreign]}}
                regular = hub_install.updated(source, "install", agent)
                self.assertFalse(any(hub_install.is_gate(handler)
                    for group in regular["hooks"]["PreToolUse"] for handler in group["hooks"]))
                installed = hub_install.updated(regular, "install", agent, gate=True)
                groups = installed["hooks"]["PreToolUse"]
                self.assertEqual(groups[0], foreign)
                normal = [handler for group in groups for handler in group["hooks"]
                          if hub_install.is_ours(handler) and not hub_install.is_gate(handler)]
                gates = [(group, handler) for group in groups for handler in group["hooks"]
                         if hub_install.is_gate(handler)]
                self.assertEqual(len(normal), 1)
                self.assertEqual(normal[0]["timeout"], 10)
                self.assertEqual(len(gates), 1)
                group, handler = gates[0]
                self.assertEqual(handler["timeout"], 120)
                self.assertEqual(handler["command"], hub_install.command(agent, gate=True))
                if agent == "cc":
                    self.assertEqual(group["matcher"], "Bash|Edit|Write|mcp__.*")
                else:
                    self.assertNotIn("matcher", group)
                self.assertEqual(hub_install.updated(installed, "install", agent, gate=True), installed)
                self.assertEqual(hub_install.updated(installed, "uninstall", agent), source)

    def test_reinstall_preserves_gate_and_reconciles_gate_and_telemetry_options(self):
        for agent in ("cc", "cx"):
            with self.subTest(agent=agent):
                installed = hub_install.updated({}, "install", agent, gate=True)
                updated = hub_install.updated(installed, "install", agent,
                                               port=47910, approve_timeout=85)
                own = [handler for group in updated["hooks"]["PreToolUse"]
                       for handler in group["hooks"] if hub_install.is_ours(handler)]
                self.assertEqual(len(own), 2)
                self.assertEqual(sum(hub_install.is_gate(handler) for handler in own), 1)
                for handler in own:
                    gate = hub_install.is_gate(handler)
                    self.assertEqual(handler["command"], hub_install.command(agent,
                                     port=47910, approve_timeout=85, gate=gate))
                    self.assertEqual(handler["timeout"], 120 if gate else 10)
                self.assertEqual(hub_install.updated(updated, "install", agent,
                    port=47910, approve_timeout=85, gate=True), updated)

    def test_gate_cli_dry_run_and_temp_home_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "isolated"
            with patch("sys.stdout", io.StringIO()) as output:
                self.assertEqual(hub_install.main(["install", "--gate", "--dry-run",
                                                  "--home", str(home)]), 0)
            self.assertFalse(home.exists())
            self.assertIn("--gate", output.getvalue())
            self.assertIn("Bash|Edit|Write|mcp__.*", output.getvalue())
            with patch("sys.stdout", io.StringIO()):
                self.assertEqual(hub_install.main(["install", "--gate", "--home", str(home)]), 0)
            snapshots = {path: path.read_bytes() for path in home.rglob("*.json")}
            self.assertEqual(len(snapshots), 2)
            self.assertEqual(hub_install.apply("install", home=home, gate=True, output=io.StringIO()), [])
            self.assertEqual(list(home.rglob("*.bak-agentdeck-*")), [])
            for path, raw in snapshots.items():
                self.assertEqual(path.read_bytes(), raw)
            hub_install.apply("uninstall", home=home, output=io.StringIO())
            for path in snapshots:
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {})
            self.assertEqual(hub_install.apply("uninstall", home=home, output=io.StringIO()), [])

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
