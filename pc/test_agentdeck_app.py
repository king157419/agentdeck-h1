"""Offline tray behavior checks: all OS, registry, sockets and GUI effects replaced."""
import errno
import ctypes
import io
import json
from pathlib import Path
from queue import SimpleQueue
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import agentdeck_app as app
import hub_install
import voice_shortcut_capture as shortcut_capture


class MenuItem:
    def __init__(self, text, action, **options):
        self.text = text
        self.action = action
        self.options = options


class Menu:
    SEPARATOR = object()

    def __init__(self, *items):
        self.items = items

    def children(self):
        if len(self.items) == 1 and callable(self.items[0]):
            return list(self.items[0]())
        return list(self.items)


class FakeRegistry:
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {"OtherApp": "other.exe"}
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def OpenKey(self, root, path):
        assert (root, path) == (self.HKEY_CURRENT_USER, app.RUN_KEY)
        return self

    def CreateKeyEx(self, root, path, reserved, rights):
        assert (root, path, reserved, rights) == (self.HKEY_CURRENT_USER, app.RUN_KEY, 0, self.KEY_SET_VALUE)
        return self

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.writes.append((name, kind, value))
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


class StatusTests(unittest.TestCase):
    def test_empty_status_and_tooltip(self):
        self.assertEqual(app.tray_status({}), ("idle", "AgentDeck · 0 个会话 · 0 个待批"))

    def test_running_sessions_are_green(self):
        status, text = app.tray_status({"sessions": [{"state": "think"}, {"state": "tool"}]})
        self.assertEqual(status, "running")
        self.assertIn("2 个会话 · 0 个待批", text)

    def test_waiting_overrides_running_without_double_counting(self):
        sessions = [{"state": "wait", "pending_requests": [{"id": "a"}, {"id": "b"}]}, {"state": "tool"}]
        self.assertEqual(app.tray_status({"sessions": sessions}),
                         ("waiting", "AgentDeck · 2 个会话 · 1 个待批"))

    def test_error_has_priority_over_waiting(self):
        status, text = app.tray_status({"sessions": [{"state": "wait"}, {"state": "error"}]})
        self.assertEqual(status, "error")
        self.assertIn("1 个待批", text)

    def test_idle_and_completed_sessions_keep_gray_icon(self):
        self.assertEqual(app.tray_status({"sessions": [{"state": "idle"}, {"state": "done"}]})[0], "idle")

    def test_locked_and_pending_requests_count_as_waiting_sessions(self):
        state = {"sessions": [{"state": "locked"}, {"state": "idle", "pending_requests": [{"id": "p"}]},
                              {"state": "tool", "locked_requests": [{"id": "q"}]}]}
        self.assertEqual(app.tray_status(state), ("waiting", "AgentDeck · 3 个会话 · 3 个待批"))

    def test_label_includes_chinese_state_tool_and_project(self):
        self.assertEqual(app.session_label({"state": "wait", "agent": "cx", "project": "中文 项目"}),
                         "待批 Codex 中文 项目")

    def test_label_falls_back_to_name_then_cwd(self):
        self.assertEqual(app.session_label({"state": "done", "agent": "cc", "name": "sample"}), "完成 Claude sample")
        self.assertTrue(app.session_label({"state": "idle", "agent": "cc", "cwd": "D:/repo"}).endswith("D:/repo"))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def test_defaults_copied_into_temporary_home_once(self):
        keys, prompts = app.prepare_configs(self.home)
        self.assertEqual(keys.parent, self.home / ".agentdeck")
        self.assertEqual(json.loads(keys.read_text(encoding="utf-8")), app.hub.load_json(app.resource_dir() / "hub_keys.json"))
        self.assertIsInstance(json.loads(prompts.read_text(encoding="utf-8")), dict)
        keys.write_text('{"custom": true}', encoding="utf-8")
        prompts.write_text('{"my template": "keep me"}', encoding="utf-8")
        self.assertEqual(app.prepare_configs(self.home), (keys, prompts))
        self.assertEqual(keys.read_text(encoding="utf-8"), '{"custom": true}')
        self.assertEqual(prompts.read_text(encoding="utf-8"), '{"my template": "keep me"}')

    def test_frozen_defaults_come_from_bundle(self):
        bundle = self.home / "bundle"
        bundle.mkdir()
        for name in ("hub_keys.json", "hub_prompts.json"):
            (bundle / name).write_text('{"bundled": true}', encoding="utf-8")
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", str(bundle), create=True):
            self.assertEqual(app.resource_dir(), bundle)
            self.assertEqual(app.hub.load_json(app.prepare_configs(self.home)[0]), {"bundled": True})

    def test_source_resource_path_is_independent_of_current_directory(self):
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(app.resource_dir(), Path(app.__file__).resolve().parent)

    def test_preferences_remember_projects_and_dismissal(self):
        prefs = app.Preferences(self.home)
        project = self.home / "中文 repo"
        prefs.project_changed(project, True)
        prefs.project_changed(project, True)
        prefs.values["onboarding_dismissed"] = True
        prefs.save()
        restored = app.Preferences(self.home)
        self.assertEqual(restored.projects, [str(project.resolve())])
        self.assertTrue(restored.values["onboarding_dismissed"])
        restored.project_changed(project, False)
        self.assertEqual(app.Preferences(self.home).projects, [])

    def test_invalid_preferences_fail_with_clear_error(self):
        folder = app.data_dir(self.home)
        folder.mkdir()
        (folder / "app.json").write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "app.json"):
            app.Preferences(self.home)

    def test_keymap_has_twenty_positions_and_four_separate_knobs(self):
        config = app.hub.load_json(app.resource_dir() / "hub_keys.json")
        model = app.keymap_model(config)
        self.assertEqual([len(row) for row in model["rows"]], [4] * 5)
        self.assertEqual(len(model["knobs"]), 4)
        self.assertEqual(model["rows"][0][0], ("E", "slot 1"))
        self.assertEqual(model["rows"][1][3], ("无信号", "无信号"))
        self.assertEqual(model["rows"][4][1], ("Ctrl+C", "未绑定"))
        self.assertEqual(model["knobs"][0], ["cycle +1", "cycle -1", "screenshot"])
        self.assertIn("voice_down", model["rows"][1][2][1])
        self.assertIn("voice_up", model["rows"][1][2][1])

    def test_keymap_uses_selected_profile_and_live_user_values(self):
        config = {"bindings": {"hid:0x08": "slot 1"}, "alternate": {"bindings": {"hid:0x08": "slot 6"}}}
        self.assertEqual(app.keymap_model(config, "alternate")["rows"][0][0][1], "slot 6")
        config["alternate"]["bindings"]["hid:0x08"] = "prompt my-template"
        self.assertEqual(app.keymap_model(config, "alternate")["rows"][0][0][1], "prompt my-template")
        with self.assertRaisesRegex(ValueError, "missing"):
            app.keymap_model(config, "missing")


