"""Device-correlated hook tests. All Win32 calls use an offline backend."""
import ctypes
from unittest.mock import patch

import deck_input as raw
from test_deck_input import Backend, Function, pointer


class Clock:
    def __init__(self):
        self.now = 1.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class HookBackend(Backend):
    def __init__(self):
        super().__init__()
        self.clock = Clock()
        self.timestamp = 1000
        self.packets, self.pending = {}, []
        self.events, self.next_calls, self.hook_calls = [], [], []
        self.next_packet = 10
        self.user.SetWindowsHookExW = Function(self.set_hook)
        self.user.UnhookWindowsHookEx = Function(self.unhook)
        self.user.CallNextHookEx = Function(self.call_next)
        self.user.GetMessageTime = Function(lambda: self.timestamp)
        self.user.PeekMessageW = Function(self.peek)

    def receiver(self, exclusive=True):
        receiver = raw.RawInput(self.events.append, self.user, self.kernel, self.hid,
                                exclusive=exclusive)
        receiver.matcher = raw.KeyboardMatcher(self.clock)
        receiver.running, receiver.hwnd = True, self.hwnd
        return receiver

    def set_hook(self, kind, callback, instance, thread):
        assert (kind, instance, thread) == (raw.WH_KEYBOARD_LL, self.hwnd, 0)
        self.hook_calls.append("install")
        return 0xABCDEF123

    def unhook(self, hook):
        assert hook == 0xABCDEF123
        self.hook_calls.append("uninstall")
        return 1

    def call_next(self, hook, code, message, address):
        self.next_calls.append((code, message))
        return 79  # preserve CallNextHookEx's exact return value

    def add_key(self, device=1, vkey=0x45, scan=0x12, flags=0, timestamp=None,
                queue=True):
        timestamp = self.timestamp if timestamp is None else timestamp
        self.packet_for(device, 1, raw.RAWKEYBOARD(scan, flags, 0, vkey,
                                                raw.WM_KEYUP if flags & 1 else raw.WM_KEYDOWN, 0))
        handle = self.next_packet
        self.next_packet += 1
        self.packets[handle] = self.packet
        if queue:
            self.pending.append((raw.WM_INPUT, handle, timestamp))
        return handle

    def add_device_change(self, device):
        self.pending.append((raw.WM_INPUT_DEVICE_CHANGE, device, self.timestamp))

    def GetRawInputData(self, handle, command, destination, size_ptr, header_size):
        self.packet = self.packets[handle]
        return super().GetRawInputData(handle, command, destination, size_ptr, header_size)

    def peek(self, message, hwnd, first, last, flags):
        packet = pointer(message, raw.MSG)
        if (first, last) == (raw.WM_INPUT_DEVICE_CHANGE, raw.WM_INPUT):
            assert hwnd == self.hwnd and flags == raw.PM_REMOVE
            if not self.pending:
                return 0
            packet.message, packet.lParam, packet.time = self.pending.pop(0)
            packet.hwnd, packet.wParam = self.hwnd, 1
            return 1
        packet.message = raw.WM_QUIT
        return 1

    def hook(self, receiver, vkey=0x45, scan=0x12, flags=0, timestamp=None, code=0):
        key = raw.KBDLLHOOKSTRUCT(vkey, scan, flags,
                                 self.timestamp if timestamp is None else timestamp, 0)
        message = raw.WM_KEYUP if flags & raw.LLKHF_UP else raw.WM_KEYDOWN
        with patch.object(raw.time, "monotonic", self.clock), \
                patch.object(raw.time, "sleep", self.clock.sleep):
            return receiver._hookproc(code, message, ctypes.addressof(key))


def decisions(backend):
    return [event["decision"] for event in backend.events if event["kind"] == "hook"]


def actions(backend):
    return [event for event in backend.events if event["kind"] != "hook"]


def test_hook_raw_before_and_after_both_directions():
    for raw_first in (True, False):
        backend = HookBackend()
        receiver = backend.receiver()
        for raw_flags, hook_flags, stamp in ((0, 0, 1000), (1, raw.LLKHF_UP, 1001)):
            packet = backend.add_key(flags=raw_flags, timestamp=stamp, queue=not raw_first)
            if raw_first:
                receiver._read(packet, stamp)
            assert backend.hook(receiver, flags=hook_flags, timestamp=stamp) == 1
        assert decisions(backend) == ["suppressed", "suppressed"]
        assert len(actions(backend)) == 1
        assert not backend.next_calls
        if not raw_first:
            assert sum(call == ("default", raw.WM_INPUT) for call in backend.calls) == 2


