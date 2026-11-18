"""Offline hotkey parsing, actions and Win32 lifecycle with injected substitutes."""
import ctypes
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from hub_hotkey import Binding, HotkeyInput, HotkeyKeys, MOD_NOREPEAT, Win32Hotkeys, parse_hotkeys


class FakeHub:
    def __init__(self):
        self.lock = threading.RLock()
        self.displayed_request_id = "request-1"
        self.desktop = None
        self.actions = []
        self.failure = None

    def action(self, payload, source):
        if self.failure:
            raise self.failure
        self.actions.append((payload, source))
        if payload["action"] == "voice_down":
            self.desktop = type("Voice", (), {"voice_active": True})()
        elif payload["action"] == "voice_up":
            self.desktop.voice_active = False
        return {"status": "sent"}


class FakeAPI:
    def __init__(self, events=(), fail=(), unregister_fail=()):
        self.events = iter(events)
        self.fail = set(fail)
        self.unregister_fail = set(unregister_fail)
        self.registered, self.unregistered, self.woken = [], [], []
        self.modifiers = False
        self.created = False
        self.on_modifiers = None

    def create_queue(self):
        self.created = True
        return 99

    def register(self, identity, binding):
        assert self.created
        self.registered.append((identity, binding))
        return identity not in self.fail

    def unregister(self, identity):
        self.unregistered.append(identity)
        if identity in self.unregister_fail:
            raise OSError("unregister failed")

    def next_event(self):
        event = next(self.events, None)
        if isinstance(event, Exception):
            raise event
        return event

    def modifiers_down(self):
        if self.on_modifiers:
            self.on_modifiers()
        return self.modifiers

    def wake(self, thread_id):
        self.woken.append(thread_id)


