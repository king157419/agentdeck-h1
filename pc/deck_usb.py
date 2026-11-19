"""Read the deck's keyboard interface through WinUSB, without Windows key input.

Only verified eight-byte HID boot keyboard reports are decoded. USB libraries
are imported when opening the receiver, so report parsing remains offline.
"""
import ctypes
from ctypes import wintypes
import json
import logging
import subprocess
import threading
import time


VID, PID, INTERFACE = 0x4132, 0x2107, 0
READ_TIMEOUT_MS = 100
RECONNECT_SECONDS = 2
ZADIG_HINT = "请先用 Zadig 把 4132:2107 接口0 换成 WinUSB"
log = logging.getLogger("agent_deck.usb")


def foreground_hwnd():
    """Sample only the foreground handle, without querying or activating windows."""
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.argtypes = []
    user.GetForegroundWindow.restype = wintypes.HWND
    return user.GetForegroundWindow() or 0


def interface0_driver():
    """Read present interface-0 PnP metadata; unknown/absent must stay on USB.

    Get-PnpDevice -PresentOnly excludes stale registry entries for unplugged
    devices. This query never opens a USB endpoint or changes any driver.
    """
    script = (
        "$ErrorActionPreference='Stop'; "
        "Get-PnpDevice -PresentOnly | Where-Object { "
        "$_.InstanceId -match '^USB\\\\VID_4132&PID_2107&MI_00\\\\' } | "
        "ForEach-Object { (Get-PnpDeviceProperty -InstanceId $_.InstanceId "
        "-KeyName 'DEVPKEY_Device_Service').Data } | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=5, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        services = json.loads(result.stdout)
        if isinstance(services, str):
            services = [services]
        if isinstance(services, list) and services:
            names = {service.casefold() for service in services if isinstance(service, str)}
            if len(names) == 1 and len(services) == sum(isinstance(s, str) for s in services):
                driver = names.pop()
                return driver if driver in ("hidusb", "winusb") else None
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        log.debug("USB interface 0 driver metadata unavailable: %s", error)
    return None


def report_modifiers(bits):
    """Use this device's bits and fold left/right modifiers together."""
    return tuple(name for name, mask in (("ctrl", 0x11), ("shift", 0x22),
                                         ("alt", 0x44), ("win", 0x88))
                 if bits & mask)


class ReportState:
    """Diff boot reports into key transitions; duplicate reports produce none."""

    def __init__(self):
        self.pressed = set()
        self.modifier_bits = 0
        self.lengths = set()

    @staticmethod
    def _event(usage, down, modifier_bits, pressed, new_modifiers, modifier=False):
        modifiers = report_modifiers(modifier_bits)
        bare = "hid:0x%02X" % usage
        keys = (("+".join(modifiers) + "+" + bare, bare)
                if modifiers and modifiers == new_modifiers and not modifier
                else (bare,))
        return {"kind": "keyboard", "keys": keys, "down": down, "usage": usage,
                "modifiers": modifiers, "modifier_bits": modifier_bits,
                "modifier": modifier, "pressed": frozenset(pressed),
                "new_modifiers": new_modifiers}

    def feed(self, report):
        report = bytes(report)
        length = len(report)
        if length not in self.lengths:
            self.lengths.add(length)
            if length == 8:
                log.info("USB keyboard report length=8 (boot keyboard)")
            else:
                log.warning("USB keyboard report length=%d unsupported; only 8-byte boot "
                            "reports are supported (NKRO/report IDs are not guessed)", length)
        if length != 8:
            return []
        # A rollover/error report is not a release of the previous good state.
        if report[1] or any(usage in (1, 2, 3) for usage in report[2:]):
            log.debug("Ignoring invalid/rollover boot report: %s", report.hex())
            return []
        modifier_bits = report[0]
        pressed = set(report[2:]) - {0}
        # Factory macros send Ctrl in one report and the key in the next, so a
        # modifier stays "fresh" until a main key consumes it; a Ctrl still held
        # after Ctrl+Z must not turn a later knob F into Ctrl+F.
        current = report_modifiers(modifier_bits)
        previous_modifiers = report_modifiers(self.modifier_bits)
        fresh = getattr(self, "fresh", set()) & set(current)
        fresh |= {name for name in current if name not in previous_modifiers}
        new_modifiers = tuple(name for name in current if name in fresh)
        self.fresh = set() if pressed - self.pressed else fresh
        events = [self._event(usage, False, modifier_bits, pressed, new_modifiers)
                  for usage in sorted(self.pressed - pressed)]
        for bit in range(8):
            mask = 1 << bit
            if (self.modifier_bits ^ modifier_bits) & mask:
                events.append(self._event(0xE0 + bit, bool(modifier_bits & mask),
                                          modifier_bits, pressed, new_modifiers, modifier=True))
        events.extend(self._event(usage, True, modifier_bits, pressed, new_modifiers)
                      for usage in sorted(pressed - self.pressed))
        self.pressed, self.modifier_bits = pressed, modifier_bits
        return events


class USBInput:
    """Claim interface zero only; retry unavailable/disconnected devices."""

    def __init__(self, callback, foreground=None, monotonic=None):
        self.callback = callback
        self.foreground = foreground_hwnd if foreground is None else foreground
        self.monotonic = time.monotonic if monotonic is None else monotonic
        self.device = None
        self.endpoint = None
        self.state = ReportState()
        self.boot_protocol = False
        self._pending_report = None
        self._pending_context = None
        self._core = self._util = None
        self._claimed = False
        self._stop = threading.Event()
        self.heartbeat = None

    def open(self):
        if self.endpoint is not None:
            return
        try:
            import usb.core
            import usb.util
            import libusb_package

            self._core, self._util = usb.core, usb.util
            backend = libusb_package.get_libusb1_backend()
            if backend is None:
                raise RuntimeError("libusb-package backend is unavailable")
            self.device = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
            if self.device is None:
                raise OSError("USB 4132:2107 not found")
            # Do not set/reset the configuration: the other interfaces retain
            # their current drivers and configuration.
            configuration = self.device.get_active_configuration()
            interface = configuration[(INTERFACE, 0)]
            endpoint = next((ep for ep in interface
                             if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN
                             and usb.util.endpoint_type(ep.bmAttributes) == usb.util.ENDPOINT_TYPE_INTR), None)
            if endpoint is None:
                raise RuntimeError("USB interface 0 has no interrupt IN endpoint")
            usb.util.claim_interface(self.device, INTERFACE)
            self._claimed = True
            try:
                self.device.ctrl_transfer(0x21, 0x0B, 0, INTERFACE, timeout=READ_TIMEOUT_MS)
                self.boot_protocol = True
            except Exception as error:
                # SET_PROTOCOL is optional; do not invent a report layout when
                # the device rejects it. feed() checks the actual report size.
                log.warning("SET_PROTOCOL boot failed (%s); checking actual report lengths; "
                            "only 8-byte boot reports are supported", error)
            self.endpoint = endpoint
            # The Windows HID backend may allow claim_interface yet reject
            # interrupt reads. A first read distinguishes that from WinUSB;
            # idle timeout is healthy, and an actual first packet is retained.
            try:
                self._pending_report = endpoint.read(max(8, endpoint.wMaxPacketSize),
                                                     timeout=READ_TIMEOUT_MS)
                self._pending_context = self._report_context()
            except usb.core.USBTimeoutError:
                pass
            log.info("USB 4132:2107 interface 0 opened; interrupt IN=0x%02X; boot=%s",
                     endpoint.bEndpointAddress, self.boot_protocol)
        except BaseException as error:
            self.close()
            if isinstance(error, Exception):
                log.warning("%s (%s)", ZADIG_HINT, error)
            raise

    def close(self):
        device, claimed = self.device, self._claimed
        self.device = self.endpoint = None
        self._claimed = False
        self.boot_protocol = False
        self._pending_report = None
        self._pending_context = None
        self.state = ReportState()
        if device is None or self._util is None:
            return
        try:
            if claimed:
                self._util.release_interface(device, INTERFACE)
        except Exception as error:
            log.debug("USB interface 0 release failed: %s", error)
        finally:
            try:
                self._util.dispose_resources(device)
            except Exception as error:
                log.debug("USB resource disposal failed: %s", error)

    def stop(self):
        self._stop.set()

    def _report_context(self):
        context = {"t": self.monotonic()}
        snapshot = getattr(self.callback, "snapshot", None)
        if callable(snapshot):
            context["shown"] = snapshot()
        try:
            hwnd = self.foreground()
        except Exception as error:
            log.debug("USB foreground handle unavailable: %s", error)
            hwnd = 0
        context["hwnd"] = hwnd
        return context

    def run(self, *, reconnect=True):
        try:
            while not self._stop.is_set():
                if self.heartbeat is not None:
                    self.heartbeat()
                if self.endpoint is None:
                    try:
                        self.open()
                    except Exception:
                        if not reconnect:
                            raise
                        self._stop.wait(RECONNECT_SECONDS)
                        continue
                try:
                    if self._pending_report is not None:
                        report, self._pending_report = self._pending_report, None
                        context, self._pending_context = self._pending_context, None
                    else:
                        report = self.endpoint.read(max(8, self.endpoint.wMaxPacketSize),
                                                    timeout=READ_TIMEOUT_MS)
                        context = self._report_context()
                except self._core.USBTimeoutError:
                    continue
                except Exception as error:
                    if not reconnect:
                        raise
                    log.warning("USB keyboard read failed (%s); %s; reconnecting in %s seconds",
                                error, ZADIG_HINT, RECONNECT_SECONDS)
                    self.close()
                    self._stop.wait(RECONNECT_SECONDS)
                    continue
                for event in self.state.feed(report):
                    event.update(context)
                    self.callback(event)
        except KeyboardInterrupt:
            pass
        finally:
            self.close()
