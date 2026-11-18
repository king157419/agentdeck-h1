"""Offline tray behavior checks: all OS, registry, sockets and GUI effects replaced."""
import errno
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
        for label, action in (("键位", "keys"), ("诊断", "diagnostics"), ("安装到项目…", "install"),
                              ("从项目卸载…", "uninstall"), ("打开日志文件夹", "logs"),
                              ("跳到等我的会话", "next_wait"), ("退出", "quit")):
            by_name[label].action()
            self.assertEqual(self.queue.get_nowait(), (action, None))
        self.engine.action.assert_not_called()
        self.overlay.show.assert_not_called()

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

    def test_legacy_removal_requires_user_confirmation(self):
        window = Mock()
        with patch("tkinter.messagebox.askyesno", return_value=False), patch("hub_install.remove_legacy_hooks") as remove:
            self.application.remove_legacy(window)
        remove.assert_not_called()
        window.destroy.assert_not_called()

    def test_legacy_removal_passes_explicit_confirmation_and_temp_home(self):
        window = Mock()
        with patch("tkinter.messagebox.askyesno", return_value=True), patch("hub_install.remove_legacy_hooks", return_value=[]) as remove, patch.object(
                self.application, "diagnostics") as diagnostics:
            self.application.remove_legacy(window)
        remove.assert_called_once_with(home=self.home, confirmed=True)
        window.destroy.assert_called_once()
        diagnostics.assert_called_once()

    def test_onboarding_skips_dismissed_or_installed_projects(self):
        self.prefs.values["onboarding_dismissed"] = True
        with patch("hub_doctor.installed_projects") as installed, patch("tkinter.Toplevel") as window:
            self.application.onboarding()
        installed.assert_not_called()
        window.assert_not_called()
        self.prefs.values["onboarding_dismissed"] = False
        with patch("hub_doctor.installed_projects", return_value=[{"path": "project", "agents": ["cc"]}]), patch("tkinter.Toplevel") as window:
            self.application.onboarding()
        window.assert_not_called()

    def test_registered_project_with_no_hooks_still_gets_onboarding(self):
        tk = MagicMock()
        with patch.dict(sys.modules, {"tkinter": tk}), patch("hub_doctor.installed_projects", return_value=[{"path": "removed", "agents": []}]):
            self.application.onboarding()
        tk.Toplevel.assert_called_once()

    def test_diagnostics_queues_report_for_gui_thread(self):
        report = {"text": "USB 未连接", "legacy_count": 0}

        def immediate_thread(*, target, **kwargs):
            return SimpleNamespace(start=target)

        with patch("hub_doctor.app_report", return_value=report) as doctor, patch.object(app.threading, "Thread", side_effect=immediate_thread):
            self.application.diagnostics()
        doctor.assert_called_once_with(home=self.home, projects=[])
        self.assertEqual(self.queue.get_nowait(), ("report", report))
        self.application.message.assert_not_called()

    def test_onboarding_three_steps_and_do_not_show_again_persist(self):
        tk = MagicMock()
        tk.BooleanVar.return_value.get.return_value = True
        with patch.dict(sys.modules, {"tkinter": tk}), patch("hub_doctor.installed_projects", return_value=[]):
            self.application.onboarding()
        label = tk.Label.call_args.kwargs["text"]
        self.assertIn("1. 安装到项目", label)
        self.assertIn("/hooks", label)
        self.assertIn("3. 开始干活", label)
        close = tk.Toplevel.return_value.protocol.call_args.args[1]
        close()
        self.assertTrue(app.Preferences(self.home).values["onboarding_dismissed"])

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


class EntryPointTests(unittest.TestCase):
    def test_secondary_launch_never_loads_configuration_or_starts_hub(self):
        instance = Mock()
        instance.acquire.return_value = False
        with patch.object(app, "SingleInstance", return_value=instance), patch.object(app, "prepare_configs") as configs, patch.object(
                app.hub, "main") as main:
            self.assertEqual(app.main([]), 0)
        configs.assert_not_called()
        main.assert_not_called()
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
                    app.hub, "main", side_effect=run_hub):
                self.assertEqual(app.main(["--home", directory, "--profile", "v2_emulation"]), 0)
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
