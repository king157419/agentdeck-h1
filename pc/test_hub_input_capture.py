"""Real Hub input integration; native message/USB boundaries are injected."""
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

import hub
from deck_usb import USBInput
from hub_hotkey import HotkeyInput


class Clock:
    value = 100.0

    def __call__(self):
        return self.value


class QueueAPI:
    """The Windows GetMessage boundary, including already queued message ages."""
    def __init__(self, events):
        self.events = iter(events)
        self.unregistered = []
        self.on_modifiers = None

    def create_queue(self):
        return 1

    def register(self, identity, binding):
        return True

    def unregister(self, identity):
        self.unregistered.append(identity)

    def next_event(self):
        return next(self.events, None)

    def modifiers_down(self):
        if self.on_modifiers is not None:
            callback, self.on_modifiers = self.on_modifiers, None
            callback()
        return False


class InputCaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.clock = Clock()
        self.engine = hub.Hub(home=temporary.name, monotonic=self.clock,
                              lcd_enabled=False, desktop_enabled=False,
                              hold_path=Path(temporary.name) / "hold")
        self.threads = []
        self.responses = {}
        self.addCleanup(self.finish)

    def finish(self):
        self.engine.close()
        for thread in self.threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())

    def permission(self, session):
        def event():
            self.responses[session] = self.engine.event("cc", {
                "hook_event_name": "PermissionRequest", "session_id": session,
                "cwd": "C:/input", "tool_name": "Bash",
                "tool_input": {"command": "echo safe"}})
        thread = threading.Thread(target=event, daemon=True)
        self.threads.append(thread)
        thread.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with self.engine.lock:
                found = next((p for p in self.engine.pending.values()
                              if p.session[1] == session), None)
            if found is not None:
                return found
            time.sleep(.001)
        self.fail("PermissionRequest was not queued")

    def test_hotkey_default_clock_is_hub_clock(self):
        reader = HotkeyInput(self.engine, {"hotkey": {}}, api=QueueAPI([]))
        self.assertIs(reader.monotonic, self.engine.monotonic)

    def test_real_hub_failed_action_cannot_retarget_queued_deny(self):
        first = self.permission("capture-first")
        second = self.permission("capture-second")
        self.engine.record_rendered(first.id, first.nonce)
        self.clock.value = 100.5
        api = QueueAPI([(1, 0), (2, .4)])

        def while_action_was_busy():
            self.clock.value = 101.0
            self.engine.event("cc", {"hook_event_name": "Stop",
                                     "session_id": first.session[1]})
            self.engine.record_rendered(second.id, second.nonce)

        api.on_modifiers = while_action_was_busy
        # Prompt fails because desktop effects are disabled. The queued deny was
        # pressed before it completed and must not decide the successor.
        reader = HotkeyInput(self.engine, {"hotkey": {
            "Ctrl+F13": "prompt continue", "F20": "deny"}},
            api=api, monotonic=self.clock)
        reader.run()
        self.assertIn(second.id, self.engine.pending)
        self.assertFalse(second.ready.is_set())
        self.assertEqual(api.unregistered, [1, 2])
        self.assertEqual(reader.last_dispatch_finished, 101.0)

    def test_real_hub_queued_deny_uses_original_render_history(self):
        first = self.permission("history-first")
        second = self.permission("history-second")
        self.engine.record_rendered(first.id, first.nonce)
        self.clock.value = 100.5
        self.engine.event("cc", {"hook_event_name": "Stop",
                                 "session_id": first.session[1]})
        self.engine.record_rendered(second.id, second.nonce)
        self.clock.value = 101.0
        api = QueueAPI([(1, .75)])  # Press happened at 100.25 on first.
        HotkeyInput(self.engine, {"hotkey": {"F20": "deny"}},
                    api=api, monotonic=self.clock).run()
        self.assertIn(second.id, self.engine.pending)
        self.assertFalse(second.ready.is_set())

    def test_usb_same_report_shares_timestamp_and_snapshot(self):
        received = []

        class Callback:
            shown = {"request_id": "old", "nonce": 123}

            def snapshot(callback):
                return dict(callback.shown)

            def __call__(callback, event):
                received.append(dict(event))
                if not event["down"] and event["usage"] == 11:
                    self.clock.value += .22
                    callback.shown = {"request_id": "new", "nonce": 456}

        callback = Callback()
        receiver = USBInput(callback, foreground=lambda: 0, monotonic=self.clock)
        receiver.state.feed(bytes.fromhex("00 00 0B 00 00 00 00 00"))

        class Endpoint:
            wMaxPacketSize = 8

            def read(endpoint, *args, **kwargs):
                receiver._stop.set()
                return bytes.fromhex("00 00 0A 00 00 00 00 00")

        receiver.endpoint = Endpoint()
        receiver._core = SimpleNamespace(USBTimeoutError=TimeoutError)
        receiver.run()
        transitions = [(e["usage"], e["down"]) for e in received]
        self.assertEqual(transitions, [(11, False), (10, True)])
        for event in received:
            self.assertEqual(event["t"], 100.0)
            self.assertEqual(event.get("shown"), {"request_id": "old", "nonce": 123})

    def test_usb_report_context_captures_before_foreground_query(self):
        def foreground():
            self.clock.value += .22
            return 42
        receiver = USBInput(lambda event: None, foreground=foreground, monotonic=self.clock)
        context = receiver._report_context()
        self.assertEqual(context["t"], 100.0)
        self.assertEqual(context["hwnd"], 42)


if __name__ == "__main__":
    unittest.main(verbosity=2)
