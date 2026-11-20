"""Hub keyboard input: prefer USB, observe the same device through Raw Input."""
import logging
import math
import threading
import time

from deck_usb import RECONNECT_SECONDS, ReportState


log = logging.getLogger("agentdeck.hub.keyboard")

# Bare usages are shared with ordinary keys on this device; modifiers make a
# different binding (for example Ctrl+F is a button, not a knob pulse).
KNOB_ROTATIONS = {
    binding: (number, direction)
    for number, pair in enumerate((("hid:0x09", "hid:0x16"),
                                   ("hid:0x15", "hid:0x13"),
                                   ("hid:0x2D", "hid:0x2E"),
                                   ("hid:0x30", "hid:0x2F")), 1)
    for binding, direction in zip(pair, (1, -1))
}


class KnobDetents:
    """Give the free-spinning encoders detents without queuing delayed steps."""

    def __init__(self, dividers=None):
        dividers = {} if dividers is None else dividers
        if (not isinstance(dividers, dict)
                or any(key not in ("1", "2", "3", "4") or type(value) is not int or value < 1
                       for key, value in dividers.items())):
            raise ValueError("knob_divider needs knob numbers 1..4 and positive integer values")
        self.dividers = {1: 4, 2: 3, 4: 3}
        self.dividers.update({int(key): value for key, value in dividers.items()})
        self._pulses = {}

    def accept(self, binding, received_at):
        rotation = KNOB_ROTATIONS.get(binding)
        if rotation is None:
            return True
        knob, direction = rotation
        state = self._pulses.get(knob)
        if state is None or received_at - state["last"] >= .250:
            state = {"direction": direction, "count": 0, "first": True,
                     "reverse_at": None, "step_at": float("-inf")}
            self._pulses[knob] = state
        state["last"] = received_at
        if direction != state["direction"]:
            reverse_at = state["reverse_at"]
            if reverse_at is None or received_at - reverse_at > .100:
                state["reverse_at"] = received_at
                return False
            state.update(direction=direction, count=0, reverse_at=None)
        else:
            state["reverse_at"] = None
        if knob == 3:
            return True
        state["count"] += 1
        threshold = 2 if state["first"] else self.dividers[knob]
        if state["count"] < threshold:
            return False
        state["count"] -= threshold
        state["first"] = False
        if received_at - state["step_at"] < .090:
            return False
        state["step_at"] = received_at
        return True


class ModifierTaps:
    """Recognize isolated USB modifier releases, never the prefix of a chord."""

    NAMES = {0xE0: "ctrl", 0xE4: "ctrl", 0xE1: "shift", 0xE5: "shift",
             0xE2: "alt", 0xE6: "alt"}

    def __init__(self):
        self.held = {}

    def feed(self, event):
        if event.get("reader", "USB") != "USB":
            self.held.clear()
            return None
        usage, down = event.get("usage"), event.get("down")
        if event.get("cancelled"):
            self.held.clear()
            return None
        if not event.get("modifier", usage is not None and usage >= 0xE0):
            if down or event.get("pressed"):
                for held in self.held.values():
                    held[1] = False
            return None
        timestamp = event.get("t", 0)
        if down:
            isolated = not self.held and not event.get("pressed")
            for held in self.held.values():
                held[1] = False
            self.held[usage] = [timestamp, isolated]
            return None
        held = self.held.pop(usage, None)
        if (held is not None and held[1] and not event.get("pressed")
                and 0 <= timestamp - held[0] <= .600 + 1e-9):
            return self.NAMES.get(usage)
        return None


# Windows virtual keys to USB keyboard usages. No mapping file is rewritten.
VKEY_USAGES = {**{0x41 + n: 0x04 + n for n in range(26)},
               **{0x31 + n: 0x1E + n for n in range(9)}, 0x30: 0x27,
               **{0x70 + n: 0x3A + n for n in range(12)},
               **{0x7C + n: 0x68 + n for n in range(12)},
               0x0D: 0x28, 0x1B: 0x29, 0x08: 0x2A, 0x09: 0x2B,
               0x20: 0x2C, 0xBD: 0x2D, 0xBB: 0x2E, 0xDB: 0x2F,
               0xDD: 0x30, 0xDC: 0x31, 0xBA: 0x33, 0xDE: 0x34,
               0xC0: 0x35, 0xBC: 0x36, 0xBE: 0x37, 0xBF: 0x38,
               0x14: 0x39, 0x2C: 0x46, 0x91: 0x47, 0x13: 0x48,
               0x2D: 0x49, 0x24: 0x4A, 0x21: 0x4B, 0x2E: 0x4C,
               0x23: 0x4D, 0x22: 0x4E, 0x27: 0x4F, 0x25: 0x50,
               0x28: 0x51, 0x26: 0x52, 0x90: 0x53, 0x6F: 0x54,
               0x6A: 0x55, 0x6D: 0x56, 0x6B: 0x57, 0x6E: 0x63,
               **{0x61 + n: 0x59 + n for n in range(9)}, 0x60: 0x62,
               0xE2: 0x64, 0x5D: 0x65,
               **{0xA0 + n: usage for n, usage in enumerate((0xE1, 0xE5,
                                                           0xE0, 0xE4, 0xE2, 0xE6))},
               0x5B: 0xE3, 0x5C: 0xE7}


