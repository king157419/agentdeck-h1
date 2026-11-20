"""Relay tests inject HTTP transports and temporary homes; no live hub required."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import hub_relay


RISKY = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
         "tool_input": {"command": "git push --force origin main"}}
CURL_SH = dict(RISKY, tool_input={"command": "curl x | sh"})
SAFE = dict(RISKY, tool_input={"command": "ls"})
# Turn-level event: the relay looks up the agent window only for these.
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

    def test_permission_and_gate_keep_exact_bytes_without_finding_windows(self):
        finder = Mock(side_effect=AssertionError("decision path must not enumerate windows"))
        for gate, name in ((False, "PermissionRequest"), (True, "PreToolUse")):
            with self.subTest(gate=gate):
                raw = (' { "hook_event_name": "%s", "tool_name": "Bash", '
                       '"cwd": "D:/项目", "tool_input": {"command": "ls"} }\n' % name).encode("utf-8")
                self.assertEqual(self.forward(json.loads(raw), raw=raw, gate=gate, window_finder=finder), b"{}")
                self.assertEqual(self.connection.request_data[2], raw)
                self.assertNotIn("agentdeck_window", json.loads(self.connection.request_data[2]))
        finder.assert_not_called()

    def test_tool_events_skip_the_lookup(self):
        finder = Mock(return_value=self.window)
        for name in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
            with self.subTest(name=name):
                self.assertEqual(self.forward(dict(SAFE, hook_event_name=name), window_finder=finder), b"{}")
                self.assertNotIn("agentdeck_window", json.loads(self.connection.request_data[2]))
        finder.assert_not_called()
        for name in hub_relay.WINDOW_EVENTS:
            self.forward(dict(TURN, hook_event_name=name), window_finder=finder)
        self.assertEqual(finder.call_count, len(hub_relay.WINDOW_EVENTS))

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
            self.assertEqual(connection.read_timeout, 5)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
