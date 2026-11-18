"""AgentDeck USB offline checks; all USB, Windows and action I/O use fakes."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import deck
import deck_input
import deck_usb as usb


def report(*usages, modifiers=0):
    assert len(usages) <= 6
    return bytes([modifiers, 0, *usages, *([0] * (6 - len(usages)))])


def ordinary(events):
    return [event for event in events if not event["modifier"]]


def transitions(events):
    return [(event["usage"], event["down"]) for event in ordinary(events)]


def raises(error, callback):
    try:
        callback()
    except error:
        return
    raise AssertionError("expected %s" % (error,))


class StopFlag:
    def __init__(self, stop_on_wait=False):
        self.stopped = False
        self.waits = []
        self.stop_on_wait = stop_on_wait

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, duration):
        self.waits.append(duration)
        if self.stop_on_wait:
            self.set()
        return self.stopped


class Timeout(Exception):
    pass


class Endpoint:
    def __init__(self, address=0x81, attributes=3, packets=None):
        self.bEndpointAddress, self.bmAttributes = address, attributes
        self.wMaxPacketSize = 32
        # An endpoint used only by open() has one idle probe. Further reads
        # still fail loudly unless the test explicitly provides packets.
        self.packets = [Timeout("idle probe")] if packets is None else list(packets)
        self.reads = []

    def read(self, size, timeout):
        self.reads.append((size, timeout))
        assert self.packets, "unexpected read: fake did not stop the loop"
        item = self.packets.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item() if callable(item) else item


class Device:
    def __init__(self, endpoints=(), configuration_error=None, protocol_error=None):
        self.endpoints = list(endpoints)
        self.configuration_error, self.protocol_error = configuration_error, protocol_error
        self.interfaces, self.controls = [], []

    def get_active_configuration(self):
        if self.configuration_error:
            raise self.configuration_error
        return self

    def __getitem__(self, interface):
        self.interfaces.append(interface)
        assert interface == (0, 0), "accessed an interface other than keyboard interface zero"
        return self.endpoints

    def ctrl_transfer(self, *args, **kwargs):
        self.controls.append((args, kwargs))
        if self.protocol_error:
            raise self.protocol_error
        return 0


class FakeUSB:
    """Only the supported API exists; resets/config changes/vendor writes fail."""

    def __init__(self, devices=(), claim_error=None, backend_available=True):
        self.devices, self.claim_error = list(devices), claim_error
        self.backend = object() if backend_available else None
        self.finds, self.claims, self.releases, self.disposals = [], [], [], []
        package = ModuleType("usb")
        package.__path__ = []
        core, util = ModuleType("usb.core"), ModuleType("usb.util")
        core.find, core.USBTimeoutError = self.find, Timeout
        util.ENDPOINT_IN, util.ENDPOINT_TYPE_INTR = 0x80, 3
        util.endpoint_direction = lambda value: value & 0x80
        util.endpoint_type = lambda value: value & 3
        util.claim_interface, util.release_interface = self.claim, self.release
        util.dispose_resources = self.disposals.append
        package.core, package.util = core, util
        backend_package = ModuleType("libusb_package")
        backend_package.get_libusb1_backend = lambda: self.backend
        self.modules = {"usb": package, "usb.core": core, "usb.util": util,
                        "libusb_package": backend_package}

    def find(self, **kwargs):
        assert kwargs == {"idVendor": 0x4132, "idProduct": 0x2107, "backend": self.backend}
        self.finds.append(kwargs)
        assert self.devices, "unexpected extra device search"
        item = self.devices.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def claim(self, device, interface):
        assert interface == 0
        self.claims.append((device, interface))
        if self.claim_error:
            raise self.claim_error

    def release(self, device, interface):
        assert interface == 0
        self.releases.append((device, interface))

    def installed(self):
        return patch.dict(sys.modules, self.modules)


def finish(receiver):
    def stop():
        receiver.stop()
        return report()
    return stop


def test_usb_report_diff_multi_key_and_repeat():
    state = usb.ReportState()
    assert state.feed(report()) == []
    assert transitions(state.feed(report(8, 5, 8))) == [(5, True), (8, True)]
    assert state.feed(report(5, 8)) == []
    changed = state.feed(report(8, 0x0B))
    assert transitions(changed) == [(5, False), (0x0B, True)]
    assert all(event["kind"] == "keyboard" for event in changed)
    assert changed[-1]["keys"] == ("hid:0x0B",)
    assert transitions(state.feed(report())) == [(8, False), (0x0B, False)]
    assert state.feed(report()) == []


def test_usb_modifier_combinations_sides_and_device_isolation():
    for bits in (1, 0x10, 0x11):
        events = usb.ReportState().feed(report(0x1D, modifiers=bits))
        key = ordinary(events)[0]
        assert key["keys"] == ("ctrl+hid:0x1D", "hid:0x1D")
        assert key["modifiers"] == ("ctrl",)
        assert all(event["modifier"] for event in events[:-1])
    assert usb.report_modifiers(0xFF) == ("ctrl", "shift", "alt", "win")
    state = usb.ReportState()
    assert ordinary(state.feed(report(9, modifiers=0xAA)))[0]["keys"] == (
        "shift+win+hid:0x09", "hid:0x09")
    # Changing only modifiers while the key is held does not press it again.
    assert ordinary(state.feed(report(9, modifiers=0xFF))) == []
    assert transitions(state.feed(report())) == [(9, False)]
    main_keyboard, deck_keyboard = usb.ReportState(), usb.ReportState()
    main_keyboard.feed(report(modifiers=1))
    assert ordinary(deck_keyboard.feed(report(0x1D)))[0]["keys"] == ("hid:0x1D",)
    assert deck_keyboard.modifier_bits == 0


def test_usb_unknown_lengths_and_rollover_preserve_state():
    state = usb.ReportState()
    state.feed(report(8, modifiers=1))
    with patch.object(usb.log, "warning") as warned:
        for packet in (b"", bytes(7), bytes(9), bytes(32), bytes(9)):
            assert state.feed(packet) == []
        assert warned.call_count == 4
        assert {call.args[1] for call in warned.call_args_list} == {0, 7, 9, 32}
    for packet in (report(1), report(2), report(3), bytes([0, 1, 0, 0, 0, 0, 0, 0])):
        assert state.feed(packet) == []
        assert state.pressed == {8} and state.modifier_bits == 1
    assert ordinary(state.feed(report(8, modifiers=1))) == []
    assert transitions(state.feed(report())) == [(8, False)]


def test_usb_action_dispatch_ignores_release_repeat_and_prefers_combo():
    actions = []
    dispatcher = deck.ActionQueue({"ctrl+hid:0x1D": "slot 3", "hid:0x1D": "auto",
                                   "hid:0x08": "slot 1"},
                                  SimpleNamespace(execute=actions.append))
    dispatcher.thread.start()
    state = usb.ReportState()
    try:
        for packet in (report(0x1D, modifiers=1), report(0x1D, modifiers=1),
                       report(0x1D), report(), report(8), report(8), report(), report(8)):
            for event in state.feed(packet):
                dispatcher.events.put(event)
    finally:
        dispatcher.close()
    assert actions == ["slot 3", "slot 1", "slot 1"]
    assert not dispatcher.thread.is_alive()


def test_usb_open_selects_only_interface_zero_interrupt_in():
    endpoint = Endpoint()
    device = Device([Endpoint(0x01), Endpoint(0x82, 2), endpoint, Endpoint(0x83)])
    backend = FakeUSB([device])
    receiver = usb.USBInput(lambda event: None)
    with backend.installed():
        receiver.open()
        receiver.open()
        assert receiver.endpoint is endpoint and receiver.boot_protocol
        assert len(backend.finds) == 1
        assert device.interfaces == [(0, 0)]
        assert backend.claims == [(device, 0)]
        assert device.controls == [((0x21, 0x0B, 0, 0), {"timeout": 100})]
        assert endpoint.reads == [(32, 100)]
        receiver.close()
        receiver.close()
    assert backend.releases == [(device, 0)] and backend.disposals == [device]
    assert receiver.device is None and receiver.endpoint is None and not receiver.boot_protocol


def test_usb_auto_rejects_claimed_but_unreadable_interface_with_zadig_hint():
    callback = lambda event: None
    for failure in (OSError("Input/Output Error"), NotImplementedError("HID read unavailable"),
                    PermissionError("Access denied")):
        endpoint = Endpoint(packets=[failure])
        device = Device([endpoint])
        backend = FakeUSB([device])
        with backend.installed(), patch.object(deck_input, "RawInput") as raw, \
                patch.object(usb.log, "warning") as usb_warned, patch.object(deck.log, "warning") as warned:
            assert deck.select_backend(callback) == ("rawinput", raw.return_value)
        raw.assert_called_once_with(callback, exclusive=False)
        assert endpoint.reads == [(32, 100)]
        assert backend.claims == [(device, 0)] and backend.releases == [(device, 0)]
        assert backend.disposals == [device]
        assert any(usb.ZADIG_HINT in str(call.args) for call in usb_warned.call_args_list)
        assert any("宏键盘按键会漏到窗口" in call.args[0] for call in warned.call_args_list)


def test_usb_probe_timeout_proves_readable_idle_interface():
    endpoint = Endpoint(packets=[Timeout("no key pressed")])
    device = Device([endpoint])
    backend = FakeUSB([device])
    receiver = usb.USBInput(lambda event: None)
    with backend.installed():
        receiver.open()
        receiver.open()
        assert receiver.endpoint is endpoint and receiver._pending_report is None
        assert endpoint.reads == [(32, 100)]
        assert len(backend.finds) == 1
        receiver.close()
    assert backend.releases == [(device, 0)] and backend.disposals == [device]


def test_usb_probe_first_report_is_dispatched_once_without_losing_key():
    packet = report(0x1D, modifiers=1)
    endpoint = Endpoint(packets=[packet, packet])
    device, events = Device([endpoint]), []
    backend = FakeUSB([device])
    receiver = usb.USBInput(events.append)
    receiver._stop = StopFlag()
    endpoint.packets.append(finish(receiver))
    with backend.installed():
        receiver.open()
        assert endpoint.reads == [(32, 100)] and events == []
        assert bytes(receiver._pending_report) == packet
        receiver.run()
    assert transitions(events) == [(0x1D, True), (0x1D, False)]
    assert ordinary(events)[0]["keys"] == ("ctrl+hid:0x1D", "hid:0x1D")
    assert endpoint.reads == [(32, 100)] * 3
    assert receiver._pending_report is None and receiver._stop.waits == []
    assert len(backend.finds) == 1


def test_usb_boot_protocol_failure_still_reads_real_length():
    endpoint = Endpoint(packets=[bytes(9), report(8)])
    device = Device([endpoint], protocol_error=OSError("unsupported SET_PROTOCOL"))
    backend = FakeUSB([device])
    events = []
    receiver = usb.USBInput(events.append)
    receiver._stop = StopFlag()
    endpoint.packets.append(finish(receiver))
    with backend.installed(), patch.object(usb.log, "warning") as warned:
        receiver.run()
    assert transitions(events) == [(8, True), (8, False)]
    assert all(item == (32, 100) for item in endpoint.reads)
    assert any("SET_PROTOCOL boot failed" in call.args[0] for call in warned.call_args_list)
    assert any("report length=%d" in call.args[0] and call.args[1] == 9 for call in warned.call_args_list)
    assert receiver._stop.waits == []


def test_usb_timeouts_keep_connection_and_stop_releases_resources():
    endpoint = Endpoint(packets=[Timeout("idle"), report(8), Timeout("idle")])
    device, events = Device([endpoint]), []
    backend = FakeUSB([device])
    receiver = usb.USBInput(events.append)
    receiver._stop = StopFlag()
    endpoint.packets.append(finish(receiver))
    with backend.installed():
        receiver.run()
    assert len(backend.finds) == 1 and receiver._stop.waits == []
    assert transitions(events) == [(8, True), (8, False)]
    assert backend.releases == [(device, 0)] and backend.disposals == [device]


def test_usb_disconnect_reconnects_after_two_seconds_and_resets_keys():
    first_endpoint = Endpoint(packets=[report(8), OSError("unplugged")])
    second_endpoint = Endpoint(packets=[report(8)])
    first, second = Device([first_endpoint]), Device([second_endpoint])
    backend, events = FakeUSB([first, second]), []
    receiver = usb.USBInput(events.append)
    receiver._stop = StopFlag()
    second_endpoint.packets.append(finish(receiver))
    with backend.installed(), patch.object(usb.log, "warning") as warned:
        receiver.run()
    assert len(backend.finds) == 2 and receiver._stop.waits == [2]
    assert transitions(events) == [(8, True), (8, True), (8, False)]
    assert backend.releases == [(first, 0), (second, 0)]
    assert backend.disposals == [first, second]
    assert any("reconnecting" in call.args[0] for call in warned.call_args_list)


def test_usb_initial_open_failure_retries_and_zadig_hint():
    endpoint = Endpoint(packets=[report(8)])
    device = Device([endpoint])
    backend, events = FakeUSB([NotImplementedError("driver has no USB API"), device]), []
    receiver = usb.USBInput(events.append)
    receiver._stop = StopFlag()
    endpoint.packets.append(finish(receiver))
    with backend.installed(), patch.object(usb.log, "warning") as warned:
        receiver.run()
    assert receiver._stop.waits == [2] and len(backend.finds) == 2
    assert transitions(events) == [(8, True), (8, False)]
    assert any(call.args[1] == usb.ZADIG_HINT for call in warned.call_args_list if len(call.args) > 1)
    # Missing device and missing native backend both remain stoppable.
    for backend in (FakeUSB([None]), FakeUSB(backend_available=False)):
        receiver = usb.USBInput(lambda event: None)
        receiver._stop = StopFlag(stop_on_wait=True)
        with backend.installed(), patch.object(usb.log, "warning") as warned:
            receiver.run()
        assert receiver._stop.waits == [2]
        assert any(usb.ZADIG_HINT in str(call.args) for call in warned.call_args_list)


def test_usb_open_failures_dispose_and_close_is_idempotent():
    cases = [(Device(configuration_error=OSError("access denied")), None),
             (Device([Endpoint()]), NotImplementedError("WinUSB required")),
             (Device([Endpoint(0x01), Endpoint(0x82, 2)]), None)]
    for device, claim_error in cases:
        backend = FakeUSB([device], claim_error=claim_error)
        receiver = usb.USBInput(lambda event: None)
        with backend.installed(), patch.object(usb.log, "warning") as warned:
            raises((OSError, NotImplementedError, RuntimeError), receiver.open)
            receiver.close()
        assert backend.disposals == [device] and backend.releases == []
        assert receiver.device is None and receiver.endpoint is None
        assert any(usb.ZADIG_HINT in str(call.args) for call in warned.call_args_list)
    device = Device([Endpoint()])
    backend = FakeUSB([device])
    receiver = usb.USBInput(lambda event: None)
    with backend.installed():
        receiver.open()
        backend.modules["usb.util"].release_interface = Mock(side_effect=OSError("removed"))
        receiver.close()
        receiver.close()
    assert backend.disposals == [device]


def test_usb_callback_error_and_interrupt_cleanup():
    for failure in (RuntimeError("fake callback failure"), KeyboardInterrupt()):
        device = Device([Endpoint(packets=[report(8)])])
        backend = FakeUSB([device])
        receiver = usb.USBInput(Mock(side_effect=failure))
        with backend.installed():
            if isinstance(failure, KeyboardInterrupt):
                receiver.run()
            else:
                raises(RuntimeError, receiver.run)
        assert backend.releases == [(device, 0)] and backend.disposals == [device]


def test_usb_auto_backend_selection_success_and_observer_fallback():
    callback = lambda event: None
    fake = SimpleNamespace(open=Mock(), close=Mock(), run=Mock())
    with patch.object(usb, "USBInput", return_value=fake) as construct, \
            patch.object(deck_input, "RawInput") as raw:
        assert deck.select_backend(callback) == ("usb", fake)
        construct.assert_called_once_with(callback)
        fake.open.assert_called_once_with()
        fake.close.assert_not_called()
        raw.assert_not_called()
    for failure in (ImportError("pyusb unavailable"), OSError("access denied"),
                    NotImplementedError("WinUSB unavailable"), RuntimeError("no native backend")):
        fake.open = Mock(side_effect=failure)
        fake.close.reset_mock()
        with patch.object(usb, "USBInput", return_value=fake), \
                patch.object(deck_input, "RawInput") as raw, patch.object(deck.log, "warning") as warned:
            assert deck.select_backend(callback) == ("rawinput", raw.return_value)
            raw.assert_called_once_with(callback, exclusive=False)
            fake.close.assert_called_once_with()
            assert any("宏键盘按键会漏到窗口" in call.args[0] for call in warned.call_args_list)


def test_usb_explicit_backends_and_experimental_hook_opt_in():
    callback = lambda event: None
    fake = SimpleNamespace(open=Mock(), close=Mock(), run=Mock())
    with patch.object(usb, "USBInput", return_value=fake), patch.object(deck_input, "RawInput") as raw:
        assert deck.select_backend(callback, "usb") == ("usb", fake)
        fake.open.assert_not_called()  # explicit USB run owns the reconnect loop
        raw.assert_not_called()
    with patch.object(usb, "USBInput") as construct, \
            patch.object(deck_input, "RawInput") as raw, patch.object(deck.log, "warning"):
        assert deck.select_backend(callback, "rawinput") == ("rawinput", raw.return_value)
        raw.assert_called_once_with(callback, exclusive=False)
        construct.assert_not_called()
        raw.reset_mock()
        deck.select_backend(callback, "rawinput", exclusive=True)
        raw.assert_called_once_with(callback, exclusive=True)
    raises(ValueError, lambda: deck.select_backend(callback, "invalid"))


def test_usb_mapping_normalization_and_old_rawinput_bindings():
    expected = {"hid:0x08": "slot 1", "hid:0x05": "slot 2", "ctrl+hid:0x1D": "slot 3",
                "hid:0x2C": "slot 4", "hid:0x0A": "approve", "ctrl+hid:0x09": "deny",
                "hid:0x0B": "next_wait", "hid:0x30": "cycle +1", "hid:0x2F": "cycle -1",
                "ctrl+hid:0x27": "next_wait", "hid:0x0F": "auto",
                "hid:0x16": "cycle +1", "hid:0x09": "cycle -1", "hid:0x15": "cycle +1",
                "hid:0x13": "cycle -1", "hid:0x2D": "cycle +1", "hid:0x2E": "cycle -1",
                "hid:0x14": "next_wait", "hid:0x19": "next_wait"}
    assert deck.load_map() == expected
    old = json.loads(deck.DEFAULT_MAP.read_text(encoding="utf-8"))["_rawinput_bindings"]
    assert deck.load_map(backend="rawinput") == old and len(old) == 10
    assert old["ctrl+vk:0x5A"] == "slot 3" and old["vk:0xDD"] == "cycle +1"
    assert deck.normalize_key("HID:0x8") == "hid:0x08"
    assert deck.normalize_key("WIN+Alt+CTRL+shift+hid:0x1d") == "ctrl+shift+alt+win+hid:0x1D"
    for key in ("hid:0x00", "hid:0x01", "hid:0x100", "ctrl+ctrl+hid:0x08", "meta+hid:0x08"):
        raises(ValueError, lambda: deck.normalize_key(key))
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "map.json"
        for text in ('{"version":1,"bindings":{"hid:0x8":"auto","HID:0x08":"deny"}}',
                     '{"version":1,"bindings":{"alt+ctrl+hid:0x9":"auto","ctrl+alt+hid:0x09":"deny"}}'):
            path.write_text(text, encoding="utf-8")
            raises(ValueError, lambda: deck.load_map(path))
        path.write_text(json.dumps({"version": 1, "bindings": {"vk:0x45": "slot 1"}}), encoding="utf-8")
        assert deck.load_map(path, backend="rawinput") == {"vk:0x45": "slot 1"}
        path.write_text(json.dumps({"version": 1, "bindings": {}, "_rawinput_bindings": []}), encoding="utf-8")
        raises(ValueError, lambda: deck.load_map(path, backend="rawinput"))


def test_usb_run_uses_selected_backend_mapping_and_cleans_up():
    import deck_windows
    for backend, keys in (("usb", ("hid:0x08", "ctrl+hid:0x1D")),
                          ("rawinput", ("vk:0x45", "ctrl+vk:0x5A"))):
        actions, closed = [], []
        lock = SimpleNamespace(acquire=lambda: True, close=lambda: closed.append("lock"))

        def select(callback, requested, exclusive):
            assert requested == backend and exclusive is False

            def emit():
                for key in keys:
                    callback({"kind": "keyboard", "keys": (key,), "down": True})
                    callback({"kind": "keyboard", "keys": (key,), "down": False})
            return backend, SimpleNamespace(run=emit, close=lambda: closed.append("receiver"))

        with patch.object(deck, "SingleInstance", return_value=lock), \
                patch.object(deck_windows, "WindowControl"), \
                patch.object(deck, "Controller", return_value=SimpleNamespace(execute=actions.append)), \
                patch.object(deck, "select_backend", side_effect=select):
            assert deck.run(backend=backend) == 0
        assert actions == ["slot 1", "slot 3"]
        assert closed == ["receiver", "lock"]


def test_usb_learn_prints_hid_key_once_and_cli_selects_usb():
    state = usb.ReportState()
    with contextlib.redirect_stdout(io.StringIO()) as output:
        for packet in (report(0x1D, modifiers=1), report(0x1D, modifiers=1), report()):
            for event in state.feed(packet):
                deck.learn_event(event)
    lines = output.getvalue().splitlines()
    assert len(lines) == 1 and "ctrl+hid:0x1D" in lines[0] and "hid:0x1D" in lines[0]
    receiver = SimpleNamespace(run=Mock(), close=Mock())
    with patch.object(deck, "select_backend", return_value=("usb", receiver)) as select, \
            patch.object(deck.logging, "basicConfig"), contextlib.redirect_stdout(io.StringIO()):
        assert deck.main(["learn", "--backend", "usb"]) == 0
    select.assert_called_once_with(deck.learn_event, "usb")
    receiver.run.assert_called_once_with()
    receiver.close.assert_called_once_with()
    with patch.object(deck, "run", return_value=0) as run, patch.object(deck.logging, "basicConfig"):
        for arguments, backend, exclusive in ((["run", "-v"], "auto", False),
                                               (["run", "--backend", "usb", "-v"], "usb", False),
                                               (["run", "--backend", "rawinput", "--exclusive", "-v"], "rawinput", True)):
            assert deck.main(arguments) == 0
            run.assert_called_with(deck.DEFAULT_MAP, exclusive=exclusive, backend=backend)


def main():
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("deck USB offline tests: %d groups passed" % len(tests))


if __name__ == "__main__":
    main()
