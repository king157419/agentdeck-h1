"""Optional pynput adapter for macOS; callbacks only enqueue hotkey events."""
import importlib
import queue
import threading
import time


class PynputHotkeys:
    """Implement HotkeyInput's queue API without blocking the listener thread."""

    def __init__(self, *, keyboard=None, monotonic=None):
        if keyboard is None:
            try:
                keyboard = importlib.import_module("pynput.keyboard")
            except Exception as error:
                raise OSError("macOS hotkeys disabled: optional pynput is unavailable (%s); "
                              "install pynput in this Python environment to enable hotkeys" % error) from error
        self.keyboard = keyboard
        self.monotonic = time.monotonic if monotonic is None else monotonic
        self.events = queue.Queue()
        self.bindings = {}
        self.held = set()
        self.modifiers = {}
        self.lock = threading.Lock()
        self.lifecycle = threading.Lock()
        self.stopped = threading.Event()
        self.listener = None
        for name, mask in (("ctrl", 2), ("shift", 4), ("alt", 1), ("cmd", 8)):
            for suffix in ("", "_l", "_r"):
                key = getattr(keyboard.Key, name + suffix, None)
                if key is not None:
                    self.modifiers[key] = mask

    def create_queue(self):
        # Registration finishes before the listener is started by next_event().
        return 1

    def register(self, identity, binding):
        key = getattr(self.keyboard.Key, "f%d" % (binding.vkey - 0x7C + 13), None)
        if key is None:
            return False  # Darwin pynput currently exposes F1..F20 only.
        with self.lock:
            self.bindings[identity] = (key, binding.modifiers)
        return True

    def unregister(self, identity):
        with self.lock:
            self.bindings.pop(identity, None)
            finished = not self.bindings
        if finished:
            self.wake(1)

    def _press(self, key):
        if key is None or self.stopped.is_set():
            return
        with self.lock:
            if key in self.held:
                return
            self.held.add(key)
            mask = 0
            for held in self.held:
                mask |= self.modifiers.get(held, 0)
            for identity, (main, expected) in self.bindings.items():
                if key == main and mask == expected:
                    self.events.put((identity, self.monotonic()))

    def _release(self, key):
        with self.lock:
            self.held.discard(key)

    def _start(self):
        with self.lifecycle:
            if self.listener is not None or self.stopped.is_set():
                return
            if not getattr(self.keyboard.Listener, "IS_TRUSTED", True):
                raise OSError("macOS hotkeys disabled: allow this Python/terminal in "
                              "System Settings > Privacy & Security > Accessibility / Input Monitoring")
            try:
                self.listener = self.keyboard.Listener(on_press=self._press, on_release=self._release)
                self.listener.start()
            except Exception as error:
                raise OSError("macOS hotkeys disabled: pynput listener failed (%s); check "
                              "Accessibility / Input Monitoring permissions" % error) from error

    def next_event(self):
        with self.lock:
            if not self.bindings:
                return None
        self._start()
        while not self.stopped.is_set():
            try:
                event = self.events.get(timeout=0.1)
            except queue.Empty:
                if not self.listener.is_alive():
                    try:
                        self.listener.join(timeout=0)
                    except Exception as error:
                        raise OSError("macOS hotkey listener stopped: %s" % error) from error
                    raise OSError("macOS hotkey listener stopped; check Accessibility / Input Monitoring permissions")
                continue
            if event is None:
                return None
            identity, pressed_at = event
            return identity, self.monotonic() - pressed_at
        return None

    def modifiers_down(self):
        with self.lock:
            return any(key in self.modifiers for key in self.held)

    def wake(self, thread_id):
        self.stopped.set()
        self.events.put(None)
        with self.lifecycle:
            listener = self.listener
        if listener is not None:
            try:
                listener.stop()
            except Exception as error:
                raise OSError("macOS hotkey listener cleanup failed: %s" % error) from error
