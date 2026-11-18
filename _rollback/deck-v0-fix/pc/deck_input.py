"""Windows Raw Input and conservative, device-correlated keyboard suppression.

No Win32 calls occur on import. Consumer reports are interpreted by hid.dll
using the device's preparsed descriptor, rather than a guessed packet layout.
"""
import ctypes
from collections import deque
import logging
import os
import re
import time

U16, U32 = ctypes.c_uint16, ctypes.c_uint32
PTR, UPTR, IPTR = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ssize_t
BOOL = ctypes.c_int
WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
WNDPROC = WINFUNCTYPE(IPTR, PTR, U32, UPTR, IPTR)
HOOKPROC = WINFUNCTYPE(IPTR, ctypes.c_int, UPTR, IPTR)
UINT_ERROR = 0xFFFFFFFF
RID_INPUT, RID_HEADER = 0x10000003, 0x10000005
RIDI_PREPARSEDDATA, RIDI_DEVICENAME = 0x20000005, 0x20000007
WM_INPUT, WM_INPUT_DEVICE_CHANGE = 0xFF, 0xFE
WM_CLOSE, WM_DESTROY, WM_QUIT = 0x10, 2, 0x12
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
WH_KEYBOARD_LL, LLKHF_INJECTED, LLKHF_UP = 13, 0x10, 0x80
PM_REMOVE = 1
RIDEV_INPUTSINK, RIDEV_DEVNOTIFY, RIDEV_REMOVE = 0x100, 0x2000, 1
HIDP_STATUS_SUCCESS = 0x00110000
USAGES = ((1, 6), (1, 2), (0x0C, 1))
log = logging.getLogger("agent_deck.input")


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", U32), ("dwSize", U32), ("hDevice", PTR), ("wParam", UPTR)]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [("MakeCode", U16), ("Flags", U16), ("Reserved", U16),
                ("VKey", U16), ("Message", U32), ("ExtraInformation", U32)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", U32), ("scanCode", U32), ("flags", U32),
                ("time", U32), ("dwExtraInfo", UPTR)]


class _MOUSEBUTTONS(ctypes.Structure):
    _fields_ = [("usButtonFlags", U16), ("usButtonData", U16)]


class _MOUSEUNION(ctypes.Union):
    _anonymous_ = ("buttons",)
    _fields_ = [("ulButtons", U32), ("buttons", _MOUSEBUTTONS)]


class RAWMOUSE(ctypes.Structure):
    _anonymous_ = ("buttons",)
    _fields_ = [("usFlags", U16), ("buttons", _MOUSEUNION), ("ulRawButtons", U32),
                ("lLastX", ctypes.c_int32), ("lLastY", ctypes.c_int32),
                ("ulExtraInformation", U32)]


class RAWHID(ctypes.Structure):
    _fields_ = [("dwSizeHid", U32), ("dwCount", U32)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", U16), ("usUsage", U16), ("dwFlags", U32), ("hwndTarget", PTR)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", U32), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", PTR), ("hIcon", PTR),
                ("hCursor", PTR), ("hbrBackground", PTR),
                ("lpszMenuName", ctypes.c_wchar_p), ("lpszClassName", ctypes.c_wchar_p)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", PTR), ("message", U32), ("wParam", UPTR), ("lParam", IPTR),
                ("time", U32), ("pt", POINT), ("lPrivate", U32)]


def target_path(path):
    """Exact VID/PID tokens; a different keyboard is never accepted."""
    return bool(re.search(r"(?:^|[\\#&])VID_4132&PID_2107(?:[&#\\]|$)", path, re.I))


MODIFIERS = {0x10: "shift", 0x11: "ctrl", 0x12: "alt", 0x5B: "win", 0x5C: "win",
             0xA0: "shift", 0xA1: "shift", 0xA2: "ctrl", 0xA3: "ctrl",
             0xA4: "alt", 0xA5: "alt"}
MODIFIER_ORDER = ("ctrl", "shift", "alt", "win")


def generic_vkey(vkey):
    return {0xA0: 0x10, 0xA1: 0x10, 0xA2: 0x11, 0xA3: 0x11,
            0xA4: 0x12, 0xA5: 0x12}.get(vkey, vkey)


