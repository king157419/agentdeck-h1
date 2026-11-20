"""Offline tray behavior checks: all OS, registry, sockets and GUI effects replaced."""
import errno
import ctypes
import codecs
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
import xml.etree.ElementTree as ET

import agentdeck_app as app
import hub_install
import voice_shortcut_capture as shortcut_capture


def legacy_keymap(shipped, version):
    bindings = {key: value for key, value in dict(app.V8_BINDINGS, **app.OLD_DEFAULTS[version]).items()
                if value is not None}
    return dict({key: value for key, value in shipped.items() if key != "layers"},
                version=version, bindings=bindings)


class ExplodingOS:
    """A module-level tripwire: no test can use the real login configuration."""
    def __getattr__(self, name):
        raise AssertionError("real winreg access: " + name)


class ExplodingScheduler:
    def query(self, name):
        raise AssertionError("real schtasks query")

    def create(self, name, xml_text):
        raise AssertionError("real schtasks create")

    def delete(self, name):
        raise AssertionError("real schtasks delete")


# Low-level adapter tests use this saved class only inside a subprocess.run patch.
RealSchTasks = app.SchTasks
app.SchTasks = ExplodingScheduler
sys.modules["winreg"] = ExplodingOS()
_subprocess_run = subprocess.run


def guarded_subprocess_run(argv, *args, **kwargs):
    program = argv[0] if isinstance(argv, (list, tuple)) else str(argv).split()[0]
    if Path(str(program).strip('"')).name.lower() in ("schtasks", "schtasks.exe"):
        raise AssertionError("real schtasks subprocess; inject a fake run")
    return _subprocess_run(argv, *args, **kwargs)


subprocess.run = guarded_subprocess_run
SID = "S-1-5-21-1-2-3-1001"
TARGET = (Path("D:/App folder/AgentDeck.exe"), "--background", Path("D:/App folder"))
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


class FakeScheduler:
    def __init__(self, xml=None, *, create_error=None, readback=None, query_error=None,
                 delete_error=None, keep_on_delete=False):
        self.xml = xml
        self.calls = []
        self.create_error = create_error
        self.readback = readback
        self.query_error = query_error
        self.delete_error = delete_error
        self.keep_on_delete = keep_on_delete

    def query(self, name):
        self.calls.append(("query", name))
        if self.query_error:
            raise self.query_error
        return self.xml

    def create(self, name, xml_text):
        self.calls.append(("create", name, xml_text))
        if self.create_error:
            raise self.create_error
        self.xml = xml_text if self.readback is None else self.readback

    def delete(self, name):
        self.calls.append(("delete", name))
        if self.delete_error:
            raise self.delete_error
        if not self.keep_on_delete:
            self.xml = None


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

    def OpenKey(self, root, path, reserved=0, rights=0):
        assert (root, path) == (self.HKEY_CURRENT_USER, app.RUN_KEY)
        assert reserved == 0 and rights in (0, self.KEY_SET_VALUE)
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


class TrayRegistry:
    """HKCU\\Control Panel\\NotifyIconSettings substitute; never the real registry."""
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_DWORD = 4

    def __init__(self, records=None):
        self.records = {} if records is None else records
        self.writes = []

    class Key:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def OpenKey(self, parent, path, reserved=0, rights=0):
        base = parent.path + "\\" + path if isinstance(parent, self.Key) else path
        if base != app.NOTIFY_KEY and base.rsplit("\\", 1)[-1] not in self.records:
            raise FileNotFoundError(base)
        if base == app.NOTIFY_KEY and not self.records:
            raise FileNotFoundError(base)
        return self.Key(base)

    def EnumKey(self, key, index):
        names = list(self.records)
        if index >= len(names):
            raise OSError("no more items")
        return names[index]

    def QueryValueEx(self, key, name):
        values = self.records[key.path.rsplit("\\", 1)[-1]]
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], 1

    def SetValueEx(self, key, name, reserved, kind, value):
        self.writes.append((key.path, name, kind, value))
        self.records[key.path.rsplit("\\", 1)[-1]][name] = value


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

    def test_prepare_configs_upgrades_untouched_v5_and_keeps_original_backup(self):
        shipped = app.hub.load_json(app.resource_dir() / "hub_keys.json")
        original = json.dumps(legacy_keymap(shipped, 5), indent=3).encode("utf-8")
        target = app.data_dir(self.home) / "hub_keys.json"
        target.parent.mkdir()
        target.write_bytes(original)
        keys, _ = app.prepare_configs(home=self.home)
        self.assertEqual(keys, target)
        self.assertEqual(app.hub.load_json(keys), shipped)
        self.assertEqual(shipped["version"], 9)
        self.assertEqual(target.with_name("hub_keys.json.bak-v5").read_bytes(), original)
        app.prepare_configs(home=self.home)
        self.assertEqual(target.with_name("hub_keys.json.bak-v5").read_bytes(), original)

    def test_prepare_configs_keeps_edited_v5_byte_identical(self):
        shipped = app.hub.load_json(app.resource_dir() / "hub_keys.json")
        old = legacy_keymap(shipped, 5)
        old["bindings"]["hid:0x08"] = "slot 6"
        original = json.dumps(old, indent=3).encode("utf-8")
        target = app.data_dir(self.home) / "hub_keys.json"
        target.parent.mkdir()
        target.write_bytes(original)
        app.prepare_configs(home=self.home)
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(target.with_name("hub_keys.json.bak-v5").exists())

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
        self.assertEqual(model["rows"][0][0], ("E", "app claude"))
        self.assertEqual(model["rows"][1][3], ("Alt", "ctx 4"))
        self.assertEqual(model["rows"][3][:2], [("Ctrl", "interrupt"), ("Shift", "screenshot")])
        self.assertEqual(model["rows"][3][2:], [("U", "send"), ("X", "clear")])
        self.assertEqual(model["rows"][4][1], ("Ctrl+C", "deny"))
        self.assertEqual(model["knobs"][0], ["window next", "window prev", "window back"])
        self.assertEqual(model["knobs"][3], ["ctx next", "ctx prev", "ctx select"])
        self.assertIn("voice_down", model["rows"][4][2][1])
        self.assertIn("voice_up", model["rows"][4][2][1])

    def test_keymap_layer_overrides_global_bindings(self):
        config = {"bindings": {"hid:0x0A": "ctx 1", "hid:0x08": "app claude"},
                  "layers": {"chat": {"hid:0x0A": "prompt custom"}}}
        self.assertEqual(app.keymap_model(config, layer="chat")["rows"][1][0][1], "prompt custom")
        self.assertEqual(app.keymap_model(config, layer="browser")["rows"][1][0][1], "ctx 1")
        self.assertEqual(app.keymap_model(config, layer="chat")["rows"][0][0][1], "app claude")
        config["layers"]["chat"] = []
        with self.assertRaisesRegex(ValueError, "layers"):
            app.keymap_model(config, layer="chat")

    def test_keymap_uses_selected_profile_and_live_user_values(self):
        config = {"bindings": {"hid:0x08": "slot 1"}, "alternate": {"bindings": {"hid:0x08": "slot 6"}}}
        self.assertEqual(app.keymap_model(config, "alternate")["rows"][0][0][1], "slot 6")
        config["alternate"]["bindings"]["hid:0x08"] = "prompt my-template"
        self.assertEqual(app.keymap_model(config, "alternate")["rows"][0][0][1], "prompt my-template")
        with self.assertRaisesRegex(ValueError, "missing"):
            app.keymap_model(config, "missing")

    def test_session_label_prefers_title_and_bounds_its_length(self):
        session = {"agent": "cc", "state": "think", "title": "实际会话标题", "name": "h1"}
        self.assertIn("实际会话标题", app.session_label(session))
        self.assertNotIn("h1", app.session_label(session))
        session["title"] = "题" * 100
        self.assertEqual(app.session_label(session).count("题"), 48)


