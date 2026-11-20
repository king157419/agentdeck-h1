"""Platform hotkey input; importing this module has no native effects."""
import ctypes
from dataclasses import dataclass
import logging
import os
import re
import sys
import threading

from deck_input import MSG


MODIFIERS = {"ctrl": 0x0002, "shift": 0x0004, "alt": 0x0001}
MOD_NOREPEAT = 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
MAX_EVENT_AGE = 1.0
# WM_HOTKEY timestamps use Windows' coarse tick clock. Attribute an ambiguous
# message to the earlier instant, so a pre-switch press cannot target its successor.
WINDOWS_TIME_UNCERTAINTY = .016
log = logging.getLogger("agentdeck.hub.hotkey")


@dataclass(frozen=True)
class Binding:
    name: str
    modifiers: int
    vkey: int
    action: str


def parse_hotkeys(config):
    """Parse the top-level hotkey section, rejecting normalized duplicates."""
    if not isinstance(config, dict) or not isinstance(config.get("hotkey"), dict):
        raise ValueError("hotkey configuration needs a hotkey object")
    bindings = []
    seen = set()
    for key, action in config["hotkey"].items():
        if not isinstance(key, str) or not isinstance(action, str) or not action.strip():
            raise ValueError("hotkeys need key names and nonempty action strings")
        parts = [part.strip().lower() for part in key.split("+")]
        if not re.fullmatch(r"f(?:1[3-9]|2[0-4])", parts[-1]):
            raise ValueError("hotkey must end with F13..F24: %r" % key)
        modifiers = parts[:-1]
        if (len(modifiers) != len(set(modifiers))
                or any(part not in MODIFIERS for part in modifiers)):
            raise ValueError("hotkey modifiers must be Ctrl, Shift or Alt: %r" % key)
        mask = sum(MODIFIERS[part] for part in modifiers)
        vkey = 0x7C + int(parts[-1][1:]) - 13
        identity = (mask, vkey)
        if identity in seen:
            raise ValueError("duplicate hotkey: %r" % key)
        seen.add(identity)
        name = "+".join([part for part in MODIFIERS if part in modifiers] + [parts[-1].upper()])
        bindings.append(Binding(name, mask, vkey, action.strip()))
    return bindings


class HotkeyKeys:
    """Use Hub's shared action path, keeping decisions tied to the seen request."""

    def __init__(self, hub):
        self.hub = hub

    def snapshot(self, received_at=None):
        if hasattr(self.hub, "input_snapshot"):
            return self.hub.input_snapshot(received_at)
        return dict(self.hub.rendered_request)

    def dispatch(self, binding, shown, *, received_at=None):
        received_at = self.hub.monotonic() if received_at is None else received_at
        action = binding.action
        try:
            with self.hub.lock:
                if action == "voice_toggle":
                    desktop = self.hub.desktop
                    action = "voice_up" if desktop is not None and desktop.voice_active else "voice_down"
                payload = {"action": action}
                if action in ("approve", "deny"):
                    # Keep the snapshot captured when the key was received,
                    # including through modifier-release waits and lock contention.
                    payload.update(shown or {"request_id": None, "nonce": None})
                elif action == "interrupt":
                    request_id = shown["request_id"] if shown else None
                    if self.hub.displayed_request_id != request_id:
                        log.warning("Hotkey %s ignored: displayed request changed", binding.name)
                        return False
                    payload["request_id"] = request_id
            # Outside the lock: Hub.action releases it before window/input effects,
            # and the interrupt request id is still revalidated there.
            result = self.hub.action(payload, source="hotkey", received_at=received_at)
            log.info("Hotkey %s -> %s", binding.name, result)
            self._note(action, result=result)
            return True
        except (ValueError, RuntimeError) as error:
            log.warning("Hotkey %s action failed: %s", binding.name, error)
            self._note(action, error=error)
            return False

    def _note(self, action, result=None, error=None):
        note = getattr(self.hub, "note_input", None)
        if not callable(note):
            return
        try:
            from hub import Hub, describe_input
            if isinstance(self.hub, Hub):
                self.hub.note_action(action, result, error)
            else:
                note(*describe_input(action, result, error))
        except Exception as failure:
            log.debug("Hotkey feedback unavailable: %s", failure)


