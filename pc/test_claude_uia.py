"""Offline UIA bridge checks: every process and pipe is a fake."""
import json
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import unittest
from unittest.mock import call, patch

from claude_uia import ClaudeUIA


class Output:
    def __init__(self):
        self.lines = queue.Queue()
        self.closed = False

    def readline(self):
        return self.lines.get()

    def close(self):
        self.closed = True


class Input:
    def __init__(self, process):
        self.process = process
        self.text = ''
        self.closed = False

    def write(self, text):
        if self.process.returncode is not None:
            raise BrokenPipeError('process exited')
        self.text += text

    def flush(self):
        request = json.loads(self.text)
        self.text = ''
        self.process.requests.append(request)
        response = self.process.respond(request)
        if response is not None:
            if isinstance(response, dict):
                response = json.dumps(dict(response, id=request['id']), ensure_ascii=False)
            self.process.stdout.lines.put(response + '\n')

    def close(self):
        self.closed = True


class Process:
    def __init__(self, respond):
        self.respond = respond
        self.returncode = None
        self.requests = []
        self.stdout = Output()
        self.stdin = Input(self)
        self.killed = 0

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed += 1
        self.returncode = -1
        self.stdout.lines.put('')

    def wait(self, timeout=None):
        return self.returncode


SNAPSHOT = {'ok': True, 'hwnd': 101, 'current_title': '现状与前景讨论',
            'sessions': [{'title': '现状与前景讨论', 'status': 'Running'},
                         {'title': '授权 BibiGPT MCP', 'status': 'Started by Claude from desktop'}]}


