"""Desktop effects for Hub actions; importing this module never accesses Win32."""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import datetime
import logging
from pathlib import Path
import threading
import time
import uuid

from deck_windows import INPUT, KEYBDINPUT, WindowControl


VOICE_POLL_SECONDS = 0.1
VOICE_MAX_SECONDS = 60.0
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


class HubWindowControl(WindowControl):
    """Add guarded key combinations without changing the existing deck adapter."""

    def __init__(self):
        super().__init__()
        self.user.IsWindow.argtypes = [wintypes.HWND]
        self.user.IsWindow.restype = wintypes.BOOL

    def exists(self, hwnd):
        return bool(self.user.IsWindow(hwnd))

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
                 shots_dir=None, now=None, sleeper=None, monotonic=None,
                 voice_wait=None):
        self._windows = windows
        self.clipboard = set_clipboard if clipboard is None else clipboard
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

    @property
    def voice_active(self):
        with self._voice_lock:
            return self._voice is not None and not self._voice.closed

    def voice_down(self, session, sessions, *, on_stop=None):
        """Start one owned dictation interval, pinned to the original hwnd."""
        with self._voice_commands:
            with self._voice_lock:
                previous = self._voice
                if previous is not None and not previous.closed:
                    return True
            if previous is not None and previous.thread.ident is not None:
                previous.thread.join()
            window = self.focus(session, sessions)
            self._combo((0x5B, 0x48), window)  # Win+H, never text or approval.
            voice = _Voice(dict(session), window[0], self.monotonic(), on_stop)
            voice.thread = threading.Thread(target=self._guard_voice, args=(voice,),
                                            name="AgentDeck voice focus", daemon=True)
            with self._voice_lock:
                self._voice = voice
            try:
                voice.thread.start()
            except Exception as error:
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
        except Exception as error:
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
                # Restore the target before closing when it is still available.
                # If it vanished or activation fails, Win+H is a global stop;
                # this path never pastes or injects a text/approval key.
                exists = self._voice_exists(voice)
                if not exists and voice.reason == "released":
                    voice.reason = "window_lost"
                if (exists and voice.reason != "focus_failed"
                        and self.windows()[0] != voice.hwnd):
                    self._restore_voice(voice)
            except Exception as error:
                voice.error = str(error)
            try:
                self._combo((0x5B, 0x48), self.windows())
                voice.closed, voice.close_error = True, None
            except Exception as error:
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
            # state lock that it needs to finish the one closing Win+H.
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