class ShortcutRecordingTests(unittest.TestCase):
    def event(self, code, symbol):
        return SimpleNamespace(keycode=code, keysym=symbol)

    def test_chord_is_complete_only_after_every_key_is_released(self):
        recorder = app.ShortcutRecorder()
        control, shift, key = self.event(17, "Control_L"), self.event(16, "Shift_L"), self.event(32, "space")
        for event in (control, shift, key, key):
            recorder.press(event)
        self.assertIsNone(recorder.release(key))
        self.assertIsNone(recorder.release(control))
        self.assertEqual(recorder.release(shift), {"key_codes": [32], "modifiers": ["control", "shift"]})
        self.assertEqual(recorder.label, "Ctrl + Shift + Space")
        recorder.press(self.event(65, "a"))
        self.assertEqual(recorder.shortcut["key_codes"], [32])

    def test_single_side_modifier_is_not_discarded(self):
        for symbol, code in (("Alt_R", 0xA5), ("Control_R", 0xA3), ("Shift_L", 0xA0), ("Win_R", 0x5C)):
            with self.subTest(symbol=symbol):
                recorder = app.ShortcutRecorder()
                event = self.event(18, symbol)
                recorder.press(event)
                self.assertEqual(recorder.release(event), {"key_codes": [code], "modifiers": []})

    def test_modifier_only_chord_preserves_sides(self):
        recorder = app.ShortcutRecorder()
        keys = [self.event(17, "Control_R"), self.event(18, "Alt_R")]
        for key in keys:
            recorder.press(key)
        recorder.release(keys[0])
        self.assertEqual(recorder.release(keys[1]), {"key_codes": [0xA3, 0xA5], "modifiers": []})

    def test_right_modifier_with_main_key_keeps_its_specific_virtual_key(self):
        recorder = app.ShortcutRecorder()
        keys = [self.event(17, "Control_L"), self.event(18, "Alt_R"), self.event(75, "k")]
        for key in keys:
            recorder.press(key)
        for key in keys[:-1]:
            recorder.release(key)
        self.assertEqual(recorder.release(keys[-1]), {"key_codes": [0xA5, 75], "modifiers": ["control"]})

    def test_ordinary_key_and_unknown_release(self):
        recorder = app.ShortcutRecorder()
        key = self.event(72, "h")
        self.assertIsNone(recorder.release(key))
        recorder.press(self.event(0, "??"))
        recorder.press(key)
        self.assertEqual(recorder.release(key), {"key_codes": [72], "modifiers": []})
        self.assertEqual(recorder.label, "H")


class NativeShortcutCaptureTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.errors = []
        self.calls = []
        self.foreground = 13
        self.window = Mock()
        self.window.winfo_id.return_value = 7
        api = SimpleNamespace(root=lambda child: 13, foreground=lambda: self.foreground,
                              install=lambda proc: self.calls.append(("install", proc)) or 91,
                              remove=lambda handle: self.calls.append(("remove", handle)),
                              next=lambda *args: self.calls.append(("next", args)) or 73)
        self.capture = shortcut_capture.ShortcutCapture(self.window,
                lambda down, event: self.events.append((down, event.keycode, event.keysym)), self.errors.append, api=api)
        self.capture.start()
        self.addCleanup(self.capture.close)

    def feed(self, code, *, down=True, scan=0, flags=0, hook_code=0):
        flags |= 0 if down else shortcut_capture.LLKHF_UP
        data = shortcut_capture.KBDLLHOOKSTRUCT(code, scan, flags, 0, 0)
        message = shortcut_capture.WM_KEYDOWN if down else shortcut_capture.WM_KEYUP
        return self.capture._hookproc(hook_code, message, ctypes.addressof(data))

    def test_ordinary_chord_is_suppressed_and_close_unhooks_once(self):
        self.assertEqual(self.feed(0x11), 1)
        self.assertEqual(self.feed(0x4B), 1)
        self.assertEqual(self.feed(0x4B, down=False), 1)
        self.assertEqual(self.feed(0x11, down=False), 1)
        self.assertEqual(self.events, [(True, 0xA2, "Control_L"), (True, 0x4B, "K"),
                                      (False, 0x4B, "K"), (False, 0xA2, "Control_L")])
        self.capture.close()
        self.capture.close()
        self.assertEqual([call for call in self.calls if call[0] == "remove"], [("remove", 91)])
        self.assertNotIn(91, shortcut_capture._installed)

    def test_extended_control_alt_and_shift_scan_preserve_sides(self):
        for code, scan, flags, expected in ((0x11, 0, 1, 0xA3), (0x12, 0, 1, 0xA5),
                                            (0x10, 0x36, 0, 0xA1), (0x10, 0x2A, 0, 0xA0),
                                            (0xA5, 0, 0, 0xA5)):
            with self.subTest(code=code, scan=scan, flags=flags):
                self.assertEqual(self.feed(code, scan=scan, flags=flags), 1)
                self.assertEqual(self.events[-1][1], expected)
                self.feed(code, down=False, scan=scan, flags=flags)

    def test_negative_hook_code_and_injected_events_pass_through(self):
        for options in ({"hook_code": -1}, {"flags": 0x10}, {"flags": 2}):
            self.assertEqual(self.feed(65, **options), 73)
        self.assertEqual(self.events, [])
        self.assertTrue(self.capture.active)

    def test_keyup_without_owned_keydown_passes_through(self):
        self.assertEqual(self.feed(0x11, down=False), 73)
        self.assertEqual(self.events, [])

    def test_foreground_loss_unhooks_and_never_swallows_another_windows_input(self):
        self.foreground = 99
        self.assertEqual(self.feed(65), 73)
        self.assertFalse(self.capture.active)
        self.assertIsNone(self.capture.handle)
        self.assertEqual(self.events, [])
        self.assertEqual(self.errors, ["窗口已失焦，请重录"])

    def test_callback_exception_unhooks_and_is_contained(self):
        self.capture.on_key = Mock(side_effect=RuntimeError("fake callback failure"))
        self.assertEqual(self.feed(65), 73)
        self.assertFalse(self.capture.active)
        self.assertIsNone(self.capture.handle)
        self.assertEqual(self.errors, ["录制失败，请重录"])

    def test_install_failure_never_owns_or_intercepts_keyboard(self):
        self.capture.close()
        self.capture.api.install = Mock(side_effect=OSError("fake hook failure"))
        with self.assertRaisesRegex(OSError, "fake hook failure"):
            self.capture.start()
        self.assertFalse(self.capture.active)
        self.assertIsNone(self.capture.handle)


class AutostartTests(unittest.TestCase):
    def setUp(self):
        self.registry = FakeRegistry()
        self.command = '"D:\\App folder\\AgentDeck.exe"'
        self.start = app.AutoStart(self.registry, self.command)

    def test_register_and_unregister_only_agentdeck_value(self):
        self.assertFalse(self.start.enabled())
        self.start.set_enabled(True)
        self.assertTrue(self.start.enabled())
        self.assertEqual(self.registry.values["AgentDeck"], self.command)
        self.start.set_enabled(False)
        self.start.set_enabled(False)
        self.assertFalse(self.start.enabled())
        self.assertEqual(self.registry.values, {"OtherApp": "other.exe"})

    def test_stale_autostart_path_is_not_reported_as_current(self):
        self.registry.values["AgentDeck"] = '"D:\\Old folder\\AgentDeck.exe"'
        self.assertFalse(self.start.enabled())
        self.start.set_enabled(True)
        self.assertTrue(self.start.enabled())

    def test_frozen_launch_command_quotes_exe_without_python(self):
        executable = Path("D:/App folder/AgentDeck.exe")
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(executable)):
            self.assertEqual(app.launch_command(), subprocess.list2cmdline([str(executable.resolve())]))
            self.assertNotIn("python", app.launch_command().lower())

    def test_source_launch_command_uses_pythonw_and_absolute_script(self):
        with patch.object(sys, "frozen", False, create=True), patch.object(sys, "executable", "D:/Conda folder/python.exe"):
            self.assertEqual(app.launch_command(), subprocess.list2cmdline(
                ["D:\\Conda folder\\pythonw.exe", str(Path(app.__file__).resolve())]))


class InitializationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.registry = FakeRegistry()
        self.start = app.AutoStart(self.registry, "AgentDeck.exe")
        guard = patch.object(Path, "home", side_effect=AssertionError("real home access"))
        guard.start()
        self.addCleanup(guard.stop)

    def test_initialization_backs_up_migrates_preserves_settings_and_is_idempotent(self):
        before = {}
        foreign = {"type": "command", "command": "echo keep"}
        for agent, folders in hub_install.TARGETS.items():
            path = self.home.joinpath(*folders)
            path.parent.mkdir()
            data = {"custom": True, "hooks": {"Stop": [{"hooks": [foreign,
                    {"type": "command", "command": "python old/agent_lcd.py hook " + agent}]}]}}
            path.write_text(json.dumps(data), encoding="utf-8")
            before[path] = data
        trust = self.home / ".codex" / "requirements.toml"
        trust.write_text("# leave trust to Codex\n", encoding="utf-8")
        prefs = app.Preferences(self.home)
        prefs.values["projects"] = ["remember this project"]
        prefs.save()
        result = app.init_all(self.home, autostart=self.start)
        self.assertTrue(self.start.enabled())
        self.assertTrue(hub_install.global_status(home=self.home)["enabled"])
        self.assertTrue(app.Preferences(self.home).values["initialized"])
        self.assertEqual(app.Preferences(self.home).projects, ["remember this project"])
        for path, original in before.items():
            self.assertIn(original, [json.loads(backup.read_text(encoding="utf-8"))
                          for backup in path.parent.glob(path.name + ".bak-agentdeck-*")])
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data["custom"])
            entries = [entry for groups in data["hooks"].values() for group in groups for entry in group["hooks"]]
            self.assertIn(foreign, entries)
            self.assertFalse(any(hub_install.is_legacy(entry) for entry in entries))
        snapshot = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(app.init_all(self.home, autostart=self.start), result)
        self.assertEqual({p.relative_to(self.home): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}, snapshot)
        self.assertEqual(len(self.registry.writes), 1)
        self.assertEqual(trust.read_text(encoding="utf-8"), "# leave trust to Codex\n")
        self.assertEqual(self.registry.values["OtherApp"], "other.exe")

    def test_backup_failure_stops_install_and_startup_and_does_not_mark_initialized(self):
        with patch.object(hub_install, "remove_legacy_hooks", side_effect=OSError("backup failed")), patch.object(
                hub_install, "apply") as install:
            with self.assertRaisesRegex(OSError, "backup failed"):
                app.init_all(self.home, autostart=self.start)
        install.assert_not_called()
        self.assertEqual(self.registry.writes, [])
        self.assertNotIn("initialized", app.Preferences(self.home).values)

    def test_startup_failure_can_be_retried_without_duplicate_hooks(self):
        failing = Mock()
        failing.enabled.return_value = False
        failing.set_enabled.side_effect = OSError("registry denied")
        with self.assertRaisesRegex(OSError, "registry denied"):
            app.init_all(self.home, autostart=failing)
        self.assertNotIn("initialized", app.Preferences(self.home).values)
        before = {self.home.joinpath(*folders): self.home.joinpath(*folders).read_bytes()
                  for folders in hub_install.TARGETS.values()}
        app.init_all(self.home, autostart=self.start)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(list(path.parent.glob(path.name + ".bak-agentdeck-*")), [])

    def test_hook_install_failure_does_not_enable_startup_or_mark_initialized(self):
        with patch.object(hub_install, "apply", side_effect=OSError("write denied")):
            with self.assertRaisesRegex(OSError, "write denied"):
                app.init_all(self.home, autostart=self.start)
        self.assertEqual(self.registry.writes, [])
        self.assertNotIn("initialized", app.Preferences(self.home).values)

    def test_cli_init_and_uninstall_bypass_all_runtime_and_gui_startup(self):
        for frozen in (False, True):
            with self.subTest(frozen=frozen), patch.object(sys, "frozen", frozen, create=True), patch.object(
                    app, "AutoStart", return_value=self.start), patch.object(app, "SingleInstance") as instance, patch.object(
                    app, "configure_logging") as logging_setup, patch.object(app.hub, "main") as hub_main, patch.object(
                    app, "prepare_configs") as configs, patch("tkinter.Toplevel") as window, patch(
                    "tkinter.messagebox.showerror") as error, patch.object(sys, "stdout", io.StringIO()) as output:
                self.assertEqual(app.main(["--home", str(self.home), "--init"]), 0)
                self.assertTrue(json.loads(output.getvalue())["initialized"])
                self.assertTrue(self.start.enabled())
                output.seek(0)
                output.truncate()
                self.assertEqual(app.main(["--home", str(self.home), "--uninstall"]), 0)
                self.assertFalse(json.loads(output.getvalue())["autostart"])
                self.assertFalse(self.start.enabled())
                self.assertFalse(hub_install.global_status(home=self.home)["enabled"])
                self.assertNotIn("initialized", app.Preferences(self.home).values)
            for forbidden in (instance, logging_setup, hub_main, configs, window, error):
                forbidden.assert_not_called()

    def test_cli_failure_reports_to_stderr_without_a_dialog(self):
        with patch.object(app, "AutoStart", return_value=self.start), patch.object(
                hub_install, "remove_legacy_hooks", side_effect=OSError("backup denied")), patch.object(
                sys, "stderr", io.StringIO()) as errors, patch("tkinter.messagebox.showerror") as dialog:
            self.assertEqual(app.main(["--home", str(self.home), "--init"]), 1)
        self.assertIn("backup denied", errors.getvalue())
        dialog.assert_not_called()
        self.assertEqual(self.registry.writes, [])

    def test_cli_init_and_uninstall_are_mutually_exclusive(self):
        with patch.object(sys, "stderr", io.StringIO()), self.assertRaises(SystemExit) as raised:
            app.main(["--home", str(self.home), "--init", "--uninstall"])
        self.assertEqual(raised.exception.code, 2)

    def test_cli_uninstall_failure_keeps_completion_marker_and_startup(self):
        app.init_all(self.home, autostart=self.start)
        with patch.object(app, "AutoStart", return_value=self.start), patch.object(
                hub_install, "apply", side_effect=OSError("write denied")), patch.object(
                sys, "stderr", io.StringIO()) as errors, patch("tkinter.messagebox.showerror") as dialog:
            self.assertEqual(app.main(["--home", str(self.home), "--uninstall"]), 1)
        self.assertIn("write denied", errors.getvalue())
        dialog.assert_not_called()
        self.assertTrue(self.start.enabled())
        self.assertTrue(app.Preferences(self.home).values["initialized"])


class CliOutputTests(unittest.TestCase):
    def test_source_console_streams_are_retained_without_native_calls(self):
        with patch.object(sys, "stdout", io.StringIO()) as output, patch("ctypes.windll", create=True) as native:
            app.restore_cli_output()
            self.assertIs(sys.stdout, output)
        native.kernel32.GetStdHandle.assert_not_called()

    def check_missing_streams(self, handles):
        kernel = MagicMock()
        kernel.GetStdHandle.side_effect = handles
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(sys, "platform", "win32"), patch.object(sys, "stdout", None), patch.object(
                sys, "stderr", None), patch("ctypes.windll", SimpleNamespace(kernel32=kernel), create=True), patch(
                "msvcrt.open_osfhandle", side_effect=[21, 22]) as descriptor, patch.object(
                app.os, "fdopen", side_effect=[output, errors]) as fdopen:
            app.restore_cli_output()
            self.assertIs(sys.stdout, output)
            self.assertIs(sys.stderr, errors)
        self.assertEqual([call.args for call in descriptor.call_args_list], [(101, app.os.O_WRONLY), (102, app.os.O_WRONLY)])
        self.assertEqual([call.args for call in fdopen.call_args_list], [(21, "w"), (22, "w")])
        return kernel

    @unittest.skipUnless(sys.platform == "win32", "Windows console API")
    def test_windowed_build_reuses_inherited_pipe_without_attaching_console(self):
        kernel = self.check_missing_streams([101, 101, 102])
        kernel.AttachConsole.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Windows console API")
    def test_windowed_build_attaches_existing_parent_console_when_handles_absent(self):
        kernel = self.check_missing_streams([None, 101, 102])
        kernel.AttachConsole.assert_called_once()