class KeyboardMatcher:
    """One-use raw evidence; exact event timestamps prevent stale near matches.

    Expiry is measured with a monotonic clock, independently of Windows' DWORD
    event-time wrap. Consumed identities remain tombstones until expiry: two
    indistinguishable hooks/packets must never reuse one target observation.
    """

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.recent = deque(maxlen=512)
        self.used = deque(maxlen=512)

    def _expire(self):
        now = self.clock()
        for records in (self.recent, self.used):
            while records and now - records[0][0] > 0.100:
                records.popleft()

    def record(self, handle, target, vkey, scan, flags, timestamp):
        self._expire()
        if vkey in (0, 0xFF) or scan == 0xFF or flags & 4:
            return
        identity = (generic_vkey(vkey), bool(flags & 1), timestamp & 0xFFFFFFFF,
                    scan, bool(flags & 2))
        self.recent.append((self.clock(), identity, handle, bool(handle and target)))

    def match(self, vkey, scan, flags, timestamp):
        """Return None when no evidence exists, otherwise a fail-open verdict."""
        self._expire()
        identity = (generic_vkey(vkey), bool(flags & LLKHF_UP), timestamp & 0xFFFFFFFF,
                    scan, bool(flags & 1))
        if any(record[1] == identity for record in self.used):
            return "ambiguous"
        matches = [record for record in self.recent if record[1] == identity]
        if not matches:
            return None
        # Consume all conflicting evidence, including unknown-device records.
        self.recent = deque((record for record in self.recent if record[1] != identity), maxlen=512)
        self.used.append((self.clock(), identity))
        if len(matches) != 1:
            return "ambiguous"
        return "suppressed" if matches[0][3] else "other-device"

    def reject(self, vkey, scan, flags, timestamp):
        """Do not let late raw input prove a hook that has already passed."""
        self._expire()
        identity = (generic_vkey(vkey), bool(flags & LLKHF_UP), timestamp & 0xFFFFFFFF,
                    scan, bool(flags & 1))
        self.used.append((self.clock(), identity))

    def forget(self, handle):
        self.recent = deque((record for record in self.recent if record[2] != handle), maxlen=512)


class EventState:
    """Normalize press transitions without any hardware or platform access."""

    def __init__(self):
        self.pressed = set()
        self.modifiers = {}
        self.consumer_pressed = {}
        self.wheels = {}

    def forget(self, handle):
        self.pressed = {item for item in self.pressed if item[0] != handle}
        self.consumer_pressed = {key: value for key, value in self.consumer_pressed.items() if key[0] != handle}
        self.wheels.pop(handle, None)
        self.modifiers.pop(handle, None)

    def keyboard(self, handle, vkey, make_code, flags):
        if not handle or vkey in (0, 0xFF) or make_code == 0xFF:
            return []
        extended = flags & 6
        token = (handle, vkey, make_code, extended)
        modifiers = self.modifiers.setdefault(handle, {})
        modifier = MODIFIERS.get(vkey)
        if flags & 1:
            self.pressed.discard(token)
            modifiers.pop((generic_vkey(vkey), make_code, extended), None)
            return []
        if token in self.pressed:
            return []
        self.pressed.add(token)
        keys = ("vk:0x%02X" % vkey, "scan:0x%04X:%d" % (make_code, extended))
        if modifier:
            modifiers[(generic_vkey(vkey), make_code, extended)] = modifier
            if generic_vkey(vkey) != vkey:
                keys = (keys[0], "vk:0x%02X" % generic_vkey(vkey), keys[1])
        else:
            prefix = "+".join(name for name in MODIFIER_ORDER if name in modifiers.values())
            if prefix:
                keys = tuple(prefix + "+" + key for key in keys) + keys
        return [{"kind": "keyboard", "keys": keys, "vkey": vkey,
                 "make_code": make_code, "flags": flags, "device": handle,
                 "modifier": modifier}]

    def mouse(self, handle, button_flags, button_data):
        if not handle or not button_flags & 0x400:
            return []
        delta = ctypes.c_int16(button_data).value
        total = self.wheels.get(handle, 0) + delta
        events = []
        while abs(total) >= 120:
            direction = 1 if total > 0 else -1
            events.append({"kind": "mouse", "keys": ("wheel:%+d" % direction,), "delta": direction * 120})
            total -= direction * 120
        self.wheels[handle] = total
        return events

    def consumer(self, handle, report_id, usages):
        if not handle:
            return []
        key = (handle, report_id)
        current = set(usages)
        previous = self.consumer_pressed.get(key, set())
        self.consumer_pressed[key] = current
        return [{"kind": "consumer", "keys": ("consumer:0x%04X" % usage,), "usage": usage}
                for usage in sorted(current - previous) if usage]


def _signature(dll, name, restype, argtypes):
    function = getattr(dll, name)
    function.restype, function.argtypes = restype, argtypes


