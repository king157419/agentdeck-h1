"""Offline installer checks; all configuration writes stay in temporary homes."""
import copy
from contextlib import chdir
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import hub_install


class InstallTests(unittest.TestCase):
    def test_default_python_is_the_running_interpreter(self):
        with patch.object(hub_install.sys, "platform", "darwin"), \
                patch.object(hub_install.sys, "executable", "C:/active env/python.exe"):
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


class ProjectInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "isolated home"
        self.project = self.root / "project with spaces"
        self.targets = {"cc": (".claude", "settings.local.json"),
                        "cx": (".codex", "hooks.json")}
        for name, raw in {
            ".claude/settings.json": b'\xef\xbb\xbf{"theme": "keep"}\r\n',
            ".claude/settings.local.json": b'{"local": true}\n',
            ".codex/hooks.json": b'{deliberately invalid global JSON\r\n',
            ".codex/config.toml": b'# untouched trust state\r\n',
        }.items():
            path = self.home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.home_before = self.snapshot(self.home)
        environment = patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        environment.start()
        self.addCleanup(environment.stop)
        home = patch.object(Path, "home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)

    def tearDown(self):
        # Include backups and newly created files, not just the original JSON files.
        self.assertEqual(self.snapshot(self.home), self.home_before)

    @staticmethod
    def snapshot(directory):
        return {str(path.relative_to(directory)): path.read_bytes()
                for path in directory.rglob("*") if path.is_file()}

    def test_project_cli_preserves_foreign_hooks_and_is_idempotent(self):
        foreign = {"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python foreign.py --note hub_relay.py", "timeout": 7}]}
        source = {"theme": "dark", "hooks": {"PreToolUse": [foreign],
                  "PermissionRequest": [foreign], "ForeignEvent": [foreign]}}
        shared = self.project / ".claude" / "settings.json"
        shared.parent.mkdir(parents=True)
        shared.write_bytes(b'{untouched shared settings\r\n')
        shared_before = shared.read_bytes()
        (self.project / ".git").mkdir()
        for folders in self.targets.values():
            path = self.project.joinpath(*folders)
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(source), encoding="utf-8")
        arguments = ["install", "--project", str(self.project), "--home", str(self.home), "--gate"]
        with patch("sys.stdout", io.StringIO()):
            self.assertEqual(hub_install.main(arguments), 0)
        installed = self.snapshot(self.project)
        self.assertEqual(len(list(self.project.rglob("*.bak-agentdeck-*"))), 2)
        with patch("sys.stdout", io.StringIO()):
            self.assertEqual(hub_install.main(arguments), 0)
        self.assertEqual(self.snapshot(self.project), installed)
        for agent, folders in self.targets.items():
            data = json.loads(self.project.joinpath(*folders).read_text(encoding="utf-8"))
            self.assertEqual(data["theme"], "dark")
            self.assertEqual(data["hooks"]["ForeignEvent"], [foreign])
            for event in ("PreToolUse", "PermissionRequest"):
                self.assertEqual(data["hooks"][event][0], foreign)
            for groups in data["hooks"].values():
                own = [entry for group in groups for entry in group["hooks"] if hub_install.is_ours(entry)]
                if own:
                    self.assertEqual(len(own), 2 if groups is data["hooks"]["PreToolUse"] else 1)
                for entry in own:
                    parts = hub_install.split_command(entry["command"])
                    self.assertEqual(Path(parts[0]), Path(sys.executable).resolve())
                    self.assertEqual(Path(parts[1]), Path(hub_install.__file__).with_name("hub_relay.py").resolve())
                    self.assertTrue(all(Path(part).is_absolute() for part in parts[:2]))
            gates = [group for group in data["hooks"]["PreToolUse"]
                     if any(hub_install.is_gate(entry) for entry in group["hooks"])]
            self.assertEqual(len(gates), 1)
            self.assertEqual(gates[0]["matcher"], "Bash|Edit|Write|mcp__.*" if agent == "cc"
                             else "Bash|apply_patch|Edit|Write|mcp__.*")
        with patch("sys.stdout", io.StringIO()):
            self.assertEqual(hub_install.main(["uninstall", "--project", str(self.project)]), 0)
        for folders in self.targets.values():
            self.assertEqual(json.loads(self.project.joinpath(*folders).read_text(encoding="utf-8")), source)
        self.assertEqual(shared.read_bytes(), shared_before)
        self.assertEqual(hub_install.apply("uninstall", project=self.project, output=io.StringIO()), [])

    def test_project_cli_agent_selection_and_codex_alias(self):
        for names, expected in ((["cc"], "cc"), (["cx"], "cx"), (["codex"], "cx"),
                                (["cx", "codex"], "cx")):
            with self.subTest(names=names):
                project = self.project / "-".join(names)
                arguments = [*names, "--project", str(project)]
                with patch("sys.stdout", io.StringIO()):
                    self.assertEqual(hub_install.main(["install", *arguments, "--gate"]), 0)
                expected_path = project.joinpath(*self.targets[expected])
                self.assertEqual([path for path in project.rglob("*") if path.is_file()], [expected_path])
                with patch("sys.stdout", io.StringIO()):
                    self.assertEqual(hub_install.main(["uninstall", *arguments]), 0)
                self.assertEqual(json.loads(expected_path.read_text()), {})

    def test_project_resolves_relative_directory_and_python_override(self):
        executable = "python env/python.exe"
        with chdir(self.root), patch("sys.stdout", io.StringIO()):
            self.assertEqual(hub_install.main(["install", "--project", self.project.name,
                                              "--python", executable, "--gate"]), 0)
        for folders in self.targets.values():
            data = json.loads(self.project.joinpath(*folders).read_text(encoding="utf-8"))
            for groups in data["hooks"].values():
                for group in groups:
                    for entry in group["hooks"]:
                        parts = hub_install.split_command(entry["command"])
                        self.assertEqual(Path(parts[0]), (self.root / executable).resolve())
                        self.assertEqual(Path(parts[1]), Path(hub_install.SCRIPT))
                        self.assertTrue(all(Path(part).is_absolute() for part in parts[:2]))

    def test_project_default_uses_current_interpreter_on_windows(self):
        executable = self.root / "different python env" / "python.exe"
        with patch.object(hub_install.sys, "platform", "win32"), \
                patch.object(hub_install.sys, "executable", str(executable)):
            hub_install.apply("install", project=self.project, gate=True, output=io.StringIO())
        for folders in self.targets.values():
            data = json.loads(self.project.joinpath(*folders).read_text(encoding="utf-8"))
            for groups in data["hooks"].values():
                for group in groups:
                    for entry in group["hooks"]:
                        self.assertEqual(hub_install.split_command(entry["command"])[0],
                                         executable.resolve().as_posix())

    def test_project_invalid_python_is_rejected_before_writing(self):
        for executable in ("", "  ", "python\0evil"):
            with self.subTest(executable=executable), self.assertRaises(ValueError):
                hub_install.apply("install", project=self.project, python=executable, output=io.StringIO())
            self.assertFalse(self.project.exists())

    def test_project_dry_run_prints_only_diff_and_never_writes(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(hub_install.main(["install", "--project", str(self.project),
                                              "--gate", "--dry-run"]), 0)
        self.assertFalse(self.project.exists())
        for folders in self.targets.values():
            self.assertIn(str(self.project.joinpath(*folders)), output.getvalue())
        self.assertIn("Bash|apply_patch|Edit|Write|mcp__.*", output.getvalue())
        self.assertIn("--- ", output.getvalue())
        for message in ("Warning:", "Next steps:", "Rollback:"):
            self.assertNotIn(message, output.getvalue())
        hub_install.apply("install", project=self.project, gate=True, output=io.StringIO())
        before = self.snapshot(self.project)
        output = io.StringIO()
        self.assertEqual(hub_install.apply("install", project=self.project, gate=True,
                                          dry_run=True, output=output), [])
        self.assertEqual(output.getvalue(), "")
        with patch("sys.stdout", output):
            self.assertEqual(hub_install.main(["uninstall", "--project", str(self.project), "--dry-run"]), 0)
        self.assertIn("--- ", output.getvalue())
        self.assertNotIn("Rollback:", output.getvalue())
        self.assertEqual(self.snapshot(self.project), before)

    def test_project_malformed_json_and_schema_abort_before_any_write(self):
        for action in ("install", "uninstall"):
            for agent, folders in self.targets.items():
                for index, raw in enumerate((b"", b"{broken", b"[]", b'{"hooks": []}',
                                             b'{"hooks": {"Stop": {}}}', b"\xff")):
                    with self.subTest(action=action, agent=agent, raw=raw):
                        project = self.project / (action + agent + str(index))
                        path = project.joinpath(*folders)
                        path.parent.mkdir(parents=True)
                        path.write_bytes(raw)
                        before = self.snapshot(project)
                        with patch("sys.stderr", io.StringIO()) as errors, patch("sys.stdout", io.StringIO()):
                            self.assertEqual(hub_install.main([action, "--project", str(project)]), 1)
                        self.assertIn("AgentDeck hooks:", errors.getvalue())
                        self.assertEqual(self.snapshot(project), before)

    def test_project_atomic_replace_uses_same_directory_and_exact_backup(self):
        path = self.project.joinpath(*self.targets["cx"])
        path.parent.mkdir(parents=True)
        original = b'\xef\xbb\xbf{"theme": "keep"}\r\n'
        path.write_bytes(original)
        replace = os.replace

        def checked_replace(temporary, target):
            self.assertEqual(Path(temporary).parent, path.parent)
            self.assertEqual(Path(target), path)
            self.assertEqual(path.read_bytes(), original)
            self.assertTrue(str(temporary).endswith(".tmp"))
            json.loads(Path(temporary).read_text(encoding="utf-8"))
            replace(temporary, target)

        with patch.object(hub_install.os, "replace", side_effect=checked_replace) as atomic:
            self.assertEqual(hub_install.apply("install", project=self.project, agents=("codex",),
                                              output=io.StringIO()), [path])
        self.assertEqual(atomic.call_count, 1)
        backups = list(self.project.rglob("*.bak-agentdeck-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertEqual(list(self.project.rglob("*.tmp")), [])

    def test_project_failed_replace_preserves_original_and_cleans_temporary(self):
        path = self.project.joinpath(*self.targets["cc"])
        path.parent.mkdir(parents=True)
        original = b'{"theme": "keep"}\r\n'
        path.write_bytes(original)
        with patch.object(hub_install.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                hub_install.apply("install", project=self.project, agents=("cc",), output=io.StringIO())
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.project.rglob("*.tmp")), [])

    def test_project_missing_git_prints_trust_guidance_and_executable_rollback(self):
        output = io.StringIO()
        hub_install.apply("install", project=self.project, gate=True, output=output)
        text = output.getvalue()
        self.assertIn("has no .git", text)
        self.assertIn("Codex uses .git to find the project root", text)
        self.assertIn("git init", text)
        self.assertFalse((self.project / ".git").exists())
        self.assertIn("restart open sessions in " + str(self.project), text)
        self.assertIn("Start claude in " + str(self.project) + " and accept directory trust", text)
        self.assertIn("Start codex in " + str(self.project), text)
        self.assertIn("/hooks", text)
        self.assertIn("approve", text)
        rollback = next(line.removeprefix("Rollback: ") for line in text.splitlines()
                        if line.startswith("Rollback: "))
        parts = hub_install.split_command(rollback)
        self.assertEqual(Path(parts[0]), Path(sys.executable).resolve())
        self.assertEqual(Path(parts[1]), Path(hub_install.__file__).resolve())
        self.assertEqual(parts[2:], ["uninstall", "cc", "cx", "--project", str(self.project)])
        with patch("sys.stdout", io.StringIO()):
            self.assertEqual(hub_install.main(parts[2:]), 0)
        for folders in self.targets.values():
            self.assertEqual(json.loads(self.project.joinpath(*folders).read_text()), {})

    def test_project_git_directory_or_worktree_marker_suppresses_warning(self):
        for kind in ("directory", "file"):
            with self.subTest(kind=kind):
                project = self.project / kind
                project.mkdir(parents=True)
                marker = project / ".git"
                if kind == "directory":
                    marker.mkdir()
                else:
                    marker.write_text("gitdir: elsewhere\n", encoding="utf-8")
                output = io.StringIO()
                hub_install.apply("install", project=project, output=output)
                self.assertNotIn("Warning:", output.getvalue())

    def test_project_never_resolves_or_reads_home_even_with_home_option(self):
        read_text = Path.read_text

        def checked_read(path, *args, **kwargs):
            self.assertFalse(path.is_relative_to(self.home), "Project scope read HOME: " + str(path))
            return read_text(path, *args, **kwargs)

        with patch.object(Path, "home", side_effect=AssertionError("project resolved HOME")), \
                patch.object(Path, "read_text", checked_read):
            for home in (None, self.home):
                hub_install.apply("install", project=self.project, home=home, output=io.StringIO())
                hub_install.apply("uninstall", project=self.project, home=home, output=io.StringIO())

    def test_project_rejects_directory_links_to_home_before_reading_or_writing(self):
        for agent, folders in self.targets.items():
            for action in ("install", "uninstall"):
                for dry_run in (False, True):
                    with self.subTest(agent=agent, action=action, dry_run=dry_run):
                        project = self.project / (agent + action + str(dry_run))
                        project.mkdir(parents=True)
                        link = project / folders[0]
                        target = self.home / folders[0]
                        if sys.platform == "win32":
                            from _winapi import CreateJunction
                            CreateJunction(str(target), str(link))
                        else:
                            link.symlink_to(target, target_is_directory=True)
                        arguments = [action, "--project", str(project)]
                        if dry_run:
                            arguments.append("--dry-run")
                        with patch.object(Path, "read_text", side_effect=AssertionError("read before validation")), \
                                patch("sys.stderr", io.StringIO()) as errors, \
                                patch("sys.stdout", io.StringIO()) as output:
                            self.assertEqual(hub_install.main(arguments), 1)
                        self.assertIn("outside project directory", errors.getvalue())
                        self.assertEqual(output.getvalue(), "")
                        other = ".codex" if agent == "cc" else ".claude"
                        self.assertFalse((project / other).exists())

    def test_project_rejects_file_link_outside_project_before_reading(self):
        # Model a file symlink without requiring Windows symlink privileges.
        resolve = Path.resolve
        for agent, folders in self.targets.items():
            with self.subTest(agent=agent):
                path = self.project.joinpath(*folders)

                def redirected(candidate, *args, **kwargs):
                    if candidate == path:
                        return self.home.joinpath(*folders)
                    return resolve(candidate, *args, **kwargs)

                with patch.object(Path, "resolve", redirected), \
                        patch.object(Path, "read_text", side_effect=AssertionError("read before validation")):
                    with self.assertRaisesRegex(ValueError, "outside project directory"):
                        hub_install.apply("install", project=self.project, output=io.StringIO())
                self.assertFalse(self.project.exists())

    def test_project_repairs_existing_gate_matcher_without_changing_foreign_scope(self):
        foreign = {"type": "command", "command": "python foreign.py", "timeout": 9}
        for mixed in (False, True):
            with self.subTest(mixed=mixed):
                project = self.project / str(mixed)
                path = project.joinpath(*self.targets["cx"])
                path.parent.mkdir(parents=True)
                gate = {"type": "command", "command": hub_install.command("cx", gate=True), "timeout": 120}
                group = {"matcher": "Bash", "hooks": [foreign, gate] if mixed else [gate]}
                path.write_text(json.dumps({"hooks": {"PreToolUse": [group]}}), encoding="utf-8")
                hub_install.apply("install", project=project, agents=("cx",), output=io.StringIO())
                installed = json.loads(path.read_text(encoding="utf-8"))
                groups = installed["hooks"]["PreToolUse"]
                if mixed:
                    self.assertEqual(groups[0], {"matcher": "Bash", "hooks": [foreign]})
                gates = [group for group in groups if any(hub_install.is_gate(entry) for entry in group["hooks"])]
                self.assertEqual(len(gates), 1)
                self.assertEqual(gates[0]["matcher"], "Bash|apply_patch|Edit|Write|mcp__.*")
                before = self.snapshot(project)
                self.assertEqual(hub_install.apply("install", project=project, agents=("cx",),
                                                  output=io.StringIO()), [])
                self.assertEqual(self.snapshot(project), before)
                hub_install.apply("uninstall", project=project, agents=("cx",), output=io.StringIO())
                expected = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [foreign]}]}} if mixed else {}
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), expected)


class LegacyWindowsInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "_rollback" / "hub-pre-mac" / "hub_install.py"
        spec = importlib.util.spec_from_file_location("legacy_hub_install", path)
        cls.legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.legacy)

    def test_windows_global_hook_commands_match_pre_mac_bytes(self):
        for script in (hub_install.SCRIPT, "D:/Hub project/pc/hub_relay.py"):
            with patch.object(hub_install.sys, "platform", "win32"), \
                    patch.object(hub_install.sys, "executable", r"C:\different env\python.exe"), \
                    patch.object(hub_install, "SCRIPT", script), \
                    patch.object(self.legacy, "SCRIPT", script):
                for agent in ("cc", "cx"):
                    for options in ({}, {"gate": True}, {"port": 47910, "approve_timeout": 85},
                                    {"port": 47910, "approve_timeout": 85, "gate": True}):
                        with self.subTest(script=script, agent=agent, options=options):
                            self.assertEqual(hub_install.command(agent, **options).encode("utf-8"),
                                             self.legacy.command(agent, **options).encode("utf-8"))

    def test_windows_global_reinstall_of_pre_mac_config_never_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            snapshots = {}
            with patch.object(hub_install.sys, "platform", "win32"), \
                    patch.object(self.legacy, "SCRIPT", hub_install.SCRIPT):
                for agent, folders in hub_install.TARGETS.items():
                    path = home.joinpath(*folders)
                    path.parent.mkdir()
                    data = self.legacy.updated({"theme": "keep"}, "install", agent, gate=True)
                    raw = b"\xef\xbb\xbf" + (json.dumps(data, indent=2) + "\r\n").encode("utf-8")
                    path.write_bytes(raw)
                    snapshots[path] = raw
                output = io.StringIO()
                with patch.object(hub_install.sys, "executable", r"C:\another python\python.exe"), \
                        patch.object(hub_install.os, "replace", side_effect=AssertionError("reinstall wrote config")), \
                        patch.object(hub_install.shutil, "copy2", side_effect=AssertionError("reinstall made backup")):
                    self.assertEqual(hub_install.apply("install", home=home, gate=True, output=output), [])
            self.assertEqual(output.getvalue(), "")
            self.assertEqual({path: path.read_bytes() for path in snapshots}, snapshots)
            self.assertEqual(list(home.rglob("*.bak-agentdeck-*")), [])

    def test_windows_explicit_python_override_uses_forward_slashes(self):
        executable = r"C:\Python env\python.exe"
        with patch.object(hub_install.sys, "platform", "win32"):
            self.assertEqual(hub_install.command("cc", python=executable),
                             subprocess.list2cmdline(["C:/Python env/python.exe", hub_install.SCRIPT,
                                                      "--agent", "cc"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
