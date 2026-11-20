"""Offline USB/Raw Input switching and parity; every native boundary is fake."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import hub
from deck_usb import ReportState
import deck_input
from hub_keyboard import KeyboardInput, KnobDetents, ModifierTaps, RawKeys, VKEY_USAGES
from test_deck_input import Backend


def raw_event(vkey, down=True, *, device=1, scan=0, flags=0):
    return {"kind": "keyboard", "vkey": vkey, "make_code": scan,
            "device": device, "flags": flags | (0 if down else 1), "down": down}


def report(*keys, bits=0):
    return bytes([bits, 0, *keys] + [0] * (6 - len(keys)))


def ordinary(events):
    return [e for e in events if not e.get("modifier")]


class KnobDetentTests(unittest.TestCase):
    """CXT encoders: one pulse per notch, slow turns ~0.5 s apart, occasional bounce."""

    def test_every_pulse_is_a_step_even_when_turned_slowly(self):
        for binding in ("hid:0x09", "hid:0x16", "hid:0x15", "hid:0x13", "hid:0x30", "hid:0x2F"):
            with self.subTest(binding=binding):
                detents = KnobDetents()
                self.assertTrue(detents.accept(binding, 0.0))
                self.assertTrue(detents.accept(binding, .55))
                self.assertTrue(detents.accept(binding, 1.6))

    def test_opposite_pulse_right_after_is_bounce_but_later_is_a_real_reversal(self):
        detents = KnobDetents()
        self.assertTrue(detents.accept("hid:0x15", 0.0))
        self.assertFalse(detents.accept("hid:0x13", .05))   # bounce
        self.assertTrue(detents.accept("hid:0x15", .15))    # still turning forward
        self.assertTrue(detents.accept("hid:0x13", .40))    # deliberate reversal
        self.assertTrue(detents.accept("hid:0x13", .70))

    def test_divider_counts_pulses_within_a_run(self):
        detents = KnobDetents({"2": 2})
        self.assertFalse(detents.accept("hid:0x15", 0))
        self.assertTrue(detents.accept("hid:0x15", .3))
        self.assertFalse(detents.accept("hid:0x15", 1.5))   # run expired: count restarts
        self.assertTrue(detents.accept("hid:0x15", 1.8))

    def test_rate_limit_drops_steps_without_queuing(self):
        detents = KnobDetents()
        self.assertTrue(detents.accept("hid:0x09", 0))
        self.assertFalse(detents.accept("hid:0x09", .02))
        self.assertTrue(detents.accept("hid:0x09", .07))

    def test_scroll_only_drops_bounce_and_never_divides(self):
        detents = KnobDetents({"3": 99})
        self.assertTrue(detents.accept("hid:0x2D", 0))
        self.assertTrue(detents.accept("hid:0x2D", .001))
        self.assertFalse(detents.accept("hid:0x2E", .002))
        self.assertTrue(detents.accept("hid:0x2E", .300))

    def test_each_knob_has_independent_state_and_buttons_are_unfiltered(self):
        detents = KnobDetents()
        for binding in ("hid:0x09", "hid:0x15", "hid:0x30"):
            self.assertTrue(detents.accept(binding, 0))
        for binding in ("hid:0x16", "hid:0x13", "hid:0x2F"):
            self.assertFalse(detents.accept(binding, .01))  # bounce per knob
        for binding in [keys[2] for keys in hub.KNOBS] + ["ctrl+hid:0x09", "alt", "F13"]:
            self.assertTrue(detents.accept(binding, .02))

    def test_invalid_dividers_fail_before_input_is_read(self):
        for config in ([], 1, {"0": 2}, {"5": 2}, {"1": 0}, {"2": -1},
                       {"1": True}, {"1": 1.5}, {"1": "2"}):
            with self.subTest(config=config), self.assertRaisesRegex(ValueError, "knob_divider"):
                KnobDetents(config)


class ModifierTapTests(unittest.TestCase):
    def setUp(self):
        self.taps = ModifierTaps()
        self.state = ReportState()

    def feed(self, packet, timestamp, reader="USB", **extra):
        return [binding for event in self.state.feed(packet)
                if (binding := self.taps.feed(dict(event, t=timestamp, reader=reader, **extra))) is not None]

    def test_both_sides_trigger_only_on_short_isolated_release(self):
        for bits, name in ((1, "ctrl"), (2, "shift"), (4, "alt"),
                           (0x10, "ctrl"), (0x20, "shift"), (0x40, "alt")):
            with self.subTest(bits=bits):
                self.assertEqual(self.feed(report(bits=bits), 0), [])
                self.assertEqual(self.feed(report(), .599), [name])

    def test_modifier_first_macro_never_triggers_interrupt_or_tap(self):
        self.assertEqual(self.feed(report(bits=1), 0), [])
        self.assertEqual(self.feed(report(0x1D, bits=1), .02), [])
        self.assertEqual(self.feed(report(bits=1), .04), [])
        self.assertEqual(self.feed(report(), .06), [])

    def test_main_key_present_in_modifier_release_report_cancels(self):
        self.feed(report(bits=1), 0)
        self.assertEqual(self.feed(report(0x1D), .02), [])

    def test_exact_600ms_release_is_included(self):
        self.feed(report(bits=1), 1)
        self.assertEqual(self.feed(report(), 1.6), ["ctrl"])

    def test_multiple_modifiers_long_holds_and_raw_input_never_trigger(self):
        self.feed(report(bits=3), 0)
        self.assertEqual(self.feed(report(), .1), [])
        self.feed(report(bits=1), 1)
        self.assertEqual(self.feed(report(), 1.601), [])
        self.feed(report(bits=4), 2, reader="Raw Input")
        self.assertEqual(self.feed(report(), 2.1, reader="Raw Input"), [])

    def test_synthetic_disconnect_release_never_becomes_a_tap(self):
        self.feed(report(bits=1), 0)
        self.assertEqual(self.feed(report(), .1, cancelled=True), [])


class AdapterTests(unittest.TestCase):
    def test_all_actual_bindings_and_function_keys_match_usb(self):
        config = hub.load_json(Path(__file__).with_name("hub_keys.json"))
        usages = {int(key.split(":")[-1], 16) for section in
                  (config, config["v2_emulation"]) for key in section["bindings"] if "hid:" in key}
        usages.update(range(0x68, 0x74))
        inverse = {usage: key for key, usage in VKEY_USAGES.items()}
        for usage in sorted(usages):
            for bits in (0, 1, 2, 4, 8, 0x10):
                with self.subTest(usage=usage, bits=bits):
                    events = []
                    adapter = RawKeys(events.append, lambda: 10.)
                    modifiers = {1: 0xA2, 2: 0xA0, 4: 0xA4, 8: 0x5B, 0x10: 0xA3}
                    if bits:
                        adapter(raw_event(modifiers[bits]))
                    adapter(raw_event(inverse[usage]))
                    usb = ordinary(ReportState().feed(report(usage, bits=bits)))[0]
                    actual = ordinary(events)[-1]
                    for field in ("keys", "down", "usage", "modifiers", "modifier_bits",
                                  "pressed", "new_modifiers"):
                        self.assertEqual(actual[field], usb[field], field)

    def test_fresh_modifiers_repeats_and_releases_match_report_state(self):
        raw_events, usb_events = [], []
        adapter, state = RawKeys(raw_events.append, lambda: 10.), ReportState()
        sequence = [(raw_event(0x11, flags=2), report(bits=0x10)),
                    (raw_event(0x5A), report(0x1D, bits=0x10)),
                    (raw_event(0x5A), report(0x1D, bits=0x10)),
                    (raw_event(0x5A, False), report(bits=0x10)),
                    (raw_event(0x46), report(9, bits=0x10)),
                    (raw_event(0x46, False), report(bits=0x10)),
                    (raw_event(0x11, False, flags=2), report())]
        for raw, packet in sequence:
            adapter(raw)
            usb_events.extend(state.feed(packet))
        fields = ("keys", "down", "modifiers", "pressed", "new_modifiers", "usage", "modifier")
        self.assertEqual([{f: e[f] for f in fields} for e in raw_events],
                         [{f: e[f] for f in fields} for e in usb_events])

    def test_main_keyboard_cannot_trigger_or_modify_deck(self):
        backend, events = Backend(), []
        receiver = deck_input.RawInput(RawKeys(events.append, lambda: 10.),
                                      backend.user, backend.kernel, backend.hid, transitions=True)
        for device, vkey in ((2, 0x11), (2, 0x45), (1, 0x45)):
            backend.packet_for(device, 1, deck_input.RAWKEYBOARD(18, 0, 0, vkey, 0x100, 0))
            receiver._read(1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["keys"], ("hid:0x08",))
        self.assertEqual(events[0]["modifiers"], ())

    def test_device_modifiers_are_isolated_and_right_shift_is_normalized(self):
        events = []
        adapter = RawKeys(events.append, lambda: 10.)
        adapter(raw_event(0x10, scan=0x36, device=1))
        adapter(raw_event(0x45, device=2))
        self.assertEqual(events[-1]["keys"], ("hid:0x08",))
        self.assertEqual(events[-1]["modifiers"], ())
        adapter(raw_event(0x45, device=1))
        self.assertEqual(events[-1]["keys"], ("shift+hid:0x08", "hid:0x08"))
        self.assertEqual(events[-1]["modifier_bits"], 0x20)

    def test_snapshot_time_and_voice_release_on_removal(self):
        actions, shown, now = [], {"request_id": "before", "nonce": "n"}, [10.]
        engine = SimpleNamespace(monotonic=lambda: now[0], input_snapshot=lambda received_at=None: dict(shown),
                                 action=lambda payload, **kw: actions.append((payload, kw)))
        callback = hub.USBKeys(engine, {"bindings": {"hid:0x0B": {
            "down": "voice_down", "up": "voice_up"}}})
        events = []

        class Capture:
            snapshot = callback.snapshot

            def __call__(self, event):
                events.append(event)
                callback(event)

        adapter = RawKeys(Capture(), engine.monotonic)
        adapter(raw_event(0x48))
        now[0] += 5
        shown["request_id"] = "after"
        adapter({"kind": "device_removed", "device": 1})
        self.assertEqual([a[0]["action"] for a in actions], ["voice_down", "voice_up"])
        self.assertEqual(events[0]["shown"]["request_id"], "before")
        self.assertEqual(events[0]["t"], 10.)
        self.assertEqual(callback.held, {})

    def test_unknown_held_key_and_chords_block_single_key_actions(self):
        actions = []
        engine = SimpleNamespace(monotonic=lambda: 10., input_snapshot=lambda received_at=None: {},
                                 action=lambda payload, **kw: actions.append(payload))
        adapter = RawKeys(hub.USBKeys(engine, {"bindings": {"hid:0x08": "slot 1"}}), engine.monotonic)
        adapter(raw_event(0xFE))  # unmapped key must count in single-key guard
        adapter(raw_event(0x45))
        self.assertEqual(actions, [])
        adapter(raw_event(0x45, False))
        adapter(raw_event(0xFE, False))
        adapter(raw_event(0x45))
        self.assertEqual(actions, [{"action": "slot 1"}])

    def test_mouse_consumer_and_unknown_removal_do_not_generate_keyboard_actions(self):
        events = []
        adapter = RawKeys(events.append)
        for event in ({"kind": "mouse", "keys": ("wheel:+1",)},
                      {"kind": "consumer", "usage": 0xE9},
                      {"kind": "device_removed", "device": 999}):
            adapter(event)
        self.assertEqual(events, [])

    def test_overflow_waits_for_all_keys_up_without_replaying_held_keys(self):
        events = []
        adapter = RawKeys(events.append, lambda: 10.)
        for vkey in range(0x41, 0x48):
            adapter(raw_event(vkey))
        events.clear()
        for vkey in range(0x42, 0x48):
            adapter(raw_event(vkey, False))
        self.assertEqual(events, [])
        adapter(raw_event(0x41, False))
        adapter(raw_event(0x45))
        self.assertEqual([(e["usage"], e["down"]) for e in events], [(8, True)])

    def test_invalid_keyboard_packets_do_not_pollute_pressed_state(self):
        events = []
        adapter = RawKeys(events.append, lambda: 10.)
        for event in (raw_event(0), raw_event(0xFF), raw_event(0x45, scan=0xFF),
                      raw_event(0x45, flags=4)):
            adapter(event)
        adapter(raw_event(0x45))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["pressed"], frozenset((8,)))

    def test_queued_event_uses_original_age_and_historical_snapshot(self):
        events, sampled = [], []

        class Capture:
            def snapshot_at(self, received_at):
                sampled.append(received_at)
                return {"request_id": "older"}

            def __call__(self, event):
                events.append(event)

        adapter = RawKeys(Capture(), lambda: 20.)
        event = raw_event(0x45)
        event["age"] = .5
        adapter(event)
        self.assertEqual(sampled, [19.5])
        self.assertEqual(events[0]["t"], 19.5)
        self.assertEqual(events[0]["shown"], {"request_id": "older"})


class SwitchingTests(unittest.TestCase):
    def make_reader(self, *, open_results=(), raw_run=None, usb_run=None, raw_factory_error=None):
        driver = patch("deck_usb.interface0_driver", return_value="winusb")
        driver.start()
        self.addCleanup(driver.stop)
        events, trace, clock, instances = [], [], [10.], []
        results = iter(open_results)

        class USB:
            def __init__(self, callback, **kwargs):
                self.callback, self.closed = callback, False
                instances.append(self)

            def open(self):
                trace.append("usb.open")
                result = next(results, None)
                if isinstance(result, Exception):
                    raise result
                self.closed = False

            def run(self, *, reconnect):
                self_outer.assertFalse(reconnect)
                trace.append("usb.run")
                if usb_run:
                    usb_run(reader, self.callback, trace)
                else:
                    reader.stop()

            def stop(self):
                trace.append("usb.stop")

            def close(self):
                trace.append("usb.close")
                self.closed = True

        class Raw:
            def __init__(self, callback, *, transitions, poll, monotonic):
                trace.append("raw.create")
                if raw_factory_error:
                    reader.stop()
                    raise raw_factory_error
                self_outer.assertTrue(transitions)
                self.callback, self.poll, self.stopped = callback, poll, False
                instances.append(self)

            def run(self):
                trace.append("raw.run")
                if raw_run:
                    raw_run(reader, self, trace, clock)
                else:
                    reader.stop()
                trace.append("raw.closed")

            def stop(self):
                self.stopped = True
                trace.append("raw.stop")

        self_outer = self
        reader = KeyboardInput(events.append, monotonic=lambda: clock[0],
                               usb_factory=USB, raw_factory=Raw)
        return reader, events, trace, instances

    def test_non_winusb_never_opens_usb_even_on_repeated_raw_polls(self):
        def raw_run(reader, raw, trace, clock):
            for _ in range(3):
                clock[0] += 2
                raw.poll()
                probe = getattr(reader, "_probe_thread", None)
                if probe is not None:
                    probe.join(timeout=1)
            self.assertNotIn("usb.open", trace)
            reader.stop()

        for driver in ("hidusb", None, "other"):
            with self.subTest(driver=driver):
                reader, _, trace, _ = self.make_reader(raw_run=raw_run)
                with patch("deck_usb.interface0_driver", return_value=driver), self.assertLogs(
                        "agentdeck.hub.keyboard", "INFO") as logs:
                    reader.run()
                self.assertNotIn("usb.open", trace)
                skipped = [line for line in logs.output if "USB probe skipped" in line]
                self.assertEqual(len(skipped), 1)

    def test_usb_open_failure_falls_back_and_stop_cleans_both(self):
        reader, events, trace, instances = self.make_reader(open_results=[OSError("HID driver")])
        with self.assertLogs("agentdeck.hub.keyboard", "INFO") as logs:
            reader.run()
        self.assertEqual(trace[:3], ["usb.open", "raw.create", "raw.run"])
        self.assertIn("Raw Input", "\n".join(logs.output))
        self.assertTrue(instances[0].closed)
        self.assertTrue(instances[1].stopped)
        self.assertIsNone(reader.raw)

    def test_raw_switches_to_usb_without_dispatch_overlap(self):
        def raw_run(reader, raw, trace, clock):
            raw.callback(raw_event(0x48))
            clock[0] += 2.
            raw.poll()
            reader._probe_thread.join(timeout=1)
            raw.poll()
            self.assertTrue(raw.stopped)

        reader, events, trace, _ = self.make_reader(open_results=[OSError("HID"), None], raw_run=raw_run)
        reader.run()
        self.assertLess(trace.index("raw.closed"), trace.index("usb.run"))
        self.assertEqual([(e["usage"], e["down"]) for e in events], [(0x0B, True), (0x0B, False)])
        self.assertEqual(trace.count("usb.open"), 2)

    def test_usb_read_failure_falls_back_and_releases_held_voice(self):
        def usb_run(reader, callback, trace):
            for event in ReportState().feed(report(0x0B)):
                event["t"] = 10.
                callback(event)
            raise OSError("unplugged")

        reader, events, trace, _ = self.make_reader(usb_run=usb_run)
        reader.run()
        self.assertIn("raw.run", trace)
        self.assertEqual([e["down"] for e in events], [True, False])

    def test_failed_probe_keeps_raw_and_retries_at_bounded_interval(self):
        def raw_run(reader, raw, trace, clock):
            raw.poll()
            self.assertEqual(trace.count("usb.open"), 1)
            clock[0] += 2
            raw.poll()
            reader._probe_thread.join(timeout=1)
            self.assertEqual(trace.count("usb.open"), 2)
            self.assertFalse(raw.stopped)
            raw.poll()
            self.assertEqual(trace.count("usb.open"), 2)
            reader.stop()

        reader, _, _, _ = self.make_reader(open_results=[OSError("HID"), OSError("still HID")],
                                            raw_run=raw_run)
        reader.run()

    def test_raw_startup_failure_and_preemptive_stop_release_resources(self):
        reader, _, trace, instances = self.make_reader(open_results=[OSError("USB unavailable")],
                                                       raw_factory_error=OSError("register failed"))
        reader.run()
        self.assertTrue(instances[0].closed)
        self.assertNotIn("raw.run", trace)
        reader, _, trace, instances = self.make_reader()
        reader.stop()
        reader.run()
        self.assertNotIn("usb.open", trace)
        self.assertNotIn("raw.create", trace)
        self.assertTrue(instances[0].closed)

    def test_stop_during_raw_construction_cannot_start_listener(self):
        reader, _, trace, instances = self.make_reader(open_results=[OSError("USB unavailable")])
        original_factory = reader.raw_factory

        def create(*args, **kwargs):
            raw = original_factory(*args, **kwargs)
            reader.stop()
            return raw

        reader.raw_factory = create
        reader.run()
        self.assertNotIn("raw.run", trace)
        self.assertTrue(instances[1].stopped)
        self.assertTrue(instances[0].closed)

    def test_two_unavailable_backends_wait_before_retrying(self):
        reader, _, trace, _ = self.make_reader(open_results=[OSError("USB unavailable")])

        def unavailable(*args, **kwargs):
            trace.append("raw.unavailable")
            raise OSError("Raw unavailable")

        reader.raw_factory = unavailable
        with patch.object(reader._stop, "wait", side_effect=lambda seconds: reader.stop()) as wait:
            reader.run()
        wait.assert_called_once_with(2)
        self.assertEqual(trace.count("usb.open"), 1)
        self.assertEqual(trace.count("raw.unavailable"), 1)
        self.assertNotIn("raw.run", trace)

    def test_slow_driver_probe_does_not_block_raw_message_pump(self):
        import threading

        entered, release = threading.Event(), threading.Event()

        def query():
            entered.set()
            release.wait(2)
            return "hidusb"

        def raw_run(reader, raw, trace, clock):
            clock[0] += 2
            with patch("deck_usb.interface0_driver", side_effect=query):
                raw.poll()
                self.assertTrue(entered.wait(1))
                try:
                    raw.callback(raw_event(0x45))
                    self.assertEqual(events[-1]["usage"], 8)
                    self.assertEqual(events[-1]["reader"], "Raw Input")
                    self.assertFalse(raw.stopped)
                    raw.poll()  # a pending probe must not spawn a second one
                finally:
                    release.set()
                    reader._probe_thread.join(timeout=1)
                reader.stop()

        reader, events, trace, _ = self.make_reader(raw_run=raw_run)
        with patch("deck_usb.interface0_driver", return_value="hidusb"):
            reader.run()
        self.assertNotIn("usb.open", trace)

    def test_driver_change_to_winusb_enables_probe(self):
        def raw_run(reader, raw, trace, clock):
            clock[0] += 2
            with patch("deck_usb.interface0_driver", return_value="winusb"):
                raw.poll()
                reader._probe_thread.join(timeout=1)
            raw.poll()
            self.assertTrue(raw.stopped)

        reader, _, trace, _ = self.make_reader(raw_run=raw_run)
        with patch("deck_usb.interface0_driver", return_value="hidusb"):
            reader.run()
        self.assertEqual(trace.count("usb.open"), 1)
        self.assertLess(trace.index("raw.closed"), trace.index("usb.run"))

    def test_snapshot_is_forwarded_to_usb_probe_callback(self):
        events = []

        class Capture:
            snapshot = lambda self: {"request_id": "captured", "nonce": "n"}
            __call__ = lambda self, event: events.append(event)

        fake = SimpleNamespace(stop=lambda: None, close=lambda: None)
        reader = KeyboardInput(Capture(), usb_factory=lambda callback, **kw: fake,
                               raw_factory=lambda *a, **kw: None)
        self.assertEqual(reader.snapshot(), {"request_id": "captured", "nonce": "n"})

    def test_idle_usb_timeouts_and_raw_polls_still_beat(self):
        from deck_usb import USBInput

        class Timeout(Exception):
            pass

        receiver = USBInput(lambda event: None)
        receiver.heartbeat = Mock()
        receiver._core = SimpleNamespace(USBTimeoutError=Timeout)

        def read(*args, **kwargs):
            if receiver.heartbeat.call_count == 5:
                receiver.stop()
            raise Timeout()

        receiver.endpoint = SimpleNamespace(read=read, wMaxPacketSize=8)
        receiver.run(reconnect=False)
        self.assertEqual(receiver.heartbeat.call_count, 5)

        def raw_run(reader, raw, trace, clock):
            before = reader.heartbeat.call_count
            for _ in range(5):
                raw.poll()
            self.assertEqual(reader.heartbeat.call_count - before, 5)
            reader.stop()

        reader, _, _, _ = self.make_reader(raw_run=raw_run)
        reader.heartbeat = Mock()
        with patch("deck_usb.interface0_driver", return_value="hidusb"):
            reader.run()

    def test_stop_during_probe_closes_late_usb_without_switching(self):
        import threading

        entered, release = threading.Event(), threading.Event()

        def raw_run(reader, raw, trace, clock):
            original = reader.usb.open

            def slow_open():
                entered.set()
                release.wait(2)
                original()

            reader.usb.open = slow_open
            clock[0] += 2
            with patch("deck_usb.interface0_driver", return_value="winusb"):
                raw.poll()
                try:
                    self.assertTrue(entered.wait(1))
                    reader.stop()
                finally:
                    release.set()
                    reader._probe_thread.join(timeout=1)

        reader, _, trace, instances = self.make_reader(raw_run=raw_run)
        with patch("deck_usb.interface0_driver", return_value="hidusb"):
            reader.run()
        self.assertTrue(instances[0].closed)
        self.assertFalse(reader._usb_ready)
        self.assertNotIn("usb.run", trace)


class KeyboardLogTests(unittest.TestCase):
    def test_binding_labels(self):
        labels = {"hid:0x18": "U", "ctrl+hid:0x09": "Ctrl+F",
                  "ctrl+shift+alt+win+hid:0x27": "Ctrl+Shift+Alt+Win+0",
                  "hid:0x04": "A", "hid:0x1D": "Z", "hid:0x1E": "1",
                  "hid:0x28": "Enter", "hid:0x29": "Esc", "hid:0x2A": "Backspace",
                  "hid:0x2B": "Tab", "hid:0x2C": "Space", "hid:0x2D": "-",
                  "hid:0x2E": "=", "hid:0x2F": "[", "hid:0x30": "]", "hid:0x31": "\\",
                  "hid:0x33": ";", "hid:0x34": "'", "hid:0x35": "`", "hid:0x36": ",",
                  "hid:0x37": ".", "hid:0x38": "/", "hid:0x3A": "F1", "hid:0x45": "F12",
                  "hid:0x68": "F13", "hid:0x73": "F24", "hid:0xFF": "0xFF"}
        for binding, label in labels.items():
            with self.subTest(binding=binding):
                self.assertEqual(hub.binding_label(binding), label)
        for binding in (None, 123, {}, "hid:0xnope", "", "ctrl+unknown"):
            with self.subTest(binding=binding):
                self.assertIsInstance(hub.binding_label(binding), str)

    def test_warning_names_reader_binding_label_action_and_reason(self):
        engine = SimpleNamespace(monotonic=lambda: 10., input_snapshot=lambda: {},
                                 action=Mock(side_effect=hub.HubError("no session")))
        keys = hub.USBKeys(engine, {"bindings": {"hid:0x18": "prompt commit"}})
        for reader, reason in (("Raw Input", "keys leak into the window under Raw Input; install WinUSB"),
                               ("USB", "no session")):
            with self.subTest(reader=reader), self.assertLogs("agentdeck.hub", "WARNING") as logs:
                keys(dict(ReportState().feed(report(0x18))[0], t=10., reader=reader))
            self.assertEqual(logs.output, ["WARNING:agentdeck.hub:%s hid:0x18 (U; 第 4 排第 3 颗) prompt commit blocked: %s" %
                                          (reader, reason)])
        self.assertEqual(engine.action.call_count, 1)  # Raw Input was refused before dispatch.

    def test_hub_logs_receipt_and_action_result_with_reader(self):
        for reader in ("USB", "Raw Input"):
            engine = SimpleNamespace(monotonic=lambda: 10., input_snapshot=lambda: {},
                                     action=Mock(return_value={"status": "selected"}))
            keys = hub.USBKeys(engine, {"bindings": {"hid:0x08": "slot 1"}})
            event = dict(ReportState().feed(report(8))[0], t=10., reader=reader)
            with self.assertLogs("agentdeck.hub.keys", "DEBUG") as logs:
                keys(event)
            output = "\n".join(logs.output)
            self.assertIn("entered hub reader=" + reader, output)
            self.assertIn("action=slot 1", output)
            self.assertIn("'status': 'selected'", output)
            self.assertEqual(len(logs.output), 2)

    def test_blocked_action_is_logged_with_reader_and_reason(self):
        engine = SimpleNamespace(monotonic=lambda: 10., input_snapshot=lambda: {},
                                 action=Mock(side_effect=hub.HubError("no session")))
        keys = hub.USBKeys(engine, {"bindings": {"hid:0x08": "slot 1"}})
        with self.assertLogs("agentdeck.hub.keys", "DEBUG") as logs:
            keys(dict(ReportState().feed(report(8))[0], t=10., reader="Raw Input"))
        self.assertIn("reader=Raw Input", logs.output[-1])
        self.assertIn("result=blocked: no session", logs.output[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
