"""Temporary foreground-only shortcut recording; imports never install a hook."""
import ctypes
import logging
from types import SimpleNamespace

from deck_input import (HOOKPROC, KBDLLHOOKSTRUCT, WH_KEYBOARD_LL, LLKHF_INJECTED,
                        LLKHF_UP, WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP)


log = logging.getLogger("agentdeck.app.shortcut")
# Keep callbacks alive until Windows confirms removal, even if a window closes.
_installed = {}


class Win32CaptureAPI:
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        declarations = {
            "SetWindowsHookExW": ([ctypes.c_int, HOOKPROC, ctypes.c_void_p, ctypes.c_uint32], ctypes.c_void_p),
            "UnhookWindowsHookEx": ([ctypes.c_void_p], ctypes.c_int),
            "CallNextHookEx": ([ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t], ctypes.c_ssize_t),
            "GetForegroundWindow": ([], ctypes.c_void_p),
            "GetAncestor": ([ctypes.c_void_p, ctypes.c_uint32], ctypes.c_void_p),
        }
        for name, (arguments, result) in declarations.items():
            method = getattr(self.user, name)
            method.argtypes, method.restype = arguments, result
        self.kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        self.kernel.GetModuleHandleW.restype = ctypes.c_void_p

    def root(self, hwnd):
        return self.user.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT: Tk's native wrapper.

    def foreground(self):
        return self.user.GetForegroundWindow()

    def install(self, procedure):
        handle = self.user.SetWindowsHookExW(WH_KEYBOARD_LL, procedure,
                                             self.kernel.GetModuleHandleW(None), 0)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def remove(self, handle):
        if not self.user.UnhookWindowsHookEx(handle):
            error = ctypes.get_last_error()
            if error != 1404:  # ERROR_INVALID_HOOK_HANDLE: Windows already removed it.
                raise ctypes.WinError(error)

    def next(self, handle, code, message, address):
        return self.user.CallNextHookEx(handle, code, message, address)


class ShortcutCapture:
    """Install on the Tk thread; its existing message loop drives the callback."""
    def __init__(self, window, on_key, on_error, *, api=None):
        self.window, self.on_key, self.on_error = window, on_key, on_error
        self.api = api
        self.handle = self.procedure = None
        self.active = False
        self.held = set()

    def start(self):
        self.close()
        if self.api is None:
            self.api = Win32CaptureAPI()
        self.target = self.api.root(self.window.winfo_id())
        self.procedure = HOOKPROC(self._hookproc)
        self.handle = self.api.install(self.procedure)
        _installed[self.handle] = self
        self.held.clear()
        self.active = True

    def close(self):
        self.active = False
        self.held.clear()
        if self.handle is not None:
            handle = self.handle
            self.api.remove(handle)
            self.handle = None
            _installed.pop(handle, None)

    @staticmethod
    def event(key):
        code = key.vkCode
        if code == 0x10:
            code = 0xA1 if key.scanCode == 0x36 else 0xA0
        elif code in (0x11, 0x12):
            code = (0xA2 if code == 0x11 else 0xA4) + bool(key.flags & 1)
        names = {0xA0: "Shift_L", 0xA1: "Shift_R", 0xA2: "Control_L", 0xA3: "Control_R",
                 0xA4: "Alt_L", 0xA5: "Alt_R", 0x5B: "Win_L", 0x5C: "Win_R",
                 0x20: "space", 0x0D: "Return", 0x1B: "Escape", 0x09: "Tab", 0x08: "Backspace"}
        name = names.get(code)
        if name is None:
            name = (chr(code) if 0x30 <= code <= 0x39 or 0x41 <= code <= 0x5A else
                    "F%d" % (code - 0x6F) if 0x70 <= code <= 0x87 else "VK 0x%02X" % code)
        return SimpleNamespace(keycode=code, keysym=name)

    def _hookproc(self, code, message, address):
        try:
            if code >= 0 and self.active:
                if self.api.foreground() != self.target:
                    self.close()
                    self.on_error("窗口已失焦，请重录")
                elif message in (WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP):
                    key = ctypes.cast(address, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    up = message in (WM_KEYUP, WM_SYSKEYUP)
                    if (not key.flags & (LLKHF_INJECTED | 2) and bool(key.flags & LLKHF_UP) == up
                            and 1 <= key.vkCode <= 254):
                        event = self.event(key)
                        if up and event.keycode not in self.held:
                            return self.api.next(self.handle, code, message, address)
                        if up:
                            self.held.remove(event.keycode)
                        else:
                            self.held.add(event.keycode)
                        self.on_key(not up, event)
                        return 1  # Keep the recorded chord out of the remaining hook chain.
        except BaseException:
            # Exceptions must never cross the ctypes callback into Windows.
            try:
                self.close()
            except Exception:
                log.exception("无法移除录制钩子；已停止拦截")
            try:
                self.on_error("录制失败，请重录")
            except Exception:
                pass
        try:
            return self.api.next(self.handle, code, message, address)
        except BaseException:
            return 0
