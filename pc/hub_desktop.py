"""Platform-dispatched desktop effects; imports never access native windows."""
import ctypes
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
import logging
import ntpath
from pathlib import Path
import sys
import threading
import time
import uuid

if sys.platform == "win32":
    from ctypes import wintypes
    from deck_windows import INPUT, KEYBDINPUT, MOUSEINPUT, WindowControl


VOICE_POLL_SECONDS = 0.1
VOICE_MAX_SECONDS = 60.0
DICTATION_MODIFIERS = {"control": 0x11, "option": 0x12, "shift": 0x10, "command": 0x5B}
log = logging.getLogger("agentdeck.hub.voice")


@dataclass
class _Voice:
    session: dict
    hwnd: int
    started: float
    on_stop: object = None
    stop: threading.Event = field(default_factory=threading.Event)
    thread: object = None
    reason: str = "released"
    restores: int = 0
    error: object = None
    close_error: object = None
    closed: bool = False
    result: object = None
    mode: str = "toggle"
    keys: tuple = ()
    cleanup_only: bool = False
    closing_triggered: bool = False
    uncertain: bool = False


if sys.platform == "win32":
    class HubWindowControl(WindowControl):
        """Add guarded key combinations without changing the existing deck adapter."""

        def __init__(self):
            super().__init__()
            self.user.IsWindow.argtypes = [wintypes.HWND]
            self.user.IsWindow.restype = wintypes.BOOL

        def exists(self, hwnd):
            return bool(self.user.IsWindow(hwnd))

        def is_terminal(self, hwnd):
            self.user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            self.user.GetClassNameW.restype = ctypes.c_int
            name = ctypes.create_unicode_buffer(256)
            if not self.user.GetClassNameW(hwnd, name, len(name)):
                raise ctypes.WinError(ctypes.get_last_error())
            return name.value.casefold() in {
                "consolewindowclass", "cascadia_hosting_window_class", "pseudoconsolewindow"}

        def send_combo(self, keys, expected):
            self._combo_triggered = False
            keys = tuple(keys)
            if not self._can_press(keys, expected):
                return False
            transitions = [(key, 0) for key in keys]
            transitions.extend((key, 2) for key in reversed(keys))
            return self._send_owned(transitions)

        def hold_combo(self, keys, expected):
            keys = tuple(keys)
            if not self._can_press(keys, expected):
                return False
            return self._send_owned([(key, 0) for key in keys])

        def _can_press(self, keys, expected):
            modifiers = (0x10, 0x11, 0x12, 0x5B, 0x5C, *range(0xA0, 0xA6))
            # Same window handle: Claude Code animates its title, which must not
            # make a correct target look like a foreground change.
            return (bool(keys) and not getattr(self, "_held_keys", ())
                    and not any(self.user.GetAsyncKeyState(key) & 0x8000
                                for key in set(modifiers + keys))
                    and self()[0] == expected[0])

        def _dpi_aware(self):
            """Physical pixels for rects, cursor and virtual screen on this thread."""
            method = getattr(self.user, "SetThreadDpiAwarenessContext", None)
            if method is None:
                return None
            method.argtypes, method.restype = [ctypes.c_void_p], ctypes.c_void_p
            return method(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2

        def _restore_dpi(self, previous):
            if previous:
                self.user.SetThreadDpiAwarenessContext(previous)

        def scroll_point(self, hwnd):
            """First sample point of the window not covered by another window (e.g. the overlay)."""
            rect = wintypes.RECT()
            self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            self.user.GetWindowRect.restype = wintypes.BOOL
            self.user.WindowFromPoint.argtypes = [wintypes.POINT]
            self.user.WindowFromPoint.restype = wintypes.HWND
            self.user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            self.user.GetAncestor.restype = wintypes.HWND
            if not self.user.GetWindowRect(hwnd, ctypes.byref(rect)):
                raise ctypes.WinError(ctypes.get_last_error())
            for fx, fy in SCROLL_POINTS:
                point = wintypes.POINT(rect.left + int((rect.right - rect.left) * fx),
                                       rect.top + int((rect.bottom - rect.top) * fy))
                hit = self.user.WindowFromPoint(point)
                if hit and self.user.GetAncestor(hit, 2) == hwnd:  # GA_ROOT
                    return point.x, point.y
            raise RuntimeError("窗口被挡住")

        def wheel(self, hwnd, notches, expected):
            """One SendInput batch: move to the window, wheel, move back."""
            previous = self._dpi_aware()
            try:
                if self()[0] != expected[0] or getattr(self, "_held_keys", ()):
                    return False
                x, y = self.scroll_point(hwnd)
                cursor = wintypes.POINT()
                self.user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
                self.user.GetCursorPos.restype = wintypes.BOOL
                if not self.user.GetCursorPos(ctypes.byref(cursor)):
                    raise ctypes.WinError(ctypes.get_last_error())
                self.user.GetSystemMetrics.argtypes = [ctypes.c_int]
                self.user.GetSystemMetrics.restype = ctypes.c_int
                screen = tuple(self.user.GetSystemMetrics(index) for index in (76, 77, 78, 79))
                events = wheel_events((x, y), (cursor.x, cursor.y), notches, screen)
                sent = self.user.SendInput(len(events), events, ctypes.sizeof(INPUT))
                return sent == len(events)
            finally:
                self._restore_dpi(previous)

        def _send_owned(self, transitions):
            # Reserve ownership before native input: even an exception after
            # insertion must leave enough information to release our keys.
            self._held_keys = list(dict.fromkeys(key for key, flags in transitions if not flags))
            events = self._events(transitions)
            self._combo_triggered = None  # An interrupted native call has unknown delivery.
            try:
                sent = self.user.SendInput(len(events), events, ctypes.sizeof(INPUT))
            except BaseException:
                self.release_combo()
                raise
            self._combo_triggered = sent >= len(self._held_keys)
            self._held_keys = []
            for key, flags in transitions[:sent]:
                if flags:
                    self._held_keys.remove(key)
                else:
                    self._held_keys.append(key)
            if sent != len(events):
                self.release_combo()
                return False
            return True

        def release_combo(self):
            # Cleanup contains ONLY key-ups for keys owned by this adapter.
            # It must work even after the target disappears or focus changes.
            for attempt in range(2):
                keys = list(reversed(getattr(self, "_held_keys", ())))
                if not keys:
                    return True
                events = self._events([(key, 2) for key in keys])
                try:
                    sent = self.user.SendInput(len(events), events, ctypes.sizeof(INPUT))
                except BaseException:
                    if attempt:
                        raise
                    continue
                for key in keys[:sent]:
                    self._held_keys.remove(key)
            return not self._held_keys

        @staticmethod
        def _events(transitions):
            events = (INPUT * len(transitions))()
            # Side-specific modifiers need their hardware scan code as well
            # as the extended flag so low-level hooks distinguish Right Alt.
            scans = {0x10: 0x2A, 0x11: 0x1D, 0x12: 0x38,
                     0xA0: 0x2A, 0xA1: 0x36, 0xA2: 0x1D, 0xA3: 0x1D,
                     0xA4: 0x38, 0xA5: 0x38, 0x5B: 0x5B, 0x5C: 0x5C}
            for event, (key, flags) in zip(events, transitions):
                event.type = 1  # INPUT_KEYBOARD
                extended = key in (0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27,
                                   0x28, 0x2C, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D,
                                   0x6F, 0x90, 0xA3, 0xA5)
                event.ki = KEYBDINPUT(key, scans.get(key, 0), flags | int(extended), 0, 0)
            return events


SCROLL_POINTS = ((0.5, 0.6), (0.5, 0.85), (0.25, 0.5), (0.75, 0.5), (0.5, 0.3))


def absolute(point, screen):
    """Pixel -> 0..65535 on the virtual desktop (SM_X/Y/CX/CYVIRTUALSCREEN)."""
    left, top, width, height = screen
    width, height = max(1, width), max(1, height)
    x = min(65535, max(0, ((point[0] - left) * 65536 + width - 1) // width))
    y = min(65535, max(0, ((point[1] - top) * 65536 + height - 1) // height))
    return x, y


def wheel_events(target, cursor, notches, screen):
    """Move|absolute|virtualdesk to target, wheel -120*notches, move back to cursor."""
    events = (INPUT * 3)()
    move = 0x0001 | 0x8000 | 0x4000  # MOVE | ABSOLUTE | VIRTUALDESK
    for event, flags, point in ((events[0], move, target), (events[1], 0x0800, None),
                                (events[2], move, cursor)):
        event.type = 0  # INPUT_MOUSE
        dx, dy = absolute(point, screen) if point is not None else (0, 0)
        data = (-120 * notches) & 0xFFFFFFFF if point is None else 0
        event.mi = MOUSEINPUT(dx, dy, data, flags, 0, 0)
    return events


def set_clipboard(text):
    """Copy Unicode text with Win32 ownership rules; only called for an action."""
    if not isinstance(text, str) or "\0" in text:
        raise ValueError("clipboard text must be a string without NUL characters")
    _set_clipboard_data(((13, (text + "\0").encode("utf-16-le")),))  # CF_UNICODETEXT


def set_image_clipboard(image):
    """Publish a packed DIB and PNG so desktop apps can paste an attachment."""
    dib, png = BytesIO(), BytesIO()
    image.convert("RGB").save(dib, format="BMP")
    image.save(png, format="PNG")
    # CF_DIB starts at BITMAPINFOHEADER, after the 14-byte BMP file header.
    _set_clipboard_data(((8, dib.getvalue()[14:]), ("PNG", png.getvalue())))


def _set_clipboard_data(formats):
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
    user.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user.RegisterClipboardFormatW.restype = wintypes.UINT
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
    opened = False
    try:
        owner = user.GetForegroundWindow()
        if not owner or not user.OpenClipboard(owner):
            raise ctypes.WinError(ctypes.get_last_error())
        opened = True
        if not user.EmptyClipboard():
            raise ctypes.WinError(ctypes.get_last_error())
        for format_id, payload in formats:
            if isinstance(format_id, str):
                format_id = user.RegisterClipboardFormatW(format_id)
                if not format_id:
                    raise ctypes.WinError(ctypes.get_last_error())
            handle = kernel.GlobalAlloc(0x0002, len(payload))  # GMEM_MOVEABLE
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            transferred = False
            try:
                pointer = kernel.GlobalLock(handle)
                if not pointer:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    ctypes.memmove(pointer, payload, len(payload))
                finally:
                    kernel.GlobalUnlock(handle)
                if not user.SetClipboardData(format_id, handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                transferred = True  # Windows owns this handle after success.
            finally:
                if not transferred:
                    kernel.GlobalFree(handle)
    finally:
        if opened:
            user.CloseClipboard()


def capture_screen():
    from PIL import ImageGrab
    return ImageGrab.grab(all_screens=True)


class DesktopEffects:
    """Inject windows, clipboard, capture, clock and sleep to run entirely offline."""

    def __new__(cls, *args, **kwargs):
        if cls is DesktopEffects and sys.platform == "darwin":
            from hub_desktop_mac import MacDesktopEffects
            return object.__new__(MacDesktopEffects)
        return object.__new__(cls)

    def __init__(self, windows=None, *, clipboard=None, image_clipboard=None, capture=None,
                 shots_dir=None, now=None, sleeper=None, monotonic=None,
                 voice_wait=None, dictation_shortcut=None):
        self._windows = windows
        self.clipboard = set_clipboard if clipboard is None else clipboard
        self.image_clipboard = set_image_clipboard if image_clipboard is None else image_clipboard
        self.capture = capture_screen if capture is None else capture
        self.shots_dir = (Path.home() / ".agentdeck" / "shots"
                          if shots_dir is None else Path(shots_dir))
        self.now = datetime.now if now is None else now
        self.sleep = time.sleep if sleeper is None else sleeper
        self.monotonic = time.monotonic if monotonic is None else monotonic
        self.voice_wait = (lambda stop, seconds: stop.wait(seconds)) if voice_wait is None else voice_wait
        self._voice = None
        self._voice_lock = threading.RLock()
        self._voice_commands = threading.RLock()
        self.set_dictation_shortcut(dictation_shortcut)

    @staticmethod
    def _shortcut(shortcut):
        if shortcut is None:
            shortcut = {"key_codes": [0x48], "modifiers": ["command"]}
        if (not isinstance(shortcut, dict)
                or set(shortcut) - {"key_codes", "modifiers", "mode"}):
            raise ValueError("dictation_shortcut needs key_codes, optional modifiers and mode")
        codes, modifiers = shortcut.get("key_codes"), shortcut.get("modifiers", [])
        mode = shortcut.get("mode", "toggle")
        if (not isinstance(codes, list) or not 1 <= len(codes) <= 4
                or any(type(code) is not int or not 1 <= code <= 254 for code in codes)
                or len(codes) != len(set(codes))
                or not isinstance(modifiers, list)
                or any(not isinstance(modifier, str) or modifier not in DICTATION_MODIFIERS
                       for modifier in modifiers)
                or len(modifiers) != len(set(modifiers))
                or mode not in ("toggle", "hold", "tap")):
            raise ValueError("invalid dictation key_codes, modifiers or mode")
        keys = [DICTATION_MODIFIERS[name] for name in modifiers] + codes
        families = ({0x10, 0xA0, 0xA1}, {0x11, 0xA2, 0xA3},
                    {0x12, 0xA4, 0xA5}, {0x5B, 0x5C})
        if any(sum(key in family for key in keys) > 1 for family in families):
            raise ValueError("duplicate dictation modifier")
        return {"key_codes": list(codes), "modifiers": list(modifiers), "mode": mode}

    def set_dictation_shortcut(self, shortcut):
        shortcut = DesktopEffects._shortcut(shortcut)
        with self._voice_commands, self._voice_lock:
            if self.voice_active:
                raise RuntimeError("release voice before changing its shortcut")
            self.dictation_shortcut = shortcut
            self._dictation_mode = shortcut["mode"]
            self._dictation_keys = tuple(DICTATION_MODIFIERS[name] for name in shortcut["modifiers"]) + tuple(shortcut["key_codes"])

    @property
    def windows(self):
        if self._windows is None:
            self._windows = HubWindowControl()
        return self._windows

    def focus(self, session, sessions):
        return self._focus(session, sessions)

    def app(self, session, sessions, direction):
        """Switch Claude's conversation without changing the Hub selection."""
        keys = {"next": 0xDD, "prev": 0xDB}
        if direction not in keys:
            raise ValueError("app needs next or prev")
        with self._voice_commands:
            if self.voice_active:
                raise RuntimeError("release voice before switching app sessions")
            windows = self.windows.windows()
            window = None
            if (session is not None
                    and ntpath.basename(session.get("window_exe") or "").casefold() == "claude.exe"):
                window = self._bound_window(session, windows)
            if window is None:
                window = next((info for info in windows
                               if ntpath.basename(info[1] or "").casefold() == "claude.exe"
                               and info[2] == "Claude"), None)
            if window is None:
                raise RuntimeError("没找到 Claude 桌面版窗口")
            if not self.windows.activate(window[0]) or self.windows()[0] != window[0]:
                raise RuntimeError("could not activate Claude desktop window")
            self._combo((0x11, 0x10, keys[direction]), window)
            return True

    @staticmethod
    def _bound_window(session, windows):
        """The window the relay recorded for this session, if it still exists."""
        hwnd = session.get("hwnd")
        if type(hwnd) is not int or hwnd <= 0:
            return None
        expected = session.get("window_exe") or ""
        for info in windows:
            if info[0] != hwnd:
                continue
            process = ntpath.basename(info[1] or "")
            # A reused handle of a different program is not this session's window.
            if expected and process and process.casefold() != ntpath.basename(expected).casefold():
                return None
            return info
        return None

    def _focus(self, session, sessions):
        from deck import Session, window_for_session
        windows = self.windows.windows()
        window = self._bound_window(session, windows)
        shared = window is not None and sum(
            1 for item in sessions if type(item.get("hwnd")) is int and item["hwnd"] == window[0]) > 1
        if window is None or shared:
            target = Session(session["key"], session["state"], session["name"])
            candidates = [Session(item["key"], item["state"], item["name"])
                          for item in sessions]
            matched, reason = window_for_session(target, windows, candidates)
            if matched is not None and (window is None or matched[0] != window[0]):
                window = matched
            if window is None:
                raise RuntimeError("窗口已关闭或找不到（%s）" % reason)
        # Compare handles only: Claude Code keeps changing its terminal title.
        if not self.windows.activate(window[0]) or self.windows()[0] != window[0]:
            raise RuntimeError("could not activate the selected session window")
        return window

    def _combo(self, keys, expected):
        # Reset before the outer foreground check too: a rejected attempt must
        # never inherit delivery information from the previous toggle.
        if hasattr(self.windows, "_combo_triggered"):
            self.windows._combo_triggered = False
        if self.windows()[0] != expected[0] or not self.windows.send_combo(keys, expected):
            raise RuntimeError("foreground changed or key combination failed")

    def _key(self, key, expected):
        if self.windows()[0] != expected[0] or not self.windows.send_key(key, expected):
            raise RuntimeError("foreground changed or key input failed")

    def _paste(self, text, expected):
        if self.windows()[0] != expected[0]:
            raise RuntimeError("foreground changed before paste")
        self.clipboard(text)
        self._combo((0x11, 0x56), expected)  # Ctrl+V

    def _voice_shortcut(self, expected):
        self._combo(self._dictation_keys, expected)

    @property
    def dictation_shortcut_label(self):
        names = {0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc",
                 0x20: "Space", 0x10: "Shift", 0x11: "Ctrl", 0x12: "Alt",
                 0x5B: "Win", 0x5C: "右 Win", 0xA0: "左 Shift", 0xA1: "右 Shift",
                 0xA2: "左 Ctrl", 0xA3: "右 Ctrl", 0xA4: "左 Alt", 0xA5: "右 Alt"}
        names.update((key, chr(key)) for key in (*range(0x30, 0x3A), *range(0x41, 0x5B)))
        names.update((key, "F%d" % (key - 0x6F)) for key in range(0x70, 0x88))
        return "+".join(names.get(key, "VK 0x%02X" % key) for key in self._dictation_keys)

    def interrupt(self, session, sessions):
        self._key(0x1B, self._focus(session, sessions))
        return True

    def nav(self, session, sessions, key):
        """Arrow keys pick an option in the agent's question; Enter submits."""
        self._key({"up": 0x26, "down": 0x28, "enter": 0x0D}[key], self._focus(session, sessions))
        return True

    def scroll(self, session, sessions, notches):
        """Mouse wheel over the agent window (positive notches scroll toward newer text).

        Terminals scroll their scrollback, full-screen TUIs and editors handle the
        wheel themselves; scrolling keys would mean different things per app.
        """
        if type(notches) is not int or not notches:
            raise ValueError("scroll needs a nonzero integer")
        window = self._focus(session, sessions)  # foreground: works without "scroll inactive windows"
        wheel = getattr(self.windows, "wheel", None)
        if wheel is None:
            raise RuntimeError("mouse wheel input unavailable")
        if not wheel(window[0], notches, window):
            raise RuntimeError("foreground changed or wheel input failed")
        return True

    @property
    def voice_active(self):
        with self._voice_lock:
            return self._voice is not None and not self._voice.closed

    def voice_down(self, session, sessions, *, on_stop=None):
        """Tap the shortcut or start dictation pinned to the original hwnd."""
        with self._voice_commands:
            with self._voice_lock:
                previous = self._voice
                if previous is not None and not previous.closed:
                    return True
            if previous is not None and previous.thread.ident is not None:
                previous.thread.join()
            window = self._focus(session, sessions)
            if self._dictation_mode == "tap":
                self._voice_shortcut(window)
                return {"mode": "tap", "shortcut": self.dictation_shortcut_label}
            voice = _Voice(dict(session), window[0], self.monotonic(), on_stop,
                           mode=self._dictation_mode, keys=self._dictation_keys)
            voice.thread = threading.Thread(target=self._guard_voice, args=(voice,),
                                            name="AgentDeck voice focus", daemon=True)
            try:
                if voice.mode == "hold":
                    # Publish ownership before key-down, including partial input
                    # or exceptions raised while starting the guard thread.
                    with self._voice_lock:
                        self._voice = voice
                    if self.windows() != window or not self.windows.hold_combo(voice.keys, window):
                        raise RuntimeError("foreground changed or key combination failed")
                else:
                    self._voice_shortcut(window)
                    with self._voice_lock:
                        self._voice = voice
                voice.thread.start()
            except BaseException as error:
                triggered = getattr(self.windows, "_combo_triggered", False)
                if self._voice is not voice and (getattr(self.windows, "_held_keys", ())
                                                or triggered is not False):
                    # A failed toggle may still own a partially inserted key.
                    # Complete key-down delivery may also have started dictation.
                    voice.cleanup_only = triggered is False
                    voice.uncertain = triggered is None
                    with self._voice_lock:
                        self._voice = voice
                if self._voice is voice:
                    voice.reason, voice.error = "error", str(error)
                    self._finish_voice(voice)
                raise
            log.info("Voice started: target=%s hwnd=%s", voice.session["key"], voice.hwnd)
        return True

    def _guard_voice(self, voice):
        try:
            while not self.voice_wait(voice.stop, VOICE_POLL_SECONDS):
                with self._voice_lock:
                    if voice.stop.is_set():
                        break
                    if self.monotonic() - voice.started >= VOICE_MAX_SECONDS:
                        voice.reason = "timeout"
                        voice.stop.set()
                        break
                    if not self._voice_exists(voice):
                        voice.reason = "window_lost"
                        voice.stop.set()
                        break
                    if self.windows()[0] != voice.hwnd and not self._restore_voice(voice):
                        voice.reason = "focus_failed"
                        voice.stop.set()
                        break
        except BaseException as error:
            with self._voice_lock:
                voice.reason, voice.error = "error", str(error)
                voice.stop.set()
        finally:
            self._finish_voice(voice)

    def _restore_voice(self, voice):
        if not self.windows.activate(voice.hwnd) or self.windows()[0] != voice.hwnd:
            return False
        voice.restores += 1
        log.info("Voice kept target: target=%s hwnd=%s restores=%d",
                 voice.session["key"], voice.hwnd, voice.restores)
        return True

    def _voice_exists(self, voice):
        exists = getattr(self.windows, "exists", None)
        if exists is not None:
            return exists(voice.hwnd)
        return any(window[0] == voice.hwnd for window in self.windows.windows())

    def _finish_voice(self, voice):
        with self._voice_lock:
            if voice.closed:
                return
            voice.stop.set()
            try:
                # Restore the original target before a closing toggle. Hold
                # cleanup releases owned keys even if restoring is impossible.
                exists = self._voice_exists(voice)
                if not exists and voice.reason == "released":
                    voice.reason = "window_lost"
                if (exists and voice.reason != "focus_failed"
                        and self.windows()[0] != voice.hwnd):
                    self._restore_voice(voice)
            except BaseException as error:
                voice.error = str(error)
            try:
                self._close_voice(voice)
                voice.closed, voice.close_error = True, None
            except BaseException as error:
                voice.close_error = str(error)
            result = {"session": voice.session, "reason": voice.reason,
                      "restores": voice.restores, "closed": voice.closed}
            error = voice.close_error or voice.error
            if error is not None:
                result["error"] = error
            voice.result = result
        log.info("Voice guard stopped: target=%s hwnd=%s reason=%s restores=%d closed=%s",
                 voice.session["key"], voice.hwnd, voice.reason, voice.restores, voice.closed)
        if error is not None:
            log.warning("Voice stop error: %s", error)
        if voice.on_stop is not None:
            try:
                voice.on_stop(result)
            except Exception:
                log.exception("Voice completion callback failed")

    def _close_voice(self, voice):
        release = getattr(self.windows, "release_combo", None)
        if release is not None and not release():
            raise RuntimeError("dictation key release failed")
        if voice.mode != "hold" and not voice.cleanup_only:
            if voice.uncertain:
                raise RuntimeError("dictation shortcut delivery is unknown; input remains blocked")
            if voice.closing_triggered:
                return
            foreground = self.windows()
            if foreground[0] != voice.hwnd:
                raise RuntimeError("voice target is not foreground; cannot stop dictation")
            try:
                self._combo(voice.keys, foreground)
            except BaseException:
                triggered = getattr(self.windows, "_combo_triggered", False)
                voice.closing_triggered = triggered is True
                voice.uncertain = triggered is None
                raise

    def _stop_voice(self, reason):
        with self._voice_commands:
            with self._voice_lock:
                voice = self._voice
                if voice is None:
                    return None
                already_finished = voice.result is not None
                if not voice.stop.is_set():
                    voice.reason = reason
                    voice.stop.set()
            # The guard does not need _voice_commands; never join under the
            # state lock that it needs to release the owned shortcut.
            if (voice.thread.ident is not None
                    and voice.thread is not threading.current_thread()):
                voice.thread.join()
            if already_finished and voice.closed:
                return None
            if already_finished:
                # The guard has ended, but a failed Win+H still owns dictation.
                # Retry once on an explicit release, keeping all other input
                # blocked until this closing combination succeeds.
                self._finish_voice(voice)
            if not voice.closed:
                raise RuntimeError(voice.close_error)
            return voice.result

    def voice_up(self):
        return self._stop_voice("released")

    def voice(self, session, sessions):
        with self._voice_commands:
            self.voice_down(session, sessions)
            self.voice_up()
        return True

    def close(self):
        return self._stop_voice("shutdown")

    def screenshot(self, session, sessions):
        image = self.capture()
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        stamp = self.now().strftime("%Y%m%d-%H%M%S-%f")
        path = (self.shots_dir / (stamp + "-" + uuid.uuid4().hex[:8] + ".png")).resolve()
        image.save(path, format="PNG")
        window = self._focus(session, sessions)
        process = ntpath.basename(window[1] or "").casefold()
        if ((process == "claude.exe" or "codex" in process)
                and not self.windows.is_terminal(window[0])):
            if self.windows()[0] != window[0]:
                raise RuntimeError("foreground changed before paste")
            self.image_clipboard(image)
            self._combo((0x11, 0x56), window)
            return {"path": str(path), "paste": "image"}
        self._paste(str(path), window)
        return str(path)

    def prompt(self, session, sessions, text):
        if not isinstance(text, str) or not text:
            raise ValueError("prompt text must be a nonempty string")
        expected = self._focus(session, sessions)
        self._paste(text, expected)
        self.sleep(0.05)
        self._key(0x0D, expected)
        return True