class InstanceTests(unittest.TestCase):
    def setUp(self):
        self.queue = SimpleQueue()
        self.listener = MagicMock()
        self.connector = Mock()
        self.instance = app.SingleInstance(self.queue, socket_factory=Mock(return_value=self.listener),
                                           connector=self.connector)

    def test_owner_binds_loopback_and_closes_listener(self):
        thread = Mock()
        with patch.object(app.threading, "Thread", return_value=thread):
            self.assertTrue(self.instance.acquire())
        self.listener.bind.assert_called_once_with(("127.0.0.1", app.APP_PORT))
        thread.start.assert_called_once()
        self.connector.assert_not_called()
        self.instance.close()
        self.listener.close.assert_called_once()
        thread.join.assert_called_once()

    def test_second_instance_requests_show_and_exits_without_listener_thread(self):
        self.listener.bind.side_effect = OSError(errno.EADDRINUSE, "used")
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.recv.return_value = b"AgentDeck OK\n"
        self.connector.return_value = connection
        with patch.object(app.threading, "Thread") as thread:
            self.assertFalse(self.instance.acquire())
        connection.sendall.assert_called_once_with(b"AgentDeck SHOW\n")
        thread.assert_not_called()
        self.listener.close.assert_called_once()

    def test_unrelated_port_owner_is_an_error_not_a_second_hub(self):
        self.listener.bind.side_effect = OSError(errno.EADDRINUSE, "used")
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.recv.return_value = b"unrelated process"
        self.connector.return_value = connection
        with patch.object(self.instance.stopped, "wait", return_value=False), self.assertRaisesRegex(RuntimeError, "单实例端口"):
            self.instance.acquire()
        self.assertIsNone(self.instance.listener)

    def test_non_collision_bind_failure_propagates(self):
        self.listener.bind.side_effect = OSError(errno.EACCES, "denied")
        with self.assertRaises(PermissionError):
            self.instance.acquire()
        self.connector.assert_not_called()

    def test_listener_accepts_fragmented_show_message_and_acknowledges(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.recv.side_effect = [b"AgentDeck ", b"SHOW\n"]
        connection.sendall.side_effect = lambda data: self.instance.stopped.set()
        self.listener.accept.return_value = (connection, ("127.0.0.1", 1))
        self.instance.listener = self.listener
        self.instance._listen()
        self.assertEqual(self.queue.get_nowait(), ("show", None))
        connection.sendall.assert_called_once_with(b"AgentDeck OK\n")


class TrayMessageTests(unittest.TestCase):
    def test_right_click_refreshes_before_opening_menu_on_same_thread(self):
        events = []
        owner = threading.get_ident()

        class Icon:
            def update_menu(self):
                events.append(("refresh", threading.get_ident()))

            def _on_notify(self, wparam, lparam):
                events.append(("open", threading.get_ident(), wparam, lparam))
                return "handled"

        icon = app.tray_icon_type(Icon)()
        self.assertEqual(icon._on_notify(17, 0x0205), "handled")
        self.assertEqual(events, [("refresh", owner), ("open", owner, 17, 0x0205)])

    def test_other_tray_messages_do_not_rebuild_menu(self):
        events = []

        class Icon:
            def update_menu(self):
                events.append("refresh")

            def _on_notify(self, wparam, lparam):
                events.append((wparam, lparam))

        icon = app.tray_icon_type(Icon)()
        for message in (0x0200, 0x0202, 0x0203):
            icon._on_notify(17, message)
        self.assertEqual(events, [(17, 0x0200), (17, 0x0202), (17, 0x0203)])


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.home_guard = patch.object(Path, "home", side_effect=AssertionError("real home access"))
        self.home_guard.start()
        self.addCleanup(self.home_guard.stop)
        self.engine = Mock(home=self.home)
        self.engine.lock = threading.RLock()
        self.engine.state.return_value = {"sessions": []}
        self.overlay = Mock(hidden=False)
        self.overlay.stopped.is_set.return_value = False
        self.registry = FakeRegistry()
        self.prefs = app.Preferences(self.home)
        self.queue = SimpleQueue()
        self.application = app.TrayApplication(self.engine, commands=self.queue, prefs=self.prefs,
                                              keys_path=app.resource_dir() / "hub_keys.json",
                                              autostart=app.AutoStart(self.registry, "AgentDeck.exe"),
                                              overlay=self.overlay)
        self.application.message = Mock()

    def test_menu_callbacks_enqueue_without_native_actions(self):
        menu = self.application.menu(SimpleNamespace(Menu=Menu, MenuItem=MenuItem))
        rows = [r for r in menu.children() if isinstance(r, MenuItem)]
        by_name = {r.text: r for r in rows if isinstance(r.text, str)}
        for label, action in (("键位", "keys"), ("诊断", "diagnostics"), ("所有项目启用", "global"),
                              ("日志", "logs"),
                              ("下一个待批", "next_wait"), ("退出", "quit")):
            by_name[label].action()
            self.assertEqual(self.queue.get_nowait(), (action, None))
        self.assertNotIn("安装…", by_name)
        self.assertNotIn("卸载…", by_name)
        for row, action in zip(by_name["单个项目"].action.children(), ("install", "uninstall")):
            row.action()
            self.assertEqual(self.queue.get_nowait(), (action, None))
        self.assertEqual([row.text for row in by_name["单个项目"].action.children()],
                         ["安装…", "卸载…"])
        self.engine.action.assert_not_called()
        self.overlay.show.assert_not_called()

    def voice_desktop(self):
        from hub_desktop import DesktopEffects
        desktop = DesktopEffects(shots_dir=self.home / "shots")
        self.engine._desktop.return_value = desktop
        return desktop

    def test_voice_shortcut_save_preserves_other_hub_config_and_applies_immediately(self):
        desktop = self.voice_desktop()
        path = app.data_dir(self.home) / "config.json"
        path.parent.mkdir()
        path.write_text('{"gate_mode":"adaptive","custom":{"keep":true}}', encoding="utf-8")
        shortcut = {"key_codes": [0xA5], "modifiers": [], "mode": "hold"}
        self.application.save_voice_shortcut(shortcut)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                         {"gate_mode": "adaptive", "custom": {"keep": True}, "dictation_shortcut": shortcut})
        self.assertEqual(desktop.dictation_shortcut, shortcut)
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_voice_shortcut_save_default_mode_and_restart_read(self):
        desktop = self.voice_desktop()
        self.application.save_voice_shortcut({"key_codes": [72], "modifiers": ["command"]})
        config = app.hub.load_json(app.data_dir(self.home) / "config.json")
        self.assertEqual(config["dictation_shortcut"]["mode"], "toggle")
        self.assertEqual(desktop._shortcut(config["dictation_shortcut"]), desktop.dictation_shortcut)

    def test_voice_shortcut_bad_config_and_invalid_chord_preserve_file_and_desktop(self):
        desktop = self.voice_desktop()
        original = desktop.dictation_shortcut
        path = app.data_dir(self.home) / "config.json"
        path.parent.mkdir()
        path.write_text("[]", encoding="utf-8")
        for shortcut in ({"key_codes": [72]}, {"key_codes": []}):
            with self.assertRaises(ValueError):
                self.application.save_voice_shortcut(shortcut)
        self.assertEqual(path.read_text(encoding="utf-8"), "[]")
        self.assertEqual(desktop.dictation_shortcut, original)

    def test_voice_shortcut_save_failure_rolls_back_memory_and_preserves_existing_config(self):
        desktop = self.voice_desktop()
        original = desktop.dictation_shortcut
        path = app.data_dir(self.home) / "config.json"
        path.parent.mkdir()
        path.write_text('{"custom":true}', encoding="utf-8")
        with patch.object(app.os, "replace", side_effect=OSError("write denied")):
            with self.assertRaisesRegex(OSError, "write denied"):
                self.application.save_voice_shortcut({"key_codes": [0xA5], "mode": "hold"})
        self.assertEqual(path.read_text(encoding="utf-8"), '{"custom":true}')
        self.assertEqual(desktop.dictation_shortcut, original)
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_voice_shortcut_changes_are_blocked_while_voice_is_active(self):
        desktop = self.voice_desktop()
        with patch.object(type(desktop), "voice_active", new_callable=lambda: property(lambda self: True)):
            with self.assertRaisesRegex(RuntimeError, "松开语音键"):
                self.application.save_voice_shortcut({"key_codes": [0xA5], "mode": "hold"})
        self.assertFalse((app.data_dir(self.home) / "config.json").exists())

    def build_voice_settings(self):
        tk = MagicMock()
        commands, bindings = {}, {}
        mode = SimpleNamespace(value="hold")
        mode.get = lambda: mode.value
        tk.StringVar.return_value = mode
        tk.Toplevel.return_value.bind.side_effect = lambda event, command: bindings.__setitem__(event, command)
        captures = []

        def capture(window, on_key, on_error):
            native = Mock(on_key=on_key, on_error=on_error)
            captures.append(native)
            bindings["<KeyPress>"] = lambda event: on_key(True, event)
            bindings["<KeyRelease>"] = lambda event: on_key(False, event)
            return native

        tk.capture_instances = captures

        def button(parent, text, command, kind="primary", **kwargs):
            commands[text] = command
            return Mock()

        with patch.dict(sys.modules, {"tkinter": tk}), patch.object(app.theme, "label", side_effect=lambda *a, **kw: Mock()), patch.object(
                app.theme, "button", side_effect=button), patch.object(
                app.theme, "style_window", side_effect=lambda window, title: window), patch.object(app.theme, "center"), patch.object(
                app, "ShortcutCapture", side_effect=capture):
            self.application.show_voice_shortcut()
        # Re-record invokes the same injectable substitute after construction.
        original = commands["重录"]

        def rerecord():
            with patch.object(app, "ShortcutCapture", side_effect=capture):
                original()

        commands["重录"] = rerecord
        return tk, commands, bindings, mode

    def test_voice_settings_records_chord_then_saves_selected_mode_and_closes(self):
        self.voice_desktop()
        tk, commands, bindings, mode = self.build_voice_settings()
        event = SimpleNamespace(keycode=18, keysym="Alt_R")
        bindings["<KeyPress>"](event)
        bindings["<KeyRelease>"](event)
        mode.value = "toggle"
        commands["保存"]()
        self.assertEqual(app.hub.load_json(app.data_dir(self.home) / "config.json")["dictation_shortcut"],
                         {"key_codes": [0xA5], "modifiers": [], "mode": "toggle"})
        tk.capture_instances[0].close.assert_called_once()
        tk.Toplevel.return_value.destroy.assert_called_once()

    def test_voice_settings_cancel_and_rerecord_never_apply_partial_chords(self):
        tk, commands, bindings, mode = self.build_voice_settings()
        with patch.object(self.application, "save_voice_shortcut") as save:
            commands["保存"]()
            event = SimpleNamespace(keycode=18, keysym="Alt_R")
            bindings["<KeyPress>"](event)
            bindings["<KeyRelease>"](event)
            commands["重录"]()
            commands["保存"]()
            commands["取消"]()
        save.assert_not_called()
        tk.Toplevel.return_value.destroy.assert_called_once()

    def test_voice_settings_focus_loss_discards_incomplete_chord_without_refocusing(self):
        tk, commands, bindings, mode = self.build_voice_settings()
        event = SimpleNamespace(keycode=17, keysym="Control_L")
        bindings["<KeyPress>"](event)
        tk.Toplevel.return_value.focus_force.reset_mock()
        bindings["<FocusOut>"](SimpleNamespace(widget=tk.Toplevel.return_value))
        tk.capture_instances[0].close.assert_called_once()
        tk.Toplevel.return_value.focus_force.assert_not_called()
        with patch.object(self.application, "save_voice_shortcut") as save:
            commands["保存"]()
        save.assert_not_called()

    def test_voice_settings_destroy_unhooks_and_rerecord_creates_new_capture(self):
        tk, commands, bindings, mode = self.build_voice_settings()
        commands["重录"]()
        self.assertEqual(len(tk.capture_instances), 2)
        tk.capture_instances[0].close.assert_called_once()
        bindings["<Destroy>"](SimpleNamespace(widget=tk.Toplevel.return_value))
        tk.capture_instances[1].close.assert_called_once()

    def test_voice_settings_native_error_disables_save_and_keeps_dialog_open(self):
        tk, commands, bindings, mode = self.build_voice_settings()
        tk.capture_instances[0].on_error("录制失败，请重录")
        with patch.object(self.application, "save_voice_shortcut") as save:
            commands["保存"]()
        save.assert_not_called()
        tk.Toplevel.return_value.destroy.assert_not_called()

    def test_keys_window_has_voice_shortcut_entry(self):
        tk = MagicMock()
        commands = {}

        def button(parent, text, command, kind="primary", **kwargs):
            commands[text] = command
            return Mock()

        with patch.dict(sys.modules, {"tkinter": tk}), patch.object(app.theme, "label", return_value=Mock()), patch.object(
                app.theme, "button", side_effect=button), patch.object(app.theme, "style_window", side_effect=lambda w, title: w), patch.object(
                app.theme, "center"), patch.object(self.application, "show_voice_shortcut") as settings:
            self.application.show_keys()
            commands["语音快捷键"]()
        settings.assert_called_once_with()

    def test_dynamic_session_menu_preserves_full_identity(self):
        menu = self.application.menu(SimpleNamespace(Menu=Menu, MenuItem=MenuItem))
        submenu = next(r.action for r in menu.children() if isinstance(r, MenuItem) and r.text == "会话")
        self.assertFalse(submenu.children()[0].options["enabled"])
        session = {"agent": "cx", "session_id": "complete-session-id", "state": "wait", "project": "project"}
        self.application.state = {"sessions": [session]}
        row = submenu.children()[0]
        self.assertEqual(row.text, "待批 Codex project")
        row.action()
        self.assertEqual(self.queue.get_nowait(), ("select", ("cx", "complete-session-id")))

    def test_menu_open_uses_latest_cached_sessions_without_timer_rebuild(self):
        menu = self.application.menu(SimpleNamespace(Menu=Menu, MenuItem=MenuItem))
        submenu = next(r.action for r in menu.children() if isinstance(r, MenuItem) and r.text == "会话")
        opened = []

        class Icon:
            rows = None

            def update_menu(self):
                self.rows = submenu.children()

            def _on_notify(self, wparam, lparam):
                opened.append([row.text for row in self.rows])

        icon = app.tray_icon_type(Icon)()
        icon._on_notify(0, 0x0205)
        self.application.state = {"sessions": [{"agent": "cc", "session_id": "new-full-id",
                                                "state": "tool", "project": "new-project"}]}
        icon._on_notify(0, 0x0205)
        self.assertEqual(opened, [["暂无会话"], ["运行 Claude new-project"]])
        icon.rows[0].action()
        self.assertEqual(self.queue.get_nowait(), ("select", ("cc", "new-full-id")))

    def test_show_and_toggle_use_overlay_visibility_methods(self):
        self.application.dispatch("show")
        self.overlay.show.assert_called_once()
        self.application.dispatch("toggle")
        self.overlay.hide.assert_called_once()
        self.overlay.hidden = True
        self.application.dispatch("toggle")
        self.assertEqual(self.overlay.show.call_count, 2)

    def test_select_and_next_wait_use_existing_hub_action(self):
        self.engine.state.return_value = {"sessions": [{"agent": "cc", "session_id": "abcdef-full", "slot": 3}]}
        self.application.dispatch("select", ("cc", "abcdef-full"))
        self.engine.action.assert_called_once_with({"action": "slot 3"})
        self.application.dispatch("next_wait")
        self.engine.action.assert_called_with({"action": "next_wait"})

    def test_stale_or_same_prefix_session_never_focuses_recycled_slot(self):
        self.engine.state.return_value = {"sessions": [{"agent": "cc", "session_id": "abcdef-new", "slot": 1}]}
        with self.assertRaisesRegex(ValueError, "会话已结束"):
            self.application.dispatch("select", ("cc", "abcdef-old"))
        self.engine.action.assert_not_called()

    def test_selection_holds_identity_lock_until_action_finishes(self):
        session = {"agent": "cc", "session_id": "original", "slot": 2}
        attempted = threading.Event()
        replaced = threading.Event()
        workers = []

        def replace_session():
            attempted.set()
            with self.engine.lock:
                session["session_id"] = "replacement"
                replaced.set()

        def state():
            worker = threading.Thread(target=replace_session)
            workers.append(worker)
            worker.start()
            self.assertTrue(attempted.wait(1))
            self.assertFalse(replaced.is_set())
            return {"sessions": [dict(session)]}

        def action(payload):
            self.assertFalse(replaced.is_set())
            self.assertEqual(session["session_id"], "original")
            self.assertEqual(payload, {"action": "slot 2"})

        self.engine.state.side_effect = state
        self.engine.action.side_effect = action
        try:
            self.application.dispatch("select", ("cc", "original"))
        finally:
            for worker in workers:
                worker.join(timeout=2)
        self.assertTrue(replaced.is_set())

    def test_autostart_menu_toggles_registration_and_checkmark(self):
        self.application.dispatch("autostart")
        self.assertTrue(self.application.autostart_enabled)
        self.assertEqual(self.registry.values["AgentDeck"], "AgentDeck.exe")
        self.application.dispatch("autostart")
        self.assertFalse(self.application.autostart_enabled)
        self.assertEqual(self.registry.values, {"OtherApp": "other.exe"})

    def test_logs_action_opens_only_app_log_folder(self):
        with patch.object(app.os, "startfile", create=True) as startfile:
            self.application.dispatch("logs")
        startfile.assert_called_once_with(str(self.home / ".agentdeck" / "logs"))

    def test_exit_stops_overlay(self):
        self.application.dispatch("quit")
        self.overlay.stop.assert_called_once()

    def test_project_install_and_uninstall_are_local_and_remembered(self):
        project = self.home / "project"
        project.mkdir()
        global_dir = self.home / ".claude"
        global_dir.mkdir()
        global_path = global_dir / "settings.json"
        global_path.write_text('{"keep":true}', encoding="utf-8")
        with patch("tkinter.filedialog.askdirectory", return_value=str(project)):
            self.application.project_action("install")
            self.assertTrue((project / ".claude" / "settings.local.json").exists())
            self.assertTrue((project / ".codex" / "hooks.json").exists())
            self.assertEqual(app.Preferences(self.home).projects, [str(project.resolve())])
            self.assertIn("/hooks", self.application.message.call_args.args[1])
            self.application.project_action("uninstall")
        self.assertEqual(app.Preferences(self.home).projects, [])
        for folders in hub_install.PROJECT_TARGETS.values():
            data = app.hub.load_json(project.joinpath(*folders))
            self.assertFalse(any(hub_install.is_ours(entry) for groups in data.get("hooks", {}).values()
                                 for group in groups for entry in group.get("hooks", [])))
        self.assertEqual(global_path.read_text(encoding="utf-8"), '{"keep":true}')

    def test_project_picker_cancel_does_not_write_any_config(self):
        with patch("tkinter.filedialog.askdirectory", return_value=""), patch("hub_install.apply") as install:
            self.application.project_action("install")
        install.assert_not_called()
        self.assertFalse(self.prefs.path.exists())

    def test_global_checkmark_reads_both_configs_each_time_instead_of_preferences(self):
        self.prefs.values["global_enabled"] = True
        menu = self.application.menu(SimpleNamespace(Menu=Menu, MenuItem=MenuItem))
        row = next(row for row in menu.children() if isinstance(row, MenuItem) and row.text == "所有项目启用")
        checked = row.options["checked"]
        self.assertFalse(checked(row))
        hub_install.apply("install", home=self.home, agents=("cc",), output=io.StringIO())
        self.assertFalse(checked(row))
        hub_install.apply("install", home=self.home, agents=("cx",), output=io.StringIO())
        self.assertTrue(checked(row))
        hub_install.apply("uninstall", home=self.home, agents=("cc",), output=io.StringIO())
        self.assertFalse(checked(row))

    def test_global_enable_cancel_leaves_home_untouched(self):
        with patch("agentdeck_theme.confirm", return_value=False) as confirm, patch.object(
                hub_install, "remove_legacy_hooks") as remove, patch.object(hub_install, "apply") as install:
            self.application.dispatch("global")
        confirm.assert_called_once()
        text = confirm.call_args.args[2]
        for phrase in ("备份两份全局配置", "旧版 1602 钩子", "AgentDeck 未运行", "终端确认"):
            self.assertIn(phrase, text)
        remove.assert_not_called()
        install.assert_not_called()
        self.assertEqual(list(self.home.iterdir()), [])

    def test_global_enable_migrates_legacy_with_backups_and_disable_does_not_restore_it(self):
        before = {}
        foreign = {"type": "command", "command": "echo keep"}
        for agent, folders in hub_install.TARGETS.items():
            path = self.home.joinpath(*folders)
            path.parent.mkdir(parents=True)
            data = {"custom": True, "hooks": {"Stop": [{"hooks": [foreign,
                    {"type": "command", "command": "python old/agent_lcd.py hook " + agent}]}]}}
            path.write_text(json.dumps(data), encoding="utf-8")
            before[path] = data
        with patch("agentdeck_theme.confirm", return_value=True) as confirm, patch.object(
                hub_install, "remove_legacy_hooks", wraps=hub_install.remove_legacy_hooks) as remove, patch.object(
                hub_install, "apply", wraps=hub_install.apply) as install:
            calls = Mock()
            calls.attach_mock(remove, "remove")
            calls.attach_mock(install, "apply")
            self.application.dispatch("global")
            self.assertEqual([call[0] for call in calls.mock_calls], ["remove", "apply"])
            remove.assert_called_once_with(home=self.home, confirmed=True)
            self.assertEqual(install.call_args.args, ("install",))
            self.assertEqual(install.call_args.kwargs["home"], self.home)
            self.assertTrue(hub_install.global_status(home=self.home)["enabled"])
            self.application.dispatch("global")
            confirm.assert_called_once()
            remove.assert_called_once()
            self.assertEqual(install.call_args.args, ("uninstall",))
        self.assertFalse(hub_install.global_status(home=self.home)["enabled"])
        for path, original in before.items():
            self.assertIn(original, [json.loads(backup.read_text(encoding="utf-8"))
                          for backup in path.parent.glob(path.name + ".bak-agentdeck-*")])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                             {"custom": True, "hooks": {"Stop": [{"hooks": [foreign]}]}})
        self.assertFalse(self.prefs.path.exists())

    def test_global_backup_failure_does_not_continue_to_install(self):
        with patch("agentdeck_theme.confirm", return_value=True), patch.object(
                hub_install, "remove_legacy_hooks", side_effect=OSError("backup failed")), patch.object(
                hub_install, "apply") as install:
            with self.assertRaisesRegex(OSError, "backup failed"):
                self.application.global_action()
        install.assert_not_called()

    def test_legacy_removal_requires_user_confirmation(self):
        window = Mock()
        with patch("agentdeck_theme.confirm", return_value=False), patch("hub_install.remove_legacy_hooks") as remove:
            self.application.remove_legacy(window)
        remove.assert_not_called()
        window.destroy.assert_not_called()

    def test_legacy_removal_passes_explicit_confirmation_and_temp_home(self):
        window = Mock()
        with patch("agentdeck_theme.confirm", return_value=True), patch("hub_install.remove_legacy_hooks", return_value=[]) as remove, patch.object(
                self.application, "diagnostics") as diagnostics:
            self.application.remove_legacy(window)
        remove.assert_called_once_with(home=self.home, confirmed=True)
        window.destroy.assert_called_once()
        diagnostics.assert_called_once()

    def build_onboarding(self):
        tk = MagicMock()
        commands = {}
        caption = Mock()
        button = Mock()

        def make_button(parent, text, command, kind="primary", **kwargs):
            commands[text] = command
            return button

        with patch.dict(sys.modules, {"tkinter": tk}), patch.object(app.theme, "label", return_value=caption) as label, patch.object(
                app.theme, "button", side_effect=make_button), patch.object(
                app.theme, "style_window", side_effect=lambda window, title: window), patch.object(app.theme, "center"):
            self.application.onboarding()
        return tk, commands, caption, label, button

    def test_onboarding_skips_only_completed_initialization(self):
        self.prefs.values["initialized"] = True
        with patch("tkinter.Toplevel") as window, patch("hub_doctor.installed_projects") as installed:
            self.application.onboarding()
        window.assert_not_called()
        installed.assert_not_called()

    def test_onboarding_is_one_line_and_one_button_even_with_legacy_dismissal_or_hooks(self):
        self.prefs.values["onboarding_dismissed"] = True
        hub_install.apply("install", home=self.home, output=io.StringIO())
        tk, commands, caption, label, button = self.build_onboarding()
        tk.Toplevel.assert_called_once_with(self.overlay.root)
        label.assert_called_once()
        self.assertNotIn("\n", label.call_args.args[1])
        self.assertEqual(list(commands), ["开始使用"])
        self.assertNotIn("initialized", self.prefs.values)
        self.assertEqual(self.registry.writes, [])

    def test_onboarding_initializes_and_closes_without_preexisting_codex(self):
        tk, commands, caption, label, button = self.build_onboarding()
        commands["开始使用"]()
        self.assertTrue(hub_install.global_status(home=self.home)["enabled"])
        self.assertTrue(self.application.autostart_enabled)
        self.assertTrue(app.Preferences(self.home).values["initialized"])
        tk.Toplevel.return_value.destroy.assert_called_once()
        self.application.message.assert_not_called()

    def test_onboarding_displays_codex_trust_in_same_window_and_removes_button(self):
        (self.home / ".codex").mkdir()
        tk, commands, caption, label, button = self.build_onboarding()
        commands["开始使用"]()
        caption.configure.assert_called_with(text="在 Codex 里输入 /hooks，信任一次", fg=app.theme.TEXT)
        button.destroy.assert_called_once()
        tk.Toplevel.return_value.destroy.assert_not_called()
        tk.Toplevel.assert_called_once()
        self.application.message.assert_not_called()
        with patch.object(app, "init_all") as initialize:
            commands["开始使用"]()
        initialize.assert_not_called()

    def test_onboarding_failure_stays_in_same_window_and_allows_retry(self):
        tk, commands, caption, label, button = self.build_onboarding()
        with patch.object(app, "init_all", side_effect=OSError("backup failed")), self.assertLogs(app.log, level="ERROR"):
            commands["开始使用"]()
        self.assertIn("backup failed", caption.configure.call_args.kwargs["text"])
        tk.Toplevel.return_value.destroy.assert_not_called()
        button.destroy.assert_not_called()
        self.assertNotIn("initialized", self.prefs.values)
        self.application.message.assert_not_called()
        commands["开始使用"]()
        self.assertTrue(app.Preferences(self.home).values["initialized"])
        tk.Toplevel.return_value.destroy.assert_called_once()

    def test_diagnostics_queues_report_for_gui_thread(self):
        report = {"text": "USB 未连接", "legacy_count": 0}

        def immediate_thread(*, target, **kwargs):
            return SimpleNamespace(start=target)

        with patch("hub_doctor.app_report", return_value=report) as doctor, patch.object(app.threading, "Thread", side_effect=immediate_thread):
            self.application.diagnostics()
        doctor.assert_called_once_with(home=self.home, projects=[])
        self.assertEqual(self.queue.get_nowait(), ("report", report))
        self.application.message.assert_not_called()

    def test_closing_onboarding_does_not_mark_initialization_complete(self):
        tk, commands, caption, label, button = self.build_onboarding()
        tk.Toplevel.return_value.protocol.call_args.args[1]()
        self.assertNotIn("initialized", app.Preferences(self.home).values)
        self.assertEqual(self.registry.writes, [])

    def test_run_always_stops_tray_even_when_overlay_fails(self):
        self.application.icon = Mock()
        self.application.tray_thread = Mock()
        self.overlay.run.side_effect = RuntimeError("Tk failed")
        with self.assertRaisesRegex(RuntimeError, "Tk failed"):
            self.application.run()
        self.application.icon.stop.assert_called_once()
        self.application.tray_thread.join.assert_called_once()

    def test_pump_updates_icon_and_dispatches_queued_actions_on_tk_thread(self):
        self.application.icon = Mock()
        self.queue.put(("show", None))
        self.engine.state.return_value = {"sessions": [{"state": "wait"}]}
        with patch.object(self.application, "draw_icon", return_value="amber"):
            self.application.pump()
        self.overlay.show.assert_called_once()
        self.assertEqual(self.application.icon.icon, "amber")
        self.assertEqual(self.application.icon.title, "AgentDeck · 1 个会话 · 1 个待批")
        self.application.icon.update_menu.assert_not_called()
        self.overlay.root.after.assert_called_with(300, self.application.pump)


    def test_live_menu_actions_defer_hub_locks_and_native_focus(self):
        self.application._background_enabled = True
        self.application.dispatch("select", ("cc", "session"))
        self.engine.state.assert_not_called()
        self.engine.action.assert_not_called()
        self.overlay.defer.assert_called_once()
        work = self.overlay.defer.call_args.args[0]
        self.engine.state.return_value = {"sessions": [
            {"agent": "cc", "session_id": "session", "slot": 3}]}
        work()
        self.engine.action.assert_called_once_with({"action": "slot 3"})

    def test_live_pump_uses_background_snapshot_without_hub_lock(self):
        self.application._background_enabled = True
        self.overlay.state = {"sessions": []}
        self.application.icon = Mock()
        self.application.pump()
        self.engine.state.assert_not_called()
        self.assertEqual(self.application.state, {"sessions": []})


class GlobalRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.old = self.home / "旧目录" / "AgentDeck.exe"
        self.current = self.home / "新目录 with spaces" / "AgentDeck.exe"
        self.current.parent.mkdir()
        self.current.with_name("AgentDeck-relay.exe").touch()
        guard = patch.object(Path, "home", side_effect=AssertionError("real home access"))
        guard.start()
        self.addCleanup(guard.stop)

    def install_at(self, executable, agents=("cc", "cx")):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(executable)):
            hub_install.apply("install", home=self.home, agents=agents, output=io.StringIO())

    def test_moved_bundle_repairs_both_configs_once_without_confirmation(self):
        self.install_at(self.old)
        before = {self.home.joinpath(*folders): self.home.joinpath(*folders).read_bytes()
                  for folders in hub_install.TARGETS.values()}
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(self.current)), patch(
                "tkinter.messagebox.askyesno") as confirm, patch.object(
                hub_install, "remove_legacy_hooks") as remove, self.assertLogs(app.log, level="INFO") as logs:
            self.assertTrue(app.repair_global_hooks(self.home))
            self.assertFalse(app.repair_global_hooks(self.home))
            self.assertTrue(hub_install.global_status(home=self.home)["enabled"])
            self.assertFalse(hub_install.global_status(home=self.home)["needs_repair"])
        confirm.assert_not_called()
        remove.assert_not_called()
        self.assertIn("全局钩子 relay 路径已修复", "\n".join(logs.output))
        for path, raw in before.items():
            backups = list(path.parent.glob(path.name + ".bak-agentdeck-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), raw)
            data = json.loads(path.read_text(encoding="utf-8"))
            for groups in data["hooks"].values():
                for group in groups:
                    for entry in group["hooks"]:
                        self.assertEqual(Path(hub_install.relay_info(entry)["paths"][0]),
                                         self.current.with_name("AgentDeck-relay.exe"))

    def test_partial_or_absent_installation_is_not_enabled_automatically(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(self.current)):
            self.assertFalse(app.repair_global_hooks(self.home))
        self.install_at(self.old, agents=("cc",))
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(self.current)), patch.object(
                hub_install, "apply") as install:
            self.assertFalse(app.repair_global_hooks(self.home))
        install.assert_not_called()
        self.assertFalse(self.home.joinpath(*hub_install.TARGETS["cx"]).exists())

    def test_source_launch_never_rewrites_global_paths(self):
        self.install_at(self.old)
        with patch.object(sys, "frozen", False, create=True), patch.object(hub_install, "global_status") as status, patch.object(
                hub_install, "apply") as install:
            self.assertFalse(app.repair_global_hooks(self.home))
        status.assert_not_called()
        install.assert_not_called()

    def test_repair_failure_is_logged_without_interrupting_startup(self):
        self.install_at(self.old)
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(self.current)), patch.object(
                hub_install, "apply", side_effect=OSError("read only")), self.assertLogs(app.log, level="ERROR") as logs:
            self.assertFalse(app.repair_global_hooks(self.home))
        self.assertIn("路径修复失败", "\n".join(logs.output))
        self.assertIn("read only", "\n".join(logs.output))


