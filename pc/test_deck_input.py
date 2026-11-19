"""Offline Raw Input assertions: fake Win32 and hid.dll, no device access."""
import ctypes
from types import SimpleNamespace
from unittest.mock import patch

import deck_input as raw


class Function:
    def __init__(self, function=lambda *args: 1):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


def pointer(pointer, kind):
    return ctypes.cast(pointer, ctypes.POINTER(kind)).contents


class Backend:
    def __init__(self):
        self.paths = {1: r"\\?\HID#VID_4132&PID_2107&MI_00#deck",
                      2: r"\\?\HID#VID_3837&PID_0001#main"}
        self.packet = b""
        self.calls, self.registrations = [], []
        self.reports = {b"\x01\xA5\x00": [0xE9], b"\x01\x00\x00": [],
                        b"\x02\xA5\x00": [0xEA]}
        self.hwnd = 0x123456789
        names = ("GetRawInputData", "GetRawInputDeviceInfoW", "RegisterRawInputDevices", "RegisterClassW",
                 "UnregisterClassW", "CreateWindowExW", "DestroyWindow", "DefWindowProcW", "PeekMessageW",
                 "TranslateMessage", "DispatchMessageW", "GetMessageTime")
        self.user = SimpleNamespace(**{name: Function(getattr(self, name, lambda *args: 1)) for name in names})
        self.kernel = SimpleNamespace(GetModuleHandleW=Function(lambda name: self.hwnd),
                                      GetTickCount=Function(lambda: 17))
        self.hid = SimpleNamespace(HidP_MaxUsageListLength=Function(self.max_usages),
                                   HidP_GetUsages=Function(self.get_usages))

    def receiver(self, callback):
        return raw.RawInput(callback, self.user, self.kernel, self.hid)

    def GetRawInputDeviceInfoW(self, handle, command, destination, size_ptr):
        self.calls.append(("info", handle, command, destination is None))
        size = pointer(size_ptr, raw.U32)
        if command == raw.RIDI_DEVICENAME:
            if destination is None:
                size.value = len(self.paths[handle]) + 1
            else:
                destination.value = self.paths[handle]
            return len(self.paths[handle])
        assert command == raw.RIDI_PREPARSEDDATA
        if destination is None:
            size.value = 8
        else:
            ctypes.memmove(destination, b"DESCRIPT", 8)
        return 8

    def GetRawInputData(self, handle, command, destination, size_ptr, header_size):
        self.calls.append(("raw", command))
        assert header_size == ctypes.sizeof(raw.RAWINPUTHEADER)
        content = self.packet[:header_size] if command == raw.RID_HEADER else self.packet
        assert pointer(size_ptr, raw.U32).value >= len(content)
        ctypes.memmove(destination, content, len(content))
        return len(content)

    def packet_for(self, handle, kind, payload):
        payload = bytes(payload)
        header = raw.RAWINPUTHEADER(kind, ctypes.sizeof(raw.RAWINPUTHEADER) + len(payload), handle, 1)
        self.packet = bytes(header) + payload

    def max_usages(self, report_type, page, descriptor):
        assert report_type == 0 and page == 0x0C
        assert ctypes.string_at(descriptor, 8) == b"DESCRIPT"
        return 8

    def get_usages(self, report_type, page, link, usages, count_ptr, descriptor, report, length):
        assert (report_type, page, link) == (0, 0x0C, 0)
        assert ctypes.string_at(descriptor, 8) == b"DESCRIPT"
        packet = ctypes.string_at(report, length)
        self.calls.append(("hid", packet))
        values = self.reports.get(packet)
        if values is None:
            return -1
        assert pointer(count_ptr, raw.U32).value >= len(values)
        for index, usage in enumerate(values):
            usages[index] = usage
        pointer(count_ptr, raw.U32).value = len(values)
        return raw.HIDP_STATUS_SUCCESS

    def RegisterRawInputDevices(self, devices, count, size):
        assert size == ctypes.sizeof(raw.RAWINPUTDEVICE)
        rows = [(devices[i].usUsagePage, devices[i].usUsage, devices[i].dwFlags, devices[i].hwndTarget)
                for i in range(count)]
        self.registrations.append(rows)
        return 1

    def RegisterClassW(self, window_class):
        self.calls.append(("register_class",))
        self.wndproc = pointer(window_class, raw.WNDCLASSW).lpfnWndProc
        return 1

    def CreateWindowExW(self, extended, name, title, style, x, y, width, height, parent, menu, instance, param):
        assert style & 0x10000000 == 0  # no WS_VISIBLE
        assert instance == self.hwnd
        self.calls.append(("create",))
        return self.hwnd

    def PeekMessageW(self, message, hwnd, start, end, remove):
        pointer(message, raw.MSG).message = raw.WM_QUIT
        return 1

    def DestroyWindow(self, hwnd):
        assert hwnd == self.hwnd
        self.calls.append(("destroy",))
        return 1

    def UnregisterClassW(self, name, instance):
        assert instance == self.hwnd
        self.calls.append(("unregister_class",))
        return 1

    def DefWindowProcW(self, hwnd, message, wparam, lparam):
        self.calls.append(("default", message))
        return 0