class HotkeyTests(unittest.TestCase):
    def test_default_mapping(self):
        config = json.loads(Path(__file__).with_name("hub_keys.json").read_text(encoding="utf-8-sig"))
        bindings = {binding.name: binding.action for binding in parse_hotkeys(config)}
        self.assertEqual({"F%d" % (12 + slot): "slot %d" % slot for slot in range(1, 7)},
                         {key: value for key, value in bindings.items() if value.startswith("slot ")})
        for name, action in {"F19": "approve", "F20": "deny", "F21": "voice_toggle",
                             "F22": "screenshot", "F23": "cycle +1", "F24": "cycle -1",
                             "ctrl+F20": "interrupt", "ctrl+F13": "prompt continue",
                             "ctrl+F14": "prompt tests", "ctrl+F15": "prompt summary",
                             "ctrl+F16": "prompt commit"}.items():
            self.assertEqual(bindings[name], action)

    def test_parser_normalizes_modifiers_and_vkeys(self):
        parsed = parse_hotkeys({"hotkey": {" Alt + SHIFT + ctrl + f24 ": " prompt tests "}})
        self.assertEqual(parsed, [Binding("ctrl+shift+alt+F24", 7, 0x87, "prompt tests")])
        self.assertEqual(parse_hotkeys({"hotkey": {}}), [])

    def test_parser_rejects_unsupported_and_duplicate_keys(self):
        invalid = ({}, {"hotkey": []}, {"hotkey": {"F12": "approve"}},
                   {"hotkey": {"F25": "approve"}}, {"hotkey": {"Win+F13": "approve"}},
                   {"hotkey": {"F13+Ctrl": "approve"}}, {"hotkey": {"Ctrl+Ctrl+F13": "approve"}},
                   {"hotkey": {"F13": " "}}, {"hotkey": {"F13": {"down": "approve"}}},
                   {"hotkey": {1: "approve"}},
                   {"hotkey": {"Ctrl+Shift+F13": "approve", "shift+ctrl+f13": "deny"}})
        for config in invalid:
            with self.subTest(config=config), self.assertRaises(ValueError):
                parse_hotkeys(config)

    def test_dispatch_uses_shared_action_and_observed_request(self):
        engine = FakeHub()
        keys = HotkeyKeys(engine)
        self.assertTrue(keys.dispatch(Binding("F19", 0, 0x82, "approve"), keys.snapshot()))
        self.assertEqual(engine.actions, [({"action": "approve", "request_id": "request-1"}, "hotkey")])
        engine.displayed_request_id = "request-2"
        with self.assertLogs("agentdeck.hub.hotkey", level="WARNING"):
            self.assertFalse(keys.dispatch(Binding("F19", 0, 0x82, "approve"), "request-1"))
            self.assertFalse(keys.dispatch(Binding("F20", 0, 0x83, "deny"), None))
        self.assertEqual(len(engine.actions), 1)

    def test_voice_toggle_tracks_actual_voice_after_timeout_and_failure(self):
        engine = FakeHub()
        keys = HotkeyKeys(engine)
        binding = Binding("F21", 0, 0x84, "voice_toggle")
        keys.dispatch(binding, None)
        keys.dispatch(binding, None)
        keys.dispatch(binding, None)
        engine.desktop.voice_active = False  # guard timed out independently
        keys.dispatch(binding, None)
        engine.failure = ValueError("closing shortcut failed")
        with self.assertLogs("agentdeck.hub.hotkey", level="WARNING"):
            self.assertFalse(keys.dispatch(binding, None))
        engine.failure = None
        keys.dispatch(binding, None)
        self.assertEqual([payload["action"] for payload, _ in engine.actions],
                         ["voice_down", "voice_up", "voice_down", "voice_down", "voice_up"])

    def test_registration_conflict_warns_once_other_keys_dispatch_and_cleanup(self):
        engine = FakeHub()
        api = FakeAPI(events=[(1, 0), (2, 0), (999, 0)], fail={1})
        reader = HotkeyInput(engine, {"hotkey": {"F13": "slot 1", "F14": "slot 2"}}, api=api)
        with self.assertLogs("agentdeck.hub.hotkey", level="WARNING") as records:
            reader.run()
        self.assertEqual(len(records.output), 1)
        self.assertIn("F13 unavailable", records.output[0])
        self.assertEqual(engine.actions, [({"action": "slot 2"}, "hotkey")])
        self.assertEqual(api.unregistered, [2])
        self.assertIsNone(reader.thread_id)

    def test_cleanup_continues_after_message_and_unregister_failures(self):
        api = FakeAPI(events=[OSError("message failed")], unregister_fail={1})
        reader = HotkeyInput(FakeHub(), {"hotkey": {"F13": "slot 1", "F14": "slot 2"}}, api=api)
        with self.assertLogs("agentdeck.hub.hotkey", level="WARNING"):
            reader.run()
        self.assertEqual(api.unregistered, [1, 2])

    def test_stop_wakes_running_message_thread_and_releases_all_keys(self):
        api = FakeAPI()
        entered, woken = threading.Event(), threading.Event()

        def next_event():
            entered.set()
            if not woken.wait(2):
                raise OSError("test wake timed out")
            return None

        def wake(thread_id):
            api.woken.append(thread_id)
            woken.set()

        api.next_event, api.wake = next_event, wake
        reader = HotkeyInput(FakeHub(), {"hotkey": {"F13": "slot 1"}}, api=api)
        thread = threading.Thread(target=reader.run)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            reader.stop()
        finally:
            woken.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(api.woken, [99])
        self.assertEqual(api.unregistered, [1])

    def test_stop_before_run_has_no_native_effects(self):
        reader = HotkeyInput(FakeHub(), {"hotkey": {"F13": "slot 1"}})
        reader.stop()
        with patch("hub_hotkey.Win32Hotkeys", side_effect=AssertionError("native access")):
            reader.run()

    def test_stale_events_never_dispatch(self):
        engine = FakeHub()
        api = FakeAPI(events=[(1, 1.01), (1, -0.01), (1, 0.01)])
        HotkeyInput(engine, {"hotkey": {"F19": "approve"}}, api=api).run()
        self.assertEqual(len(engine.actions), 1)

    def test_modifier_release_precedes_prompt_dispatch(self):
        engine = FakeHub()
        api = FakeAPI(events=[(1, 0)])
        held = iter([True, False, False])
        api.modifiers_down = lambda: next(held, False)
        HotkeyInput(engine, {"hotkey": {"Ctrl+F13": "prompt continue"}}, api=api).run()
        self.assertEqual(engine.actions, [({"action": "prompt continue"}, "hotkey")])

    def test_decision_queued_before_previous_action_finished_is_dropped(self):
        engine = FakeHub()
        api = FakeAPI(events=[(1, 0), (1, 0.5), (1, 0)])
        # First dispatch completes at t=10.2. The second key was already queued
        # at t=9.8 and must not decide the next displayed request. A new press
        # at t=10.4 remains actionable.
        moments = iter([10.0, 10.1, 10.2, 10.3, 10.4, 10.4, 10.5])
        with self.assertLogs("agentdeck.hub.hotkey", level="WARNING"):
            HotkeyInput(engine, {"hotkey": {"F19": "approve"}}, api=api,
                        monotonic=lambda: next(moments)).run()
        self.assertEqual(len(engine.actions), 2)

    def test_decision_cannot_retarget_during_modifier_wait(self):
        engine = FakeHub()
        api = FakeAPI(events=[(1, 0)])
        api.on_modifiers = lambda: setattr(engine, "displayed_request_id", "request-2")
        with self.assertLogs("agentdeck.hub.hotkey", level="WARNING"):
            HotkeyInput(engine, {"hotkey": {"Ctrl+F19": "approve"}}, api=api).run()
        self.assertEqual(engine.actions, [])

    def test_modifier_wait_is_bounded_and_stale_action_dropped(self):
        engine = FakeHub()
        api = FakeAPI(events=[(1, 0)])
        api.modifiers = True
        moments = iter([0, 1.1])
        HotkeyInput(engine, {"hotkey": {"Ctrl+F13": "prompt continue"}}, api=api,
                    monotonic=lambda: next(moments, 1.1)).run()
        self.assertEqual(engine.actions, [])

    def test_native_register_uses_no_repeat_and_pointer_safe_queue(self):
        # Exercise the adapter through substituted DLL functions only.
        class Function:
            def __init__(self, result=1):
                self.result, self.calls = result, []

            def __call__(self, *arguments):
                self.calls.append(arguments)
                return self.result

        class DLL:
            def __getattr__(self, name):
                function = Function()
                setattr(self, name, function)
                return function

        user, kernel = DLL(), DLL()
        with patch("hub_hotkey.os.name", "nt"), patch.object(ctypes, "WinDLL", create=True,
                                                               side_effect=[user, kernel]):
            native = Win32Hotkeys()
        binding = Binding("ctrl+F13", 2, 0x7C, "prompt continue")
        native.create_queue()
        self.assertTrue(native.register(42, binding))
        self.assertEqual(user.RegisterHotKey.calls, [(None, 42, 2 | MOD_NOREPEAT, 0x7C)])
        self.assertEqual(user.RegisterHotKey.argtypes[0], ctypes.c_void_p)
        self.assertEqual(user.PostThreadMessageW.argtypes[-2:], [ctypes.c_size_t, ctypes.c_ssize_t])
        native.unregister(42)
        native.wake(99)
        self.assertEqual(user.UnregisterHotKey.calls, [(None, 42)])
        self.assertEqual(user.PostThreadMessageW.calls, [(99, 0x12, 0, 0)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