def key_usage(event):
    vkey, scan, flags = event.get("vkey"), event.get("make_code", 0), event.get("flags", 0)
    if vkey == 0x10:
        return 0xE5 if scan == 0x36 else 0xE1
    if vkey in (0x11, 0x12):
        return (0xE0 if vkey == 0x11 else 0xE2) + (4 if flags & 2 else 0)
    if vkey == 0x0D and flags & 2:
        return 0x58
    return VKEY_USAGES.get(vkey)


def capture(callback, monotonic, age=0, received_at=None):
    if received_at is None:
        received_at = monotonic() - age
    context = {"t": received_at}
    snapshot_at = getattr(callback, "snapshot_at", None)
    snapshot = getattr(callback, "snapshot", None)
    if callable(snapshot_at):
        context["shown"] = snapshot_at(received_at)
        return context
    if callable(snapshot):
        context["shown"] = snapshot()
    return context


class RawKeys:
    """Translate filtered Raw Input transitions into USBKeys' existing contract."""

    def __init__(self, callback, monotonic=time.monotonic, reader=None):
        self.callback, self.monotonic = callback, monotonic
        self.reader = reader
        self.devices = {}
        self.unknown = {}
        self.pressed = {}
        self.modifiers = {}
        self.overflow = set()

    def __call__(self, event):
        handle = event.get("device")
        if event.get("kind") == "device_removed":
            self.release(handle)
            return
        if event.get("kind") != "keyboard" or not handle:
            return
        if (event.get("vkey") in (0, 0xFF) or event.get("make_code") == 0xFF
                or event.get("flags", 0) & 4):
            return
        age = event.get("age", 0)
        if (isinstance(age, bool) or not isinstance(age, (int, float))
                or not math.isfinite(age) or age < 0):
            return
        received_at = event.get("t")
        if received_at is not None and (isinstance(received_at, bool)
                or not isinstance(received_at, (int, float)) or not math.isfinite(received_at)):
            return
        context = capture(self.callback, self.monotonic, age, received_at)
        usage = key_usage(event)
        state = self.devices.setdefault(handle, ReportState())
        unknown = self.unknown.setdefault(handle, set())
        down = event.get("down", not event.get("flags", 0) & 1)
        if usage is None:
            token = (event.get("vkey"), event.get("make_code"), event.get("flags", 0) & 6)
            (unknown.add if down else unknown.discard)(token)
            return
        pressed = self.pressed.setdefault(handle, set())
        bits = self.modifiers.get(handle, 0)
        if usage >= 0xE0:
            mask = 1 << (usage - 0xE0)
            bits = bits | mask if down else bits & ~mask
        else:
            (pressed.add if down else pressed.discard)(usage)
        self.modifiers[handle] = bits
        # Keep every held key for USBKeys' single-key guard even past boot 6KRO.
        if handle in self.overflow:
            if pressed or bits:
                return
            self.overflow.discard(handle)
        report = bytes([bits, 0] + sorted(pressed))
        if len(pressed) <= 6:
            report += bytes(6 - len(pressed))
        else:
            # ReportState intentionally ignores non-boot packets. Release old
            # holds, then wait for a fresh single key after the chord is up.
            self.overflow.add(handle)
            for release in state.feed(bytes(8)):
                release.update(context)
                release["device"] = handle
                self._emit(release)
            return
        for normalized in state.feed(report):
            normalized.update(context)
            normalized["device"] = handle
            if unknown:
                normalized["pressed"] |= frozenset(unknown)
            self._emit(normalized)

    def _emit(self, event):
        if self.reader is not None:
            event["reader"] = self.reader
        self.callback(event)

    def release(self, handle=None):
        handles = list(self.devices) if handle is None else [handle]
        for device in handles:
            state = self.devices.pop(device, None)
            self.unknown.pop(device, None)
            self.pressed.pop(device, None)
            self.modifiers.pop(device, None)
            self.overflow.discard(device)
            if state is not None:
                context = capture(self.callback, self.monotonic)
                for event in state.feed(bytes(8)):
                    event.update(context)
                    event["device"] = device
                    self._emit(event)


