"""Offline approval nonce acceptance tests; no serial port or live hub access."""
import http.client
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hub
from hub_hotkey import HotkeyKeys
from test_hub import Clock


class NonceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.clock = Clock()
        self.engine = hub.Hub(home=temp.name, monotonic=self.clock,
                              lcd_enabled=False, desktop_enabled=False,
                              hold_path=Path(temp.name) / 'hold')
        self.addCleanup(self.engine.close)
        self.counter = 0

    def request(self, risk='low'):
        self.counter += 1
        sid = 'nonce-session-%s' % self.counter
        self.engine.event('cc', {'hook_event_name': 'SessionStart',
                                 'session_id': sid, 'cwd': 'C:/nonce'})
        request = hub.Pending('nonce-request-%s' % self.counter, ('cc', sid),
                              'Bash', 'echo safe', risk, 1.0,
                              self.clock() + 110)
        with self.engine.lock:
            self.engine.pending[request.id] = request
            if self.engine.displayed_request_id is None:
                self.engine._next_request()
        return request

    def approve(self, request, **fields):
        return self.engine.action(dict(action='approve', nonce=request.nonce, **fields))

    def reject(self, payload, reason='stale_nonce'):
        with self.assertRaises(hub.HubError) as caught:
            self.engine.action(payload)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(str(caught.exception), reason)

    def snapshot(self):
        return (self.engine.displayed_request_id,
                [(p.id, p.status, p.armed_at, dict(p.response), p.ready.is_set())
                 for p in self.engine.pending.values()])

    def test_nonce_is_random_32_bit_and_public(self):
        with patch.object(hub.secrets, 'randbits', return_value=0x1234ABCD) as random:
            request = self.request()
        random.assert_called_once_with(32)
        self.assertEqual(request.nonce, 0x1234ABCD)
        self.assertEqual(self.engine.state()['pending'][0]['nonce'], request.nonce)
        self.assertIs(self.engine.state()['nonce_required'], False)

    def test_matching_nonce_approves(self):
        request = self.request()
        self.clock.value += .301
        self.assertEqual(self.approve(request, request_id=request.id)['status'], 'allowed')
        self.assertTrue(request.ready.is_set())

    def test_mismatch_rejects_without_mutation(self):
        request = self.request()
        self.clock.value += .301
        before = self.snapshot()
        self.reject({'action': 'approve', 'nonce': request.nonce ^ 1})
        self.assertEqual(self.snapshot(), before)

    def test_invalid_nonce_types_never_coerce(self):
        request = self.request()
        self.clock.value += .301
        for nonce in (None, True, False, str(request.nonce), float(request.nonce), [], {}):
            with self.subTest(nonce=nonce):
                before = self.snapshot()
                self.reject({'action': 'approve', 'nonce': nonce})
                self.assertEqual(self.snapshot(), before)

    def test_malformed_nan_and_nested_nonce_values_are_auditable(self):
        self.request()
        for nonce in (float('nan'), float('inf'), {'nested': [float('nan')]}, [None, {'nonce': 7}]):
            with self.subTest(nonce=repr(nonce)):
                before = self.snapshot()
                self.reject({'action': 'approve', 'nonce': nonce})
                self.assertEqual(self.snapshot(), before)
                record = self.engine.audit.recent(1)[0]
                self.assertEqual(record['supplied_nonce'], repr(nonce)[:160])
                self.assertEqual(record['reason'], 'stale_nonce')

    def test_correct_nonce_wrong_request_id_rejects(self):
        request = self.request()
        self.clock.value += .301
        before = self.snapshot()
        self.reject({'action': 'deny', 'nonce': request.nonce, 'request_id': 'old'})
        self.assertEqual(self.snapshot(), before)

    def test_non_displayed_pending_nonce_rejects(self):
        first = self.request()
        second = self.request()
        self.clock.value += .301
        before = self.snapshot()
        self.reject({'action': 'approve', 'nonce': second.nonce, 'request_id': second.id})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.engine.displayed_request_id, first.id)

    def test_expiry_boundary_rejects_without_expiring_or_arming(self):
        request = self.request('high')
        self.clock.value = request.deadline
        before = self.snapshot()
        self.reject({'action': 'approve', 'nonce': request.nonce})
        self.assertEqual(self.snapshot(), before)

    def test_expired_nonce_cannot_replay_after_maintenance_and_new_request(self):
        expired = self.request()
        self.clock.value = expired.deadline
        self.engine.maintain()
        replacement = self.request()
        self.clock.value += .301
        before = self.snapshot()
        self.reject({'action': 'approve', 'nonce': expired.nonce, 'request_id': expired.id})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.approve(replacement)['status'], 'allowed')

    def test_real_requests_resample_expired_nonce_collision_before_accepting_replay(self):
        threads = []
        errors = []

        def start_request(sid):
            def request():
                try:
                    self.engine.event('cc', {'hook_event_name': 'PermissionRequest',
                                            'session_id': sid, 'cwd': 'C:/nonce',
                                            'tool_name': 'Bash', 'tool_input': {'command': 'echo safe'}})
                except Exception as error:
                    errors.append(error)

            thread = threading.Thread(target=request, daemon=True)
            threads.append(thread)
            thread.start()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                with self.engine.lock:
                    found = next((p for p in self.engine.pending.values() if p.session[1] == sid), None)
                if found is not None:
                    return found
                if errors:
                    raise errors[0]
                time.sleep(.002)
            self.fail('real permission event did not create pending request')

        try:
            with patch.object(hub.secrets, 'randbits', side_effect=[0x12345678, 0x12345678, 0x87654321]) as random:
                expired = start_request('collision-first')
                self.clock.value = expired.deadline
                self.engine.maintain()
                replacement = start_request('collision-second')
                self.assertEqual(expired.nonce, 0x12345678)
                self.assertEqual(replacement.nonce, 0x87654321)
                self.assertEqual(random.call_count, 3)
                self.clock.value += .301
                before = self.snapshot()
                self.reject({'action': 'approve', 'nonce': expired.nonce})
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.approve(replacement)['status'], 'allowed')
        finally:
            self.engine.close()
            for thread in threads:
                thread.join(2)
                self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_initial_switch_guard_and_boundary(self):
        request = self.request()
        before = self.snapshot()
        self.reject({'action': 'approve', 'nonce': request.nonce}, 'switch_guard')
        self.assertEqual(self.snapshot(), before)
        self.clock.value += .299
        self.reject({'action': 'approve', 'nonce': request.nonce}, 'switch_guard')
        self.clock.value += .002
        self.assertEqual(self.approve(request)['status'], 'allowed')

    def test_queue_switch_restarts_guard_and_deny_is_exempt(self):
        first = self.request()
        second = self.request()
        self.clock.value += .301
        self.approve(first)
        self.reject({'action': 'approve', 'nonce': second.nonce}, 'switch_guard')
        self.assertEqual(self.engine.action({'action': 'deny', 'nonce': second.nonce})['status'], 'denied')

    def test_deny_is_exempt_from_initial_guard(self):
        request = self.request()
        self.assertEqual(self.engine.action({'action': 'deny', 'nonce': request.nonce})['status'], 'denied')

    def test_high_risk_second_wrong_nonce_preserves_armed_state(self):
        request = self.request('high')
        self.clock.value += .301
        self.assertEqual(self.approve(request)['status'], 'confirm')
        before = self.snapshot()
        self.reject({'action': 'approve', 'nonce': request.nonce ^ 1})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.approve(request)['status'], 'allowed')

    def test_legacy_missing_nonce_works_after_guard(self):
        self.request()
        self.reject({'action': 'approve'}, 'switch_guard')
        self.clock.value += .301
        self.assertEqual(self.engine.action({'action': 'approve'})['status'], 'allowed')

    def test_require_nonce_rejects_missing_approve_but_keeps_legacy_deny(self):
        self.engine.require_nonce = True
        self.request()
        self.clock.value += .301
        before = self.snapshot()
        self.reject({'action': 'approve'}, 'nonce_required')
        self.assertEqual(self.snapshot(), before)
        self.assertIs(self.engine.state()['nonce_required'], True)
        self.assertEqual(self.engine.action({'action': 'deny'})['status'], 'denied')

    def test_require_nonce_constructor_requires_strict_boolean(self):
        for value in (None, 0, 1, 'true', [], {}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'require_nonce must be a boolean'):
                    hub.Hub(require_nonce=value)
        with tempfile.TemporaryDirectory() as home:
            engine = hub.Hub(home=home, require_nonce=True, lcd_enabled=False, desktop_enabled=False)
            try:
                self.assertIs(engine.state()['nonce_required'], True)
            finally:
                engine.close()

    def test_main_forwards_require_nonce_from_explicit_config(self):
        class ConstructorReached(Exception):
            pass

        with tempfile.TemporaryDirectory() as home:
            config = Path(home) / 'nonce-config.json'
            config.write_text(json.dumps({'require_nonce': True}), encoding='utf-8')
            with patch.object(hub, 'Hub', side_effect=ConstructorReached) as constructor:
                with self.assertRaises(ConstructorReached):
                    hub.main(['--config', str(config), '--home', home,
                              '--no-lcd', '--no-desktop', '--backend', 'none'])
            self.assertIs(constructor.call_args.kwargs['require_nonce'], True)

    def test_locked_request_accepts_current_nonce_without_unlocking(self):
        request = self.request('critical')
        self.engine.pending.pop(request.id)
        request.status = 'locked'
        self.engine.locked[request.id] = request
        for action in ('approve', 'deny'):
            result = self.engine.action({'action': action, 'nonce': request.nonce})
            self.assertEqual(result['status'], 'locked')
            self.assertIs(self.engine.locked[request.id], request)
            self.assertEqual(request.status, 'locked')

    def test_locked_wrong_or_expired_nonce_rejects_without_mutation(self):
        request = self.request('critical')
        self.engine.pending.pop(request.id)
        request.status = 'locked'
        self.engine.locked[request.id] = request
        before = (request.status, request.armed_at, dict(request.response), request.ready.is_set())
        self.reject({'action': 'approve', 'nonce': request.nonce ^ 1})
        self.clock.value = request.deadline
        self.reject({'action': 'deny', 'nonce': request.nonce})
        self.assertIs(self.engine.locked[request.id], request)
        self.assertEqual((request.status, request.armed_at, request.response, request.ready.is_set()), before)

    def test_high_and_critical_gates_preserve_armed_state_on_wrong_second_nonce(self):
        for risk in ('high', 'critical'):
            with self.subTest(risk=risk):
                request = self.request(risk)
                request.gate = True
                self.clock.value += .301
                self.assertEqual(self.approve(request)['status'], 'confirm')
                before = self.snapshot()
                self.reject({'action': 'approve', 'nonce': request.nonce ^ 1})
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.approve(request)['status'], 'allowed')
                self.assertTrue(request.ready.is_set())
                self.assertEqual(request.response, {})
                self.assertIn((request.session, request.input_hash), self.engine.gate_passed)

    def test_guard_allows_exact_300ms_boundary(self):
        self.clock.value = 0
        request = self.request()
        self.clock.value = .3
        self.assertEqual(self.approve(request)['status'], 'allowed')

    def test_rejected_nonce_and_guard_are_audited(self):
        request = self.request()
        for supplied, reason in ((request.nonce ^ 1, 'stale_nonce'), (request.nonce, 'switch_guard')):
            self.reject({'action': 'approve', 'nonce': supplied}, reason)
            record = self.engine.audit.recent(1)[0]
            self.assertEqual(record['decision'], reason)
            self.assertEqual(record['reason'], reason)
            self.assertEqual(record['action'], 'approve')
            self.assertEqual(record['nonce'], request.nonce)
            self.assertEqual(record['supplied_nonce'], supplied)
            self.assertEqual(record['request_id'], request.id)

    def test_http_stale_nonce_returns_409(self):
        request = self.request()
        server = hub.HubServer(self.engine, 'nonce-test-token', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(*server.server_address, timeout=3)
            try:
                connection.request('POST', '/action', json.dumps({'action': 'approve', 'nonce': request.nonce ^ 1}),
                                   {'Content-Type': 'application/json', 'X-AgentDeck-Token': 'nonce-test-token'})
                response = connection.getresponse()
                self.assertEqual(response.status, 409)
                self.assertEqual(json.loads(response.read())['error'], 'stale_nonce')
            finally:
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)

    def test_hotkey_uses_last_rendered_request_after_logical_switch(self):
        first = self.request()
        second = self.request()
        self.engine.record_rendered(first.id, first.nonce)
        self.engine.action({'action': 'deny', 'nonce': first.nonce})
        self.clock.value += .301
        keys = HotkeyKeys(self.engine)
        self.assertEqual(keys.snapshot(), {'request_id': first.id, 'nonce': first.nonce})
        self.assertFalse(keys.dispatch(SimpleNamespace(action='approve', name='test'), keys.snapshot()))
        self.assertIn(second.id, self.engine.pending)
        self.assertEqual(self.engine.audit.recent(1)[0]['reason'], 'stale_nonce')

    def test_hotkey_snapshot_is_copy_and_survives_dispatch_lock_wait(self):
        first = self.request()
        second = self.request()
        self.engine.record_rendered(first.id, first.nonce)
        keys = HotkeyKeys(self.engine)
        shown = keys.snapshot()
        altered = keys.snapshot()
        altered['nonce'] = -1
        self.assertEqual(self.engine.rendered_request['nonce'], first.nonce)
        original_lock = self.engine.lock
        waiting = threading.Event()

        class ObservedLock:
            def __enter__(self):
                if threading.current_thread() is not threading.main_thread():
                    waiting.set()
                return original_lock.__enter__()

            def __exit__(self, *args):
                return original_lock.__exit__(*args)

        results = []
        self.engine.lock = ObservedLock()
        with original_lock:
            thread = threading.Thread(target=lambda: results.append(keys.dispatch(
                SimpleNamespace(action='approve', name='test'), shown)))
            thread.start()
            self.assertTrue(waiting.wait(2))
            self.engine.action({'action': 'deny', 'nonce': first.nonce})
            self.engine.record_rendered(second.id, second.nonce)
            self.clock.value += .301
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [False])
        self.assertEqual(shown, {'request_id': first.id, 'nonce': first.nonce})
        self.assertIn(second.id, self.engine.pending)

    def test_usb_captures_rendered_snapshot_before_lock_contention(self):
        first = self.request()
        second = self.request()
        self.engine.record_rendered(first.id, first.nonce)
        keys = hub.USBKeys(self.engine, mapping={'bindings': {'hid:0x0A': 'approve'}}, monotonic=self.clock)
        entered = threading.Event()
        payloads = []
        action = self.engine.action

        def observed(payload, source='http', *, received_at=None):
            if source == 'key':
                payloads.append(dict(payload))
                entered.set()
            return action(payload, source=source, received_at=received_at)

        event = dict(down=True, usage=10, keys=['hid:0x0A'], pressed=[10],
                     modifiers=[], new_modifiers=[], t=self.clock())
        with patch.object(self.engine, 'action', side_effect=observed):
            with self.engine.lock:
                thread = threading.Thread(target=keys, args=(event,))
                thread.start()
                self.assertTrue(entered.wait(2))
                action({'action': 'deny', 'nonce': first.nonce})
                self.engine.record_rendered(second.id, second.nonce)
                self.clock.value += .301
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(payloads, [{'action': 'approve', 'request_id': first.id, 'nonce': first.nonce}])
        self.assertIn(second.id, self.engine.pending)
        self.assertEqual(self.engine.audit.recent(1)[0]['reason'], 'stale_nonce')

    def test_lcd_failed_send_preserves_rendered_snapshot_and_ack_publishes(self):
        request = self.request()
        self.engine.record_rendered('old-render', 123)
        self.engine.lcd_enabled = True
        self.engine.focus_guard = lambda **kwargs: nullcontext()
        self.engine.sender = lambda *args, **kwargs: ''
        self.engine._show()
        self.assertEqual(self.engine.rendered_request, {'request_id': 'old-render', 'nonce': 123})
        session = self.engine.sessions[request.session]
        key = session['key']
        self.engine.sender = lambda *args, **kwargs: 'ok set %s idle\nok focus %s' % (key, key)
        self.engine._show()
        self.assertEqual(self.engine.rendered_request, {'request_id': request.id, 'nonce': request.nonce})
        self.assertEqual(self.engine.rendered_source, 'lcd')

    def test_short_lcd_name_displays_low_four_hex_digits(self):
        request = self.request()
        request.nonce = 0x1234ABCD
        session = self.engine.sessions[request.session]
        session['name'] = 'abc'
        self.assertEqual(self.engine._display_name(session), 'abc abcd')

    def test_http_action_receipt_guard_survives_same_request_lock_contention(self):
        self.clock.value = 0
        request = self.request('high')
        before = self.snapshot()
        original_lock = self.engine.lock
        waiting = threading.Event()

        class ObservedLock:
            def __enter__(self):
                if threading.current_thread() is not threading.main_thread():
                    waiting.set()
                return original_lock.__enter__()

            def __exit__(self, *args):
                return original_lock.__exit__(*args)

        self.engine.lock = ObservedLock()
        errors = []

        def approve():
            try:
                self.approve(request)
            except Exception as error:
                errors.append(error)

        with original_lock:
            self.clock.value = .1
            thread = threading.Thread(target=approve)
            thread.start()
            self.assertTrue(waiting.wait(2))
            self.clock.value = .401
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], hub.HubError)
        self.assertEqual(str(errors[0]), 'switch_guard')
        self.assertEqual(errors[0].status, 409)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.engine.audit.recent(1)[0]['reason'], 'switch_guard')

    def test_hotkey_modifier_wait_preserves_original_guard_receipt(self):
        self.clock.value = 0
        request = self.request('high')
        self.engine.record_rendered(request.id, request.nonce)
        keys = HotkeyKeys(self.engine)
        shown = keys.snapshot()
        before = self.snapshot()
        self.clock.value = .401
        self.assertFalse(keys.dispatch(SimpleNamespace(action='approve', name='test'), shown,
                                       received_at=.1))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.engine.audit.recent(1)[0]['reason'], 'switch_guard')

    def test_usb_guard_uses_callback_receipt_before_same_request_lock_wait(self):
        self.clock.value = 0
        request = self.request('high')
        self.engine.record_rendered(request.id, request.nonce)
        before = self.snapshot()
        keys = hub.USBKeys(self.engine, mapping={'bindings': {'hid:0x0A': 'approve'}}, monotonic=self.clock)
        action = self.engine.action
        entered = threading.Event()
        receipts = []

        def observed(payload, source='http', *, received_at=None):
            receipts.append(received_at)
            entered.set()
            return action(payload, source=source, received_at=received_at)

        self.clock.value = .1
        event = dict(down=True, usage=10, keys=['hid:0x0A'], pressed=[10],
                     modifiers=[], new_modifiers=[], t=.1)
        with patch.object(self.engine, 'action', side_effect=observed):
            with self.engine.lock:
                thread = threading.Thread(target=keys, args=(event,))
                thread.start()
                self.assertTrue(entered.wait(2))
                self.clock.value = .401
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(receipts, [.1])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.engine.audit.recent(1)[0]['reason'], 'switch_guard')

    def test_json_received_at_cannot_bypass_switch_guard(self):
        self.clock.value = 0
        request = self.request('high')
        self.clock.value = .1
        before = self.snapshot()
        self.reject({'action': 'approve', 'nonce': request.nonce, 'received_at': 9999}, 'switch_guard')
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
