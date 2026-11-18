"""macOS scripts and shared voice lifecycle, with subprocesses entirely faked."""
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import hub
from hub_desktop import DesktopEffects
from hub_desktop_mac import APPLICATIONS, MacDesktopEffects, MacWindowControl, literal
from test_hub_desktop import GuardTicks


SESSION = {"key": "cc-abcdef", "name": "app", "state": "think"}
WINDOW = ((42, "101", ""), "Terminal", "app - Claude")
OTHER = ((43, "202", ""), "Safari", "other")


class Commands:
    def __init__(self):
        self.items = [WINDOW]
        self.foreground = WINDOW
        self.calls = []
        self.inputs = []
        self.copies = []
        self.failure = None
        self.change_on_copy = None
        self.change_on_paste = None
        self.activation_ok = True
        self.dictation_ok = True
        self.bundle_ids = {}
        self.foreground_sequence = []

    @staticmethod
    def row(window):
        handle, app, title = window
        return "\x1f".join((str(handle[0]), app, handle[1], title))

    @staticmethod
    def matches(script, window, pid):
        number = re.search(r'my windowNumber\(w\) is "(\d+)"', script)
        title = re.search(r'(?:\(name of w as text\)|my windowTitleText\(w\)) is ("(?:[^"\\]|\\.)*")', script)
        return (window[0][0] == pid
                and (window[0][1] == number[1] if number else window[2] == json.loads(title[1])))

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        assert 0 < kwargs["timeout"] <= 3 and kwargs["encoding"] == "utf-8"
        assert kwargs["capture_output"] and kwargs["text"] and not kwargs["check"]
        if self.failure is not None:
            if isinstance(self.failure, Exception):
                raise self.failure
            return subprocess.CompletedProcess(args, 1, "", self.failure)
        output = ""
        if args[0] == "pbcopy":
            self.copies.append(kwargs["input"])
            if self.change_on_copy:
                self.foreground = self.change_on_copy
        elif args[0] == "screencapture":
            assert args[1] == "-x"
            Path(args[2]).write_bytes(b"fake png")
        else:
            assert args[:2] == ["osascript", "-e"]
            script = args[2]
            if "set rows to {}" in script:
                names = re.search(r'\(name of p as text\) is in (\{[^}]*\})', script)
                allowed_names = json.loads(names[1].replace("{", "[").replace("}", "]"))
                bundles = re.search(r'\(appID as text\) is in (\{[^}]*\})', script)
                allowed_ids = (json.loads(bundles[1].replace("{", "[").replace("}", "]"))
                               if bundles else [])
                supported = []
                for window in self.items:
                    app_id = self.bundle_ids.get(window[0][0])
                    allowed = app_id in allowed_ids if bundles and app_id is not None else window[1] in allowed_names
                    if allowed:
                        supported.append(window)
                output = "\x1e".join(self.row(w) for w in supported)
            elif "set targets to {}" in script:
                if self.activation_ok:
                    pid = int(re.search(r"unix id is (\d+)", script)[1])
                    self.foreground = next(w for w in self.items if self.matches(script, w, pid))
                    output = "ok"
                else:
                    output = "false"
            elif "if not (exists" in script:
                pid = int(re.search(r"unix id is (\d+)", script)[1])
                output = str(sum(self.matches(script, w, pid) for w in self.items) == 1).lower()
            elif "unix id of p) is not" in script:
                pid = int(re.search(r"unix id of p\) is not (\d+)", script)[1])
                allowed = (self.matches(script, self.foreground, pid)
                           and sum(self.matches(script, w, pid) for w in self.items) == 1)
                commands = script.split('-- guarded input\n')[-1].split('return "true"')[0].strip()
                if "key code 49" in commands and not self.dictation_ok:
                    allowed = False
                output = str(allowed).lower()
                if allowed:
                    self.inputs.append(commands)
                    if ('keystroke "v"' in commands or 'key code 9 using command down' in commands) and self.change_on_paste:
                        self.foreground = self.change_on_paste
                        # The final foreground guard runs after the paste delay.
                        after_delay = commands.partition("delay 0.08")[2]
                        checks_process = "if not (frontmost of p)" in after_delay
                        checks_window = "set w to front window of p" in after_delay
                        moved_process = self.foreground[0][0] != pid
                        moved_window = not self.matches(script, self.foreground, pid)
                        if ((checks_process and moved_process) or (checks_window and moved_window)):
                            self.inputs[-1] = commands.split("delay 0.08")[0].strip()
                            output = "false"
            else:
                assert "return my windowRow(p, front window of p)" in script
                if self.foreground_sequence:
                    self.foreground = self.foreground_sequence.pop(0)
                output = self.row(self.foreground) if self.foreground[0] else ""
        return subprocess.CompletedProcess(args, 0, output + "\n", "")