class RawInput:
    """Receive only the deck's presses in a hidden, unfocused window."""

    def __init__(self, callback, user=None, kernel=None, hid=None, *, exclusive=False):
        if user is None:
            if os.name != "nt":
                raise OSError("AgentDeck learn/run require Windows Raw Input")
            user = ctypes.WinDLL("user32", use_last_error=True)
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            hid = ctypes.WinDLL("hid", use_last_error=True)
        self.user, self.kernel, self.hid = user, kernel, hid
        self.callback = callback
        self.state = EventState()
        self.devices, self.preparsed = {}, {}
        self.hwnd, self.running = None, False
        self._callback_error = None
        self.exclusive = exclusive
        self.matcher = KeyboardMatcher()
        self.hook = None
        self._inside_hook = False
        self._configure()

    def _configure(self):
        for name, result, args in (
                ("GetRawInputData", U32, [PTR, U32, PTR, ctypes.POINTER(U32), U32]),
                ("GetRawInputDeviceInfoW", U32, [PTR, U32, PTR, ctypes.POINTER(U32)]),
                ("RegisterRawInputDevices", BOOL, [ctypes.POINTER(RAWINPUTDEVICE), U32, U32]),
                ("RegisterClassW", U16, [ctypes.POINTER(WNDCLASSW)]),
                ("UnregisterClassW", BOOL, [ctypes.c_wchar_p, PTR]),
                ("CreateWindowExW", PTR, [U32, ctypes.c_wchar_p, ctypes.c_wchar_p, U32,
                                          ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                          PTR, PTR, PTR, PTR]),
                ("DestroyWindow", BOOL, [PTR]),
                ("DefWindowProcW", IPTR, [PTR, U32, UPTR, IPTR]),
                ("PeekMessageW", BOOL, [ctypes.POINTER(MSG), PTR, U32, U32, U32]),
                ("TranslateMessage", BOOL, [ctypes.POINTER(MSG)]),
                ("DispatchMessageW", IPTR, [ctypes.POINTER(MSG)])):
            _signature(self.user, name, result, args)
        _signature(self.kernel, "GetModuleHandleW", PTR, [ctypes.c_wchar_p])
        if self.exclusive:
            for name, result, args in (
                    ("SetWindowsHookExW", PTR, [ctypes.c_int, HOOKPROC, PTR, U32]),
                    ("UnhookWindowsHookEx", BOOL, [PTR]),
                    ("CallNextHookEx", IPTR, [PTR, ctypes.c_int, UPTR, IPTR]),
                    ("GetMessageTime", ctypes.c_int32, [])):
                _signature(self.user, name, result, args)
        _signature(self.hid, "HidP_MaxUsageListLength", U32, [ctypes.c_int, U16, PTR])
        _signature(self.hid, "HidP_GetUsages", ctypes.c_int32,
                   [ctypes.c_int, U16, U16, ctypes.POINTER(U16), ctypes.POINTER(U32), PTR, PTR, U32])

    def _target(self, handle):
        if not handle:
            return False
        if handle not in self.devices:
            size = U32()
            result = self.user.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, None, ctypes.byref(size))
            if result == UINT_ERROR or not 0 < size.value <= 32768:
                return False
            name = ctypes.create_unicode_buffer(size.value + 1)
            result = self.user.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, name, ctypes.byref(size))
            if result == UINT_ERROR:
                return False
            self.devices[handle] = target_path(name.value)
        return self.devices[handle]

    def forget(self, handle):
        self.devices.pop(handle, None)
        self.preparsed.pop(handle, None)
        self.state.forget(handle)
        self.matcher.forget(handle)

    def _consumer_usages(self, handle, report):
        if handle not in self.preparsed:
            size = U32()
            result = self.user.GetRawInputDeviceInfoW(handle, RIDI_PREPARSEDDATA, None, ctypes.byref(size))
            if result == UINT_ERROR or not 0 < size.value <= 1024 * 1024:
                return None
            data = ctypes.create_string_buffer(size.value)
            result = self.user.GetRawInputDeviceInfoW(handle, RIDI_PREPARSEDDATA, data, ctypes.byref(size))
            if result == UINT_ERROR:
                return None
            count = self.hid.HidP_MaxUsageListLength(0, 0x0C, data)
            if not 0 < count <= 65536:
                return None
            self.preparsed[handle] = (data, count)
        data, count = self.preparsed[handle]
        usages = (U16 * count)()
        length = U32(count)
        packet = ctypes.create_string_buffer(report, len(report))
        status = self.hid.HidP_GetUsages(0, 0x0C, 0, usages, ctypes.byref(length), data, packet, len(report))
        if status & 0xFFFFFFFF != HIDP_STATUS_SUCCESS or length.value > count:
            return None
        return usages[:length.value]

    def _read(self, raw_handle, timestamp=None):
        # Observer mode excludes other devices before reading their payload.
        # Exclusive mode also needs negative keyboard evidence to fail open.
        header = RAWINPUTHEADER()
        size = U32(ctypes.sizeof(header))
        result = self.user.GetRawInputData(raw_handle, RID_HEADER, ctypes.byref(header),
                                           ctypes.byref(size), ctypes.sizeof(header))
        if result != ctypes.sizeof(header):
            return
        target = self._target(header.hDevice)
        if not target and not (self.exclusive and header.dwType == 1):
            return
        if not ctypes.sizeof(header) <= header.dwSize <= 1024 * 1024:
            return
        data = ctypes.create_string_buffer(header.dwSize)
        size = U32(len(data))
        result = self.user.GetRawInputData(raw_handle, RID_INPUT, data, ctypes.byref(size), ctypes.sizeof(header))
        if result == UINT_ERROR or result != header.dwSize:
            return
        actual = RAWINPUTHEADER.from_buffer_copy(data)
        if (actual.hDevice, actual.dwType, actual.dwSize) != (header.hDevice, header.dwType, header.dwSize):
            return
        payload = data.raw[ctypes.sizeof(header):]
        events = []
        if header.dwType == 1 and len(payload) >= ctypes.sizeof(RAWKEYBOARD):
            key = RAWKEYBOARD.from_buffer_copy(payload)
            if self.exclusive:
                if timestamp is None:
                    timestamp = self.user.GetMessageTime()
                self.matcher.record(header.hDevice, target, key.VKey, key.MakeCode, key.Flags, timestamp)
            if target:
                events = self.state.keyboard(header.hDevice, key.VKey, key.MakeCode, key.Flags)
        elif header.dwType == 0 and len(payload) >= ctypes.sizeof(RAWMOUSE):
            mouse = RAWMOUSE.from_buffer_copy(payload)
            events = self.state.mouse(header.hDevice, mouse.usButtonFlags, mouse.usButtonData)
        elif header.dwType == 2 and len(payload) >= ctypes.sizeof(RAWHID):
            hid = RAWHID.from_buffer_copy(payload)
            reports = payload[ctypes.sizeof(hid):]
            if not hid.dwSizeHid or hid.dwSizeHid * hid.dwCount > len(reports):
                return
            for offset in range(0, hid.dwSizeHid * hid.dwCount, hid.dwSizeHid):
                report = reports[offset:offset + hid.dwSizeHid]
                usages = self._consumer_usages(header.hDevice, report)
                if usages is not None:
                    events.extend(self.state.consumer(header.hDevice, report[0], usages))
        for event in events:
            self.callback(event)

    def _hookproc(self, code, message, address):
        if code != 0 or not self.running:
            return self.user.CallNextHookEx(self.hook, code, message, address)
        if self._inside_hook:
            # PeekMessage may deliver another hook synchronously. Its input has
            # passed already; future hooks must not claim its delayed raw record.
            try:
                key = ctypes.cast(address, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                self.matcher.reject(key.vkCode, key.scanCode, key.flags, key.time)
            except KeyboardInterrupt:
                self.running = False
            except Exception as error:
                self._callback_error = error
                self.running = False
            return self.user.CallNextHookEx(self.hook, code, message, address)
        self._inside_hook = True
        try:
            key = ctypes.cast(address, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            decision = "injected" if key.flags & (LLKHF_INJECTED | 2) else None
            if message not in (WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP):
                decision = "unsupported"
            elif bool(key.flags & LLKHF_UP) != (message in (WM_KEYUP, WM_SYSKEYUP)):
                decision = "unsupported"
            if decision is None:
                deadline = time.monotonic() + 0.050
                packet = MSG()
                while True:
                    # Keep device changes ordered with raw messages: handles can
                    # be reused, so an older removal must invalidate cached
                    # ownership before a new keyboard packet is considered.
                    drained = True
                    for _ in range(100):
                        if time.monotonic() >= deadline:
                            drained = False
                            break
                        if not self.user.PeekMessageW(ctypes.byref(packet), self.hwnd,
                                                      WM_INPUT_DEVICE_CHANGE, WM_INPUT, PM_REMOVE):
                            break
                        try:
                            if packet.message == WM_INPUT_DEVICE_CHANGE:
                                self.forget(packet.lParam)
                            else:
                                self._read(packet.lParam, packet.time)
                        finally:
                            self.user.DefWindowProcW(packet.hwnd, packet.message, packet.wParam, packet.lParam)
                    else:
                        drained = False
                    # A partial drain could hide conflicting main-keyboard input.
                    if not drained:
                        decision = "timeout"
                        break
                    decision = self.matcher.match(key.vkCode, key.scanCode, key.flags, key.time)
                    if decision is not None:
                        break
                    if time.monotonic() >= deadline:
                        decision = "timeout"
                        break
                    time.sleep(0.001)
            if decision != "suppressed":
                self.matcher.reject(key.vkCode, key.scanCode, key.flags, key.time)
            self.callback({"kind": "hook", "decision": decision,
                           "keys": ("vk:0x%02X" % key.vkCode,), "vkey": key.vkCode,
                           "flags": key.flags, "time": key.time})
            if decision == "suppressed":
                return 1
        except KeyboardInterrupt:
            self.running = False
        except Exception as error:
            self._callback_error = error
            self.running = False
            try:
                self.callback({"kind": "hook", "decision": "error", "keys": (),
                               "error": str(error)})
            except Exception:
                pass  # the queue itself may be the source of the failure
        finally:
            self._inside_hook = False
        return self.user.CallNextHookEx(self.hook, code, message, address)

    def _wndproc(self, hwnd, message, wparam, lparam):
        try:
            if message == WM_INPUT:
                self._read(lparam)
            elif message == WM_INPUT_DEVICE_CHANGE:
                self.forget(lparam)
            elif message in (WM_CLOSE, WM_DESTROY):
                self.running = False
        except KeyboardInterrupt:
            # Interrupts inside a ctypes callback must not escape into Windows.
            self.running = False
        except Exception as error:
            # ctypes callbacks cannot propagate exceptions through Windows.
            self._callback_error = error
            self.running = False
        # DefWindowProc must see foreground WM_INPUT for system cleanup.
        return self.user.DefWindowProcW(hwnd, message, wparam, lparam)

    def _register_devices(self, remove=False):
        flags = RIDEV_REMOVE if remove else RIDEV_INPUTSINK | RIDEV_DEVNOTIFY
        devices = (RAWINPUTDEVICE * len(USAGES))(
            *(RAWINPUTDEVICE(page, usage, flags, None if remove else self.hwnd) for page, usage in USAGES))
        return self.user.RegisterRawInputDevices(devices, len(devices), ctypes.sizeof(RAWINPUTDEVICE))

    def run(self):
        instance = self.kernel.GetModuleHandleW(None)
        class_name = "AgentDeckRawInput_%d_%x" % (os.getpid(), id(self))
        procedure = WNDPROC(self._wndproc)  # keep callback alive until class is unregistered
        hook_procedure = HOOKPROC(self._hookproc)  # same thread as Raw Input
        window_class = WNDCLASSW(lpfnWndProc=procedure, hInstance=instance, lpszClassName=class_name)
        if not self.user.RegisterClassW(ctypes.byref(window_class)):
            raise ctypes.WinError()
        registered = False
        try:
            # No WS_VISIBLE and no ShowWindow: the window never takes focus.
            self.hwnd = self.user.CreateWindowExW(0, class_name, "AgentDeck input", 0,
                                                  0, 0, 0, 0, None, None, instance, None)
            if not self.hwnd:
                raise ctypes.WinError()
            if not self._register_devices():
                raise ctypes.WinError()
            registered = True
            self.running = True
            if self.exclusive:
                self.hook = self.user.SetWindowsHookExW(WH_KEYBOARD_LL, hook_procedure, instance, 0)
                if not self.hook:
                    raise ctypes.WinError()
                self.callback({"kind": "hook", "decision": "installed", "keys": ()})
            message = MSG()
            while self.running:
                # A bounded drain permits Ctrl+C even during busy input streams.
                for _ in range(100):
                    if not self.user.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                        break
                    if message.message == WM_QUIT:
                        self.running = False
                        break
                    self.user.TranslateMessage(ctypes.byref(message))
                    self.user.DispatchMessageW(ctypes.byref(message))
                    if not self.running:
                        break
                if self._callback_error:
                    raise self._callback_error
                time.sleep(0.01)
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            unhook_error = None
            unhooked = False
            if self.hook:
                if not self.user.UnhookWindowsHookEx(self.hook):
                    unhook_error = ctypes.WinError()
                else:
                    unhooked = True
                self.hook = None
            if registered:
                self._register_devices(remove=True)
            if self.hwnd:
                self.user.DestroyWindow(self.hwnd)
                self.hwnd = None
            self.user.UnregisterClassW(class_name, instance)
            self.devices.clear()
            self.preparsed.clear()
            self.state = EventState()
            self.matcher = KeyboardMatcher()
            if unhook_error:
                raise unhook_error
            if unhooked:
                self.callback({"kind": "hook", "decision": "uninstalled", "keys": ()})