class KeymapUpgradeTests(unittest.TestCase):
    def test_untouched_v3_keymap_is_upgraded_and_edited_one_kept(self):
        source = app.resource_dir() / "hub_keys.json"
        shipped = json.loads(source.read_text(encoding="utf-8"))
        self.assertEqual(shipped["bindings"]["hid:0x14"], "session select")
        old = legacy_keymap(shipped, 3)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hub_keys.json"
            target.write_text(json.dumps(old), encoding="utf-8")
            self.assertTrue(app.upgrade_keymap(target, source))
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["bindings"]["hid:0x14"], "session select")
            self.assertTrue(target.with_name("hub_keys.json.bak-v3").exists())
            edited = dict(old, bindings=dict(old["bindings"], **{"hid:0x08": "slot 4"}))
            target.write_text(json.dumps(edited), encoding="utf-8")
            self.assertFalse(app.upgrade_keymap(target, source))
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), edited)

    def test_v8_default_is_upgraded_with_exact_backup_and_custom_edits_are_kept(self):
        source = app.resource_dir() / "hub_keys.json"
        shipped = json.loads(source.read_text(encoding="utf-8"))
        old = legacy_keymap(shipped, 8)
        old["_instructions"] = ["the original v8 instructions"]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hub_keys.json"
            original = json.dumps(old, ensure_ascii=False, indent=3).encode("utf-8")
            target.write_bytes(original)
            self.assertTrue(app.upgrade_keymap(target, source))
            backup = target.with_name("hub_keys.json.bak-v8")
            self.assertEqual(backup.read_bytes(), original)
            self.assertEqual(json.loads(target.read_bytes()), shipped)
            target.write_bytes(original)
            backup.write_bytes(b"earlier backup")
            self.assertTrue(app.upgrade_keymap(target, source))
            self.assertEqual(backup.read_bytes(), b"earlier backup")
            for field in ("bindings", "hotkey", "v2_emulation", "layers", "custom"):
                with self.subTest(field=field):
                    edited = json.loads(original)
                    if field == "bindings":
                        edited[field]["hid:0x08"] = "slot 6"
                    elif field == "hotkey":
                        edited[field]["F13"] = "slot 6"
                    elif field == "v2_emulation":
                        edited[field]["bindings"]["hid:0x08"] = "slot 6"
                    else:
                        edited[field] = {}
                    raw = json.dumps(edited).encode("utf-8")
                    target.write_bytes(raw)
                    self.assertFalse(app.upgrade_keymap(target, source))
                    self.assertEqual(target.read_bytes(), raw)


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
        self.scheduler = FakeScheduler()
        self.start = app.AutoStart(self.registry, self.command, scheduler=self.scheduler, sid=SID, target=TARGET)

    def test_register_and_unregister_only_agentdeck_value(self):
        self.assertFalse(self.start.enabled())
        self.start.set_enabled(True)
        self.assertTrue(self.start.enabled())
        self.assertNotIn("AgentDeck", self.registry.values)
        self.assertEqual(self.start.snapshot()["mode"], "task")
        self.start.set_enabled(False)
        self.start.set_enabled(False)
        self.assertFalse(self.start.enabled())
        self.assertEqual(self.registry.values, {"OtherApp": "other.exe"})

    def test_stale_autostart_path_is_not_reported_as_current(self):
        self.registry.values["AgentDeck"] = '"D:\\Old folder\\AgentDeck.exe"'
        self.assertFalse(self.start.enabled())
        self.start.set_enabled(True)
        self.assertTrue(self.start.enabled())

    def test_login_registration_uses_background_and_upgrades_legacy_value(self):
        registry = FakeRegistry()
        executable = Path("D:/App folder/AgentDeck.exe")
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(executable)):
            scheduler = FakeScheduler()
            start = app.AutoStart(registry, scheduler=scheduler, sid=SID,
                                  target=(executable.resolve(), "--background", executable.resolve().parent))
            self.assertTrue(start.command.endswith("--background"))
            registry.values["AgentDeck"] = app.launch_command()  # written by an older build
            self.assertTrue(start.enabled())
            self.assertTrue(start.upgrade())
            self.assertNotIn("AgentDeck", registry.values)
            self.assertEqual(start.snapshot()["mode"], "task")
            self.assertFalse(start.upgrade())

    def test_upgrade_accepts_all_current_run_forms_and_verifies_before_delete(self):
        executable = Path("D:/AgentDeck/AgentDeck.exe")
        target = (executable, "--background", executable.parent)
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(executable)):
            for form in ("command", "quoted", "legacy", "quoted_legacy"):
                with self.subTest(form=form):
                    registry, scheduler = FakeRegistry(), FakeScheduler()
                    start = app.AutoStart(registry, scheduler=scheduler, sid=SID, target=target)
                    values = {"command": start.command, "quoted": start.quoted, "legacy": start.legacy,
                              "quoted_legacy": '"%s"' % executable.resolve()}
                    registry.values["AgentDeck"] = values[form]
                    original_delete = registry.DeleteValue

                    def delete(key, name):
                        self.assertTrue(app.task_matches(scheduler.xml, target))
                        self.assertEqual(scheduler.calls[-1], ("query", "AgentDeck"))
                        original_delete(key, name)

                    registry.DeleteValue = delete
                    self.assertTrue(start.upgrade())
                    self.assertNotIn("AgentDeck", registry.values)
                    self.assertEqual(start.snapshot()["mode"], "task")
                    self.assertEqual(sum(c[0] == "create" for c in scheduler.calls), 1)

    def test_upgrade_create_failure_preserves_quoted_run_fallback(self):
        self.registry.values["AgentDeck"] = self.command
        self.scheduler.create_error = OSError("拒绝访问\n详细信息")
        with self.assertLogs(app.log, level="WARNING"):
            self.assertTrue(self.start.upgrade())
        self.assertEqual(self.registry.values["AgentDeck"], self.start.quoted)
        self.assertEqual(self.start.snapshot()["mode"], "registry")
        self.assertIn("拒绝访问", self.start.snapshot()["reason"])
        self.assertNotIn("\n", self.start.snapshot()["reason"])
        self.assertIn("用注册表方式（计划任务不可用：", self.start.describe())
        reason = self.start.snapshot()["reason"]
        self.start.refresh()
        self.assertEqual(self.start.snapshot()["reason"], reason)

    def test_upgrade_retries_after_prior_create_denial(self):
        self.registry.values["AgentDeck"] = self.command
        self.scheduler.create_error = OSError("拒绝访问")
        with self.assertLogs(app.log, level="WARNING"):
            self.assertTrue(self.start.upgrade())
        self.start.refresh()
        self.assertEqual(self.start.snapshot()["mode"], "registry")
        self.assertIn("拒绝访问", self.start.snapshot()["error"])
        self.assertEqual(self.registry.values["AgentDeck"], self.start.quoted)
        self.scheduler.create_error = None
        self.assertTrue(self.start.upgrade())
        self.assertEqual(self.start.snapshot()["mode"], "task")
        self.assertIsNone(self.start.snapshot()["error"])
        self.assertIsNone(self.start.snapshot()["reason"])
        self.assertNotIn("AgentDeck", self.registry.values)
        self.assertEqual(sum(c[0] == "create" for c in self.scheduler.calls), 2)

    def test_upgrade_readback_mismatch_preserves_run(self):
        self.registry.values["AgentDeck"] = self.command
        self.scheduler.readback = app.task_xml((Path("D:/Other.exe"), "", Path("D:/")), SID)
        with self.assertLogs(app.log, level="WARNING"):
            self.assertTrue(self.start.upgrade())
        self.assertEqual(self.registry.values["AgentDeck"], self.start.quoted)
        self.assertEqual(self.start.snapshot()["mode"], "registry")
        self.assertTrue(self.start.snapshot()["reason"])

    def test_upgrade_respects_off_stale_run_and_foreign_or_disabled_task(self):
        for value in (None, '"D:\\Old\\AgentDeck.exe"'):
            for xml in (None, app.task_xml((Path("D:/Other.exe"), "", Path("D:/")), SID),
                        app.task_xml(TARGET, SID).replace("<Enabled>true</Enabled>", "<Enabled>false</Enabled>")):
                with self.subTest(value=value, xml=xml):
                    registry, scheduler = FakeRegistry(), FakeScheduler(xml)
                    if value is not None:
                        registry.values["AgentDeck"] = value
                    start = app.AutoStart(registry, self.command, scheduler=scheduler, sid=SID, target=TARGET)
                    self.assertFalse(start.upgrade())
                    self.assertEqual(registry.values.get("AgentDeck"), value)
                    self.assertFalse(any(c[0] == "create" for c in scheduler.calls))
        for xml in (app.task_xml((Path("D:/Other.exe"), "", Path("D:/")), SID),
                    app.task_xml(TARGET, SID).replace("<Enabled>true</Enabled>", "<Enabled>false</Enabled>")):
            self.registry.values["AgentDeck"] = self.command
            self.scheduler.xml = xml
            self.assertFalse(self.start.upgrade())
            self.assertEqual(self.registry.values["AgentDeck"], self.command)
            self.assertFalse(any(c[0] == "create" for c in self.scheduler.calls))

    def test_matching_task_removes_only_owned_run_without_create(self):
        self.scheduler.xml = app.task_xml(TARGET, SID)
        self.registry.values["AgentDeck"] = self.command
        self.start.upgrade()
        self.assertEqual(self.registry.values, {"OtherApp": "other.exe"})
        self.assertEqual(self.start.snapshot()["mode"], "task")
        self.assertFalse(any(c[0] == "create" for c in self.scheduler.calls))

    def test_matching_task_preserves_stale_run_path(self):
        self.scheduler.xml = app.task_xml(TARGET, SID)
        self.registry.values["AgentDeck"] = '"D:\\Old\\AgentDeck.exe"'
        self.start.upgrade()
        self.assertEqual(self.registry.values["AgentDeck"], '"D:\\Old\\AgentDeck.exe"')
        self.assertEqual(self.start.snapshot()["mode"], "task")
        self.assertFalse(any(c[0] == "create" for c in self.scheduler.calls))

    def test_upgrade_query_failure_does_not_treat_unreadable_task_as_missing(self):
        self.registry.values["AgentDeck"] = self.command
        self.scheduler.query_error = subprocess.TimeoutExpired("fake schtasks", 15)
        self.assertFalse(self.start.upgrade())
        self.assertEqual(self.registry.values["AgentDeck"], self.command)
        self.assertFalse(any(c[0] == "create" for c in self.scheduler.calls))
        self.assertTrue(self.start.snapshot()["reason"])

    def test_refresh_timeout_is_cached_and_enabled_does_not_repeat_io(self):
        self.scheduler.query_error = subprocess.TimeoutExpired("fake schtasks", 15)
        self.registry.values["AgentDeck"] = self.command
        self.start.refresh()
        self.assertEqual(self.start.snapshot()["mode"], "registry")
        self.assertTrue(self.start.snapshot()["checked"])
        self.assertIn("15", self.start.snapshot()["reason"])
        calls = list(self.scheduler.calls)
        self.assertTrue(self.start.enabled())
        self.start.snapshot()
        self.start.describe()
        self.assertEqual(self.scheduler.calls, calls)

    def test_snapshot_and_describe_do_not_wait_for_scheduler_lock(self):
        entered, release, read = threading.Event(), threading.Event(), threading.Event()
        results = []

        def query(name):
            entered.set()
            if not release.wait(3):
                raise AssertionError("test did not release scheduler")
            return None

        def cached():
            results.extend((self.start.snapshot(), self.start.describe()))
            read.set()

        self.scheduler.query = query
        operation = threading.Thread(target=self.start.refresh)
        reader = threading.Thread(target=cached)
        operation.start()
        try:
            self.assertTrue(entered.wait(1))
            reader.start()
            self.assertTrue(read.wait(1), "cached UI state waited for a scheduler operation")
            self.assertFalse(results[0]["checked"])
            self.assertEqual(results[1], "检查中…")
        finally:
            release.set()
            operation.join(3)
            if reader.ident is not None:
                reader.join(3)
        self.assertFalse(operation.is_alive())
        self.assertFalse(reader.is_alive())

    def test_sid_is_computed_only_when_building_task(self):
        start = app.AutoStart(self.registry, self.command, scheduler=self.scheduler, target=TARGET)
        with patch.object(app, "current_user_sid", side_effect=AssertionError("unexpected SID lookup")):
            start.refresh()
            self.assertFalse(start.upgrade())
        with patch.object(app, "current_user_sid", return_value=SID) as lookup:
            start.set_enabled(True)
        lookup.assert_called_once_with()

    def test_set_enabled_falls_back_and_propagates_registry_failure(self):
        self.scheduler.create_error = OSError("拒绝访问")
        self.start.set_enabled(True)
        self.assertEqual(self.registry.values["AgentDeck"], self.start.quoted)
        self.assertEqual(self.start.snapshot()["mode"], "registry")
        self.registry.SetValueEx = Mock(side_effect=OSError("registry denied"))
        with self.assertRaisesRegex(OSError, "registry denied"):
            self.start.set_enabled(True)

    def test_disable_removes_task_and_run_and_reports_surviving_task(self):
        self.scheduler.xml = app.task_xml(TARGET, SID)
        self.registry.values["AgentDeck"] = self.command
        self.start.set_enabled(False)
        self.assertIsNone(self.scheduler.xml)
        self.assertNotIn("AgentDeck", self.registry.values)
        self.assertIsNone(self.start.snapshot()["mode"])
        self.scheduler.xml = app.task_xml(TARGET, SID)
        self.scheduler.keep_on_delete = True
        with self.assertRaisesRegex(RuntimeError, "无法删除计划任务 AgentDeck"):
            self.start.set_enabled(False)

    def test_disable_delete_failure_still_removes_run_and_raises(self):
        self.scheduler.xml = app.task_xml(TARGET, SID)
        self.scheduler.delete_error = OSError("拒绝访问")
        self.registry.values["AgentDeck"] = self.command
        with self.assertRaisesRegex(RuntimeError, "无法删除计划任务 AgentDeck：拒绝访问"):
            self.start.set_enabled(False)
        self.assertNotIn("AgentDeck", self.registry.values)
        self.assertIsNotNone(self.scheduler.xml)
        self.assertIn("拒绝访问", self.start.snapshot()["error"])

    def test_frozen_launch_command_quotes_exe_without_python(self):
        executable = Path("D:/App folder/AgentDeck.exe")
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(executable)):
            self.assertEqual(app.launch_command(), subprocess.list2cmdline([str(executable.resolve())]))
            self.assertNotIn("python", app.launch_command().lower())

    def test_source_launch_command_uses_pythonw_and_absolute_script(self):
        with patch.object(sys, "frozen", False, create=True), patch.object(sys, "executable", "D:/Conda folder/python.exe"):
            self.assertEqual(app.launch_command(), subprocess.list2cmdline(
                ["D:\\Conda folder\\pythonw.exe", str(Path(app.__file__).resolve())]))

    def test_launch_target_separates_command_arguments_and_working_directory(self):
        executable = Path("D:/App folder/AgentDeck.exe").resolve()
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(executable)):
            self.assertEqual(app.launch_target(True), (executable, "--background", executable.parent))
            self.assertEqual(app.launch_target(), (executable, "", executable.parent))
        script = Path(app.__file__).resolve()
        with patch.object(sys, "frozen", False, create=True), patch.object(sys, "executable", "D:/Conda folder/python.exe"):
            self.assertEqual(app.launch_target(True), (Path("D:/Conda folder/pythonw.exe"),
                             subprocess.list2cmdline([str(script), "--background"]), script.parent))