def test_hook_other_unknown_injected_and_timeout_pass():
    for device in (2, 0):
        backend = HookBackend()
        receiver = backend.receiver()
        backend.add_key(device=device)
        assert backend.hook(receiver) == 79
        assert decisions(backend) == ["other-device"]
        assert not actions(backend)
    for flags in (raw.LLKHF_INJECTED, raw.LLKHF_INJECTED | 2, 2,
                  raw.LLKHF_INJECTED | raw.LLKHF_UP):
        backend = HookBackend()
        receiver = backend.receiver()
        backend.add_key()  # injected hooks must not consume unrelated raw evidence
        assert backend.hook(receiver, flags=flags) == 79
        assert decisions(backend) == ["injected"]
        assert backend.pending and backend.clock.now == 1.0
    backend = HookBackend()
    receiver = backend.receiver()
    assert backend.hook(receiver) == 79
    assert decisions(backend) == ["timeout"]
    assert 0.050 <= backend.clock.now - 1.0 <= 0.051
    assert backend.hook(receiver, code=-1) == 79
    assert len(decisions(backend)) == 1


def test_hook_matches_direction_scan_timestamp_and_exact_device():
    cases = ({"vkey": 0x42}, {"flags": 1}, {"scan": 0x13},
             {"flags": 2}, {"timestamp": 999})
    for change in cases:
        backend = HookBackend()
        receiver = backend.receiver()
        backend.add_key(**change)
        assert backend.hook(receiver) == 79
        assert decisions(backend) == ["timeout"]
    backend = HookBackend()
    receiver = backend.receiver()
    backend.paths[1] = r"\\?\HID#VID_4132&PID_21070#different"
    backend.add_key()
    assert backend.hook(receiver) == 79
    assert not actions(backend)


def test_hook_recent_expiry_one_use_ambiguity_and_late_raw():
    backend = HookBackend()
    receiver = backend.receiver()
    packet = backend.add_key(queue=False)
    receiver._read(packet, 1000)
    backend.clock.now += 0.101
    assert backend.hook(receiver) == 79
    assert decisions(backend) == ["timeout"]
    backend = HookBackend()
    receiver = backend.receiver()
    backend.add_key()
    assert backend.hook(receiver) == 1
    assert backend.hook(receiver) == 79
    assert decisions(backend) == ["suppressed", "ambiguous"]
    for devices in ((1, 2), (2, 1), (1, 1), (1, 0)):
        backend = HookBackend()
        receiver = backend.receiver()
        for device in devices:
            backend.add_key(device=device)
        assert backend.hook(receiver) == 79
        assert decisions(backend) == ["ambiguous"]
    # Timed-out hook's late raw packet cannot prove a later same-key main event.
    backend = HookBackend()
    receiver = backend.receiver()
    assert backend.hook(receiver) == 79
    backend.add_key(timestamp=1000)
    backend.add_key(device=2, timestamp=1001)
    assert backend.hook(receiver, timestamp=1001) == 79
    assert decisions(backend) == ["timeout", "other-device"]
    # Even a second indistinguishable hook in the same Windows millisecond
    # cannot borrow the raw record of the timed-out event.
    backend = HookBackend()
    receiver = backend.receiver()
    assert backend.hook(receiver) == 79
    backend.add_key()
    assert backend.hook(receiver) == 79
    assert decisions(backend) == ["timeout", "ambiguous"]
    # DWORD timestamp wrap still matches exactly; TTL uses monotonic time.
    for stamp in (0xFFFFFFFF, 0):
        backend = HookBackend()
        receiver = backend.receiver()
        backend.add_key(timestamp=stamp)
        assert backend.hook(receiver, timestamp=stamp) == 1


def test_hook_device_change_invalidates_cached_handle_and_recent_evidence():
    backend = HookBackend()
    receiver = backend.receiver()
    assert receiver._target(1)  # cache the deck's old handle ownership
    backend.paths[1] = backend.paths[2]  # Windows reuses the handle for the main keyboard
    backend.add_device_change(1)
    backend.add_key(device=1)
    assert backend.hook(receiver) == 79
    assert decisions(backend) == ["other-device"]
    assert not actions(backend)
    assert receiver.devices[1] is False
    assert ("default", raw.WM_INPUT_DEVICE_CHANGE) in backend.calls
    # A notification must also remove raw-before-hook evidence for the old
    # device, even when no replacement raw packet is queued yet.
    backend = HookBackend()
    receiver = backend.receiver()
    packet = backend.add_key(queue=False)
    receiver._read(packet, backend.timestamp)
    assert len(actions(backend)) == 1
    backend.paths[1] = backend.paths[2]
    backend.add_device_change(1)
    assert backend.hook(receiver) == 79
    assert decisions(backend) == ["timeout"]
    assert len(actions(backend)) == 1
    assert not receiver.matcher.recent
    assert not receiver.state.pressed
    assert 1 not in receiver.devices