class BridgeTests(unittest.TestCase):
    def bridge(self, *responders, timeout=.08):
        self.processes = []
        self.launches = []
        remaining = iter(responders or (lambda request: SNAPSHOT,))

        def launch(args, **kwargs):
            process = Process(next(remaining))
            self.processes.append(process)
            self.launches.append((args, kwargs))
            return process

        bridge = ClaudeUIA(popen=launch, timeout=timeout)
        self.addCleanup(bridge.close)
        return bridge

    def test_lazy_persistent_list_and_unicode_encoding(self):
        bridge = self.bridge()
        self.assertEqual(self.processes, [])
        self.assertEqual(bridge.list(hwnd=101), SNAPSHOT)
        self.assertEqual(bridge.list(), SNAPSHOT)
        self.assertEqual(len(self.processes), 1)
        self.assertEqual(self.processes[0].requests[0], {'command': 'list', 'id': 1, 'hwnd': 101})
        args, options = self.launches[0]
        self.assertEqual(args[0], 'powershell.exe')
        self.assertIn('-NoProfile', args)
        self.assertIn('-NonInteractive', args)
        self.assertEqual(options['encoding'], 'utf-8')
        self.assertEqual(options['creationflags'], getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def test_invoke_exact_unicode_title_and_duplicate_index(self):
        bridge = self.bridge(lambda request: {'ok': True, 'title': request['title'],
                                              'index': request['index'], 'matches': 2, 'hwnd': 101})
        self.assertEqual(bridge.invoke('同名 “会话”', index=1, hwnd=101),
                         {'ok': True, 'title': '同名 “会话”', 'index': 1, 'matches': 2, 'hwnd': 101})
        self.assertEqual(self.processes[0].requests[0]['title'], '同名 “会话”')

    def test_panes_preserve_chat_and_unknown_fields_when_sorting_rectangles(self):
        bridge = self.bridge(lambda request: {'ok': True, 'hwnd': 101,
                             'panes': [{'rect': [600.5, 0, 1000, 800], 'chat': False, 'future': 'right'},
                                       {'rect': [10.5, 45, 500, 800], 'chat': True, 'future': {'kept': 1}}]})
        self.assertEqual(bridge.panes(hwnd=101),
                         {'ok': True, 'hwnd': 101,
                          'panes': [{'rect': [10, 45, 500, 800], 'chat': True, 'future': {'kept': 1}},
                                    {'rect': [600, 0, 1000, 800], 'chat': False, 'future': 'right'}]})
        self.assertEqual(self.processes[0].requests[0], {'command': 'panes', 'id': 1, 'hwnd': 101})

    def test_invoke_passes_optional_group_without_changing_legacy_request(self):
        bridge = self.bridge(lambda request: {'ok': True, 'expanded': True})
        self.assertEqual(bridge.invoke('同名标题', group='h1', hwnd=101),
                         {'ok': True, 'expanded': True})
        self.assertEqual(self.processes[0].requests[0],
                         {'command': 'invoke', 'id': 1, 'hwnd': 101,
                          'title': '同名标题', 'index': 0, 'group': 'h1'})
        bridge.invoke('同名标题')
        self.assertNotIn('group', self.processes[0].requests[1])

    def test_invoke_waits_ten_seconds_and_list_keeps_five_second_default(self):
        bridge = self.bridge(lambda request: SNAPSHOT, timeout=None)
        bridge.list()
        with patch.object(bridge._responses, 'get', wraps=bridge._responses.get) as wait:
            self.assertIsNotNone(bridge.invoke('target'))
            self.assertEqual(bridge.list(), SNAPSHOT)
        self.assertEqual(wait.call_args_list, [call(timeout=10.0), call(timeout=5.0)])
        self.assertNotIn('timeout', self.processes[0].requests[1])

    def test_not_found_returns_none_without_replaying_or_restarting(self):
        bridge = self.bridge(lambda request: {'ok': False, 'error': 'Session title not found'}
                             if request['command'] == 'invoke' else SNAPSHOT)
        self.assertIsNone(bridge.invoke('missing'))
        self.assertEqual(bridge.list(), SNAPSHOT)
        self.assertEqual(len(self.processes), 1)
        self.assertEqual([item['command'] for item in self.processes[0].requests], ['invoke', 'list'])

    def test_timeout_kills_child_and_next_command_restarts(self):
        bridge = self.bridge(lambda request: None, lambda request: SNAPSHOT, timeout=.03)
        started = time.monotonic()
        self.assertIsNone(bridge.invoke('slow'))
        self.assertLess(time.monotonic() - started, .6)
        self.assertEqual(self.processes[0].killed, 1)
        self.assertEqual(bridge.list(), SNAPSHOT)
        self.assertEqual(len(self.processes), 2)
        self.assertEqual(len(self.processes[0].requests), 1)

    def test_dead_process_restarts_before_command(self):
        bridge = self.bridge(lambda request: SNAPSHOT, lambda request: SNAPSHOT)
        bridge.list()
        self.processes[0].returncode = 4
        self.assertEqual(bridge.list(), SNAPSHOT)
        self.assertEqual(len(self.processes), 2)
        self.assertTrue(self.processes[0].stdin.closed)

    def test_invalid_json_discards_process_and_restarts(self):
        bridge = self.bridge(lambda request: '{bad json', lambda request: SNAPSHOT)
        self.assertIsNone(bridge.list())
        self.assertEqual(self.processes[0].killed, 1)
        self.assertEqual(bridge.list(), SNAPSHOT)

    def test_wrong_request_id_is_rejected(self):
        bridge = self.bridge(lambda request: '{"id": 999, "ok": true}')
        self.assertIsNone(bridge.list())
        self.assertEqual(self.processes[0].killed, 1)

    def test_broken_pipe_is_failure_and_is_not_replayed(self):
        def broken(request):
            raise BrokenPipeError('broken')

        bridge = self.bridge(broken, lambda request: SNAPSHOT)
        self.assertIsNone(bridge.invoke('target'))
        self.assertEqual(bridge.list(), SNAPSHOT)
        self.assertEqual(len(self.processes), 2)

    def test_blocked_stdin_is_also_bounded(self):
        blocked = threading.Event()

        def waiting(request):
            blocked.wait(.5)
            return SNAPSHOT

        bridge = self.bridge(waiting, timeout=.02)
        started = time.monotonic()
        self.assertIsNone(bridge.list())
        elapsed = time.monotonic() - started
        blocked.set()
        self.assertLess(elapsed, .4)
        self.assertEqual(self.processes[0].killed, 1)

    def test_eof_and_invalid_list_schema_return_none(self):
        bridge = self.bridge(lambda request: None)
        # Simulate a child exiting without a JSON reply, rather than a timeout.
        def eof(request):
            self.processes[0].stdout.lines.put('')

        bridge._popen = self._launch_eof(eof)
        self.assertIsNone(bridge.list())
        malformed = self.bridge(lambda request: {'ok': True, 'sessions': [{}]})
        self.assertIsNone(malformed.list())

    def _launch_eof(self, respond):
        def launch(*args, **kwargs):
            process = Process(respond)
            self.processes.append(process)
            return process
        return launch

    def test_close_is_idempotent_and_never_starts_unused_child(self):
        bridge = self.bridge()
        bridge.close()
        bridge.close()
        self.assertIsNone(bridge.list())
        self.assertEqual(self.processes, [])
        second = self.bridge()
        second.list()
        process = self.processes[0]
        second.close()
        second.close()
        self.assertEqual(process.killed, 1)
        self.assertTrue(process.stdin.closed and process.stdout.closed)

    def test_invalid_parameters_do_not_start_process(self):
        bridge = self.bridge()
        for title in ('', ' ', None, 1):
            with self.subTest(title=title), self.assertRaises(ValueError):
                bridge.invoke(title)
        for index in (-1, True, '1'):
            with self.subTest(index=index), self.assertRaises(ValueError):
                bridge.invoke('title', index=index)
        for group in ('', ' ', 1, 'x' * 4097):
            with self.subTest(group=group), self.assertRaises(ValueError):
                bridge.invoke('title', group=group)
        for hwnd in (0, -1, True, '101'):
            with self.subTest(hwnd=hwnd), self.assertRaises(ValueError):
                bridge.list(hwnd=hwnd)
        self.assertEqual(self.processes, [])


class SidebarScriptTests(unittest.TestCase):
    def test_source_is_ascii(self):
        Path(__file__).with_name('claude_uia.ps1').read_bytes().decode('ascii')

    @unittest.skipUnless(shutil.which('powershell.exe'), 'Windows PowerShell unavailable')
    def test_offline_group_selection_expand_poll_and_restore(self):
        # Parse and load only pure selection/orchestration functions. Every UI
        # snapshot, pattern operation and sleep below is a fake.
        path = str(Path(__file__).with_name('claude_uia.ps1')).replace("'", "''")
        script = r'''
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('__PATH__', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$needed = @('Get-SessionMatches', 'Find-SnapshotButton', 'Invoke-ClaudeSession')
$ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true) |
    Where-Object { $_.Name -in $needed } | ForEach-Object { Invoke-Expression $_.Extent.Text }
function Button($name) { return @{ Current = @{ Name = $name } } }
$first = @{title='Alpha'; group='one'; button=(Button 'first')}
$second = @{title='Alpha'; group='two'; button=(Button 'second')}
$open = @{hwnd=11; entries=@($first, $second); buttons=@((Button 'Hide sidebar'))}
$closed = @{hwnd=11; entries=@(); buttons=@((Button 'Show sidebar'))}
$empty = @{hwnd=11; entries=@(); buttons=@((Button 'Hide sidebar'))}
$request = @{id=1; title='Alpha'; index=0; group='two'}
$script:calls = @()
$script:reads = 0
$script:sleeps = 0
$script:mode = 'delayed'
function Expand-Sidebar($button) { $script:calls += 'expand' }
function Start-Sleep {
    param($Milliseconds)
    $script:sleeps++
    if ($Milliseconds -ne 100) { throw 'wrong poll' }
    if ($script:mode -eq 'deadline') { $script:requestClock.ElapsedMilliseconds += $Milliseconds }
}
function Invoke-Button($button) {
    $script:calls += $button.Current.Name
    if ($script:mode -eq 'failure' -and $button.Current.Name -eq 'second') { throw 'click failed' }
}
function Get-ClaudeSnapshot($request) {
    $script:reads++
    if ($script:mode -eq 'deadline') {
        $before = $script:requestClock.ElapsedMilliseconds
        $script:requestClock.ElapsedMilliseconds += 200
        if ($before -lt 5000) { return $empty }
        $script:restoreStartedAt = $before
        return $open
    }
    if ($script:mode -eq 'timeout' -or ($script:mode -eq 'delayed' -and $script:reads -lt 3)) { return $empty }
    return $open
}
$grouped = @(Get-SessionMatches $open $request)
if ($grouped.Count -ne 1 -or $grouped[0].button.Current.Name -ne 'second') { throw 'wrong group' }
$request.group = 'missing'
if (@(Get-SessionMatches $open $request).Count -ne 2) { throw 'group fallback changed' }
$request.Remove('group')
$request.index = 1
$legacy = Invoke-ClaudeSession $request $open
if (-not $legacy.ok -or $legacy.expanded -or ($script:calls -join ',') -ne 'second') { throw 'legacy selection changed' }
$request.group = 'two'; $request.index = 0
$script:calls = @()
$delayed = Invoke-ClaudeSession $request $closed
if (-not $delayed.ok -or -not $delayed.expanded -or $script:sleeps -ne 3 -or
        ($script:calls -join ',') -ne 'expand,second,Hide sidebar') { throw 'expand/poll/restore failed' }
$script:mode = 'timeout'; $script:calls = @(); $script:sleeps = 0
$timeout = Invoke-ClaudeSession $request $closed
if ($timeout.ok -or -not $timeout.expanded -or $script:sleeps -ne 25 -or
        ($script:calls -join ',') -ne 'expand,Hide sidebar') { throw 'timeout restore failed' }
$script:mode = 'failure'; $script:calls = @()
$failure = Invoke-ClaudeSession $request $closed
if ($failure.ok -or -not $failure.expanded -or
        ($script:calls -join ',') -ne 'expand,second,Hide sidebar') { throw 'failed click restore failed' }
$script:calls = @()
$absent = Invoke-ClaudeSession $request $empty
if ($absent.ok -or $absent.expanded -or $script:calls.Count) { throw 'must not close an existing sidebar' }
$script:mode = 'deadline'; $script:calls = @(); $script:sleeps = 0; $script:reads = 0
# The initial snapshot already consumed 4.6s of the request's seven-second budget.
$script:requestClock = [pscustomobject]@{ElapsedMilliseconds=4600}
$deadline = Invoke-ClaudeSession $request $closed $script:requestClock
if ($deadline.ok -or -not $deadline.expanded -or $script:sleeps -ne 2 -or $script:reads -ne 2 -or
        $script:restoreStartedAt -ne 5000 -or $script:requestClock.ElapsedMilliseconds -ne 5200 -or
        ($script:calls -join ',') -ne 'expand,Hide sidebar') { throw 'deadline did not reserve restore time' }
$script:calls = @()
$expired = Invoke-ClaudeSession $request $closed ([pscustomobject]@{ElapsedMilliseconds=5000})
if ($expired.ok -or $expired.expanded -or $script:calls.Count) { throw 'expired request expanded sidebar' }
@{group=$true; legacy=$true; delayed=$delayed; timeout=$timeout; failure=$failure; absent=$absent;
    deadline=$deadline; expired=$expired} |
    ConvertTo-Json -Compress -Depth 5
'''.replace('__PATH__', path)
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, text=True, encoding='utf-8', timeout=15,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        checked = json.loads(result.stdout)
        self.assertTrue(checked['group'] and checked['legacy'])
        self.assertTrue(checked['delayed']['expanded'])
        self.assertFalse(checked['timeout']['ok'])
        self.assertTrue(checked['deadline']['expanded'])
        self.assertFalse(checked['deadline']['ok'])
        self.assertFalse(checked['expired']['expanded'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
