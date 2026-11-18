"""Real Hub requests and component paths; no hardware or native input access."""
from contextlib import nullcontext
from pathlib import Path
import tempfile
import http.client
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import hub
from hub_hotkey import Binding, HotkeyKeys
from hub_overlay import Overlay
from test_hub import Clock, Desktop
from test_ui import make_ui
from deck_usb import USBInput, ReportState


class NonceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.engine = hub.Hub(home=self.temp.name, lcd_enabled=False,
                              desktop_enabled=False, monotonic=self.clock)
        self.threads = []
        self.responses = []

    def tearDown(self):
        self.engine.close()
        for thread in self.threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.temp.cleanup()

    def request(self, sid='first1', command='echo safe'):
        thread = threading.Thread(target=lambda: self.responses.append(self.engine.event('cc', {
            'session_id': sid, 'hook_event_name': 'PermissionRequest',
            'cwd': 'C:/app', 'tool_name': 'Bash', 'tool_input': {'command': command}})))
        self.threads.append(thread)
        thread.start()
        until = time.monotonic() + 2
        while time.monotonic() < until:
            state = self.engine.state()
            record = next((p for p in state['pending'] + state['locked'] if p['session_id'] == sid), None)
            if record:
                return record
            time.sleep(.001)
        self.fail('real permission did not arrive')

    def overlay(self):
        overlay = Overlay(self.engine, window=Mock())
        overlay.root = Mock()
        overlay.root.state.return_value = 'normal'
        overlay.risk = Mock()
        overlay.summary = Mock()
        overlay.decision_buttons = {'approve': Mock(), 'deny': Mock()}
        overlay._poll()
        return overlay

    def key(self, action='approve', shown=None):
        keys = HotkeyKeys(self.engine)
        return keys.dispatch(Binding('F19', 0, 0x82, action), keys.snapshot() if shown is None else shown)

    def test_overlay_press_in_guard_cannot_become_valid_at_release(self):
        self.request()
        overlay = self.overlay()
        self.clock.value += .05
        overlay._decision_press(None, 'approve')
        self.clock.value += .4
        overlay._decision_release('approve')
        self.assertEqual(len(self.engine.pending), 1)
        self.assertEqual(overlay.message, 'switch_guard')

    def test_lcd_cannot_overwrite_stale_overlay_and_reverse(self):
        first = self.request()
        self.engine.record_rendered(first['id'], first['nonce'], 'overlay')
        self.engine.record_rendered(first['id'], first['nonce'], 'lcd')
        second = self.request('second2')
        self.engine.action({'action': 'deny', 'nonce': first['nonce']})
        self.engine.record_rendered(second['id'], second['nonce'], 'lcd')
        self.clock.value += .4
        self.assertFalse(self.key())
        self.assertIn(second['id'], self.engine.pending)
        self.engine.record_rendered(second['id'], second['nonce'], 'overlay')
        self.clock.value += .4
        self.assertTrue(self.key())
        self.assertEqual(self.responses[0]['hookSpecificOutput']['decision']['behavior'], 'deny')

    def test_headless_hotkey_and_usb_approve_and_deny(self):
        first = self.request()
        self.clock.value += .4
        self.assertTrue(self.key())
        second = self.request('second2')
        keys = hub.USBKeys(self.engine, mapping={'bindings': {'hid:0x09': 'deny'}})
        keys(dict(down=True, usage=9, keys=['hid:0x09'], pressed=[9],
                  modifiers=[], new_modifiers=[], t=self.clock()))
        self.assertNotIn(first['id'], self.engine.pending)
        self.assertNotIn(second['id'], self.engine.pending)

    def test_hide_keeps_seen_request_usable_and_hub_http_alive(self):
        self.request()
        overlay = self.overlay()
        self.clock.value += .4
        overlay.hide()
        self.assertFalse(self.engine.closed)
        self.assertFalse(overlay.stopped.is_set())
        server = hub.HubServer(self.engine, 'integration', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(*server.server_address, timeout=2)
            connection.request('GET', '/health')
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b'{"ok": true}')
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
        self.assertTrue(self.key())
        self.assertEqual(self.engine.pending, {})

    def test_delayed_overlay_render_has_own_guard_while_lcd_stale(self):
        first = self.request()
        overlay = self.overlay()
        self.engine.record_rendered(first['id'], first['nonce'], 'lcd')
        second = self.request('second2')
        self.clock.value += .4
        self.engine.action({'action': 'deny', 'nonce': first['nonce']})
        self.clock.value += .6
        overlay._poll()
        self.clock.value += .05
        overlay._decision_press(None, 'approve')
        self.clock.value += .4
        overlay._decision_release('approve')
        self.assertEqual(overlay.message, 'switch_guard')
        self.assertIn(second['id'], self.engine.pending)

    def test_first_late_render_restarts_physical_guard_even_same_headless_binding(self):
        self.request()
        self.clock.value += 1
        self.overlay()
        self.clock.value += .05
        self.assertFalse(self.key())
        self.clock.value += .3
        self.assertTrue(self.key())

    def test_hidden_snapshot_cannot_bind_new_unseen_request_then_reappears(self):
        first = self.request()
        overlay = self.overlay()
        overlay.hide()
        self.engine.action({'action': 'deny', 'nonce': first['nonce']})
        second = self.request('second2')
        self.clock.value += .4
        self.assertFalse(self.key())
        overlay._poll()
        self.assertFalse(overlay.hidden)
        self.clock.value += .4
        self.assertTrue(self.key())
        self.assertNotIn(second['id'], self.engine.pending)

    def test_async_lcd_does_not_hold_hub_lock_and_retries_failure(self):
        entered, release = threading.Event(), threading.Event()
        attempts = []
        def send(lines, **kwargs):
            attempts.append(lines)
            entered.set()
            if not release.wait(2):
                raise AssertionError('test serial gate not released')
            raise OSError('simulated busy serial')
        self.engine.sender = send
        self.engine.lcd_enabled = True
        self.engine.lcd_async = True
        self.engine.hold_path = Path(self.temp.name) / 'hold'
        self.engine.focus_guard = lambda **kwargs: nullcontext()
        try:
            self.request()
            self.assertTrue(entered.wait(1))
            observed = threading.Event()
            query = threading.Thread(target=lambda: (self.engine.state(), observed.set()))
            query.start()
            self.assertTrue(observed.wait(.3), 'serial wait held Hub.lock')
            query.join(1)
        finally:
            release.set()
        until = time.monotonic() + 2
        while not self.engine.lcd_jobs.empty() and time.monotonic() < until:
            time.sleep(.002)
        # Worker publishes the retry schedule under lock after the failed show.
        until = time.monotonic() + 2
        while self.engine.lcd_retry_at == float('inf') and time.monotonic() < until:
            time.sleep(.002)
        self.assertLessEqual(self.engine.lcd_retry_at, self.clock() + .5)
        count = len(attempts)
        self.clock.value += .51
        self.engine.maintain()
        until = time.monotonic() + 2
        while len(attempts) == count and time.monotonic() < until:
            time.sleep(.002)
        self.assertGreater(len(attempts), count)
        self.engine.close()
        self.engine.lcd_thread.join(2)
        self.assertFalse(self.engine.lcd_thread.is_alive())

    def test_async_old_lcd_ack_does_not_retarget_approval(self):
        first_entered, first_release = threading.Event(), threading.Event()
        second_entered, second_release = threading.Event(), threading.Event()
        def send(lines, **kwargs):
            if kwargs.get('wait_reply'):
                entered, release = ((first_entered, first_release) if 'first1' in lines[-1]
                                    else (second_entered, second_release))
                entered.set()
                if not release.wait(2):
                    raise AssertionError('LCD test gate timed out')
            return '\n'.join('ok ' + ' '.join(line.split()[:3] if line.startswith('set ') else line.split())
                             for line in lines)
        self.engine.sender = send
        self.engine.lcd_enabled = True
        self.engine.lcd_async = True
        self.engine.hold_path = Path(self.temp.name) / 'hold'
        self.engine.focus_guard = lambda **kwargs: nullcontext()
        try:
            first = self.request()
            self.assertTrue(first_entered.wait(1))
            second = self.request('second2')
            self.engine.action({'action': 'deny', 'nonce': first['nonce']})
            first_release.set()
            self.assertTrue(second_entered.wait(1))
            self.assertEqual(self.engine.rendered_by_source['lcd']['request_id'], first['id'])
            self.clock.value += .4
            self.assertFalse(self.key())
            self.assertIn(second['id'], self.engine.pending)
        finally:
            first_release.set()
            second_release.set()
            self.engine.close()
            self.engine.lcd_thread.join(2)
        self.assertFalse(self.engine.lcd_thread.is_alive())

    def test_serial_ack_reader_returns_as_soon_as_complete_reply_arrives(self):
        port = Mock()
        port.read.return_value = b'ok focus cc-first1\r\n'
        with patch.object(hub.agent_lcd.serial, 'Serial', return_value=port), patch.object(
                hub.agent_lcd, 'find_port', return_value='FAKE'):
            result = hub.agent_lcd.send(['focus cc-first1'], wait_reply=.15,
                                         expected_replies=['ok focus cc-first1'])
        self.assertEqual(result, 'ok focus cc-first1')
        port.read.assert_called_once_with(256)
        port.close.assert_called_once_with()

    def test_idle_key_is_no_request_without_audit_and_bad_nonce_has_full_schema(self):
        self.assertTrue(self.key())
        self.assertEqual(self.engine.audit.recent(), [])
        with self.assertRaises(hub.HubError):
            self.engine.action({'action': 'approve', 'nonce': 123})
        record = self.engine.audit.recent(1)[0]
        for name in ('agent', 'session_id', 'project', 'tool_name', 'command', 'risk', 'nonce', 'request_id'):
            self.assertIn(name, record)
        self.assertTrue(self.engine.audit.verify())

    def test_cancelled_high_confirmation_cannot_approve_next_low_request(self):
        self.request(command='rm -rf ./build')
        second = self.request('second2')
        self.clock.value += .4
        self.assertTrue(self.key())
        self.engine.event('cc', {'session_id': 'first1', 'hook_event_name': 'Stop'})
        self.clock.value += .4
        self.assertFalse(self.key())
        self.assertIn(second['id'], self.engine.pending)
        self.clock.value += 1.2
        self.assertTrue(self.key())

    def test_explicit_empty_interrupt_cannot_deny_new_request(self):
        self.request()
        with self.assertRaises(hub.HubError):
            self.engine.action({'action': 'interrupt', 'request_id': None})
        self.assertEqual(len(self.engine.pending), 1)

    def test_usb_voice_release_delay_cannot_age_same_packet_approval(self):
        record = self.request()
        desktop = self.engine.desktop = Desktop()
        desktop.voice_active = True
        def delayed_release():
            desktop.voice_active = False
            self.clock.value += .22
        desktop.voice_up = delayed_release
        self.clock.value += .1
        keys = hub.USBKeys(self.engine, mapping={'bindings': {
            'hid:0x0B': {'down': 'voice_down', 'up': 'voice_up'}, 'hid:0x0A': 'approve'}})
        keys.held[11] = ('hid:0x0B', 'voice_up')
        receiver = USBInput(keys, foreground=lambda: 0, monotonic=self.clock)
        receiver.state.feed(bytes.fromhex('00 00 0B 00 00 00 00 00'))
        class Endpoint:
            wMaxPacketSize = 8
            def read(endpoint, *args, **kwargs):
                receiver._stop.set()
                return bytes.fromhex('00 00 0A 00 00 00 00 00')
        receiver.endpoint = Endpoint()
        receiver._core = SimpleNamespace(USBTimeoutError=TimeoutError)
        receiver.run()
        self.assertIn(record['id'], self.engine.pending)
        self.assertEqual(self.engine.audit.recent(1)[0]['reason'], 'switch_guard')

    def test_measured_idle_keys_decode_into_real_hub_effects_in_both_profiles(self):
        self.engine.desktop_enabled = True
        desktop = self.engine.desktop = Desktop()
        for sid in ('keymap1', 'keymap2'):
            self.engine.event('cc', {'hook_event_name': 'SessionStart', 'session_id': sid, 'cwd': 'C:/app'})
        for profile in ('default', 'v2_emulation'):
            decoder = ReportState()
            keys = hub.USBKeys(self.engine, profile=profile)
            def feed(report):
                for event in decoder.feed(bytes.fromhex(report)):
                    event['t'] = self.clock()
                    keys(event)
            for report, template in (('00 00 10 00 00 00 00 00', 'continue'),
                                     ('01 00 17 00 00 00 00 00', 'tests'),
                                     ('01 00 07 00 00 00 00 00', 'summary'),
                                     ('00 00 18 00 00 00 00 00', 'commit')):
                feed(report)
                self.assertEqual(desktop.calls[-1], ('prompt', self.engine.selected[1], self.engine.prompts[template]))
                feed('00 00 00 00 00 00 00 00')
            before = self.engine.selected
            feed('00 00 1B 00 00 00 00 00')
            self.assertNotEqual(self.engine.selected, before)
            feed('00 00 00 00 00 00 00 00')
            self.engine.event('cc', {'hook_event_name': 'Notification', 'session_id': before[1],
                                      'notification_type': 'permission_prompt'})
            feed('00 00 2B 00 00 00 00 00')
            self.assertEqual(self.engine.selected, before)
            feed('00 00 00 00 00 00 00 00')
            count = len(desktop.calls)
            for report in ('01 00 06 00 00 00 00 00', '01 00 19 00 00 00 00 00'):
                feed(report)
                feed('00 00 00 00 00 00 00 00')
            self.assertEqual(len(desktop.calls), count)

    def test_lcd_actual_protocol_ack_and_external_sessions_preserve_name(self):
        ui, lcd, _ = make_ui()
        for number in range(7):
            ui.handle('set ds-x%d idle other' % number, 0)
        self.engine.lcd_enabled = True
        self.engine.lcd_async = False
        self.engine.focus_guard = lambda **kwargs: nullcontext()
        self.engine.hold_path = Path(self.temp.name) / 'hold'
        def send(lines, **kwargs):
            replies = [ui.handle(line, int(self.clock() * 1000)) for line in lines]
            ui.render(int(self.clock() * 1000))
            return '\n'.join(replies)
        self.engine.sender = send
        record = self.request()
        # At 8 board sessions a four-cell name budget cannot hold a nonce.
        self.assertNotIn('%04x' % (record['nonce'] & 0xffff), ui.sess['cc-first1'][0].decode())
        for elapsed in (0, 2800, 5000):
            ui.render(int(self.clock() * 1000) + elapsed)
            self.assertEqual(lcd.rows[1][3:6], b'app')


if __name__ == '__main__':
    unittest.main(verbosity=2)