class MacDesktopTests(unittest.TestCase):
    def setUp(self):
        self.commands = Commands()
        self.effects = MacDesktopEffects(run=self.commands, sleeper=lambda seconds: None)
        self.addCleanup(self.effects.close)

    def test_platform_dispatch_and_lazy_import(self):
        with patch("hub_desktop.sys.platform", "darwin"), patch(
                "hub_desktop.HubWindowControl", side_effect=AssertionError("Win32")):
            effects = DesktopEffects(run=self.commands)
        self.assertIsInstance(effects, MacDesktopEffects)
        self.assertEqual(self.commands.calls, [])
        for platform in ("win32", "linux"):
            with self.subTest(platform=platform), patch("hub_desktop.sys.platform", platform):
                effects = DesktopEffects()
                self.assertIs(type(effects), DesktopEffects)

    def test_all_six_apps_and_actual_process_aliases_use_title_matching(self):
        for app in APPLICATIONS:
            with self.subTest(app=app):
                window = (WINDOW[0], app, WINDOW[2])
                self.commands.items = [window]
                self.assertEqual(self.effects.focus(SESSION, [SESSION]), window)
        script = self.commands.calls[0][0][2]
        for app in ("Terminal", "iTerm2", "Visual Studio Code", "Cursor", "Warp", "Ghostty"):
            self.assertIn(literal(app), script)
        self.assertIn('windowTitle contains (character id 30)', script)
        self.assertIn('windowTitle contains (character id 31)', script)
        activation = next(args[2] for args, _ in self.commands.calls if "set targets" in args[2])
        self.assertIn('perform action "AXRaise" of targetWindow', activation)
        self.assertIn("tell application appName to activate", activation)
        self.assertIn("tell application id appID to activate", activation)
        self.assertIn("unix id is 42", activation)
        self.assertIn('my windowNumber(w) is "101"', activation)

    def test_bundle_ids_select_real_warp_and_electron_processes(self):
        for app, app_id in (("Terminal", "com.apple.Terminal"),
                            ("iTerm2", "com.googlecode.iterm2"),
                            ("Cursor", "com.todesktop.230313mzl4w4u92"),
                            ("ghostty", "com.mitchellh.ghostty"),
                            ("stable", "dev.warp.Warp-Stable"),
                            ("preview", "dev.warp.Warp-Preview"),
                            ("Electron", "com.microsoft.VSCode"),
                            ("Electron", "com.microsoft.VSCodeInsiders"),
                            ("Electron", "com.vscodium")):
            with self.subTest(app=app, app_id=app_id):
                window = (WINDOW[0], app, WINDOW[2])
                self.commands.items = [window]
                self.commands.bundle_ids = {42: app_id}
                self.assertEqual(self.effects.focus(SESSION, [SESSION]), window)
        self.commands.items = [(WINDOW[0], "Electron", WINDOW[2])]
        self.commands.bundle_ids = {42: "com.tinyspeck.slackmacgap"}
        with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING"):
            self.assertFalse(self.effects.focus(SESSION, [SESSION]))
        self.commands.items = [WINDOW]
        for app_id in ("unlisted.Terminal", ""):
            self.commands.bundle_ids = {42: app_id}
            with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING"):
                self.assertFalse(self.effects.focus(SESSION, [SESSION]))
        self.commands.bundle_ids = {42: None}
        self.assertEqual(self.effects.focus(SESSION, [SESSION]), WINDOW)

    def test_focus_waits_for_activation_and_ignores_spinner_title(self):
        renamed = (WINDOW[0], "Terminal", "app - Claude \u2819")
        self.commands.foreground_sequence = [OTHER, renamed]
        pauses = []
        self.effects.sleep = pauses.append
        self.assertEqual(self.effects.focus(SESSION, [SESSION]), WINDOW)
        self.assertEqual(pauses, [0.03])
        foreground_calls = [kwargs for args, kwargs in self.commands.calls
                            if args[0] == "osascript" and "return my windowRow(p, front window of p)" in args[2]]
        self.assertTrue(all(0 < call["timeout"] <= 0.3 for call in foreground_calls))
        self.assertTrue(self.effects.prompt(SESSION, [SESSION], "continue"))

    def test_focus_activation_polling_stops_within_300ms(self):
        self.commands.foreground_sequence = [OTHER] * 11
        pauses = []
        self.effects.monotonic = lambda: 100.0
        self.effects.sleep = pauses.append
        with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING"):
            self.assertFalse(self.effects.focus(SESSION, [SESSION]))
        self.assertLessEqual(len(pauses), 10)
        self.assertLessEqual(sum(pauses), 0.3)
        self.assertEqual(self.commands.inputs, [])

    def test_prompt_does_not_requery_foreground_before_guarded_paste(self):
        renamed = (WINDOW[0], "Terminal", "app - Claude \u2819")
        self.commands.foreground_sequence = [renamed]
        self.assertTrue(self.effects.prompt(SESSION, [SESSION], "continue"))
        foreground_calls = [args for args, _ in self.commands.calls
                            if args[0] == "osascript" and "return my windowRow(p, front window of p)" in args[2]]
        self.assertEqual(len(foreground_calls), 1)
        self.assertEqual(len(self.commands.inputs), 1)

    def test_empty_osascript_result_with_newline_does_not_log(self):
        self.commands.foreground = (None, "", "")
        with patch("hub_desktop_mac.log.warning") as warning:
            self.assertEqual(self.effects.windows(), (None, "", ""))
        warning.assert_not_called()

    def test_enumeration_keeps_good_rows_when_one_row_is_invalid(self):
        def run(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, "invalid row\x1e" + Commands.row(WINDOW) + "\n", "")
        windows = MacWindowControl(run)
        with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING"):
            self.assertEqual(windows.windows(), [WINDOW])

    def test_titleless_windows_and_disappearing_windows_are_isolated_in_script(self):
        self.commands.items = [(WINDOW[0], "Terminal", "")]
        self.assertEqual(self.effects.windows.windows(), self.commands.items)
        script = self.commands.calls[-1][0][2]
        self.assertIn('if rawTitle is missing value then return ""', script)
        self.assertRegex(script, r'repeat with w in windows of p\s+try\s+set end of rows')

    def test_prompt_uses_utf8_locale_and_single_guarded_paste_submit(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(self.effects.prompt(SESSION, [SESSION], "\u7ee7\u7eed\u6d4b\u8bd5"))
        copy = next(kwargs for args, kwargs in self.commands.calls if args[0] == "pbcopy")
        self.assertEqual(copy["env"]["LC_CTYPE"], "UTF-8")
        self.assertEqual(len(self.commands.inputs), 1)
        commands = self.commands.inputs[0]
        self.assertLess(commands.index("key code 9 using command down"), commands.index("delay 0.08"))
        self.assertLess(commands.index("delay 0.08"), commands.index("key code 36"))

    def test_voice_without_config_is_unavailable_without_sending_shortcut(self):
        with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING") as logs:
            self.assertFalse(self.effects.voice_down(SESSION, [SESSION]))
        self.assertIn("dictation_shortcut", " ".join(logs.output))
        self.assertFalse(self.effects.voice_active)
        self.assertEqual(self.commands.inputs, [])

    def test_missing_window_action_reports_focus_failure_once(self):
        self.commands.items = []
        for action in (lambda: self.effects.interrupt(SESSION, [SESSION]),
                       lambda: self.effects.prompt(SESSION, [SESSION], "continue"),
                       lambda: self.effects.voice_down(SESSION, [SESSION])):
            with self.subTest(action=action), self.assertLogs("agentdeck.hub.desktop.mac", "WARNING") as logs:
                self.assertFalse(action())
            failures = [line for line in logs.output if "failed:" in line]
            self.assertEqual(len(failures), 1)
            self.assertNotIn("foreground changed", failures[0])

    def test_boundary_tool_and_ambiguity_rules_are_preserved(self):
        for title in ("application - Claude", "app - Codex", "app", "app - Claude Codex"):
            with self.subTest(title=title):
                self.commands.items = [(WINDOW[0], "Terminal", title)]
                with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING"):
                    self.assertFalse(self.effects.focus(SESSION, [SESSION]))
        self.commands.items = [WINDOW, ((42, "102", ""), "Terminal", WINDOW[2])]
        with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING") as logs:
            self.assertFalse(self.effects.focus(SESSION, [SESSION]))
        self.assertIn("ambiguous", " ".join(logs.output))

    def test_same_project_sessions_and_unsupported_apps_are_not_guessed(self):
        duplicate = dict(SESSION, key="cc-second")
        with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING"):
            self.assertFalse(self.effects.focus(SESSION, [SESSION, duplicate]))
        self.commands.items = [(WINDOW[0], "Safari", WINDOW[2])]
        with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING"):
            self.assertFalse(self.effects.focus(SESSION, [SESSION]))

    def test_failed_activation_never_types(self):
        self.commands.activation_ok = False
        with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING"):
            self.assertFalse(self.effects.prompt(SESSION, [SESSION], "continue"))
        self.assertEqual(self.commands.inputs, [])
        self.assertEqual(self.commands.copies, [])

    def test_interrupt_sends_only_escape_keycode_53(self):
        self.assertTrue(self.effects.interrupt(SESSION, [SESSION]))
        self.assertEqual(self.commands.inputs, ["key code 53"])
        self.assertEqual(self.commands.copies, [])

    def test_prompt_copies_unicode_as_stdin_then_command_v_then_return(self):
        text = '跑测试\n"quoted" \\ $(no-shell)'
        self.assertTrue(self.effects.prompt(SESSION, [SESSION], text))
        self.assertEqual(self.commands.copies, [text])
        self.assertEqual(len(self.commands.inputs), 1)
        self.assertIn("key code 9 using command down", self.commands.inputs[0])
        self.assertIn("delay 0.08", self.commands.inputs[0])
        self.assertIn("key code 36", self.commands.inputs[0])
        copy = next(call for call in self.commands.calls if call[0][0] == "pbcopy")
        self.assertEqual(copy[0], ["pbcopy"])
        self.assertEqual(copy[1]["input"], text)
        self.assertTrue(all(text not in args[-1] for args, _ in self.commands.calls))

    def test_focus_change_after_copy_or_paste_blocks_following_input(self):
        self.commands.change_on_copy = OTHER
        with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING"):
            self.assertFalse(self.effects.prompt(SESSION, [SESSION], "continue"))
        self.assertEqual(self.commands.inputs, [])
        self.commands.change_on_copy = None
        self.commands.change_on_paste = OTHER
        with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING"):
            self.assertFalse(self.effects.prompt(SESSION, [SESSION], "continue"))
        self.assertEqual(self.commands.inputs, ['key code 9 using command down'])

    def test_another_window_of_same_app_during_paste_blocks_return(self):
        self.commands.change_on_paste = ((42, "102", ""), "Terminal", "other")
        with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING"):
            self.assertFalse(self.effects.prompt(SESSION, [SESSION], "continue"))
        self.assertEqual(self.commands.inputs, ["key code 9 using command down"])

    def test_screenshot_is_unique_png_and_pastes_path_without_return(self):
        with tempfile.TemporaryDirectory() as directory:
            self.effects.shots_dir = Path(directory) / "shots with spaces"
            self.effects.now = lambda: datetime(2026, 11, 17, 12, 34, 56)
            first = self.effects.screenshot(SESSION, [SESSION])
            second = self.effects.screenshot(SESSION, [SESSION])
            self.assertTrue(Path(first).is_file())
            self.assertNotEqual(first, second)
            self.assertEqual(self.commands.copies, [first, second])
            capture = [args for args, _ in self.commands.calls if args[0] == "screencapture"]
            self.assertEqual(capture, [["screencapture", "-x", first], ["screencapture", "-x", second]])
        self.assertEqual(self.commands.inputs, ['key code 9 using command down'] * 2)

    def test_process_failures_and_timeouts_only_log_with_one_permission_hint(self):
        for error in (FileNotFoundError("osascript"), subprocess.TimeoutExpired("osascript", 3),
                      subprocess.CalledProcessError(1, "osascript"), "not authorized (-1743)"):
            with self.subTest(error=error):
                commands = Commands()
                commands.failure = error
                effects = MacDesktopEffects(run=commands)
                with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING") as logs:
                    self.assertFalse(effects.interrupt(SESSION, [SESSION]))
                    self.assertFalse(effects.prompt(SESSION, [SESSION], "continue"))
                    self.assertFalse(effects.voice_down(SESSION, [SESSION]))
                self.assertEqual(sum("系统设置" in line for line in logs.output), 1)
                self.assertFalse(effects.voice_active)
                self.assertEqual(commands.inputs, [])

    def test_copy_capture_and_return_failures_do_not_continue(self):
        for executable in ("pbcopy", "screencapture"):
            with self.subTest(executable=executable), tempfile.TemporaryDirectory() as directory:
                commands = Commands()
                def run(args, **kwargs):
                    if args[0] == executable:
                        raise subprocess.TimeoutExpired(executable, 3)
                    return commands(args, **kwargs)
                effects = MacDesktopEffects(run=run, shots_dir=directory)
                with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING"):
                    if executable == "pbcopy":
                        self.assertFalse(effects.prompt(SESSION, [SESSION], "continue"))
                    else:
                        self.assertFalse(effects.screenshot(SESSION, [SESSION]))
                self.assertEqual(commands.inputs, [])

    def test_window_serialization_handles_unicode_quotes_and_title_changes(self):
        title = '项目 "quoted" \\ app - Claude'
        window = ((42, "101", ""), "Terminal", title)
        self.commands.items = [window]
        self.assertEqual(self.effects.windows.windows(), [window])
        fallback = ((42, "", title), "Terminal", title)
        row = self.commands.row(fallback)
        self.assertEqual(MacWindowControl._row(row), fallback)
        predicate = self.effects.windows._matches("w", fallback[0])
        self.assertIn('\\"quoted\\"', predicate)
        self.assertIn("\\\\", predicate)
        self.assertNotIn(title, predicate)
        self.assertTrue(self.effects.windows.exists(WINDOW[0]))

    def test_invalid_window_output_does_not_escape(self):
        def run(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, "invalid row", "")
        windows = MacWindowControl(run)
        with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING"):
            self.assertEqual(windows.windows(), [])
            self.assertEqual(windows(), (None, "", ""))

    def test_trailing_newlines_in_window_titles_are_preserved(self):
        window = (WINDOW[0], "Terminal", WINDOW[2] + "\n\n")
        self.commands.items = [window]
        self.commands.foreground = window
        self.assertEqual(self.effects.windows.windows(), [window])
        self.assertEqual(self.effects.windows(), window)
        self.assertEqual(self.effects.focus(SESSION, [SESSION]), window)

    def test_title_fallback_rechecks_uniqueness_for_exists_and_input(self):
        fallback = ((42, "", WINDOW[2]), "Terminal", WINDOW[2])
        self.commands.items = [fallback]
        self.commands.foreground = fallback
        self.assertEqual(self.effects.focus(SESSION, [SESSION]), fallback)
        self.assertTrue(self.effects.windows.exists(fallback[0]))
        self.commands.items.append(fallback)
        self.assertFalse(self.effects.windows.exists(fallback[0]))
        self.assertFalse(self.effects.windows.send_key(0x1B, fallback))
        self.assertEqual(self.commands.inputs, [])
        for args, _ in self.commands.calls:
            if "if not (exists" in args[2] or "unix id of p) is not" in args[2]:
                self.assertIn("set matches to matches + 1", args[2])

    def test_default_and_configurable_dictation_scripts(self):
        self.assertIsNone(self.effects.dictation_shortcut)
        effects = MacDesktopEffects(run=self.commands,
                                   dictation_shortcut={"key_codes": [49], "modifiers": ["control", "option"]})
        self.assertEqual(effects.dictation_shortcut, "key code 49 using {control down, option down}")
        for shortcut in ("arbitrary script", {}, {"key_codes": []}, {"key_codes": [True]},
                         {"key_codes": [128]}, {"key_codes": [1], "modifiers": ["shell"]},
                         {"key_codes": [1], "script": "return 1"}):
            with self.subTest(shortcut=shortcut), self.assertRaises(ValueError):
                MacDesktopEffects(run=self.commands, dictation_shortcut=shortcut)

    def test_hub_cli_reads_mac_shortcut_from_relocated_config_before_any_startup(self):
        shortcut = {"key_codes": [49], "modifiers": ["control", "option"]}
        class Constructed(Exception):
            pass
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / ".agentdeck" / "config.json"
            config.parent.mkdir()
            config.write_text(json.dumps({"dictation_shortcut": shortcut}), encoding="utf-8")
            with patch.object(sys, "platform", "darwin"), patch("hub.logging.basicConfig"), patch("hub_desktop.DesktopEffects") as factory, patch(
                    "hub.Hub", side_effect=Constructed), self.assertRaises(Constructed):
                hub.main(["--no-lcd", "--home", directory])
            factory.assert_called_once_with(shots_dir=config.parent / "shots", dictation_shortcut=shortcut)

    def test_hub_reports_unavailable_when_native_action_returns_false(self):
        with tempfile.TemporaryDirectory() as directory:
            effects = MacDesktopEffects(run=self.commands)
            owner = hub.Hub(home=directory, lcd_enabled=False, desktop=effects, prompts={"test": "continue"})
            owner.event("cc", {"session_id": "abcdef-session", "hook_event_name": "SessionStart", "cwd": "/tmp/app"})
            self.commands.failure = "permission denied"
            with self.assertLogs("agentdeck.hub.desktop.mac", "WARNING"), patch.object(sys, "platform", "darwin"):
                selected = owner.action({"action": "slot 1"})
                self.assertEqual(selected["window"], "window focus unavailable")
                effects.shots_dir = Path(directory) / "shots"
                for action in ("interrupt", "prompt test", "voice_down", "screenshot"):
                    self.assertEqual(owner.action({"action": action})["status"], "unavailable")
            self.assertFalse(effects.voice_active)


class MacVoiceTests(unittest.TestCase):
    def setUp(self):
        self.commands = Commands()
        self.ticks = GuardTicks()
        self.now = 100.0
        self.completed = []
        self.effects = MacDesktopEffects(run=self.commands, voice_wait=self.ticks, monotonic=lambda: self.now,
                                         dictation_shortcut={"key_codes": [49], "modifiers": ["control", "option"]})
        self.addCleanup(self.effects.close)

    def start(self):
        self.assertTrue(self.effects.voice_down(SESSION, [SESSION], on_stop=self.completed.append))
        self.assertEqual(self.ticks.entered.get(timeout=1), 0.1)
        self.assertTrue(self.effects.voice_active)

    def test_voice_refocuses_pinned_window_and_closes_only_dictation(self):
        self.start()
        self.commands.foreground = OTHER
        self.ticks.permits.release()
        self.assertEqual(self.ticks.entered.get(timeout=1), 0.1)
        self.assertEqual(self.commands.foreground, WINDOW)
        result = self.effects.voice_up()
        self.assertEqual(result["reason"], "released")
        self.assertEqual(result["restores"], 1)
        self.assertTrue(result["closed"])
        self.assertEqual(len(self.completed), 1)
        self.assertEqual(self.commands.inputs, [self.effects.dictation_shortcut] * 2)
        self.assertEqual(self.commands.copies, [])
        self.assertIsNone(self.effects.voice_up())

    def test_title_change_with_native_id_does_not_retarget(self):
        self.start()
        renamed = (WINDOW[0], "Terminal", "new title")
        self.commands.items = [renamed]
        self.commands.foreground = renamed
        result = self.effects.voice_up()
        self.assertEqual(result["reason"], "released")
        self.assertEqual(result["restores"], 0)
        self.assertTrue(result["closed"])

    def test_timeout_and_missing_window_stop_guard(self):
        for reason in ("timeout", "window_lost"):
            with self.subTest(reason=reason):
                self.start()
                if reason == "timeout":
                    self.now += 60
                else:
                    self.commands.items = [OTHER]
                    self.commands.foreground = OTHER
                self.ticks.permits.release()
                self.effects._voice.thread.join(1)
                self.assertFalse(self.effects._voice.thread.is_alive())
                self.assertEqual(self.completed[-1]["reason"], reason)
                self.assertFalse(self.effects.voice_active)
                self.commands.items = [WINDOW]

    def test_window_lost_or_failed_refocus_never_toggles_new_foreground(self):
        for reason in ("window_lost", "focus_failed"):
            with self.subTest(reason=reason):
                self.start()
                before = list(self.commands.inputs)
                self.commands.foreground = OTHER
                if reason == "window_lost":
                    self.commands.items = [OTHER]
                else:
                    self.commands.activation_ok = False
                self.ticks.permits.release()
                self.effects._voice.thread.join(1)
                self.assertFalse(self.effects._voice.thread.is_alive())
                self.assertEqual(self.completed[-1]["reason"], reason)
                self.assertTrue(self.completed[-1]["closed"])
                self.assertEqual(self.commands.inputs, before)
                self.assertFalse(self.effects.voice_active)
                self.commands.activation_ok = True
                self.commands.items = [WINDOW]

    def test_failed_close_logs_and_retains_ownership_until_retry(self):
        self.start()
        self.commands.dictation_ok = False
        with self.assertLogs(level="WARNING"):
            self.assertFalse(self.effects.voice_up())
        self.assertTrue(self.effects.voice_active)
        self.assertFalse(self.completed[-1]["closed"])
        self.commands.dictation_ok = True
        self.assertTrue(self.effects.voice_up()["closed"])
        self.assertFalse(self.effects.voice_active)

    def test_duplicate_down_never_starts_a_second_interval(self):
        self.start()
        self.assertTrue(self.effects.voice_down(dict(SESSION, key="cx-other"), [SESSION]))
        self.assertEqual(len(self.commands.inputs), 1)
        self.assertEqual(self.effects._voice.session, SESSION)
        self.assertEqual(self.effects.close()["reason"], "shutdown")
        self.assertEqual(len(self.commands.inputs), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
