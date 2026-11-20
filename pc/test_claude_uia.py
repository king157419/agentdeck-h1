"""Offline UIA bridge checks: every process and pipe is a fake."""
import json
import queue
import subprocess
import threading
import time
import unittest

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
        for hwnd in (0, -1, True, '101'):
            with self.subTest(hwnd=hwnd), self.assertRaises(ValueError):
                bridge.list(hwnd=hwnd)
        self.assertEqual(self.processes, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
