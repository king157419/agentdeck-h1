"""Desktop effects for Hub actions; importing this module never accesses Win32."""
import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import time
import uuid

from deck_windows import INPUT, KEYBDINPUT, WindowControl


class HubWindowControl(WindowControl):
    """Add guarded key combinations without changing the existing deck adapter."""

    def send_combo(self, keys, expected):
        keys = tuple(keys)
        modifiers = (0x10, 0x11, 0x12, 0x5B, 0x5C)
        if (not keys or self() != expected
                or any(self.user.GetAsyncKeyState(key) & 0x8000
                       for key in set(modifiers + keys))):
            return False
        transitions = [(key, 0) for key in keys]
        transitions.extend((key, 2) for key in reversed(keys))
        events = self._events(transitions)
        sent = self.user.SendInput(len(events), events, ctypes.sizeof(INPUT))
        if sent == len(events):
            return True
        held = []
        for key, flags in transitions[:sent]:
            if flags:
                held.remove(key)
            else:
                held.append(key)
        if held:
            releases = self._events([(key, 2) for key in reversed(held)])
            self.user.SendInput(len(releases), releases, ctypes.sizeof(INPUT))
        return False

    @staticmethod
    def _events(transitions):
        events = (INPUT * len(transitions))()
        for event, (key, flags) in zip(events, transitions):
            event.type = 1  # INPUT_KEYBOARD
            event.ki = KEYBDINPUT(key, 0, flags, 0, 0)
        return events


def set_clipboard(text):
    """Copy Unicode text with Win32 ownership rules; only called for an action."""
    if not isinstance(text, str) or "\0" in text:
        raise ValueError("clipboard text must be a string without NUL characters")
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.OpenClipboard.argtypes = [wintypes.HWND]
    user.OpenClipboard.restype = wintypes.BOOL
    user.GetForegroundWindow.argtypes = []
    user.GetForegroundWindow.restype = wintypes.HWND
    user.EmptyClipboard.argtypes = []
    user.EmptyClipboard.restype = wintypes.BOOL
    user.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user.SetClipboardData.restype = wintypes.HANDLE
    user.CloseClipboard.argtypes = []
    user.CloseClipboard.restype = wintypes.BOOL
    kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalUnlock.restype = wintypes.BOOL
    kernel.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalFree.restype = wintypes.HGLOBAL
    payload = (text + "\0").encode("utf-16-le")
    handle = kernel.GlobalAlloc(0x0002, len(payload))  # GMEM_MOVEABLE
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    opened = False
    transferred = False
    try:
        pointer = kernel.GlobalLock(handle)
        if not pointer:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ctypes.memmove(pointer, payload, len(payload))
        finally:
            kernel.GlobalUnlock(handle)
        owner = user.GetForegroundWindow()
        if not owner or not user.OpenClipboard(owner):
            raise ctypes.WinError(ctypes.get_last_error())
        opened = True
        if not user.EmptyClipboard() or not user.SetClipboardData(13, handle):
            raise ctypes.WinError(ctypes.get_last_error())
        transferred = True  # Windows owns memory after SetClipboardData succeeds.
    finally:
        if opened:
            user.CloseClipboard()
        if not transferred:
            kernel.GlobalFree(handle)


def capture_screen():
    from PIL import ImageGrab
    return ImageGrab.grab(all_screens=True)


class DesktopEffects:
    """Inject windows, clipboard, capture, clock and sleep to run entirely offline."""

    def __init__(self, windows=None, *, clipboard=None, capture=None,
                 shots_dir=None, now=None, sleeper=None):
        self._windows = windows
        self.clipboard = set_clipboard if clipboard is None else clipboard
        self.capture = capture_screen if capture is None else capture
        self.shots_dir = (Path.home() / ".agentdeck" / "shots"
                          if shots_dir is None else Path(shots_dir))
        self.now = datetime.now if now is None else now
        self.sleep = time.sleep if sleeper is None else sleeper

    @property
    def windows(self):
        if self._windows is None:
            self._windows = HubWindowControl()
        return self._windows

    def focus(self, session, sessions):
        from deck import Session, window_for_session
        target = Session(session["key"], session["state"], session["name"])
        candidates = [Session(item["key"], item["state"], item["name"])
                      for item in sessions]
        window, reason = window_for_session(target, self.windows.windows(), candidates)
        if window is None:
            raise RuntimeError(reason)
        if not self.windows.activate(window[0]) or self.windows() != window:
            raise RuntimeError("could not activate the selected session window")
        return window

    def _combo(self, keys, expected):
        if self.windows() != expected or not self.windows.send_combo(keys, expected):
            raise RuntimeError("foreground changed or key combination failed")

    def _key(self, key, expected):
        if self.windows() != expected or not self.windows.send_key(key, expected):
            raise RuntimeError("foreground changed or key input failed")

    def _paste(self, text, expected):
        if self.windows() != expected:
            raise RuntimeError("foreground changed before paste")
        self.clipboard(text)
        self._combo((0x11, 0x56), expected)  # Ctrl+V

    def interrupt(self, session, sessions):
        self._key(0x1B, self.focus(session, sessions))
        return True

    def voice(self, session, sessions):
        self._combo((0x5B, 0x48), self.focus(session, sessions))  # Win+H
        return True

    def screenshot(self, session, sessions):
        image = self.capture()
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        stamp = self.now().strftime("%Y%m%d-%H%M%S-%f")
        path = (self.shots_dir / (stamp + "-" + uuid.uuid4().hex[:8] + ".png")).resolve()
        image.save(path, format="PNG")
        self._paste(str(path), self.focus(session, sessions))
        return str(path)

    def prompt(self, session, sessions, text):
        if not isinstance(text, str) or not text:
            raise ValueError("prompt text must be a nonempty string")
        expected = self.focus(session, sessions)
        self._paste(text, expected)
        self.sleep(0.05)
        self._key(0x0D, expected)
        return True