class Win32Hotkeys:
    """Small native adapter; all HWND and message values retain pointer width."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("global hotkeys require Windows")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        declarations = {
            "RegisterHotKey": ([ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32], ctypes.c_int),
            "UnregisterHotKey": ([ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
            "PeekMessageW": ([ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32], ctypes.c_int),
            "GetMessageW": ([ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32], ctypes.c_int),
            "PostThreadMessageW": ([ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_ssize_t], ctypes.c_int),
            "GetAsyncKeyState": ([ctypes.c_int], ctypes.c_int16),
        }
        for name, (arguments, result) in declarations.items():
            method = getattr(self.user, name)
            method.argtypes, method.restype = arguments, result
        self.kernel.GetCurrentThreadId.argtypes = []
        self.kernel.GetCurrentThreadId.restype = ctypes.c_uint32
        self.kernel.GetTickCount.argtypes = []
        self.kernel.GetTickCount.restype = ctypes.c_uint32

    def create_queue(self):
        message = MSG()
        self.user.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
        return self.kernel.GetCurrentThreadId()

    def register(self, identity, binding):
        return bool(self.user.RegisterHotKey(None, identity, binding.modifiers | MOD_NOREPEAT, binding.vkey))

    def unregister(self, identity):
        if not self.user.UnregisterHotKey(None, identity):
            raise ctypes.WinError(ctypes.get_last_error())

    def next_event(self):
        message = MSG()
        result = self.user.GetMessageW(ctypes.byref(message), None, 0, 0)
        if result == -1:
            raise ctypes.WinError(ctypes.get_last_error())
        if result == 0:
            return None
        age = ((self.kernel.GetTickCount() - message.time) & 0xFFFFFFFF) / 1000.0
        age += WINDOWS_TIME_UNCERTAINTY
        return (int(message.wParam), age) if message.message == WM_HOTKEY else (0, age)

    def modifiers_down(self):
        return any(self.user.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12, 0x5B, 0x5C))

    def wake(self, thread_id):
        if not self.user.PostThreadMessageW(thread_id, WM_QUIT, 0, 0):
            raise ctypes.WinError(ctypes.get_last_error())


class HotkeyInput:
    """Run on one dedicated thread; stop() may be called from any thread."""

    def __init__(self, hub, mapping, *, api=None, monotonic=None):
        self.bindings = parse_hotkeys(mapping)
        self.keys = HotkeyKeys(hub)
        self.api = api
        self.monotonic = hub.monotonic if monotonic is None else monotonic
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.thread_id = None
        self.last_dispatch_finished = float("-inf")

    def run(self):
        registered = {}
        try:
            with self.lock:
                if self.stopped.is_set():
                    return
                if self.api is None:
                    if sys.platform == "darwin":
                        from hub_hotkey_mac import PynputHotkeys
                        self.api = PynputHotkeys(monotonic=self.monotonic)
                    else:
                        self.api = Win32Hotkeys()
                if hasattr(self.api, "snapshot"):
                    self.api.snapshot = self.keys.snapshot
                self.thread_id = self.api.create_queue()
            for identity, binding in enumerate(self.bindings, 1):
                if self.stopped.is_set():
                    break
                try:
                    if not self.api.register(identity, binding):
                        raise OSError("shortcut is unavailable or already registered")
                    registered[identity] = binding
                except OSError as error:
                    log.warning("Hotkey %s unavailable: %s", binding.name, error)
            while not self.stopped.is_set():
                event = self.api.next_event()
                if event is None:
                    break
                identity, age = event[:2]
                binding = registered.get(identity)
                if binding is None or not 0 <= age <= MAX_EVENT_AGE:
                    continue
                received_at = self.monotonic()
                if (binding.action in ("approve", "deny", "interrupt")
                        and received_at - age <= self.last_dispatch_finished):
                    # A previous action can advance the displayed queue. Do not
                    # apply decisions already waiting in Windows to its successor.
                    log.warning("Hotkey %s ignored: queued before previous action completed", binding.name)
                    continue
                shown = event[2] if len(event) > 2 else self.keys.snapshot(received_at - age)
                # A Ctrl+prompt shortcut must release Ctrl before guarded paste.
                # Bound this wait and use the original request id throughout.
                try:
                    while self.api.modifiers_down() and not self.stopped.is_set():
                        if age + self.monotonic() - received_at >= MAX_EVENT_AGE:
                            break
                        self.stopped.wait(0.01)
                    if (not self.stopped.is_set() and not self.api.modifiers_down()
                            and age + self.monotonic() - received_at <= MAX_EVENT_AGE):
                        self.keys.dispatch(binding, shown, received_at=received_at - age)
                finally:
                    # A failed action or modifier timeout can also have waited
                    # across a display change. Its queued decisions are stale.
                    self.last_dispatch_finished = self.monotonic()
        except OSError as error:
            log.warning("Hotkey input stopped: %s", error)
        finally:
            for identity, binding in registered.items():
                try:
                    self.api.unregister(identity)
                except OSError as error:
                    log.warning("Hotkey %s cleanup failed: %s", binding.name, error)
            with self.lock:
                self.thread_id = None

    def stop(self):
        self.stopped.set()
        with self.lock:
            if self.thread_id is not None:
                try:
                    self.api.wake(self.thread_id)
                except OSError as error:
                    log.warning("Could not wake hotkey input: %s", error)
