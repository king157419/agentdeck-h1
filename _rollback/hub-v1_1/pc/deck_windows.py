"""AgentDeck 的窗口切换与 SendInput；只有实例化时才访问 Win32。"""
import ctypes
from ctypes import wintypes

from daemon import ForegroundWindow


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", INPUTUNION)]


class WindowControl(ForegroundWindow):
    def __init__(self):
        super().__init__()
        self.enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        signatures = {
            "EnumWindows": ([self.enum_proc, wintypes.LPARAM], wintypes.BOOL),
            "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
            "IsIconic": ([wintypes.HWND], wintypes.BOOL),
            "ShowWindow": ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
            "SetForegroundWindow": ([wintypes.HWND], wintypes.BOOL),
            "AttachThreadInput": ([wintypes.DWORD, wintypes.DWORD, wintypes.BOOL], wintypes.BOOL),
            "GetAsyncKeyState": ([ctypes.c_int], ctypes.c_short),
            "SendInput": ([wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int], wintypes.UINT),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = args, result
        self.kernel.GetCurrentThreadId.argtypes = []
        self.kernel.GetCurrentThreadId.restype = wintypes.DWORD

    def windows(self):
        windows = []

        @self.enum_proc
        def collect(hwnd, unused):
            if self.user.IsWindowVisible(hwnd):
                info = self.read(hwnd)
                if info[2]:
                    windows.append(info)
            return True

        if not self.user.EnumWindows(collect, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return windows

    def activate(self, hwnd):
        if self.user.IsIconic(hwnd):
            self.user.ShowWindow(hwnd, 9)  # SW_RESTORE
        if self.user.SetForegroundWindow(hwnd) and self.user.GetForegroundWindow() == hwnd:
            return True
        current = self.kernel.GetCurrentThreadId()
        targets = {self.user.GetWindowThreadProcessId(self.user.GetForegroundWindow(), None),
                   self.user.GetWindowThreadProcessId(hwnd, None)} - {0, current}
        attached = []
        try:
            for thread in targets:
                if self.user.AttachThreadInput(current, thread, True):
                    attached.append(thread)
            self.user.SetForegroundWindow(hwnd)
            return self.user.GetForegroundWindow() == hwnd
        finally:
            for thread in reversed(attached):
                self.user.AttachThreadInput(current, thread, False)

    def send_key(self, vkey, expected):
        # 拒绝在 Ctrl/Alt/Shift/Win 按住时把 Enter 变成组合键。
        if any(self.user.GetAsyncKeyState(key) & 0x8000
               for key in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
            return False
        if self() != expected:
            return False
        events = (INPUT * 2)()
        for index, flags in enumerate((0, 2)):
            events[index].type = 1  # INPUT_KEYBOARD
            events[index].ki = KEYBDINPUT(vkey, 0, flags, 0, 0)
        sent = self.user.SendInput(2, events, ctypes.sizeof(INPUT))
        if sent == 1:
            # 极少数只插入 key-down 的失败，尽力补 key-up，避免卡键。
            self.user.SendInput(1, ctypes.byref(events[1]), ctypes.sizeof(INPUT))
        return sent == 2
