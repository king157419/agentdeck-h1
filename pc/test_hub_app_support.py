"""Offline tray installer and diagnostics checks; no hardware or real user files."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hub_doctor
import hub_install
import install as legacy_install


class GlobalStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        real_home = patch.object(Path, "home", side_effect=AssertionError("real home access"))
        real_home.start()
        self.addCleanup(real_home.stop)
        self.relay = self.home / "中文 软件" / "AgentDeck-relay.exe"

    def write_hook(self, agent, *, relay=None, command_agent=None, exec_form=False):
        path = self.home.joinpath(*hub_install.TARGETS[agent])
        path.parent.mkdir(parents=True, exist_ok=True)
        target = str(self.relay if relay is None else relay)
        if exec_form:  # what the current installer writes for the bundled Claude relay
            entry = {"type": "command", "command": target, "args": ["--agent", command_agent or agent]}
        else:
            entry = {"type": "command", "command": subprocess.list2cmdline(
                [target, "--agent", command_agent or agent])}
        path.write_text(json.dumps({"theme": "keep", "hooks": {"Stop": [{"hooks": [entry]}]}}), encoding="utf-8")
        return path

    def test_empty_and_partial_global_install_are_disabled_without_writes(self):
        self.assertEqual(hub_install.global_status(home=self.home),
                         {"enabled": False, "missing_paths": [], "needs_repair": False,
                          "shell_form": False, "errors": []})
        self.assertEqual(list(self.home.iterdir()), [])
        self.write_hook("cc")
        with patch.object(hub_install.sys, "frozen", True, create=True), patch.object(
                hub_install.sys, "executable", str(self.home / "new" / "AgentDeck.exe")):
            status = hub_install.global_status(home=self.home)
        self.assertFalse(status["enabled"])
        self.assertFalse(status["needs_repair"])

    def test_both_configs_require_their_corresponding_agent(self):
        self.write_hook("cc")
        path = self.write_hook("cx", command_agent="cc")
        self.assertFalse(hub_install.global_status(home=self.home)["enabled"])
        self.write_hook("cx")
        self.assertTrue(hub_install.global_status(home=self.home)["enabled"])
        path.unlink()
        self.assertFalse(hub_install.global_status(home=self.home)["enabled"])

    def test_current_frozen_paths_with_spaces_and_chinese_are_enabled_and_read_only(self):
        self.relay.parent.mkdir()
        self.relay.write_bytes(b"placeholder")
        for agent in hub_install.TARGETS:
            self.write_hook(agent, exec_form=agent == "cc")
        before = {path: path.read_bytes() for path in self.home.rglob("*") if path.is_file()}
        with patch.object(hub_install.sys, "frozen", True, create=True), patch.object(
                hub_install.sys, "executable", str(self.relay.with_name("AgentDeck.exe"))):
            self.assertEqual(hub_install.global_status(home=self.home),
                             {"enabled": True, "missing_paths": [], "needs_repair": False,
                              "shell_form": False, "errors": []})
            # H1: the old shell-form Claude entry cannot start under Git Bash -> repair.
            self.write_hook("cc")
            status = hub_install.global_status(home=self.home)
            self.assertEqual((status["needs_repair"], status["shell_form"]), (True, True))
            self.write_hook("cc", exec_form=True)
        self.assertEqual(before, {path: path.read_bytes() for path in self.home.rglob("*") if path.is_file()})

    def test_missing_relay_keeps_enabled_and_reports_each_path_once(self):
        for agent in hub_install.TARGETS:
            path = self.write_hook(agent)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["hooks"]["SessionStart"] = data["hooks"]["Stop"]
            path.write_text(json.dumps(data), encoding="utf-8")
        status = hub_install.global_status(home=self.home)
        self.assertTrue(status["enabled"])
        self.assertEqual(status["missing_paths"], [str(self.relay)])

    def test_frozen_folder_move_requires_repair_even_if_old_relay_still_exists(self):
        self.relay.parent.mkdir()
        self.relay.write_bytes(b"placeholder")
        for agent in hub_install.TARGETS:
            self.write_hook(agent)
        with patch.object(hub_install.sys, "frozen", True, create=True), patch.object(
                hub_install.sys, "executable", str(self.home / "new folder" / "AgentDeck.exe")):
            status = hub_install.global_status(home=self.home)
        self.assertTrue(status["enabled"])
        self.assertTrue(status["needs_repair"])
        self.assertEqual(status["missing_paths"], [])
        with patch.object(hub_install.sys, "frozen", False, create=True):
            self.assertFalse(hub_install.global_status(home=self.home)["needs_repair"])

    def test_one_stale_hook_or_source_hook_requires_frozen_repair(self):
        for agent in hub_install.TARGETS:
            self.write_hook(agent)
        path = self.home.joinpath(*hub_install.TARGETS["cx"])
        with patch.object(hub_install.sys, "frozen", False, create=True):
            source = hub_install.command("cx")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["hooks"]["Stop"][0]["hooks"].append({"type": "command", "command": source})
        path.write_text(json.dumps(data), encoding="utf-8")
        with patch.object(hub_install.sys, "frozen", True, create=True), patch.object(
                hub_install.sys, "executable", str(self.relay.with_name("AgentDeck.exe"))):
            self.assertTrue(hub_install.global_status(home=self.home)["needs_repair"])

    @unittest.skipUnless(os.name == "nt", "Windows paths ignore case and slash direction")
    def test_frozen_windows_path_comparison_ignores_case_and_slash_direction(self):
        for agent in hub_install.TARGETS:
            self.write_hook(agent, relay=str(self.relay).upper().replace("\\", "/"), exec_form=agent == "cc")
        with patch.object(hub_install.sys, "frozen", True, create=True), patch.object(
                hub_install.sys, "executable", str(self.relay.with_name("AgentDeck.exe"))):
            self.assertFalse(hub_install.global_status(home=self.home)["needs_repair"])

    def test_invalid_global_config_is_disabled_and_reports_error(self):
        self.write_hook("cc")
        path = self.write_hook("cx")
        for text in ("{bad", "[]", '{"hooks":[]}', '{"hooks":{"Stop":{}}}',
                     '{"hooks":{"Stop":[{}]}}', '{"hooks":{"Stop":[{"hooks":"bad"}]}}'):
            with self.subTest(text=text):
                path.write_text(text, encoding="utf-8")
                status = hub_install.global_status(home=self.home)
                self.assertFalse(status["enabled"])
                self.assertEqual(len(status["errors"]), 1)
                self.assertIn(str(path), status["errors"][0])
                self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_app_report_includes_global_disabled_enabled_and_invalid_path_states(self):
        def report():
            with patch.object(hub_doctor, "doctor", return_value=0):
                return hub_doctor.app_report(home=self.home,
                    usb_probe=lambda: {"connected": False}, serial_probe=lambda home: "未确认")

        self.assertIn("全局钩子：未启用", report()["text"])
        for agent in hub_install.TARGETS:
            self.write_hook(agent)
        self.assertIn("全局钩子：路径失效", report()["text"])
        self.relay.parent.mkdir()
        self.relay.write_bytes(b"placeholder")
        self.assertIn("全局钩子：已启用", report()["text"])
        with patch.object(hub_install.sys, "frozen", True, create=True), patch.object(
                hub_install.sys, "executable", str(self.home / "new" / "AgentDeck.exe")):
            self.assertIn("全局钩子：路径失效", report()["text"])


class AppSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def entry(self, command):
        return {"type": "command", "command": command}

    def test_frozen_command_is_sibling_executable_without_python(self):
        executable = self.home / "Folder with spaces" / "AgentDeck.exe"
        with patch.object(hub_install.sys, "frozen", True, create=True), \
                patch.object(hub_install.sys, "executable", str(executable)):
            command = hub_install.command("cx", port=47910, approve_timeout=85, gate=True, project=True)
            parts = hub_install.split_command(command)
            self.assertEqual(Path(parts[0]), executable.with_name("AgentDeck-relay.exe"))
            self.assertEqual(parts[1:], ["--agent", "cx", "--port", "47910", "--approve-timeout", "85", "--gate"])
            self.assertTrue(hub_install.is_gate(self.entry(command)))

    def test_frozen_install_reinstall_and_uninstall_preserve_foreign_hooks(self):
        project = self.home / "project"
        foreign = self.entry("python unrelated.py")
        config = project.joinpath(*hub_install.PROJECT_TARGETS["cx"])
        self.write(config, {"theme": "keep", "hooks": {"Stop": [{"hooks": [foreign]}]}})
        with patch.object(hub_install.sys, "frozen", True, create=True), \
                patch.object(hub_install.sys, "executable", str(self.home / "AgentDeck.exe")):
            hub_install.apply("install", project=project, output=io.StringIO())
            self.assertEqual(hub_install.apply("install", project=project, output=io.StringIO()), [])
            data = json.loads(config.read_text(encoding="utf-8"))
            for groups in data["hooks"].values():
                for group in groups:
                    for entry in group["hooks"]:
                        if entry != foreign:
                            self.assertIn("AgentDeck-relay.exe", entry["command"])
                            self.assertNotIn("hub_relay.py", entry["command"])
            hub_install.apply("uninstall", project=project, output=io.StringIO())
        self.assertEqual(json.loads(config.read_text(encoding="utf-8")),
                         {"theme": "keep", "hooks": {"Stop": [{"hooks": [foreign]}]}})

    def test_moved_executable_is_recognized_but_incidental_mentions_are_not(self):
        command = subprocess.list2cmdline([str(self.home / "missing folder" / "AgentDeck-relay.exe"), "--agent", "cx"])
        self.assertEqual(hub_install.relay_info(self.entry(command))["agent"], "cx")
        for text in ('echo AgentDeck-relay.exe --agent cx', 'python other.py --note AgentDeck-relay.exe',
                     'AgentDeck-relay.exe --agent wrong', 'AgentDeck-relay.exe --wrong cx'):
            self.assertFalse(hub_install.is_ours(self.entry(text)))

    def test_moved_source_requires_python_and_preserves_echo_hooks(self):
        foreign = [self.entry('echo hub_relay.py --agent cc'),
                   self.entry('echo D:/old/pc/hub_relay.py --agent cx')]
        for entry in foreign:
            self.assertFalse(hub_install.is_ours(entry))
        self.assertTrue(hub_install.is_ours(self.entry('python D:/old/pc/hub_relay.py --agent cc')))
        custom = subprocess.list2cmdline(["D:/custom/runtime.exe", hub_install.SCRIPT, "--agent", "cx"])
        self.assertTrue(hub_install.is_ours(self.entry(custom)))
        data = {"hooks": {"Stop": [{"hooks": [*foreign, self.entry(hub_install.command("cc"))]}]}}
        self.assertEqual(hub_install.updated(data, "uninstall", "cc"),
                         {"hooks": {"Stop": [{"hooks": foreign}]}})

    def test_existing_source_branch_uses_current_script_and_interpreter(self):
        with patch.object(hub_install.sys, "frozen", False, create=True):
            parts = hub_install.split_command(hub_install.command("cc", project=True))
        self.assertEqual(parts, [Path(hub_install.sys.executable).resolve().as_posix(), hub_install.SCRIPT, "--agent", "cc"])

    def test_project_inventory_detects_moved_paths_and_uninstall(self):
        project = self.home / "project"
        exe = self.home / "Old directory" / "AgentDeck-relay.exe"
        entry = self.entry(subprocess.list2cmdline([str(exe), "--agent", "cx"]))
        config = self.write(project.joinpath(*hub_install.PROJECT_TARGETS["cx"]),
                            {"hooks": {"Stop": [{"hooks": [entry]}]}})
        record = hub_doctor.installed_projects([project, project])[0]
        self.assertEqual(record["agents"], ["cx"])
        self.assertEqual(record["missing_paths"], [str(exe)])
        self.assertTrue(hub_doctor._has_relay(config, "cx"))
        exe.parent.mkdir()
        exe.write_bytes(b"placeholder")
        self.assertEqual(hub_doctor.installed_projects([project])[0]["missing_paths"], [])
        config.unlink()
        self.assertEqual(hub_doctor.installed_projects([project])[0]["agents"], [])

    def test_legacy_requires_confirmation_before_reading_or_writing(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("unexpected file read")):
            for confirmed in (False, None, 1, "yes"):
                with self.assertRaisesRegex(ValueError, "confirmation"):
                    hub_install.remove_legacy_hooks(home=self.home, confirmed=confirmed)

    def test_legacy_cleanup_backs_up_exact_bytes_and_preserves_other_data(self):
        legacy = self.entry('"D:/Python env/python.exe" "D:/old path/agent_lcd.py" hook cc')
        foreign = self.entry('python other.py --note agent_lcd.py')
        own = self.entry(hub_install.command("cc"))
        before = {"theme": "dark", "hooks": {"Stop": [{"matcher": "Bash", "hooks": [legacy, foreign, own]}],
                   "SessionStart": [{"hooks": [legacy]}], "EmptyForeign": []}}
        paths = []
        for folders in hub_install.TARGETS.values():
            path = self.write(self.home.joinpath(*folders), before)
            path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes() + b"\r\n")
            paths.append(path)
        originals = {path: path.read_bytes() for path in paths}
        changed = hub_install.remove_legacy_hooks(home=self.home, confirmed=True)
        self.assertCountEqual(changed, paths)
        for path in paths:
            backups = list(path.parent.glob(path.name + ".bak-agentdeck-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), originals[path])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"theme": "dark", "hooks": {
                "Stop": [{"matcher": "Bash", "hooks": [foreign, own]}], "EmptyForeign": []}})
        self.assertEqual(hub_install.remove_legacy_hooks(home=self.home, confirmed=True), [])

    def test_original_installer_command_and_args_are_counted_and_removed(self):
        # Use the original installer's actual entry factories, including Claude's
        # shell-free executable + args schema and Codex's command-string schema.
        claude = legacy_install.TARGETS["cc"]["entry"]()
        codex = legacy_install.TARGETS["codex"]["entry"]()
        self.assertTrue(hub_install.is_legacy(claude))
        self.assertTrue(hub_install.is_legacy(codex))
        with patch.object(legacy_install, "PY", "D:/Python env/python.exe"), \
                patch.object(legacy_install, "SCRIPT", "D:/old project/agent_lcd.py"):
            claude = legacy_install.TARGETS["cc"]["entry"]()
        self.assertTrue(hub_install.is_legacy(claude))
        foreign = {"type": "command", "command": claude["command"],
                   "args": ["D:/other.py", "--note", "agent_lcd.py"]}
        paths = []
        for agent, entry in (("cc", claude), ("cx", codex)):
            paths.append(self.write(self.home.joinpath(*hub_install.TARGETS[agent]), {
                "theme": "preserve", "hooks": {"Stop": [{"hooks": [entry, foreign]}]}}))
        with patch.object(hub_doctor, "doctor", return_value=0):
            report = hub_doctor.app_report(home=self.home,
                usb_probe=lambda: {"connected": False, "driver": None},
                serial_probe=lambda home: "未确认")
        self.assertEqual(report["legacy_count"], 2)
        originals = {path: path.read_bytes() for path in paths}
        self.assertCountEqual(hub_install.remove_legacy_hooks(home=self.home, confirmed=True), paths)
        for path in paths:
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {
                "theme": "preserve", "hooks": {"Stop": [{"hooks": [foreign]}]}})
            self.assertEqual(next(path.parent.glob(path.name + ".bak-agentdeck-*")).read_bytes(), originals[path])

    def test_command_and_args_schema_rejects_malformed_or_unrelated_arguments(self):
        base = {"type": "command", "command": "python.exe"}
        for args in (None, "agent_lcd.py hook cc", {}, ["agent_lcd.py", "hook", 1],
                     ["agent_lcd.py", "hook", "cc", None],
                     ["other.py", "--note", "agent_lcd.py"], ["agent_lcd.py", "doctor", "cc"]):
            with self.subTest(args=args):
                self.assertFalse(hub_install.is_legacy({**base, "args": args}))
        self.assertFalse(hub_install.is_legacy({"type": "command", "command": None,
                                               "args": ["agent_lcd.py", "hook", "cc"]}))

    def test_legacy_cleanup_prepares_all_files_before_any_write(self):
        first = self.write(self.home.joinpath(*hub_install.TARGETS["cc"]), {"hooks": {"Stop": [{
            "hooks": [self.entry("python agent_lcd.py hook cc")]}]}})
        second = self.home.joinpath(*hub_install.TARGETS["cx"])
        second.parent.mkdir()
        second.write_text("{bad", encoding="utf-8")
        before = first.read_bytes()
        with self.assertRaises(ValueError):
            hub_install.remove_legacy_hooks(home=self.home, confirmed=True)
        self.assertEqual(first.read_bytes(), before)
        self.assertEqual(list(self.home.rglob("*.bak-agentdeck-*")), [])

    def test_legacy_cleanup_will_not_replace_if_backup_fails(self):
        path = self.write(self.home.joinpath(*hub_install.TARGETS["cc"]), {"hooks": {"Stop": [{
            "hooks": [self.entry("python agent_lcd.py hook cc")]}]}})
        before = path.read_bytes()
        with patch.object(hub_install.shutil, "copy2", side_effect=OSError("backup denied")):
            with self.assertRaises(OSError):
                hub_install.remove_legacy_hooks(home=self.home, confirmed=True)
        self.assertEqual(path.read_bytes(), before)

    def test_legacy_detection_ignores_incidental_mentions_or_other_actions(self):
        for text in ('echo agent_lcd.py hook cc', 'python other.py --note agent_lcd.py',
                     'python agent_lcd.py doctor', 'python agent_lcd.py.backup hook cx'):
            self.assertFalse(hub_install.is_legacy(self.entry(text)))
        self.assertTrue(hub_install.is_legacy(self.entry('pythonw.exe D:/old/agent_lcd.py hook cx')))

    def test_app_report_reuses_doctor_in_chinese_without_mutating_home(self):
        self.write(self.home.joinpath(*hub_install.TARGETS["cc"]), {"hooks": {"Stop": [{"hooks": [
            self.entry("python agent_lcd.py hook cc")]}]}})
        project = self.home / "project"
        missing = project / "missing" / "AgentDeck-relay.exe"
        self.write(project.joinpath(*hub_install.PROJECT_TARGETS["cx"]), {"hooks": {"Stop": [{"hooks": [
            self.entry(subprocess.list2cmdline([str(missing), "--agent", "cx"]))]}]}})
        checks = [{"label": "Hub /health", "success": True, "detail": ""},
                  {"label": "Token file", "success": False, "detail": ""}]

        def doctor(**options):
            options["checks"].extend(checks)
            return 1

        before = {path: path.read_bytes() for path in self.home.rglob("*") if path.is_file()}
        with patch.object(hub_doctor, "doctor", side_effect=doctor):
            report = hub_doctor.app_report(home=self.home, projects=[project],
                usb_probe=lambda: {"connected": True, "driver": "winusb"},
                serial_probe=lambda home: "替身：未确认")
        for text in ("中枢服务：正常运行", "读键方式：USB 直读", "键盘 USB：已连接", "COM4 占用：替身",
                     "全局旧版 agent_lcd.py 钩子：1 条", "路径已失效", "重新安装", "/hooks 信任"):
            self.assertIn(text, report["text"])
        self.assertEqual(report["legacy_count"], 1)
        self.assertEqual(before, {path: path.read_bytes() for path in self.home.rglob("*") if path.is_file()})

    def test_serial_occupancy_uses_log_evidence_without_opening_port(self):
        self.assertIn("未确认", hub_doctor.serial_log_status(self.home))
        path = self.home / ".agentdeck" / "logs" / "app.log"
        path.parent.mkdir(parents=True)
        path.write_text("LCD unavailable: PermissionError: Access is denied COM4\n", encoding="utf-8")
        text = hub_doctor.serial_log_status(self.home)
        self.assertIn("最近日志显示被占用或权限不足", text)
        self.assertIn("不代表此刻仍占用", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