class EntryPointTests(unittest.TestCase):
    def test_secondary_launch_never_loads_configuration_or_starts_hub(self):
        instance = Mock()
        instance.acquire.return_value = False
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "SingleInstance", return_value=instance), patch.object(
                app, "prepare_configs") as configs, patch.object(app.hub, "main") as main, patch.object(
                app, "repair_global_hooks") as repair:
            self.assertEqual(app.main(["--home", directory]), 0)
        configs.assert_not_called()
        main.assert_not_called()
        repair.assert_not_called()
        instance.close.assert_called_once()

    def test_primary_launch_calls_in_process_hub_with_required_inputs_and_ui_factory(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = Mock()
            instance.acquire.return_value = True
            engine = Mock()
            controller = Mock()

            def run_hub(argv, *, ui_factory):
                self.assertEqual(argv[:4], ["--backend", "usb,hotkey", "--overlay", "--require-nonce"])
                self.assertEqual(argv[argv.index("--home") + 1], str(Path(directory).resolve()))
                self.assertEqual(argv[argv.index("--profile") + 1], "v2_emulation")
                self.assertTrue(Path(argv[argv.index("--keys") + 1]).is_file())
                self.assertEqual(ui_factory(engine), controller)
                return 0

            with patch.object(app, "SingleInstance", return_value=instance), patch.object(app, "TrayApplication", return_value=controller) as tray, patch.object(
                    app, "repair_global_hooks") as repair, patch.object(
                    app.hub, "main", side_effect=run_hub):
                self.assertEqual(app.main(["--home", directory, "--profile", "v2_emulation"]), 0)
            repair.assert_called_once_with(Path(directory).resolve())
            self.assertEqual(tray.call_args.args, (engine,))
            self.assertEqual(tray.call_args.kwargs["profile"], "v2_emulation")
            self.assertTrue((Path(directory) / ".agentdeck" / "logs" / "app.log").exists())
            instance.close.assert_called_once()


class OverlayReadyTests(unittest.TestCase):
    def run_overlay(self, fail_callback=False):
        with tempfile.TemporaryDirectory() as directory:
            events = []
            owner = threading.get_ident()
            root = Mock()
            root.winfo_reqheight.return_value = 200
            root.winfo_id.return_value = 123
            root.deiconify.side_effect = lambda: events.append("visible")
            root.mainloop.side_effect = lambda: events.append("mainloop")
            root.destroy.side_effect = lambda: events.append("destroy")
            window = Mock()
            window.apply.side_effect = lambda handle: events.append(("apply", handle))
            window.show.side_effect = lambda: events.append("show")
            window.close.side_effect = lambda: events.append("close")
            on_close = Mock(side_effect=lambda: events.append("on_close"))
            overlay = app.Overlay(Mock(home=Path(directory)), window=window, on_close=on_close)

            def ready():
                self.assertEqual(threading.get_ident(), owner)
                self.assertIs(overlay.root, root)
                self.assertEqual(events, [("apply", 123), "visible", "show"])
                events.append("ready")
                if fail_callback:
                    raise RuntimeError("tray initialization failed")

            callback = Mock(side_effect=ready)
            with patch("tkinter.Tk", return_value=root), patch.object(overlay, "_build"), patch.object(
                    overlay, "_poll"), patch.object(overlay, "_work_areas", return_value=[(0, 0, 1920, 1080)]), patch.object(
                    overlay, "_place"), patch.object(overlay, "_apply_alpha"):
                if fail_callback:
                    with self.assertRaisesRegex(RuntimeError, "tray initialization failed"):
                        overlay.run(on_ready=callback)
                else:
                    overlay.run(on_ready=callback)
            callback.assert_called_once_with()
            window.close.assert_called_once_with()
            root.destroy.assert_called_once_with()
            on_close.assert_called_once_with()
            self.assertIsNone(overlay.root)
            self.assertTrue(overlay.stopped.is_set())
            return events

    def test_ready_callback_runs_after_setup_before_mainloop_on_caller_thread(self):
        self.assertEqual(self.run_overlay(), [("apply", 123), "visible", "show", "ready", "mainloop",
                                               "close", "destroy", "on_close"])

    def test_ready_callback_failure_closes_native_window_and_destroys_tk(self):
        self.assertEqual(self.run_overlay(True), [("apply", 123), "visible", "show", "ready",
                                                  "close", "destroy", "on_close"])

    def test_hub_runtime_uses_supplied_ui_factory_and_stops_server(self):
        owner = threading.get_ident()
        started = threading.Event()
        stopped = threading.Event()
        server = Mock(server_port=47800)
        controller = Mock()
        engines = []

        def serve_forever(**kwargs):
            started.set()
            if not stopped.wait(3):
                raise AssertionError("temporary substitute server was not stopped")

        def factory(engine):
            self.assertEqual(threading.get_ident(), owner)
            engines.append(engine)
            return controller

        def run_ui():
            self.assertEqual(threading.get_ident(), owner)
            self.assertTrue(started.wait(2))
            self.assertFalse(engines[0].closed)

        server.serve_forever.side_effect = serve_forever
        server.shutdown.side_effect = stopped.set
        controller.run.side_effect = run_ui
        with tempfile.TemporaryDirectory() as directory, patch("hub.HubServer", return_value=server), patch(
                "hub_overlay.Overlay", side_effect=AssertionError("must use supplied UI")), patch(
                "hub_desktop.DesktopEffects", side_effect=AssertionError("native desktop access")):
            self.assertEqual(app.hub.main(["--backend", "none", "--overlay", "--no-lcd", "--no-desktop",
                                           "--home", directory], ui_factory=factory), 0)
        self.assertEqual(len(engines), 1)
        self.assertTrue(engines[0].closed)
        controller.run.assert_called_once_with()
        self.assertGreaterEqual(controller.stop.call_count, 1)
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        self.assertFalse(any(t.name in ("AgentDeck HTTP", "AgentDeck LCD hold") for t in threading.enumerate()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