class SchedulerTests(unittest.TestCase):
    def test_module_guards_reject_uninjected_os_adapters(self):
        with self.assertRaisesRegex(AssertionError, "real schtasks subprocess"):
            RealSchTasks().query("AgentDeck")
        with self.assertRaisesRegex(AssertionError, "real schtasks query"):
            app.SchTasks().query("AgentDeck")
        with self.assertRaisesRegex(AssertionError, "real winreg access"):
            sys.modules["winreg"].OpenKey

    def test_xml_has_per_user_interactive_trigger_normal_priority_and_all_settings(self):
        target = (Path("D:/App & <tools>/AgentDeck.exe"), '--background "a&<b"', Path("D:/App & <tools>"))
        xml = app.task_xml(target, SID)
        self.assertIn('encoding="UTF-16"', xml)
        self.assertIn("&amp;", xml)
        self.assertIn("&lt;", xml)
        root = ET.fromstring(xml[xml.index("<Task"):])
        self.assertEqual(root.tag, "{%s}Task" % NS["t"])
        self.assertEqual(root.attrib["version"], "1.2")
        expected = {
            "RegistrationInfo/Author": "AgentDeck",
            "RegistrationInfo/Description": "AgentDeck：登录后在后台启动托盘和浮窗",
            "Triggers/LogonTrigger/Enabled": "true", "Triggers/LogonTrigger/UserId": SID,
            "Triggers/LogonTrigger/Delay": "PT10S", "Principals/Principal/UserId": SID,
            "Principals/Principal/LogonType": "InteractiveToken", "Principals/Principal/RunLevel": "LeastPrivilege",
            "Actions/Exec/Command": str(target[0]), "Actions/Exec/Arguments": target[1],
            "Actions/Exec/WorkingDirectory": str(target[2]),
        }
        settings = {"MultipleInstancesPolicy": "IgnoreNew", "DisallowStartIfOnBatteries": "false",
                    "StopIfGoingOnBatteries": "false", "AllowHardTerminate": "true", "StartWhenAvailable": "false",
                    "RunOnlyIfNetworkAvailable": "false", "IdleSettings/StopOnIdleEnd": "false",
                    "IdleSettings/RestartOnIdle": "false", "AllowStartOnDemand": "true", "Enabled": "true",
                    "Hidden": "false", "RunOnlyIfIdle": "false", "WakeToRun": "false",
                    "ExecutionTimeLimit": "PT0S", "Priority": "4"}
        expected.update({"Settings/" + key: value for key, value in settings.items()})
        for path, value in expected.items():
            with self.subTest(path=path):
                self.assertEqual(root.findtext("/".join("t:" + part for part in path.split("/")), namespaces=NS), value)
        self.assertEqual(root.find("t:Principals/t:Principal", NS).attrib["id"], "Author")
        self.assertEqual(root.find("t:Actions", NS).attrib["Context"], "Author")
        self.assertIsNone(root.find("t:RegistrationInfo/t:URI", NS))

    def test_create_writes_utf16_bom_and_always_removes_temporary_xml(self):
        xml = app.task_xml(TARGET, SID)
        for failing in (False, True):
            paths = []

            def run(argv, **kwargs):
                self.assertEqual(Path(argv[0]).name.lower(), "schtasks.exe")
                self.assertEqual(argv[1:3], ["/Create", "/XML"])
                self.assertEqual(argv[4:], ["/TN", "AgentDeck", "/F"])
                path = Path(argv[3])
                paths.append(path)
                self.assertEqual(path.read_bytes(), codecs.BOM_UTF16_LE + xml.encode("utf-16-le"))
                self.assertTrue(kwargs["creationflags"] & 0x08000000)
                self.assertTrue(kwargs["capture_output"])
                self.assertEqual(kwargs["timeout"], 15)
                return SimpleNamespace(returncode=int(failing), stdout=b"", stderr="拒绝访问".encode("cp936"))

            with self.subTest(failing=failing), patch.object(app, "oem_encoding", return_value="cp936"), patch.object(
                    app.subprocess, "run", side_effect=run):
                if failing:
                    with self.assertRaisesRegex((OSError, RuntimeError), "拒绝访问"):
                        RealSchTasks().create("AgentDeck", xml)
                else:
                    RealSchTasks().create("AgentDeck", xml)
            self.assertEqual(len(paths), 1)
            self.assertFalse(paths[0].exists())

    def test_query_decodes_oem_bytes_missing_and_timeout(self):
        xml = '<?xml version="1.0" encoding="UTF-16"?><Task>café</Task>'
        scheduler = RealSchTasks()
        with patch.object(app, "oem_encoding", return_value="cp437"), patch.object(app.subprocess, "run", return_value=
                SimpleNamespace(returncode=0, stdout=xml.encode("cp437"), stderr=b"")) as run:
            self.assertEqual(scheduler.query("AgentDeck"), xml)
        self.assertEqual(Path(run.call_args.args[0][0]).name.lower(), "schtasks.exe")
        self.assertEqual(run.call_args.args[0][1:], ["/Query", "/TN", "AgentDeck", "/XML", "ONE"])
        self.assertTrue(run.call_args.kwargs["creationflags"] & 0x08000000)
        self.assertEqual(run.call_args.kwargs["timeout"], 15)
        with patch.object(app.subprocess, "run", return_value=SimpleNamespace(
                returncode=1, stdout=b"", stderr=b"localized missing task")):
            self.assertIsNone(scheduler.query("AgentDeck"))
        with patch.object(app.subprocess, "run", side_effect=subprocess.TimeoutExpired("fake", 15)):
            with self.assertRaises((subprocess.TimeoutExpired, OSError, RuntimeError)):
                scheduler.query("AgentDeck")

    def test_create_timeout_still_removes_temporary_file(self):
        paths = []

        def timeout(argv, **kwargs):
            paths.append(Path(argv[3]))
            self.assertTrue(paths[-1].exists())
            raise subprocess.TimeoutExpired("fake schtasks", 15)

        with patch.object(app.subprocess, "run", side_effect=timeout):
            with self.assertRaises((subprocess.TimeoutExpired, OSError, RuntimeError)):
                RealSchTasks().create("AgentDeck", app.task_xml(TARGET, SID))
        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].exists())

    def test_delete_checks_presence_after_nonzero_without_parsing_localized_error(self):
        scheduler = RealSchTasks()
        missing = SimpleNamespace(returncode=1, stdout=b"", stderr=b"localized missing task")
        with patch.object(app.subprocess, "run", return_value=missing) as run:
            scheduler.delete("AgentDeck")
        self.assertEqual(run.call_args_list[0].args[0][1:], ["/Delete", "/TN", "AgentDeck", "/F"])
        self.assertEqual(run.call_args_list[1].args[0][1:], ["/Query", "/TN", "AgentDeck", "/XML", "ONE"])
        with patch.object(app.subprocess, "run", side_effect=[missing, SimpleNamespace(
                returncode=0, stdout=app.task_xml(TARGET, SID).encode("cp437", "replace"), stderr=b"")]):
            with self.assertRaises((OSError, RuntimeError)):
                scheduler.delete("AgentDeck")

    def test_task_matches_exported_defaults_account_name_and_oem_path(self):
        target = (Path("D:/中文/café/AgentDeck.exe"), "--background", Path("D:/中文/café"))
        xml = ('<?xml version="1.0" encoding="UTF-16"?><Task xmlns="%s" version="1.2">'
               '<Principals><Principal id="Author"><UserId>%s</UserId><LogonType>InteractiveToken</LogonType>'
               '</Principal></Principals><Triggers><LogonTrigger><Delay>PT1M</Delay>'
               '<UserId>COMPUTER\\user</UserId></LogonTrigger></Triggers><Actions Context="Author"><Exec>'
               '<Command>"%s"</Command><Arguments> --background </Arguments></Exec></Actions></Task>'
               % (NS["t"], SID, target[0]))
        with patch.object(app, "oem_encoding", return_value="cp437"):
            exported = xml.encode("cp437", "replace").decode("cp437")
            self.assertTrue(app.task_matches(exported, target))
            for changed in (exported.replace("AgentDeck.exe", "Other.exe"),
                            exported.replace(" --background ", " --other "),
                            exported.replace("<Actions", "<Settings><Enabled>false</Enabled></Settings><Actions"),
                            exported.replace("LogonTrigger", "TimeTrigger"),
                            exported.replace("<Delay>", "<Enabled>false</Enabled><Delay>"), "<bad xml"):
                with self.subTest(xml=changed):
                    self.assertFalse(app.task_matches(changed, target))
        no_args = app.task_xml((TARGET[0], "", TARGET[2]), SID).replace("<Arguments></Arguments>", "")
        self.assertTrue(app.task_matches(no_args, (TARGET[0], "", TARGET[2])))


