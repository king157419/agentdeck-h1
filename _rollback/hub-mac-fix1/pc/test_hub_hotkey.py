"""Offline hotkey parsing, actions and Win32 lifecycle with injected substitutes."""
import ctypes
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hub_hotkey import Binding, HotkeyInput, HotkeyKeys, MOD_NOREPEAT, Win32Hotkeys, parse_hotkeys
from hub_hotkey_mac import PynputHotkeys


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


class MacHotkeyTests(unittest.TestCase):
    def keyboard(self, *, trusted=True, start=None):
        keys = SimpleNamespace(**{"f%d" % number: object() for number in range(13, 21)})
        for name in ("ctrl", "shift", "alt", "cmd"):
            setattr(keys, name, object())
            setattr(keys, name + "_l", getattr(keys, name))
            setattr(keys, name + "_r", object())

        class Listener:
            IS_TRUSTED = trusted

            def __init__(self, **callbacks):
                self.callbacks = callbacks
                self.started, self.stopped = False, False

            def start(self):
                self.started = True
                if start is not None:
                    start(self)

            def stop(self):
                self.stopped = True

            def is_alive(self):
                return self.started and not self.stopped

            def join(self, timeout):
                pass

        return SimpleNamespace(Key=keys, Listener=Listener)

    def test_platform_dispatch_uses_pynput_only_on_mac(self):
        for platform, expected in (("darwin", "mac"), ("win32", "win")):
            api = FakeAPI()
            with self.subTest(platform=platform), patch("hub_hotkey.sys.platform", platform), \
                    patch("hub_hotkey_mac.PynputHotkeys", return_value=api) as mac, \
                    patch("hub_hotkey.Win32Hotkeys", return_value=api) as windows:
                HotkeyInput(FakeHub(), {"hotkey": {"F13": "slot 1"}}).run()
                self.assertEqual(mac.call_count, int(expected == "mac"))
                self.assertEqual(windows.call_count, int(expected == "win"))

    def test_missing_pynput_disables_hotkeys_with_install_hint(self):
        with patch("hub_hotkey.sys.platform", "darwin"), \
                patch("hub_hotkey.Win32Hotkeys", side_effect=AssertionError("Win32 access")), \
                patch("hub_hotkey_mac.importlib.import_module", side_effect=ModuleNotFoundError("pynput")), \
                self.assertLogs("agentdeck.hub.hotkey", level="WARNING") as logs:
            reader = HotkeyInput(FakeHub(), {"hotkey": {"F13": "slot 1"}})
            reader.run()
        self.assertIn("optional pynput", logs.output[0])
        self.assertIn("install pynput", logs.output[0])
        self.assertIsNone(reader.thread_id)

    def test_pynput_import_os_error_also_disables_hotkeys(self):
        with patch("hub_hotkey.sys.platform", "darwin"), \
                patch("hub_hotkey_mac.importlib.import_module", side_effect=OSError("permission denied")), \
                self.assertLogs("agentdeck.hub.hotkey", level="WARNING"):
            HotkeyInput(FakeHub(), {"hotkey": {"F19": "approve"}}).run()

    def test_adapter_is_lazy_and_preserves_f13_to_f20_mapping(self):
        keyboard = self.keyboard()
        native = PynputHotkeys(keyboard=keyboard)
        native.create_queue()
        for index, binding in enumerate(parse_hotkeys({"hotkey": {
                "F13": "slot 1", "F18": "slot 6", "F19": "approve", "F20": "deny"}}), 1):
            self.assertTrue(native.register(index, binding))
            self.assertEqual(native.bindings[index][0], getattr(keyboard.Key, binding.name.lower()))
        self.assertIsNone(native.listener)

    def test_unsupported_function_keys_warn_and_other_bindings_continue(self):
        native = PynputHotkeys(keyboard=self.keyboard())
        engine = FakeHub()
        native._start = lambda: None
        native.events.put((2, 0))
        native.events.put(None)
        native.monotonic = lambda: 0
        with self.assertLogs("agentdeck.hub.hotkey", level="WARNING") as logs:
            HotkeyInput(engine, {"hotkey": {"F21": "voice_toggle", "F13": "slot 1"}}, api=native).run()
        self.assertEqual(len(logs.output), 1)
        self.assertIn("F21 unavailable", logs.output[0])
        self.assertEqual(engine.actions, [({"action": "slot 1"}, "hotkey")])

    def test_callbacks_queue_events_without_dispatching_and_ignore_repeat(self):
        native = PynputHotkeys(keyboard=self.keyboard(), monotonic=lambda: 12.5)
        native.register(1, Binding("F19", 0, 0x82, "approve"))
        key = native.keyboard.Key.f19
        native._press(key)
        native._press(key)
        self.assertEqual(native.events.qsize(), 1)
        self.assertEqual(native.events.get_nowait(), (1, 12.5))
        native._release(key)
        native._press(key)
        self.assertEqual(native.events.qsize(), 1)

    def test_modifiers_must_match_exactly_including_command(self):
        native = PynputHotkeys(keyboard=self.keyboard(), monotonic=lambda: 0)
        native.register(1, Binding("ctrl+F13", 2, 0x7C, "prompt continue"))
        key = native.keyboard.Key
        native._press(key.f13)
        native._release(key.f13)
        native._press(key.ctrl_r)
        native._press(key.cmd)
        native._press(key.f13)
        native._release(key.f13)
        self.assertTrue(native.events.empty())
        native._release(key.cmd)
        native._press(key.f13)
        self.assertEqual(native.events.get_nowait(), (1, 0))
        self.assertTrue(native.modifiers_down())
        native._release(key.ctrl_r)
        self.assertFalse(native.modifiers_down())

    def test_left_and_right_modifier_release_do_not_clear_other_side(self):
        native = PynputHotkeys(keyboard=self.keyboard())
        native._press(native.keyboard.Key.ctrl_l)
        native._press(native.keyboard.Key.ctrl_r)
        native._release(native.keyboard.Key.ctrl_l)
        self.assertTrue(native.modifiers_down())
        native._release(native.keyboard.Key.ctrl_r)
        self.assertFalse(native.modifiers_down())

    def test_unknown_keys_and_stopped_callbacks_have_no_effect(self):
        native = PynputHotkeys(keyboard=self.keyboard())
        native.register(1, Binding("F13", 0, 0x7C, "slot 1"))
        native._press(None)
        native._release(None)
        native.wake(1)
        native._press(native.keyboard.Key.f13)
        self.assertEqual(native.events.get_nowait(), None)
        self.assertTrue(native.events.empty())

    def test_listener_permissions_fail_without_actions_or_exception(self):
        native = PynputHotkeys(keyboard=self.keyboard(trusted=False))
        engine = FakeHub()
        with self.assertLogs("agentdeck.hub.hotkey", level="WARNING") as logs:
            HotkeyInput(engine, {"hotkey": {"F19": "approve"}}, api=native).run()
        self.assertIn("Accessibility / Input Monitoring", logs.output[0])
        self.assertEqual(engine.actions, [])

    def test_listener_start_failure_is_logged_and_cleaned_up(self):
        def failed(listener):
            raise RuntimeError("event tap denied")

        native = PynputHotkeys(keyboard=self.keyboard(start=failed))
        with self.assertLogs("agentdeck.hub.hotkey", level="WARNING") as logs:
            HotkeyInput(FakeHub(), {"hotkey": {"F19": "approve"}}, api=native).run()
        self.assertIn("event tap denied", logs.output[0])
        self.assertTrue(native.listener.stopped)

    def test_listener_callbacks_feed_shared_dispatch_after_modifier_release(self):
        native = None

        def emit(listener):
            key = native.keyboard.Key
            listener.callbacks["on_press"](key.ctrl)
            listener.callbacks["on_press"](key.f13)
            listener.callbacks["on_release"](key.f13)
            listener.callbacks["on_release"](key.ctrl)
            native.events.put(None)

        native = PynputHotkeys(keyboard=self.keyboard(start=emit))
        engine = FakeHub()
        HotkeyInput(engine, {"hotkey": {"Ctrl+F13": "prompt continue"}}, api=native).run()
        self.assertEqual(engine.actions, [({"action": "prompt continue"}, "hotkey")])
        self.assertTrue(native.listener.stopped)

    def test_queue_age_uses_press_timestamp(self):
        moments = iter([10, 11.2])
        native = PynputHotkeys(keyboard=self.keyboard(), monotonic=lambda: next(moments))
        native.register(1, Binding("F13", 0, 0x7C, "slot 1"))
        native._press(native.keyboard.Key.f13)
        identity, age = native.next_event()
        self.assertEqual(identity, 1)
        self.assertAlmostEqual(age, 1.2)
        native.wake(1)
        self.assertTrue(native.listener.stopped)

    def test_stop_wakes_queue_and_stops_listener(self):
        native = PynputHotkeys(keyboard=self.keyboard())
        native.register(1, Binding("F13", 0, 0x7C, "slot 1"))
        native._start()
        native.wake(1)
        self.assertIsNone(native.next_event())
        self.assertTrue(native.listener.stopped)

    def test_all_unsupported_bindings_do_not_start_listener(self):
        native = PynputHotkeys(keyboard=self.keyboard(start=lambda listener: self.fail("native access")))
        self.assertFalse(native.register(1, Binding("F21", 0, 0x84, "voice_toggle")))
        self.assertIsNone(native.next_event())


if __name__ == "__main__":
    unittest.main(verbosity=2)
