"""Own Alt only for a short Alt+Tab burst; importing never sends input."""
import ctypes
import logging
import threading
import time


ALT = 0x12
SHIFT = 0x10
TAB = 0x09
RELEASE_SECONDS = 0.9
SCANS = {ALT: 0x38, SHIFT: 0x2A, TAB: 0x0F}
log = logging.getLogger("agentdeck.hub.window")


class WindowSwitcher:
    """Keep Alt down between detents, releasing only keys this object owns.

    ``sender`` accepts [(virtual_key, keyup_flag), ...] and returns the number
    inserted. Tests can substitute it and ``timer_factory`` without native I/O.
    """

    def __init__(self, windows, *, monotonic=None, timer_factory=None, sender=None):
        self.windows = windows
        self.monotonic = time.monotonic if monotonic is None else monotonic
        self.timer_factory = threading.Timer if timer_factory is None else timer_factory
        self.sender = self._send if sender is None else sender
        self._native = sender is None
        self._lock = threading.RLock()
        self._owned = []
        self._timer = None
        self._generation = 0
        self._deadline = 0.0
        self._closed = False

    def _send(self, transitions):
        events = self.windows._events(transitions)
        # Hardware scan codes also let hooks recognize the modifier consistently.
        for event, (key, flags) in zip(events, transitions):
            event.ki.wVk = 0
            event.ki.wScan = SCANS[key]
            event.ki.dwFlags = flags | 0x0008  # KEYEVENTF_SCANCODE
        return self.windows.user.SendInput(len(events), events,
                                           ctypes.sizeof(events._type_))

    def _cancel_timer(self):
        self._generation += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _arm(self, delay):
        generation = self._generation
        self._timer = self.timer_factory(delay, lambda: self._timeout(generation))
        self._timer.daemon = True
        self._timer.start()

    def _timeout(self, generation):
        with self._lock:
            if generation != self._generation or self._closed:
                return
            remaining = self._deadline - self.monotonic()
            if remaining > 0:
                self._arm(remaining)
            else:
                self.release()

    def step(self, direction):
        if direction not in ("next", "prev"):
            raise ValueError("window needs next or prev")
        with self._lock:
            if self._closed:
                raise RuntimeError("window switcher is closed")
            if any(key != ALT for key in self._owned) and not self.release():
                return False
            if not self._owned and self._native:
                if getattr(self.windows, "_held_keys", ()) or any(
                        self.windows.user.GetAsyncKeyState(key) & 0x8000
                        for key in (SHIFT, 0x11, ALT, 0x5B, 0x5C, *range(0xA0, 0xA6))):
                    return False
            self._cancel_timer()
            transitions = [] if ALT in self._owned else [(ALT, 0)]
            if direction == "prev":
                transitions.append((SHIFT, 0))
            transitions.extend(((TAB, 0), (TAB, 2)))
            if direction == "prev":
                transitions.append((SHIFT, 2))
            original = list(self._owned)
            # If SendInput raises after insertion, cleanup still knows every key
            # that could have gone down, including a partially inserted Tab tap.
            self._owned = list(dict.fromkeys(original + [key for key, flags in transitions if not flags]))
            try:
                sent = self.sender(transitions)
            except BaseException:
                self.release()
                raise
            self._owned = original
            for key, flags in transitions[:sent]:
                if flags:
                    if key in self._owned:
                        self._owned.remove(key)
                elif key not in self._owned:
                    self._owned.append(key)
            if sent != len(transitions):
                self.release()
                return False
            self._deadline = self.monotonic() + RELEASE_SECONDS
            try:
                self._arm(RELEASE_SECONDS)
            except BaseException:
                self.release()
                raise
            return True

    def release(self):
        with self._lock:
            self._cancel_timer()
            for attempt in range(2):
                keys = list(reversed(self._owned))
                if not keys:
                    return True
                try:
                    sent = self.sender([(key, 2) for key in keys])
                except BaseException:
                    if attempt:
                        log.exception("Could not release window-switch keys")
                    continue
                for key in keys[:sent]:
                    self._owned.remove(key)
            if self._owned:
                log.error("Window-switch key release incomplete: %s", self._owned)
            return not self._owned

    def close(self):
        with self._lock:
            self._closed = True
            return self.release()
