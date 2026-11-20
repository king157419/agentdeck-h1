"""Own Alt only for a short Alt+Tab burst; importing never sends input."""
import ctypes
import logging
import math
import threading
import time


ALT = 0x12
SHIFT = 0x10
TAB = 0x09
ESC = 0x1B
RELEASE_SECONDS = .7
WATCHDOG_SECONDS = 5.0
SCANS = {ALT: 0x38, SHIFT: 0x2A, TAB: 0x0F, ESC: 0x01}
log = logging.getLogger("agentdeck.hub.window")


class WindowSwitcher:
    """Keep Alt down between detents, releasing only keys this object owns.

    ``sender`` accepts [(virtual_key, keyup_flag), ...] and returns the number
    inserted. Tests can substitute it and ``timer_factory`` without native I/O.
    """

    def __init__(self, windows, *, monotonic=None, timer_factory=None, sender=None, release_ms=700):
        if (isinstance(release_ms, bool) or not isinstance(release_ms, (int, float))
                or not math.isfinite(release_ms) or release_ms <= 0):
            raise ValueError("release_ms must be positive and finite")
        self.windows = windows
        self.release_seconds = release_ms / 1000.0
        self.monotonic = time.monotonic if monotonic is None else monotonic
        self.timer_factory = threading.Timer if timer_factory is None else timer_factory
        self.sender = self._send if sender is None else sender
        self._native = sender is None
        self._lock = threading.RLock()
        self._owned = []
        self._timer = None
        self._generation = 0
        self._deadline = 0.0
        self._started_at = 0.0
        self.position = 0
        self._maximum = None
        self._closed = False

    @property
    def active(self):
        return ALT in self._owned

    def _window_limit(self):
        enumerate_windows = getattr(self.windows, "windows", None)
        if callable(enumerate_windows):
            return max(0, len(enumerate_windows()) - 1)
        return None

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
            now = self.monotonic()
            if self.active and now >= self._started_at + WATCHDOG_SECONDS:
                self.release()
                return False
            if not self._owned and self._native:
                if getattr(self.windows, "_held_keys", ()) or any(
                        self.windows.user.GetAsyncKeyState(key) & 0x8000
                        for key in (SHIFT, 0x11, ALT, 0x5B, 0x5C, *range(0xA0, 0xA6))):
                    return False
            first = ALT not in self._owned
            maximum = self._window_limit() if first else self._maximum
            destination = 1 if first else self.position + (1 if direction == "next" else -1)
            if destination < 0 or maximum is not None and destination > maximum:
                if self.active:
                    # A clamped turn is still activity: retain the chooser
                    # until the user stops, subject to the total watchdog.
                    self._cancel_timer()
                    self._deadline = min(now + self.release_seconds,
                                         self._started_at + WATCHDOG_SECONDS)
                    try:
                        self._arm(self._deadline - now)
                    except BaseException:
                        self.release()
                        raise
                return False
            self._cancel_timer()
            transitions = [(ALT, 0)] if first else []
            reverse = direction == "prev" and not first
            if reverse:
                transitions.append((SHIFT, 0))
            transitions.extend(((TAB, 0), (TAB, 2)))
            if reverse:
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
            if first:
                self._started_at = now
                self._maximum = maximum
            self.position = destination
            self._deadline = min(now + self.release_seconds, self._started_at + WATCHDOG_SECONDS)
            try:
                self._arm(self._deadline - now)
            except BaseException:
                self.release()
                raise
            return True

    def back(self):
        """Confirm an open switcher; otherwise perform one complete Alt+Tab."""
        with self._lock:
            if self.active:
                return self.release()
            if not self.step("next"):
                return False
            return self.release()

    def cancel(self):
        with self._lock:
            if not self.active:
                return True
            # Keep possible Esc ownership if the native sender raises after a
            # partial insertion, just as step() does for Tab and Shift.
            self._owned.append(ESC)
            try:
                sent = self.sender([(ESC, 0), (ESC, 2)])
                if sent == 2:
                    self._owned.remove(ESC)
            except BaseException:
                self.release()
                raise
            released = self.release()
            return sent == 2 and released

    def release(self):
        with self._lock:
            self._cancel_timer()
            for attempt in range(2):
                keys = list(reversed(self._owned))
                if not keys:
                    self.position = 0
                    self._maximum = None
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
            else:
                self.position = 0
                self._maximum = None
            return not self._owned

    def close(self):
        with self._lock:
            self._closed = True
            return self.release()