def test_deck_input_transitions():
    state = raw.EventState()
    assert state.keyboard(0, 0x7C, 100, 0) == []
    assert state.keyboard(1, 0xFF, 100, 0) == []
    event = state.keyboard(1, 0x7C, 100, 0)[0]
    assert event["keys"] == ("vk:0x7C", "scan:0x0064:0")
    assert state.keyboard(1, 0x7C, 100, 0) == []
    assert state.keyboard(1, 0x7C, 100, 1) == []
    assert len(state.keyboard(1, 0x7C, 100, 0)) == 1
    assert state.keyboard(1, 0x7C, 100, 2)[0]["keys"][1] == "scan:0x0064:2"
    assert state.keyboard(1, 0x7C, 100, 3) == []
    state.forget(1)
    assert len(state.keyboard(1, 0x7C, 100, 0)) == 1
    assert state.mouse(1, 0x400, 60) == []
    assert state.mouse(1, 0x400, 60)[0]["keys"] == ("wheel:+1",)
    events = state.mouse(1, 0x400, 0xFF10)  # -240 signed
    assert len(events) == 2 and all(e["keys"] == ("wheel:-1",) for e in events)
    assert state.mouse(1, 1, 120) == []
    assert state.consumer(1, 1, [0xE9])[0]["keys"] == ("consumer:0x00E9",)
    assert state.consumer(1, 1, [0xE9]) == []
    assert state.consumer(1, 2, [0xE9])
    assert state.consumer(1, 1, []) == []
    assert state.consumer(1, 1, [0xE9])


def test_deck_input_device_filter():
    assert raw.target_path(r"\\?\HID#VID_4132&PID_2107&MI_03#deck")
    assert raw.target_path(r"\\?\hid#vid_4132&pid_2107#deck")
    for path in ("VID_4132&PID_21070", "VID_41320&PID_2107", "XVID_4132&PID_2107", "VID_3837&PID_2107"):
        assert not raw.target_path(path)
    backend, events = Backend(), []
    receiver = backend.receiver(events.append)
    keyboard = raw.RAWKEYBOARD(100, 0, 0, 0x7C, 0x100, 0)
    backend.packet_for(2, 1, keyboard)
    receiver._read(10)
    assert events == []
    assert ("raw", raw.RID_INPUT) not in backend.calls
    backend.paths[2] = backend.paths[1]
    receiver._read(10)  # cached rejection until device-change notification
    assert events == []
    receiver._wndproc(backend.hwnd, raw.WM_INPUT_DEVICE_CHANGE, 1, 2)
    receiver._read(10)
    assert len(events) == 1
    receiver._read(10)
    assert len(events) == 1
    receiver._wndproc(backend.hwnd, raw.WM_INPUT_DEVICE_CHANGE, 2, 2)
    receiver._read(10)
    assert len(events) == 2
    before = len(backend.calls)
    backend.packet_for(0, 1, keyboard)
    receiver._read(10)
    assert len(backend.calls) == before + 1  # header only, no name or full packet
    assert receiver.user.GetRawInputData.argtypes[0] is ctypes.c_void_p


def test_deck_input_packets():
    backend, events = Backend(), []
    receiver = backend.receiver(events.append)
    mouse = raw.RAWMOUSE()
    mouse.usButtonFlags, mouse.usButtonData = 0x400, 120
    backend.packet_for(1, 0, mouse)
    receiver._read(1)
    assert events[-1]["keys"] == ("wheel:+1",)
    reports = b"\x01\xA5\x00\x01\xA5\x00\x01\x00\x00\x02\xA5\x00\x01\xA5\x00"
    backend.packet_for(1, 2, bytes(raw.RAWHID(3, 5)) + reports)
    receiver._read(1)
    assert [event["keys"][0] for event in events[1:]] == ["consumer:0x00E9", "consumer:0x00EA", "consumer:0x00E9"]
    assert sum(call[:3] == ("info", 1, raw.RIDI_PREPARSEDDATA) for call in backend.calls) == 2
    before = len(events)
    backend.packet_for(1, 2, bytes(raw.RAWHID(10, 5)) + reports)
    receiver._read(1)
    backend.packet_for(1, 1, b"\x00")
    receiver._read(1)
    backend.packet_for(1, 2, bytes(raw.RAWHID(3, 1)) + b"\x01\xFF\xFF")
    receiver._read(1)
    assert len(events) == before
    receiver.forget(1)
    assert receiver.preparsed == {} and receiver.state.consumer_pressed == {}