def test_hook_sided_modifiers_and_repeat_suppression():
    backend = HookBackend()
    receiver = backend.receiver()
    backend.add_key(vkey=0x11, scan=0x1D, flags=2)
    assert backend.hook(receiver, vkey=0xA3, scan=0x1D, flags=1) == 1
    for stamp in (1001, 1002, 1003):
        backend.add_key(vkey=0x5A, scan=0x2C, timestamp=stamp)
        assert backend.hook(receiver, vkey=0x5A, scan=0x2C, timestamp=stamp) == 1
    assert len(actions(backend)) == 2  # modifier plus one Z, despite three raw downs
    assert actions(backend)[-1]["keys"] == ("ctrl+vk:0x5A", "ctrl+scan:0x002C:0",
                                           "vk:0x5A", "scan:0x002C:0")


def test_modifiers_per_device_sides_release_and_explicit_binding():
    state = raw.EventState()
    modifier = state.keyboard(1, 0x11, 0x1D, 0)[0]
    assert modifier["keys"] == ("vk:0x11", "scan:0x001D:0")
    assert modifier["modifier"] == "ctrl"
    assert state.keyboard(2, 0x5A, 0x2C, 0)[0]["keys"][0] == "vk:0x5A"
    assert state.keyboard(1, 0x5A, 0x2C, 0)[0]["keys"][0] == "ctrl+vk:0x5A"
    assert not state.keyboard(1, 0x5A, 0x2C, 0)
    assert not state.keyboard(1, 0x5A, 0x2C, 1)
    assert not state.keyboard(1, 0x11, 0x1D, 1)
    assert state.keyboard(1, 0x5A, 0x2C, 0)[0]["keys"][0] == "vk:0x5A"
    state.forget(1)
    for vkey, scan, flags in ((0xA2, 0x1D, 0), (0xA3, 0x1D, 2),
                              (0xA0, 0x2A, 0), (0xA4, 0x38, 0), (0x5B, 0x5B, 2)):
        event = state.keyboard(1, vkey, scan, flags)[0]
        assert all("+" not in key for key in event["keys"])
    assert state.keyboard(1, 0x4C, 0x26, 0)[0]["keys"][0] == "ctrl+shift+alt+win+vk:0x4C"
    state.keyboard(1, 0x4C, 0x26, 1)
    state.keyboard(1, 0xA2, 0x1D, 1)  # right Ctrl remains held
    assert state.keyboard(1, 0x4C, 0x26, 0)[0]["keys"][0].startswith("ctrl+")
    state.forget(1)
    assert state.keyboard(1, 0x4C, 0x26, 0)[0]["keys"][0] == "vk:0x4C"


def test_hook_fail_open_callback_error_and_reentrancy():
    backend = HookBackend()
    receiver = backend.receiver()
    backend.add_key()
    receiver.callback = lambda event: (_ for _ in ()).throw(ValueError("queue failure"))
    assert backend.hook(receiver) == 79
    assert not receiver.running and isinstance(receiver._callback_error, ValueError)
    backend = HookBackend()
    receiver = backend.receiver()
    receiver._inside_hook = True
    assert backend.hook(receiver) == 79
    assert not backend.events and backend.clock.now == 1.0


def test_hook_lifecycle_install_failure_and_observer():
    for exclusive in (True, False):
        backend = HookBackend()
        receiver = backend.receiver(exclusive=exclusive)
        with patch.object(raw.time, "sleep"):
            receiver.run()
        assert backend.hook_calls == (["install", "uninstall"] if exclusive else [])
        assert receiver.hook is None and receiver.hwnd is None and not receiver.running
        assert backend.calls[-2:] == [("destroy",), ("unregister_class",)]
        assert len(backend.registrations) == 2
        assert decisions(backend) == (["installed", "uninstalled"] if exclusive else [])
    backend = HookBackend()
    receiver = backend.receiver()
    backend.user.SetWindowsHookExW.function = lambda *args: 0
    try:
        receiver.run()
        raise AssertionError("hook install failure ignored")
    except OSError:
        pass
    assert not receiver.running and receiver.hwnd is None
    assert backend.calls[-2:] == [("destroy",), ("unregister_class",)]
    assert len(backend.registrations) == 2
    assert not decisions(backend)
    backend = HookBackend()
    receiver = backend.receiver()
    backend.user.UnhookWindowsHookEx.function = lambda *args: 0
    try:
        receiver.run()
        raise AssertionError("unhook failure ignored")
    except OSError:
        pass
    assert receiver.hook is None and receiver.hwnd is None and not receiver.running
    assert len(backend.registrations) == 2
    assert backend.calls[-2:] == [("destroy",), ("unregister_class",)]
    assert decisions(backend) == ["installed"]


def main():
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("deck exclusive offline tests: %d groups passed" % len(tests))


if __name__ == "__main__":
    main()
