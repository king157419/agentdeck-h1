"""Relay tests inject HTTP transports and temporary homes; no live hub required."""
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import hub_relay


RISKY = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
         "tool_input": {"command": "git push --force origin main"}}
CURL_SH = dict(RISKY, tool_input={"command": "curl x | sh"})
SAFE = dict(RISKY, tool_input={"command": "ls"})
TURN = {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "继续"}


class Connection:
    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = self
        self.read_timeout = None
        self.status = 200
        self.raw = b'{ "hookSpecificOutput": {"decision":{"behavior":"allow"}} }\n'
        self.closed = False

    def connect(self):
        pass

    def settimeout(self, value):
        self.read_timeout = value

    def request(self, method, path, body, headers):
        self.request_data = (method, path, body, headers)

    def getresponse(self):
        return self

    def read(self):
        return self.raw

    def close(self):
        self.closed = True


class WindowFinderTests(unittest.TestCase):
    def setUp(self):
        platform = patch.object(hub_relay.sys, "platform", "win32")
        platform.start()
        self.addCleanup(platform.stop)
        self.processes = {100: (90, "relay.exe"), 90: (80, "bash.exe"),
                          80: (70, "claude.exe"), 70: (60, "pwsh.exe"),
                          60: (50, "OpenConsole.exe"), 50: (0, "WindowsTerminal.exe")}
        self.windows = {100: [0x9999], 60: [], 50: [0x1234, 0x5678]}
        self.times = {pid: pid for pid in self.processes}

    def find(self, **options):
        defaults = dict(pid=100, processes=self.processes, windows=self.windows, started=self.times.get)
        defaults.update(options)
        return hub_relay.find_agent_window(**defaults)

    def test_terminal_ancestor_uses_first_window_and_excludes_relay(self):
        self.assertEqual(self.find(), {"hwnd": 0x1234, "pid": 50, "exe": "WindowsTerminal.exe"})
        self.assertIsNone(self.find(windows={100: [0x9999]}))
        with patch.object(hub_relay.os, "getpid", return_value=100):
            self.assertEqual(self.find(pid=None), self.find())

    def test_nearest_window_wins_even_if_higher_link_is_reused(self):
        self.windows[90] = [0x123456789, 0x4444]
        self.times[60] = 71
        self.assertEqual(self.find(), {"hwnd": 0x123456789, "pid": 90, "exe": "bash.exe"})

    def test_newer_parent_stops_before_its_window(self):
        self.times[60] = 71  # child pwsh started at 70
        self.windows[60] = [0x2222]
        self.assertIsNone(self.find())

    def test_missing_creation_time_stops(self):
        for pid in (100, 90, 60, 50):
            with self.subTest(pid=pid):
                times = dict(self.times)
                times[pid] = None
                self.assertIsNone(self.find(started=times.get))

    def test_depth_limit_counts_parent_hops(self):
        for depth in (-1, 0, 1, 4):
            with self.subTest(depth=depth):
                self.assertIsNone(self.find(max_depth=depth))
        self.assertEqual(self.find(max_depth=5)["pid"], 50)

    def test_missing_process_root_and_cycles_stop(self):
        for processes in ({}, {100: (90, "relay.exe")}, {100: (0, "relay.exe")},
                          {100: (100, "relay.exe")},
                          {100: (90, "relay.exe"), 90: (100, "bash.exe")}):
            with self.subTest(processes=processes):
                started = Mock(return_value=1)  # equal times let cycles reach the visited check
                self.assertIsNone(self.find(processes=processes, windows={}, started=started,
                                            max_depth=1000))
                self.assertLessEqual(started.call_count, 2)

    def test_non_windows_and_lookup_exceptions_are_harmless(self):
        started = Mock(side_effect=RuntimeError("unavailable process times"))
        self.assertIsNone(self.find(started=started))
        with patch.object(hub_relay.sys, "platform", "linux"):
            started.reset_mock()
            self.assertIsNone(self.find(started=started))
            started.assert_not_called()

    def test_desktop_shell_parent_is_never_the_agent_window(self):
        # Default-terminal handoff: the shell's parent is explorer.exe, whose
        # File Explorer windows must not receive the agent's keys.
        self.processes[60] = (40, "pwsh.exe")
        self.processes[40] = (4, "explorer.exe")
        self.times[40] = 5
        self.windows = {40: [0x4040]}
        self.assertIsNone(self.find())

    @unittest.skipUnless(os.name == "nt", "Windows ctypes ABI")
    def test_console_window_owner_wins_over_process_tree(self):
        import ctypes
        kernel, user = Mock(), Mock()
        terminal, pseudo = 0x51515, 0x60606
        kernel.GetConsoleWindow.return_value = pseudo
        user.EnumWindows.return_value = True
        user.GetAncestor.side_effect = lambda hwnd, flag: terminal if (hwnd, flag) == (pseudo, 3) else 0
        user.IsWindowVisible.side_effect = lambda hwnd: hwnd == terminal
        user.GetWindowTextLengthW.return_value = 5

        def owner(hwnd, pointer):
            pointer._obj.value = 50
            return 1

        user.GetWindowThreadProcessId.side_effect = owner
        with patch.object(ctypes, "WinDLL", side_effect=lambda name, **options:
                          kernel if name == "kernel32" else user):
            found = hub_relay.find_agent_window(pid=100, processes=self.processes,
                                                started=self.times.get)
        self.assertEqual(found, {"hwnd": terminal, "pid": 50, "exe": "WindowsTerminal.exe"})
        # A hidden console window without a visible owner falls back to the process walk.
        user.GetAncestor.side_effect = lambda hwnd, flag: 0
        with patch.object(ctypes, "WinDLL", side_effect=lambda name, **options:
                          kernel if name == "kernel32" else user):
            self.assertIsNone(hub_relay.find_agent_window(pid=100, processes=self.processes,
                                                          started=self.times.get))

    @unittest.skipUnless(os.name == "nt", "Windows ctypes ABI")
    def test_native_api_layout_filtering_order_and_handle_cleanup(self):
        import ctypes
        kernel, user = Mock(), Mock()
        kernel.GetConsoleWindow.return_value = None  # no console: the process walk decides
        snapshot = 0x12345678
        kernel.CreateToolhelp32Snapshot.return_value = snapshot
        entries = iter(self.processes.items())

        def copy_entry(handle, pointer):
            self.assertEqual(handle, snapshot)
            entry = pointer._obj
            pointer_size = ctypes.sizeof(ctypes.c_void_p)
            self.assertEqual(entry.dwSize, 568 if pointer_size == 8 else 556)
            self.assertEqual(type(entry).th32DefaultHeapID.offset, 16 if pointer_size == 8 else 12)
            try:
                pid, (parent, exe) = next(entries)
            except StopIteration:
                return False
            entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile = pid, parent, exe
            return True

        kernel.Process32FirstW.side_effect = copy_entry
        kernel.Process32NextW.side_effect = copy_entry
        kernel.OpenProcess.side_effect = lambda access, inherit, pid: pid + 1000

        def process_times(handle, creation, exit_time, kernel_time, user_time):
            creation._obj.dwHighDateTime = 1
            creation._obj.dwLowDateTime = self.times[handle - 1000]
            return True

        kernel.GetProcessTimes.side_effect = process_times
        top = 0x123456789 if ctypes.sizeof(ctypes.c_void_p) == 8 else 0x1234
        handles = {0x9999: 60, 0x8888: 70, 0x7777: 80, top: 50, 0x5678: 50}
        user.IsWindowVisible.side_effect = lambda hwnd: hwnd != 0x9999
        user.GetWindow.side_effect = lambda hwnd, relation: 1 if hwnd == 0x8888 else 0
        user.GetWindowTextLengthW.side_effect = lambda hwnd: 0 if hwnd == 0x7777 else 10

        def owner(hwnd, pointer):
            pointer._obj.value = handles[hwnd]
            return 1

        user.GetWindowThreadProcessId.side_effect = owner
        user.EnumWindows.side_effect = lambda callback, data: all(callback(hwnd, data) for hwnd in handles)
        with patch.object(ctypes, "WinDLL", side_effect=lambda name, **options:
                          kernel if name == "kernel32" else user), \
                patch.object(hub_relay.os, "getpid", return_value=100):
            self.assertEqual(hub_relay.find_agent_window(),
                             {"hwnd": top, "pid": 50, "exe": "WindowsTerminal.exe"})
        kernel.CreateToolhelp32Snapshot.assert_called_once_with(0x2, 0)
        user.EnumWindows.assert_called_once()
        self.assertEqual(kernel.CloseHandle.call_args_list[0].args, (snapshot,))
        self.assertCountEqual([call.args[0] for call in kernel.CloseHandle.call_args_list[1:]],
                              [pid + 1000 for pid in self.processes])
        self.assertEqual(kernel.OpenProcess.call_args_list[0].args, (0x1000, False, 100))


class RelayWindowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        (self.home / ".agentdeck").mkdir()
        (self.home / ".agentdeck" / "token").write_text("secret", encoding="utf-8")
        self.connection = Connection("127.0.0.1", 47800, 0.5)
        self.connection.raw = b"{}"
        self.window = {"hwnd": 0x1234, "pid": 50, "exe": "WindowsTerminal.exe"}
        environment = patch.dict(os.environ, {"AGENTDECK_NO_WINDOW": "0"})
        environment.start()
        self.addCleanup(environment.stop)

    def forward(self, event, **options):
        return hub_relay.relay(event, "cc", home=self.home,
                               connection_factory=lambda *args, **kwargs: self.connection, **options)

    def test_ordinary_body_includes_window_without_mutating_input(self):
        finder = Mock(return_value=self.window)
        event = dict(TURN, tool_response="x" * 100_000)
        self.assertEqual(self.forward(event, window_finder=finder), b"{}")
        body = json.loads(self.connection.request_data[2])
        self.assertEqual(body["agentdeck_window"], self.window)
        self.assertNotIn("tool_response", body)
        self.assertNotIn("agentdeck_window", event)
        finder.assert_called_once_with()

    def test_permission_and_gate_inject_window_preserving_other_bytes(self):
        finder = Mock(return_value=self.window)
        for gate, name in ((False, "PermissionRequest"), (True, "PreToolUse")):
            with self.subTest(gate=gate):
                raw = (' { "hook_event_name": "%s", "tool_name": "Bash", '
                       '"cwd": "D:/项目", "tool_input": {"command": "ls"} }\n' % name).encode("utf-8")
                self.assertEqual(self.forward(json.loads(raw), raw=raw, gate=gate, window_finder=finder), b"{}")
                sent = self.connection.request_data[2]
                self.assertEqual(json.loads(sent)["agentdeck_window"], self.window)
                prefix = b'{"agentdeck_window":' + json.dumps(self.window).encode("ascii") + b","
                self.assertEqual(sent, prefix + raw.lstrip()[1:])
                self.assertNotIn("agentdeck_window", json.loads(raw))
        self.assertEqual(finder.call_count, 2)

    def test_tool_events_also_include_window(self):
        finder = Mock(return_value=self.window)
        for name in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
            with self.subTest(name=name):
                self.assertEqual(self.forward(dict(SAFE, hook_event_name=name), window_finder=finder), b"{}")
                self.assertEqual(json.loads(self.connection.request_data[2])["agentdeck_window"], self.window)
        self.assertEqual(finder.call_count, 3)

    def test_injected_transport_skips_default_finder(self):
        with patch.object(hub_relay, "find_agent_window", side_effect=AssertionError("real desktop")) as finder:
            self.assertEqual(self.forward(TURN), b"{}")
        finder.assert_not_called()

    def test_default_transport_finds_windows_and_timing_opt_out_skips_it(self):
        with patch("http.client.HTTPConnection", return_value=self.connection), \
                patch.object(hub_relay, "find_agent_window", return_value=self.window) as finder:
            self.assertEqual(hub_relay.relay(TURN, "cc", home=self.home), b"{}")
            self.assertEqual(json.loads(self.connection.request_data[2])["agentdeck_window"], self.window)
            finder.assert_called_once_with()
            finder.reset_mock()
            with patch.dict(os.environ, {"AGENTDECK_NO_WINDOW": "1"}):
                self.assertEqual(hub_relay.relay(TURN, "cc", home=self.home), b"{}")
            finder.assert_not_called()
            self.assertNotIn("agentdeck_window", json.loads(self.connection.request_data[2]))

    def test_lookup_overlaps_connect_and_finishes_before_sending(self):
        from threading import Event
        connected = Event()

        def finder():
            self.assertTrue(connected.wait(2), "lookup blocked HTTP connection setup")
            return self.window

        with patch("http.client.HTTPConnection", return_value=self.connection), \
                patch.object(self.connection, "connect", side_effect=connected.set):
            self.assertEqual(hub_relay.relay(TURN, "cc", home=self.home, window_finder=finder), b"{}")
        self.assertEqual(json.loads(self.connection.request_data[2])["agentdeck_window"], self.window)

    def test_lookup_thread_start_failure_still_forwards(self):
        with patch("http.client.HTTPConnection", return_value=self.connection), \
                patch("threading.Thread", side_effect=RuntimeError("thread unavailable")):
            self.assertEqual(hub_relay.relay(TURN, "cc", home=self.home,
                                             window_finder=Mock(return_value=self.window)), b"{}")
        self.assertNotIn("agentdeck_window", json.loads(self.connection.request_data[2]))

    def test_dead_hub_skips_window_lookup_and_transport(self):
        finder = Mock(side_effect=AssertionError("dead hub must return first"))
        with patch.object(hub_relay, "hub_status", return_value="down"), \
                patch("http.client.HTTPConnection") as transport:
            self.assertIsNone(hub_relay.relay(TURN, "cc", home=self.home, window_finder=finder))
        finder.assert_not_called()
        transport.assert_not_called()

    def test_lookup_failure_or_no_window_still_forwards(self):
        for finder in (Mock(side_effect=RuntimeError("desktop unavailable")), Mock(return_value=None),
                       Mock(return_value=123)):
            with self.subTest(finder=finder):
                self.assertEqual(self.forward(TURN, window_finder=finder), b"{}")
                self.assertNotIn("agentdeck_window", json.loads(self.connection.request_data[2]))

    def test_lookup_exception_keeps_hook_exit_zero_and_forwards(self):
        output = io.StringIO()
        with patch("http.client.HTTPConnection", return_value=self.connection), \
                patch.object(hub_relay, "find_agent_window", side_effect=RuntimeError("desktop unavailable")):
            code = hub_relay.main(["--agent", "cc", "--home", str(self.home)],
                                  stdin=io.StringIO(json.dumps(TURN)), stdout=output)
        self.assertEqual((code, output.getvalue()), (0, "{}"))
        self.assertEqual(json.loads(self.connection.request_data[2])["hook_event_name"], "UserPromptSubmit")

    def test_raw_window_injection_handles_empty_object_and_non_object(self):
        event = {"agentdeck_window": self.window}
        for raw in (b"{}", b" \t{ \r\n }\n"):
            sent = hub_relay._body(event, raw, True)
            self.assertEqual(json.loads(sent), event)
            self.assertTrue(sent.endswith(raw.lstrip()[1:]))
            self.assertNotIn(b",", sent[len(b'{"agentdeck_window":') +
                                        len(json.dumps(self.window).encode("ascii")):])
        for raw in (b" [] ", b"oops"):
            self.assertEqual(hub_relay._body(event, raw, True), raw)

    def test_window_lookup_timeout_omits_metadata_without_delaying_forwarding(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def blocked_finder():
            release.wait(3)
            return self.window

        for gate, name, limit in ((False, "PreToolUse", 0.15),
                                  (False, "PermissionRequest", 0.4),
                                  (True, "PreToolUse", 0.4)):
            with self.subTest(gate=gate, name=name):
                started = time.monotonic()
                self.assertEqual(self.forward(dict(SAFE, hook_event_name=name),
                                              gate=gate, window_finder=blocked_finder), b"{}")
                self.assertLess(time.monotonic() - started, limit)
                self.assertNotIn("agentdeck_window", json.loads(self.connection.request_data[2]))


class RelayTests(unittest.TestCase):
    def assert_gate_denial(self, raw):
        output = json.loads(raw)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertTrue(output["permissionDecisionReason"].startswith("Blocked by AgentDeck gate: "))
        self.assertNotIn("allow", output)

    def test_gate_query_long_timeout_and_unmodified_empty_response(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret", encoding="utf-8")
            for agent in ("cc", "cx"):
                with self.subTest(agent=agent):
                    connection = Connection("127.0.0.1", 47800, 0.5)
                    connection.raw = b'{ }\n'
                    result = hub_relay.relay({"hook_event_name": "PreToolUse"}, agent,
                        home=home, gate=True, approve_timeout=23,
                        connection_factory=lambda *args, **kwargs: connection)
                    self.assertEqual(result, connection.raw)
                    self.assertEqual(connection.read_timeout, 28)
                    self.assertEqual(connection.request_data[1], "/event?agent=" + agent + "&gate=1")
                    self.assertEqual(connection.request_data[3]["X-AgentDeck-Token"], "secret")
                    self.assertTrue(connection.closed)

    def test_gate_accepts_only_empty_response_or_pretooluse_deny(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret", encoding="utf-8")
            connection = Connection("127.0.0.1", 47800, 0.5)
            event = RISKY
            factory = lambda *args, **kwargs: connection
            deny = hub_relay.gate_denial("rejected by user")
            connection.raw = deny
            self.assertEqual(hub_relay.relay(event, "cc", home=home, gate=True,
                                           connection_factory=factory), deny)
            for status, raw in ((503, b"{}"), (200, b"not json"), (200, b"[]"),
                    (200, b'{"hookSpecificOutput":{"permissionDecision":"allow"}}'),
                    (200, b'{"hookSpecificOutput":{"hookEventName":"PermissionRequest",'
                          b'"decision":{"behavior":"allow"}}}'),
                    (200, b'{"unexpected":"response"}')):
                with self.subTest(status=status, raw=raw):
                    connection.status, connection.raw = status, raw
                    self.assert_gate_denial(hub_relay.relay(event, "cc", home=home, gate=True,
                                                          connection_factory=factory))

    def gate(self, event, home, agent="cc", **options):
        return hub_relay.relay(event, agent, home=home, gate=True, **options)

    def test_gate_failure_denies_only_risky_operations(self):
        def unavailable(*args, **kwargs):
            raise TimeoutError("offline")
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret", encoding="utf-8")
            self.assertIsNone(self.gate(SAFE, home, connection_factory=unavailable))
            for event in (RISKY, CURL_SH):
                with self.subTest(event=event):
                    raw = self.gate(event, home, connection_factory=unavailable)
                    self.assert_gate_denial(raw)
                    self.assertIn("hub unavailable", json.loads(raw)["hookSpecificOutput"]["permissionDecisionReason"])
            (home / ".agentdeck" / "token").unlink()  # missing token behaves the same
            self.assertIsNone(self.gate(SAFE, home))
            self.assert_gate_denial(self.gate(RISKY, home))
            self.assertIsNone(self.gate(SAFE, home, approve_timeout=float("nan")))
            self.assert_gate_denial(self.gate(RISKY, home, approve_timeout=float("nan")))

    def test_gate_failure_uses_config_and_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            push = dict(RISKY, tool_input={"command": "git push origin stable"})
            ssh = dict(RISKY, tool_input={"command": "ssh deploy@prod1"})
            self.assertIsNone(self.gate(push, home))
            self.assertIsNone(self.gate(ssh, home))
            (home / ".agentdeck" / "config.json").write_text(json.dumps(
                {"protected_branches": ["stable"], "production_hosts": ["prod*"]}), encoding="utf-8")
            self.assert_gate_denial(self.gate(push, home))
            self.assert_gate_denial(self.gate(ssh, home))
            (home / ".agentdeck" / "config.json").write_text("{bad", encoding="utf-8")
            self.assertIsNone(self.gate(push, home))  # unreadable config: defaults

    def test_gate_unclassifiable_events_do_not_block_and_are_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            cases = (({}, "cc"), (None, "cc"), ({"hook_event_name": "PreToolUse"}, "cc"),
                     (dict(RISKY, hook_event_name="Stop"), "cc"),
                     (dict(RISKY, tool_name=5), "cc"))
            for event, agent in cases:
                with self.subTest(event=event, agent=agent):
                    self.assertIsNone(self.gate(event, home, agent=agent))
            self.assert_gate_denial(self.gate(RISKY, home, agent="bad"))  # risky stays fail-closed
            log = (home / ".agentdeck" / "relay.log").read_text(encoding="utf-8")
            self.assertIn("classification failed", log)

    def test_gate_cli_passes_option_and_does_not_block_malformed_input_or_exception(self):
        for input_text in ("{}", "bad json"):
            with self.subTest(input_text=input_text):
                output = io.StringIO()
                with tempfile.TemporaryDirectory() as directory:
                    with patch.object(hub_relay, "relay", side_effect=TimeoutError) as relay:
                        self.assertEqual(hub_relay.main(["--agent", "cx", "--gate", "--home", directory],
                            stdin=io.StringIO(input_text), stdout=output), 0)
                        if input_text == "{}":
                            self.assertTrue(relay.call_args.kwargs["gate"])
                self.assertEqual(output.getvalue(), "")

    def test_exact_bytes_auth_and_timeouts(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret\n")
            connection = Connection("127.0.0.1", 47800, 0.5)
            factory = lambda *args, **kwargs: connection
            result = hub_relay.relay({"hook_event_name": "PermissionRequest"}, "cx",
                                     home=home, connection_factory=factory)
            self.assertEqual(result, connection.raw)
            self.assertEqual(connection.read_timeout, 115)
            self.assertEqual(connection.request_data[1], "/event?agent=cx")
            self.assertEqual(connection.request_data[3]["X-AgentDeck-Token"], "secret")
            self.assertTrue(connection.closed)
            result = hub_relay.relay({"hook_event_name": "Stop"}, "cc", home=home,
                                     connection_factory=factory)
            self.assertGreater(connection.read_timeout, 0)
            self.assertLessEqual(connection.read_timeout, 2)
            connection.status = 401
            self.assertIsNone(hub_relay.relay({}, "cc", home=home, connection_factory=factory))
            connection.status, connection.raw = 200, b"not json"
            self.assertIsNone(hub_relay.relay({}, "cc", home=home, connection_factory=factory))

    def test_main_preserves_text_and_silences_failures(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch.object(hub_relay, "relay", return_value=b'{ "a": 1 }\n'):
            self.assertEqual(hub_relay.main(["--agent", "cc", "--home", directory], stdin=io.StringIO("{}"),
                                           stdout=output), 0)
        self.assertEqual(output.getvalue(), '{ "a": 1 }\n')
        for value in ("bad json", "{}"):
            output = io.StringIO()
            with tempfile.TemporaryDirectory() as directory, patch.object(hub_relay, "relay", side_effect=TimeoutError):
                self.assertEqual(hub_relay.main(["--agent", "cc", "--home", directory], stdin=io.StringIO(value),
                                               stdout=output), 0)
            self.assertEqual(output.getvalue(), "")

    def test_failure_diagnostics_stay_in_supplied_home(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret", encoding="utf-8")
            def unavailable(*args, **kwargs):
                raise TimeoutError("offline")

            with patch.object(hub_relay.Path, "home", side_effect=AssertionError("real home")):
                result = hub_relay.relay({"hook_event_name": "PermissionRequest"}, "cx", home=home,
                                         connection_factory=unavailable)
            self.assertIsNone(result)
            self.assertIn("offline", (home / ".agentdeck" / "relay.log").read_text(encoding="utf-8"))

    def test_missing_hub_process_silent_exit_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            token = home / ".agentdeck" / "token"
            for has_token in (False, True):
                if has_token:
                    token.write_text("secret", encoding="utf-8")
                for agent in ("cc", "cx"):
                    with self.subTest(has_token=has_token, agent=agent):
                        start = time.perf_counter()
                        process = subprocess.run(["D:/conda/miniconda3/python.exe", str(Path(hub_relay.__file__)),
                                                  "--agent", agent, "--home", str(home), "--port", "0"],
                            input=json.dumps({"hook_event_name": "PermissionRequest", "session_id": "offline"}),
                            capture_output=True, text=True, timeout=5)
                        self.assertEqual((process.returncode, process.stdout, process.stderr), (0, "", ""))
                        self.assertLess(time.perf_counter() - start, 1.5)

    def run_gate_process(self, stdin, home):
        return subprocess.run(["D:/conda/miniconda3/python.exe", str(Path(hub_relay.__file__)),
            "--agent", "cc", "--gate", "--home", str(home), "--port", "0"],
            input=stdin, capture_output=True, text=True, timeout=5)

    def test_missing_hub_process_gate_denies_risky_and_passes_the_rest(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".agentdeck").mkdir()
            (home / ".agentdeck" / "token").write_text("secret", encoding="utf-8")
            for event in (RISKY, CURL_SH):
                process = self.run_gate_process(json.dumps(event), home)
                self.assertEqual((process.returncode, process.stderr), (0, ""))
                self.assert_gate_denial(process.stdout)
            for stdin in (json.dumps(SAFE), json.dumps({"hook_event_name": "PreToolUse"}), "not json"):
                process = self.run_gate_process(stdin, home)
                self.assertEqual((process.returncode, process.stdout, process.stderr), (0, "", ""))

    def test_gate_failure_path_is_fast_and_light(self):
        import time
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            start = time.perf_counter()
            process = self.run_gate_process(json.dumps(SAFE), home)
            elapsed = time.perf_counter() - start
            self.assertEqual(process.stdout, "")
            self.assertLess(elapsed, 1.5)  # generous CI bound; ~0.1s locally
            check = subprocess.run(["D:/conda/miniconda3/python.exe", "-c",
                "import sys;sys.path.insert(0,%r);import hub_relay,hub_risk;"
                "print(any(m in sys.modules for m in ('serial','tkinter','usb','hub','daemon')))" %
                str(Path(hub_relay.__file__).parent)], capture_output=True, text=True, timeout=10)
            self.assertEqual(check.stdout.strip(), "False")


class RelayHardeningTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.data = self.home / ".agentdeck"
        self.data.mkdir()
        (self.data / "token").write_text("test-token", encoding="utf-8")

    def test_log_format_truncation_and_no_stdin_payload(self):
        event = {"hook_event_name": "StopFailure", "session_id": "abcdefgh-rest",
                 "tool_input": "private-stdin-never-log", "last_assistant_message": "also-private"}
        hub_relay._log(self.home, "cc", event, ValueError("first\r\n" + "x" * 400))
        line = (self.data / "relay.log").read_text(encoding="utf-8").rstrip("\n")
        prefix = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} cc StopFailure abcdefgh "
        self.assertRegex(line, prefix)
        message = re.sub(prefix, "", line)
        self.assertEqual(len(message), 300)
        self.assertTrue(message.startswith("ValueError: first\\r\\n"))
        self.assertNotIn("private", line)
        self.assertNotIn("\r", line)
        hub_relay._log(self.home, None, None, "missing")
        last = (self.data / "relay.log").read_text(encoding="utf-8").splitlines()[-1]
        self.assertRegex(last, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} - - - missing$")

    def test_log_escapes_controls_and_preserves_printable_unicode(self):
        hub_relay._log(self.home, "中\tcc", {"hook_event_name": "事件\x07\r\n", "session_id": "s\x00"},
                       "消息\x07\t\r\n\x1b\u2028\ud800")
        lines = (self.data / "relay.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith(
            "中\\tcc 事件\\x07\\r\\n s\\x00 消息\\x07\\t\\r\\n\\x1b\\u2028\\ud800"))
        self.assertTrue(lines[0].isprintable())

    def test_hostile_log_fields_are_capped_and_write_one_line(self):
        event = {"hook_event_name": "事件\x07\n" * 5000, "session_id": "session-id"}
        hub_relay._log(self.home, "agent\x00\r\n" * 5000, event, "message\x1b\n" * 5000)
        contents = (self.data / "relay.log").read_text(encoding="utf-8")
        self.assertEqual(contents.count("\n"), 1)
        line = contents[:-1]
        self.assertEqual(len(line), 400)
        self.assertTrue(line.isprintable())
        _, _, agent, name, session, message = line.split(" ", 5)
        self.assertLessEqual(len(agent), 64)
        self.assertLessEqual(len(name), 64)
        self.assertEqual(session, "session-")
        self.assertIn("事件\\x07\\n", name)
        self.assertIn("\\x00\\r\\n", agent)
        self.assertIn("\\x1b\\n", message)

    def test_unsupported_hook_warning_uses_the_same_escaping_and_cap(self):
        import hub

        name = "未知\x07\n\x1b" * 5000
        with patch.object(hub, "UNKNOWN_EVENTS", set()), self.assertLogs("agentdeck.hub", "WARNING") as logs:
            with self.assertRaises(hub.HubError):
                hub.Hub.event(Mock(monotonic=lambda: 0.), "cc", {"hook_event_name": name, "session_id": "s"})
        self.assertEqual(len(logs.output), 1)
        short_name = logs.output[0].split("Unsupported hook_event_name: ", 1)[1]
        self.assertEqual(short_name, hub_relay.escape_log_text(name, 64))
        self.assertLessEqual(len(short_name), 64)
        self.assertTrue(short_name.isprintable())
        self.assertIn("未知\\x07\\n\\x1b", short_name)

    def test_log_rotates_at_512_kib_and_replaces_previous_backup(self):
        path = self.data / "relay.log"
        backup = self.data / "relay.log.1"
        backup.write_text("old backup", encoding="utf-8")
        path.write_bytes(b"x" * (512 * 1024 - 1))
        hub_relay._log(self.home, "cx", {}, "cross threshold")
        self.assertEqual(backup.read_text(encoding="utf-8"), "old backup")
        previous = path.read_bytes()
        hub_relay._log(self.home, "cx", {}, "new file")
        self.assertEqual(backup.read_bytes(), previous)
        self.assertTrue(path.read_text(encoding="utf-8").endswith("cx - - new file\n"))

    def test_malformed_stdin_logs_only_exception_without_input_bytes(self):
        private_input = "secret stdin payload\nnot-json"
        output = io.StringIO()
        self.assertEqual(hub_relay.main(["--agent", "cc", "--home", str(self.home)],
            stdin=io.StringIO(private_input), stdout=output), 0)
        self.assertEqual(output.getvalue(), "")
        line = (self.data / "relay.log").read_text(encoding="utf-8")
        self.assertIn(" cc - - JSONDecodeError: ", line)
        self.assertNotIn("secret", line)
        self.assertNotIn("not-json", line)

    def test_non_200_status_and_capped_error_are_logged(self):
        connection = Connection("127.0.0.1", 1, 0.1)
        connection.status = 429
        connection.raw = json.dumps({"error": "e" * 120, "private": "never-log-response"}).encode("ascii")
        self.assertIsNone(hub_relay.relay(dict(TURN, session_id="session12345"), "cc", home=self.home,
            connection_factory=lambda *args, **kwargs: connection))
        line = (self.data / "relay.log").read_text(encoding="utf-8")
        self.assertIn("cc UserPromptSubmit session1 hub status 429: " + "e" * 100 + "\n", line)
        self.assertNotIn("e" * 101, line)
        self.assertNotIn("private", line)
        connection.raw = b"not-json"
        hub_relay.relay(TURN, "cc", home=self.home, connection_factory=lambda *args, **kwargs: connection)
        self.assertIn("hub status 429:", (self.data / "relay.log").read_text(encoding="utf-8"))

    def test_stop_failure_and_agent_id_are_forwarded_with_caps(self):
        event = {"hook_event_name": "StopFailure", "session_id": "s", "agent_id": "child-1",
                 "error": "e" * 100, "error_details": "d" * 600,
                 "last_assistant_message": "discard-prefix" + "尾" * 4000,
                 "tool_response": "private-large-response"}
        body = json.loads(hub_relay._body(event, None, False))
        self.assertEqual(body["agent_id"], "child-1")
        self.assertEqual(body["error"], "e" * 64)
        self.assertEqual(body["error_details"], "d" * 300)
        self.assertEqual(body["last_assistant_message"], "尾" * 4000)
        self.assertNotIn("tool_response", body)
        for name in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
            self.assertEqual(json.loads(hub_relay._body(dict(event, hook_event_name=name), None, False))["agent_id"],
                             "child-1")

    def test_session_end_reason_is_forwarded_capped_and_only_for_session_end(self):
        event = {"hook_event_name": "SessionEnd", "session_id": "s", "reason": "r" * 100,
                 "transcript_path": "C:/private/transcript.jsonl"}
        body = json.loads(hub_relay._body(event, None, False))
        self.assertEqual(body["reason"], "r" * 64)
        # Loopback only: the local hub reads the Claude sidebar title from this path.
        self.assertEqual(body["transcript_path"], "C:/private/transcript.jsonl")
        self.assertNotIn("reason", json.loads(hub_relay._body(dict(event, hook_event_name="Stop"), None, False)))
        self.assertNotIn("reason", json.loads(hub_relay._body(dict(event, reason=5), None, False)))

    def test_ordinary_socket_timeouts_share_one_deadline(self):
        connection = Connection("127.0.0.1", 1, 0.1)
        timeouts = []
        connection.settimeout = timeouts.append
        ticks = iter([10, 10.1, 10.4, 10.9, 11.6])
        with patch.object(hub_relay.time, "monotonic", side_effect=lambda: next(ticks)):
            self.assertIsNotNone(hub_relay.relay(TURN, "cc", home=self.home,
                connection_factory=lambda *args, **kwargs: connection))
        self.assertEqual(len(timeouts), 3)
        for actual, expected in zip(timeouts, (1.6, 1.1, 0.4)):
            self.assertAlmostEqual(actual, expected)

    def test_hub_accepting_but_never_replying_returns_within_2_5_seconds(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)
        release = threading.Event()
        failures = []

        def stall():
            try:
                with listener.accept()[0] as connection:
                    connection.recv(65536)
                    release.wait(5)
            except Exception as error:
                failures.append(error)

        thread = threading.Thread(target=stall, daemon=True)
        thread.start()
        port = listener.getsockname()[1]
        (self.data / "hub.json").write_text(json.dumps({"pid": os.getpid(), "port": port}), encoding="utf-8")
        environment = dict(os.environ, AGENTDECK_NO_WINDOW="1")
        began = time.monotonic()
        try:
            process = subprocess.run(["D:/conda/miniconda3/python.exe", "-X", "utf8", hub_relay.__file__,
                "--agent", "cc", "--home", str(self.home), "--port", str(port)],
                input=json.dumps(TURN).encode("utf-8"), capture_output=True, timeout=4, env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            elapsed = time.monotonic() - began
        finally:
            release.set()
            listener.close()
            thread.join(2)
        self.assertEqual(failures, [])
        self.assertEqual((process.returncode, process.stdout, process.stderr), (0, b"", b""))
        self.assertLessEqual(elapsed, 2.5)
        self.assertIn("TimeoutError:", (self.data / "relay.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
