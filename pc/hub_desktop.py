"""Platform-dispatched desktop effects; imports never access native windows."""
import ctypes
from dataclasses import dataclass, field
from datetime import datetime
import logging
from pathlib import Path
import sys
import threading
import time
import uuid

if sys.platform == "win32":
    from ctypes import wintypes
    from deck_windows import INPUT, KEYBDINPUT, WindowControl


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
            return (bool(keys) and not getattr(self, "_held_keys", ())
                    and not any(self.user.GetAsyncKeyState(key) & 0x8000
                                for key in set(modifiers + keys))
                    and self() == expected)

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
            for event, (key, flags) in zip(events, transitions):
                event.type = 1  # INPUT_KEYBOARD
                extended = key in (0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27,
                                   0x28, 0x2C, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D,
                                   0x6F, 0x90, 0xA3, 0xA5)
                event.ki = KEYBDINPUT(key, 0, flags | int(extended), 0, 0)
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

    def __new__(cls, *args, **kwargs):
        if cls is DesktopEffects and sys.platform == "darwin":
            from hub_desktop_mac import MacDesktopEffects
            return object.__new__(MacDesktopEffects)
        return object.__new__(cls)

    def __init__(self, windows=None, *, clipboard=None, capture=None,
                 shots_dir=None, now=None, sleeper=None, monotonic=None,
                 voice_wait=None, dictation_shortcut=None):
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
                or mode not in ("toggle", "hold")):
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

    def _focus(self, session, sessions):
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
        # Reset before the outer foreground check too: a rejected attempt must
        # never inherit delivery information from the previous toggle.
        if hasattr(self.windows, "_combo_triggered"):
            self.windows._combo_triggered = False
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

    def _voice_shortcut(self, expected):
        self._combo(self._dictation_keys, expected)

    def interrupt(self, session, sessions):
        self._key(0x1B, self._focus(session, sessions))
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
            window = self._focus(session, sessions)
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
        self._paste(str(path), self._focus(session, sessions))
        return str(path)

    def prompt(self, session, sessions, text):
        if not isinstance(text, str) or not text:
            raise ValueError("prompt text must be a nonempty string")
        expected = self._focus(session, sessions)
        self._paste(text, expected)
        self.sleep(0.05)
        self._key(0x0D, expected)
        return True