class KeyboardInput:
    """One thread dispatches both readers; USB discovery never blocks Raw Input."""

    def __init__(self, callback, monotonic=None, usb_factory=None, raw_factory=None):
        if usb_factory is None:
            from deck_usb import USBInput
            usb_factory = USBInput
        if raw_factory is None:
            from deck_input import RawInput
            raw_factory = RawInput
        self.callback = callback
        self.monotonic = time.monotonic if monotonic is None else monotonic
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.raw = None
        self.heartbeat = None
        self.usb_pressed = {}
        self.raw_factory = raw_factory
        # The callback wrapper also exposes the snapshot needed for pending USB
        # probe packets: their request identity belongs to receipt time.
        self.usb = usb_factory(self, monotonic=self.monotonic)
        if self.usb is not None:
            self.usb.heartbeat = self._beat
        self.raw_keys = RawKeys(callback, self.monotonic, reader="Raw Input")
        self._usb_ready = False
        self._next_probe = 0
        self._probe_thread = None
        self._probe_state = None
        self.mode = None  # "usb" while reading WinUSB directly, "raw" for Raw Input
        self.driver = None  # last interface-0 driver seen by the read-only probe

    def reader_mode(self):
        """'usb', 'raw' (keys also type letters), 'absent' (no keyboard) or None."""
        if self.mode == "usb":
            return "usb"
        if self.mode == "raw":
            return "raw" if self.driver == "hidusb" else "absent" if self.driver is None else None
        return None

    def _beat(self):
        if self.heartbeat is not None:
            self.heartbeat()

    def snapshot(self):
        snapshot = getattr(self.callback, "snapshot", None)
        return snapshot() if callable(snapshot) else {}

    def __call__(self, event):
        usage = event.get("usage")
        if event.get("down"):
            self.usb_pressed[usage] = dict(event)
        else:
            self.usb_pressed.pop(usage, None)
        self.callback(dict(event, reader="USB"))

    def _release_usb(self):
        held, self.usb_pressed = self.usb_pressed, {}
        context = capture(self.callback, self.monotonic)
        for event in held.values():
            event.update(context, down=False, pressed=frozenset(), cancelled=True)
            self.callback(dict(event, reader="USB"))

    def stop(self):
        self._stop.set()
        self.usb.stop()
        with self._lock:
            if self.raw is not None:
                self.raw.stop()

    def _check_usb(self):
        from deck_usb import interface0_driver
        try:
            driver = interface0_driver()
            self.driver = driver
            if driver != "winusb":
                state = ("driver", driver)
                if state != self._probe_state:
                    log.info("USB probe skipped: interface 0 driver=%s; using Raw Input", driver or "unknown/absent")
                self._probe_state = state
                return
            if self._stop.is_set():
                return
            self.usb.open()
            self._probe_state = ("driver", "winusb")
        except Exception as error:
            state = ("error", str(error))
            if state != self._probe_state:
                log.info("USB keyboard unavailable (%s); using Raw Input", error)
            self._probe_state = state
            return
        if self._stop.is_set():
            self.usb.close()
        else:
            self._usb_ready = True

    def _probe_usb(self):
        self._beat()
        if self._stop.is_set():
            self.raw.stop()
            return
        if self._usb_ready:
            self.raw.stop()
            return
        if (self.monotonic() < self._next_probe
                or self._probe_thread is not None and self._probe_thread.is_alive()):
            return
        self._next_probe = self.monotonic() + RECONNECT_SECONDS
        self._probe_thread = threading.Thread(target=self._check_usb, name="AgentDeck USB probe", daemon=True)
        self._probe_thread.start()

    def run(self):
        try:
            while not self._stop.is_set():
                self._beat()
                if self._probe_thread is not None and self._probe_thread.is_alive():
                    self._stop.wait(.01)
                    continue
                try:
                    if not self._usb_ready:
                        self._check_usb()
                    if not self._usb_ready:
                        raise OSError("WinUSB input not ready")
                    self._usb_ready = False
                    if self._stop.is_set():
                        break
                    log.info("读键方式：USB 直读 (4132:2107 interface 0)")
                    self.mode = "usb"
                    self.usb.run(reconnect=False)
                    if self._stop.is_set():
                        break
                except Exception as error:
                    log.debug("USB input ended (%s); trying Raw Input", error)
                finally:
                    self.mode = None
                    self._release_usb()
                if self._stop.is_set():
                    break
                try:
                    self._next_probe = self.monotonic() + RECONNECT_SECONDS
                    raw = self.raw_factory(self.raw_keys, transitions=True, poll=self._probe_usb,
                                           monotonic=self.monotonic)
                    with self._lock:
                        self.raw = raw
                        if self._stop.is_set():
                            raw.stop()
                    if not self._stop.is_set():
                        log.info("读键方式：Raw Input (VID_4132 / PID_2107)")
                        self.mode = "raw"
                        raw.run()
                except Exception as error:
                    log.warning("Raw Input unavailable (%s); retrying keyboard input", error)
                finally:
                    self.mode = None
                    with self._lock:
                        self.raw = None
                    self.raw_keys.release()
                if not self._usb_ready:
                    self._stop.wait(RECONNECT_SECONDS)
        finally:
            # A stuck native discovery/open must not freeze shutdown or race
            # close(). Its daemon worker closes its own result after stop.
            if self._probe_thread is None or not self._probe_thread.is_alive():
                self.usb.close()
            self._release_usb()
            self.raw_keys.release()