class HomeGuardTests(unittest.TestCase):
    def test_simulated_home_never_touches_scheduler_or_registry(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, "home", return_value=Path(directory) / "real"):
            start = app.AutoStart(ExplodingOS(), scheduler=ExplodingScheduler(), target=TARGET, sid=SID, home=directory)
            self.assertIn("模拟环境", start.describe())
            for method, args in ((start.upgrade, ()), (start.refresh, ()), (start.set_enabled, (True,)),
                                 (start.set_enabled, (False,))):
                with self.assertLogs(app.log, level="INFO") as messages:
                    self.assertFalse(method(*args))
                self.assertEqual(len(messages.output), 1)
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, "home", side_effect=OSError("no home")):
            self.assertTrue(app.AutoStart(ExplodingOS(), scheduler=ExplodingScheduler(), target=TARGET,
                                          sid=SID, home=directory).blocked)

    def test_init_simulation_skips_autostart_but_installs_hooks(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, "home", return_value=Path(directory) / "real"):
            result = app.init_all(directory)
            self.assertEqual(result["autostart"], "skipped")
            self.assertTrue(hub_install.global_status(home=Path(directory))["enabled"])
            self.assertTrue(app.Preferences(directory).values["initialized"])

    def test_uninstall_with_simulated_home_uses_exploding_defaults_safely(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, "home", return_value=Path(directory) / "real"), patch.object(
                app, "SchTasks", ExplodingScheduler), patch.dict(sys.modules, {"winreg": ExplodingOS()}), patch.object(
                sys, "stdout", io.StringIO()):
            self.assertEqual(app.main(["--home", directory, "--uninstall"]), 0)


class InitializationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.registry = FakeRegistry()
        self.scheduler = FakeScheduler()
        self.start = app.AutoStart(self.registry, "AgentDeck.exe", scheduler=self.scheduler, sid=SID, target=TARGET)
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
        self.assertEqual(self.registry.writes, [])
        self.assertEqual(sum(c[0] == "create" for c in self.scheduler.calls), 1)
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
        failing.blocked = None
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
        self.scheduler = FakeScheduler()
        self.application = app.TrayApplication(self.engine, commands=self.queue, prefs=self.prefs,
                                              keys_path=app.resource_dir() / "hub_keys.json",
                                              autostart=app.AutoStart(self.registry, "AgentDeck.exe", scheduler=self.scheduler,
                                                                      sid=SID, target=TARGET),
                                              overlay=self.overlay, registry=TrayRegistry())
        self.application.message = Mock()

    def test_construction_performs_no_scheduler_call_and_startup_upgrades(self):
        self.assertEqual(self.scheduler.calls, [])
        self.assertFalse(self.application.autostart_enabled)
        self.registry.values["AgentDeck"] = "AgentDeck.exe"
        self.application._autostart_startup()
        self.assertTrue(any(c[0] == "create" for c in self.scheduler.calls))
        self.assertTrue(self.application.autostart_enabled)
        self.assertTrue(self.application.autostart.snapshot()["checked"])

    def test_status_autostart_rows_use_cached_state_only(self):
        start = self.application.autostart

        def row():
            return next(row for row in self.application.status_model()["rows"] if row[0] == "开机自启")

        self.assertEqual(row()[1:4], ("检查中…", None, None))
        self.assertEqual(self.scheduler.calls, [])
        self.scheduler.xml = app.task_xml(TARGET, SID)
        start.refresh()
        calls = list(self.scheduler.calls)
        self.assertEqual(row()[1:4], ("✓ 已开启（计划任务）", True, None))
        self.assertEqual(self.scheduler.calls, calls)
        self.scheduler.xml = None
        self.scheduler.create_error = OSError("拒绝访问")
        start.set_enabled(True)
        self.assertIn("用注册表方式（计划任务不可用：拒绝访问）", row()[1])
        self.assertTrue(row()[2])
        start.set_enabled(False)
        self.assertEqual(row()[1:4], ("未开启", False, "开启"))
        blocked = app.AutoStart(ExplodingOS(), scheduler=ExplodingScheduler(), sid=SID, target=TARGET, home=self.home)
        self.application.autostart = blocked
        self.assertEqual(row()[1:4], (blocked.blocked, None, None))
        hub_install.apply("install", home=self.home, output=io.StringIO())
        self.prefs.values["initialized"] = True
        self.assertTrue(self.application.status_model()["complete"])

    def test_macro_keyboard_row_reports_connection_and_driver_action(self):
        for reader, text, ok, button in (("usb", "✓ 已连接（USB 直读）", True, None),
                ("raw", "已连接（Raw Input：按键会同时打字）", False, "装驱动说明"),
                ("absent", "未连接：批准交给应用自己的弹窗", False, None), (None, "启动中…", None, None)):
            with self.subTest(reader=reader):
                self.application.state = {"input_reader": reader}
                rows = {row[0]: row for row in self.application.status_model()["rows"]}
                self.assertNotIn("读键方式", rows)
                self.assertEqual(rows["宏键盘"][1:4], (text, ok, button))
                if reader == "raw":
                    self.assertEqual(rows["宏键盘"][4], "driver")
        # /state hold_active (hold always) means an absent deck still holds requests.
        self.application.state = {"input_reader": "absent", "deck_connected": False,
                                  "hold_mode": "always", "hold_active": True}
        rows = {row[0]: row for row in self.application.status_model()["rows"]}
        self.assertEqual(rows["宏键盘"][1:4], ("未连接：当前设为一直等宏键盘，请求会等到超时", False, None))
        self.application.state = {"input_reader": "absent", "deck_connected": False,
                                  "hold_mode": "auto", "hold_active": False}
        rows = {row[0]: row for row in self.application.status_model()["rows"]}
        self.assertEqual(rows["宏键盘"][1], "未连接：批准交给应用自己的弹窗")

    def test_live_autostart_work_is_daemon_thread_and_notifies_via_dispatch(self):
        self.application._background_enabled = True
        started = []

        def thread(**kwargs):
            started.append(kwargs)
            return SimpleNamespace(start=lambda: None)

        work = Mock(side_effect=RuntimeError("fake startup failure"))
        with patch.object(app.threading, "Thread", side_effect=thread):
            self.application._autostart_work(work, "test")
        self.assertEqual(started[0]["name"], "AgentDeck autostart")
        self.assertTrue(started[0]["daemon"])
        work.assert_not_called()
        with self.assertLogs(app.log, level="ERROR"):
            started[0]["target"]()
        self.application.message.assert_not_called()
        action, payload = self.queue.get_nowait()
        self.assertEqual((action, payload), ("notice", ("开机自启操作失败", "fake startup failure")))
        self.application.dispatch(action, payload)
        self.application.message.assert_called_once_with("开机自启操作失败", "fake startup failure", error=True)

    def test_concurrent_live_autostart_toggles_finish_disabled(self):
        self.application._background_enabled = True
        creating, release, second_waiting = threading.Event(), threading.Event(), threading.Event()
        threads = []
        thread_type = threading.Thread
        original_create = self.scheduler.create
        operation_lock = self.application._autostart_lock

        class ObservedLock:
            """Observe both workers reaching the real serialization boundary."""
            attempts = 0

            def __enter__(self):
                self.attempts += 1
                if self.attempts == 2:
                    second_waiting.set()
                operation_lock.acquire()

            def __exit__(self, *args):
                operation_lock.release()

        def create(name, xml_text):
            creating.set()
            if not release.wait(3):
                raise AssertionError("test did not release task creation")
            original_create(name, xml_text)

        def thread(**kwargs):
            instance = thread_type(**kwargs)
            threads.append(instance)
            return instance

        self.application._autostart_lock = ObservedLock()
        self.scheduler.create = create
        try:
            with patch.object(app.threading, "Thread", side_effect=thread):
                self.application.dispatch("autostart")
                self.assertTrue(creating.wait(1))
                self.application.dispatch("autostart")
                self.assertTrue(second_waiting.wait(1))
                self.assertFalse(self.application.autostart_enabled)
        finally:
            release.set()
            for instance in threads:
                instance.join(3)
        self.assertEqual(len(threads), 2)
        self.assertTrue(all(t.daemon and t.name == "AgentDeck autostart" for t in threads))
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(sum(c[0] == "create" for c in self.scheduler.calls), 1)
        self.assertEqual(sum(c[0] == "delete" for c in self.scheduler.calls), 1)
        self.assertIsNone(self.scheduler.xml)
        self.assertFalse(self.application.autostart_enabled)
        self.assertNotIn("AgentDeck", self.registry.values)
        self.assertTrue(self.queue.empty())

    def test_synchronous_autostart_work_reraises_failure(self):
        with self.assertLogs(app.log, level="ERROR"), self.assertRaisesRegex(RuntimeError, "fake failure"):
            self.application._autostart_work(Mock(side_effect=RuntimeError("fake failure")), "test")
        self.assertTrue(self.queue.empty())

    def test_autostart_actions_all_use_helper(self):
        with patch.object(self.application, "_autostart_work") as work:
            for action in ("hooks", "start", "autostart"):
                with self.subTest(action=action):
                    self.application.status_action(action)
                    self.assertEqual(work.call_args.args[1], action)
            self.application.dispatch("autostart")
            self.assertEqual(work.call_args.args[1], "autostart")

    def test_menu_callbacks_enqueue_without_native_actions(self):
        menu = self.application.menu(SimpleNamespace(Menu=Menu, MenuItem=MenuItem))
        rows = [r for r in menu.children() if isinstance(r, MenuItem)]
        by_name = {r.text: r for r in rows if isinstance(r.text, str)}
        for label, action in (("管理面板", "panel"), ("诊断", "diagnostics"), ("所有项目启用", "global"),
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

    def test_voice_settings_offers_and_persists_single_tap(self):
        desktop = self.voice_desktop()
        tk, commands, bindings, mode = self.build_voice_settings()
        choices = {call.kwargs["value"]: call.kwargs["text"]
                   for call in tk.Radiobutton.call_args_list}
        self.assertEqual(set(choices), {"hold", "toggle", "tap"})
        self.assertIn("单点", choices["tap"])
        event = SimpleNamespace(keycode=165, keysym="Alt_R")
        bindings["<KeyPress>"](event)
        bindings["<KeyRelease>"](event)
        mode.value = "tap"
        commands["保存"]()
        shortcut = {"key_codes": [165], "modifiers": [], "mode": "tap"}
        self.assertEqual(app.hub.load_json(app.data_dir(self.home) / "config.json")["dictation_shortcut"],
                         shortcut)
        self.assertEqual(desktop.dictation_shortcut, shortcut)
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
        with patch.object(self.application, "show_status") as status:
            self.application.dispatch("show")  # a second launch: overlay + status window
        status.assert_called_once_with()
        self.overlay.show.assert_called_once()
        self.application.dispatch("toggle")
        self.overlay.hide.assert_called_once()
        self.overlay.hidden = True
        self.application.dispatch("toggle")
        self.assertEqual(self.overlay.show.call_count, 2)

    def test_select_and_next_wait_use_existing_hub_action(self):
        self.engine.state.return_value = {"sessions": [{"agent": "cc", "session_id": "abcdef-full", "slot": 3}]}
        self.application.dispatch("select", ("cc", "abcdef-full"))
        self.engine.action.assert_called_once_with({"action": "slot 3", "session": ["cc", "abcdef-full"]})
        self.application.dispatch("next_wait")
        self.engine.action.assert_called_with({"action": "next_wait"})

    def test_stale_or_same_prefix_session_never_focuses_recycled_slot(self):
        self.engine.state.return_value = {"sessions": [{"agent": "cc", "session_id": "abcdef-new", "slot": 1}]}
        with self.assertRaisesRegex(ValueError, "会话已结束"):
            self.application.dispatch("select", ("cc", "abcdef-old"))
        self.engine.action.assert_not_called()

    def test_selection_does_not_hold_hub_lock_during_focus(self):
        # H5: window focus can take seconds; hook events must not wait for it.
        self.engine.state.return_value = {"sessions": [{"agent": "cc", "session_id": "original", "slot": 2}]}
        held = []

        def action(payload):
            other = []

            def probe():
                acquired = self.engine.lock.acquire(timeout=0.2)
                other.append(acquired)
                if acquired:
                    self.engine.lock.release()

            worker = threading.Thread(target=probe)
            worker.start()
            worker.join(1)
            held.append(other != [True])
            self.assertEqual(payload, {"action": "slot 2", "session": ["cc", "original"]})

        self.engine.action.side_effect = action
        self.application.dispatch("select", ("cc", "original"))
        self.assertEqual(held, [False])

    def test_recycled_slot_is_rejected_by_hub_under_its_lock(self):
        engine = app.hub.Hub(sender=lambda *args, **kwargs: None, desktop=Mock(voice_active=False),
                             lcd_enabled=False, home=self.home, audit=Mock(), prompts={})
        engine.event("cc", {"hook_event_name": "SessionStart", "session_id": "new-session", "cwd": "D:/p"})
        with self.assertRaises(app.hub.HubError) as caught:
            engine.action({"action": "slot 1", "session": ["cc", "old-session"]})
        self.assertEqual(caught.exception.status, 409)
        engine.desktop.focus.assert_not_called()
        self.assertEqual(engine.action({"action": "slot 1", "session": ["cc", "new-session"]})["status"],
                         "selected")

    def test_autostart_menu_toggles_registration_and_checkmark(self):
        menu = self.application.menu(SimpleNamespace(Menu=Menu, MenuItem=MenuItem))
        row = next(r for r in menu.children() if isinstance(r, MenuItem) and r.text == "开机自启")
        self.assertFalse(row.options["checked"](row))
        self.application.dispatch("autostart")
        self.assertTrue(self.application.autostart_enabled)
        self.assertTrue(row.options["checked"](row))
        self.assertTrue(app.task_matches(self.scheduler.xml, TARGET))
        self.assertNotIn("AgentDeck", self.registry.values)
        self.application.dispatch("autostart")
        self.assertFalse(self.application.autostart_enabled)
        self.assertFalse(row.options["checked"](row))
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

    def build_status(self):
        tk = MagicMock()
        buttons = {}

        def make_button(parent, text, command, kind="primary", **kwargs):
            buttons[text] = command
            return MagicMock()

        with patch.dict(sys.modules, {"tkinter": tk}), patch.object(app.theme, "label", return_value=MagicMock()), \
                patch.object(app.theme, "button", side_effect=make_button), patch.object(
                app.theme, "style_window", side_effect=lambda window, title, **kwargs: window), patch.object(app.theme, "center"):
            window = self.application.show_status()
        return tk, window, buttons

    def test_manual_launch_opens_status_and_login_launch_stays_silent(self):
        for background, initialized, expected in ((False, True, 1), (True, True, 0), (True, False, 1)):
            with self.subTest(background=background, initialized=initialized):
                self.application.background = background
                self.prefs.values["initialized"] = initialized
                with patch.object(self.application, "show_status") as status:
                    self.application.startup()
                self.assertEqual(status.call_count, expected)

    def test_status_model_explains_setup_reader_and_tray(self):
        self.application.autostart.refresh()
        self.application.state = {"sessions": [{"slot": 1}], "input_reader": "raw"}
        model = self.application.status_model()
        rows = {row[0]: row for row in model["rows"]}
        self.assertFalse(model["complete"])
        self.assertEqual(rows["钩子"][1:4], ("未启用", False, "修复"))
        self.assertEqual(rows["开机自启"][3], "开启")
        self.assertIn("按键会同时打字", rows["宏键盘"][1])
        self.assertEqual(rows["宏键盘"][3], "装驱动说明")
        self.assertIn("右下角 ^", rows["托盘图标"][1])
        self.assertIn("重开", rows["会话"][1])
        self.application.state = {"sessions": [], "input_reader": "usb"}
        self.assertEqual({row[0]: row for row in self.application.status_model()["rows"]}["宏键盘"][1:4],
                         ("✓ 已连接（USB 直读）", True, None))

    def test_status_window_start_button_initializes_and_has_done_button(self):
        tk, window, buttons = self.build_status()
        self.assertIn("开始使用", buttons)
        self.assertIn("完成", buttons)
        # Raised above the topmost overlay, then released.
        window.lift.assert_called_once_with()
        window.attributes.assert_any_call("-topmost", True)
        window.focus_force.assert_called_once_with()
        with patch.dict(sys.modules, {"tkinter": tk}), patch.object(app.theme, "label", return_value=MagicMock()), \
                patch.object(app.theme, "button", return_value=MagicMock()), patch.object(
                app.theme, "style_window", side_effect=lambda window, title, **kwargs: window), patch.object(app.theme, "center"):
            buttons["开始使用"]()
        self.assertTrue(hub_install.global_status(home=self.home)["enabled"])
        self.assertTrue(self.application.autostart_enabled)
        self.assertTrue(app.Preferences(self.home).values["initialized"])
        self.assertTrue(self.application.status_model()["complete"])
        buttons["完成"]()
        window.destroy.assert_called()

    def test_status_window_refreshes_sessions_and_reader_while_open(self):
        """Acceptance 2026-11-19: opened at startup with an empty state, the window kept
        '会话 0 个' / '宏键盘 启动中…' forever and never offered the driver guide."""
        texts, created, buttons = [], [], {}

        def make_label(parent, text="", **kwargs):
            widget = MagicMock()
            texts.append(text)
            created.append(widget)
            widget.configure.side_effect = lambda **kw: texts.append(kw.get("text", ""))
            return widget

        def make_button(parent, text, command, kind="primary", **kwargs):
            buttons[text] = command
            return MagicMock()

        self.application.state = {}
        with patch.dict(sys.modules, {"tkinter": MagicMock()}), patch.object(app.theme, "label", side_effect=make_label), \
                patch.object(app.theme, "button", side_effect=make_button), patch.object(
                app.theme, "style_window", side_effect=lambda window, title, **kwargs: window), patch.object(app.theme, "center"):
            window = self.application.show_status()
            joined = " ".join(texts)
            self.assertIn("0 个", joined)
            self.assertIn("启动中", joined)
            self.assertNotIn("装驱动说明", buttons)
            after = self.overlay.root.after
            self.assertEqual(after.call_args.args[0], app.STATUS_REFRESH_MS)
            refresh = after.call_args.args[1]

            # The Hub's first snapshot arrives after the window opened.
            mark = len(texts)
            self.application.state = {"sessions": [{"slot": 1}, {"slot": 2}], "input_reader": "raw"}
            refresh()
            joined = " ".join(texts[mark:])
            self.assertIn("2 个", joined)
            self.assertIn("按键会同时打字", joined)
            self.assertIn("装驱动说明", buttons)
            self.assertIs(self.application.status_window, window)
            self.assertEqual(after.call_args.args, (app.STATUS_REFRESH_MS, refresh))

            # A value-only change edits labels in place instead of rebuilding the window.
            mark, widgets = len(texts), len(created)
            self.application.state = {"sessions": [{"slot": 1}, {"slot": 2}, {"slot": 3}], "input_reader": "raw"}
            refresh()
            self.assertEqual(len(created), widgets)
            self.assertIn("3 个", " ".join(texts[mark:]))

            # Unchanged state touches nothing.
            mark = len(texts)
            refresh()
            self.assertEqual(texts[mark:], [])

            # Closed: the timer chain ends.
            buttons["完成"]()
            calls = after.call_count
            refresh()
            self.assertEqual(after.call_count, calls)
            self.assertIsNone(self.application.status_window)

    def test_closing_status_without_start_changes_nothing(self):
        tk, window, buttons = self.build_status()
        buttons["完成"]()
        self.assertNotIn("initialized", app.Preferences(self.home).values)
        self.assertEqual(self.registry.writes, [])
        self.assertFalse(hub_install.global_status(home=self.home)["enabled"])

    def test_tray_hint_only_when_icon_is_hidden(self):
        self.application.icon = Mock()
        executable = str(Path(sys.executable))
        self.application.registry = TrayRegistry({"111": {"ExecutablePath": executable}})
        self.assertTrue(self.application.tray_hint())
        self.application.icon.notify.assert_called_once_with(app.TRAY_HINT, "AgentDeck")
        self.application.icon.reset_mock()
        self.application.registry = TrayRegistry({"111": {"ExecutablePath": executable, "IsPromoted": 1}})
        self.assertFalse(self.application.tray_hint())
        self.application.icon.notify.assert_not_called()

    def test_promote_writes_only_this_programs_record(self):
        registry = TrayRegistry({"1": {"ExecutablePath": "C:/Other/other.exe"},
                                 "2": {"ExecutablePath": sys.executable}})
        self.assertTrue(app.promote_tray_icon(registry))
        self.assertEqual(registry.writes, [(app.NOTIFY_KEY + "\\2", "IsPromoted", 4, 1)])
        self.assertEqual(app.tray_icon_entry(registry), ("2", True))
        self.assertFalse(app.promote_tray_icon(TrayRegistry()))

    def test_overlay_menu_mirrors_tray_and_offers_driver_guide_in_raw_mode(self):
        self.application.state = {"input_reader": "usb"}
        labels = [entry[0] for entry in self.application.overlay_menu() if entry]
        self.assertIn("状态", labels)
        self.assertIn("退出", labels)
        self.assertNotIn("装驱动说明", labels)
        self.application.state = {"input_reader": "raw"}
        entries = {entry[0]: entry[1] for entry in self.application.overlay_menu() if entry}
        with patch.object(self.application, "show_driver_guide") as guide:
            entries["装驱动说明"]()
        guide.assert_called_once_with()
        menu = self.application.menu(SimpleNamespace(Menu=Menu, MenuItem=MenuItem))
        rows = {r.text: r for r in menu.children() if isinstance(r, MenuItem) and isinstance(r.text, str)}
        rows["管理面板"].action()
        self.assertEqual(self.queue.get_nowait(), ("panel", None))
        self.assertTrue(rows["管理面板"].options["default"])
        self.assertNotIn("状态", rows)
        self.assertNotIn("键位", rows)
        rows["装驱动说明（按键会打字时）"].action()
        self.assertEqual(self.queue.get_nowait(), ("driver", None))

    def test_driver_guide_covers_zadig_steps(self):
        text = app.guide_text()
        for needle in ("zadig.akeo.ie", "List All Devices", "4132 2107 00", "WinUSB", "Replace Driver"):
            self.assertIn(needle, text)

    def test_diagnostics_queues_report_for_gui_thread(self):
        report = {"text": "USB 未连接", "legacy_count": 0}

        def immediate_thread(*, target, **kwargs):
            return SimpleNamespace(start=target)

        with patch("hub_doctor.app_report", return_value=report) as doctor, patch.object(app.threading, "Thread", side_effect=immediate_thread):
            self.application.diagnostics()
        doctor.assert_called_once_with(home=self.home, projects=[])
        self.assertEqual(self.queue.get_nowait(), ("report", report))
        self.application.message.assert_not_called()

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
        with patch.object(self.application, "draw_icon", return_value="amber"), patch.object(
                self.application, "show_status") as status:
            self.application.pump()
        status.assert_called_once_with()
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
        self.engine.action.assert_called_once_with({"action": "slot 3", "session": ["cc", "session"]})

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
                self.assertEqual(events, [("apply", 123)])  # Ready while the idle overlay stays hidden.
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
        self.assertEqual(self.run_overlay(), [("apply", 123), "ready", "mainloop",
                                               "close", "destroy", "on_close"])

    def test_ready_callback_failure_closes_native_window_and_destroys_tk(self):
        self.assertEqual(self.run_overlay(True), [("apply", 123), "ready",
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