def test_deck_input_lifecycle():
    assert ctypes.sizeof(raw.RAWKEYBOARD) == 16
    assert ctypes.sizeof(raw.RAWMOUSE) == 24
    assert ctypes.sizeof(raw.RAWHID) == 8
    assert ctypes.sizeof(raw.RAWINPUTHEADER) == (24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16)
    assert raw.RAWMOUSE.buttons.offset == 4
    for interruption in (False, True):
        backend = Backend()
        receiver = backend.receiver(lambda event: None)
        if interruption:
            backend.user.PeekMessageW.function = lambda *args: (_ for _ in ()).throw(KeyboardInterrupt())
        with patch.object(raw.time, "sleep"):
            receiver.run()
        assert receiver.hwnd is None and not receiver.running
        assert len(backend.registrations) == 2
        active, removed = backend.registrations
        assert [(page, usage) for page, usage, flags, hwnd in active] == list(raw.USAGES)
        assert all(flags == raw.RIDEV_INPUTSINK | raw.RIDEV_DEVNOTIFY and hwnd == backend.hwnd
                   for page, usage, flags, hwnd in active)
        assert all(flags == raw.RIDEV_REMOVE and hwnd is None for page, usage, flags, hwnd in removed)
        assert backend.calls[-2:] == [("destroy",), ("unregister_class",)]
    backend = Backend()
    receiver = backend.receiver(lambda event: None)
    receiver._read = lambda handle: (_ for _ in ()).throw(ValueError("callback failure"))
    receiver.running = True
    receiver._wndproc(backend.hwnd, raw.WM_INPUT, 1, 5)
    assert not receiver.running and isinstance(receiver._callback_error, ValueError)
    assert backend.calls[-1] == ("default", raw.WM_INPUT)
    # Ctrl+C can arrive inside WM_INPUT, where ctypes would otherwise discard it.
    receiver._read = lambda handle: (_ for _ in ()).throw(KeyboardInterrupt())
    receiver._callback_error = None
    receiver.running = True
    callback = raw.WNDPROC(receiver._wndproc)
    assert callback(backend.hwnd, raw.WM_INPUT, 1, 5) == 0
    assert not receiver.running and receiver._callback_error is None
    assert backend.calls[-1] == ("default", raw.WM_INPUT)
    backend = Backend()
    receiver = backend.receiver(lambda event: None)
    backend.user.RegisterRawInputDevices.function = lambda *args: 0
    try:
        receiver.run()
        raise AssertionError("registration failure ignored")
    except OSError:
        pass
    assert backend.calls[-2:] == [("destroy",), ("unregister_class",)]


def test_deck_input_hub_transitions_and_poll():
    backend, events = Backend(), []
    receiver = raw.RawInput(events.append, backend.user, backend.kernel, backend.hid,
                            transitions=True, monotonic=lambda: 10.)
    for handle, flags in ((2, 0), (1, 0), (1, 1)):
        backend.packet_for(handle, 1, raw.RAWKEYBOARD(100, flags, 0, 0x7C, 0x100, 0))
        receiver._read(10)
    assert [event["down"] for event in events] == [True, False]
    assert all(event["device"] == 1 and event["vkey"] == 0x7C for event in events)
    receiver._wndproc(backend.hwnd, raw.WM_INPUT_DEVICE_CHANGE, 2, 1)
    assert events[-1] == {"kind": "device_removed", "device": 1}
    backend.packet_for(1, 1, raw.RAWKEYBOARD(100, 0, 0, 0x7C, 0x100, 0))
    backend.user.GetMessageTime.function = lambda: 0xFFFFFFF1
    receiver._wndproc(backend.hwnd, raw.WM_INPUT, 0, 10)
    assert abs(events[-1]["t"] - 9.952) < 1e-9  # DWORD wrap plus 16 ms uncertainty
    # Stop during poll and before run must both be respected, without a
    # message pump clearing the stop request at listener startup.
    receiver.poll = receiver.stop
    backend.user.PeekMessageW.function = lambda *args: (_ for _ in ()).throw(
        AssertionError("poll stop must precede message dispatch"))
    receiver.run()
    assert receiver.hwnd is None and not receiver.running
    assert backend.calls[-2:] == [("destroy",), ("unregister_class",)]
    backend = Backend()
    receiver = backend.receiver(events.append)
    receiver.stop()
    receiver.run()
    assert backend.calls == [] and backend.registrations == []


def main():
    tests = (test_deck_input_transitions, test_deck_input_device_filter, test_deck_input_packets,
             test_deck_input_lifecycle, test_deck_input_hub_transitions_and_poll)
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("deck Raw Input offline tests: %d groups passed" % len(tests))


if __name__ == "__main__":
    main()
