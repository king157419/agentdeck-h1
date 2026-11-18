"""Offline probe tests: every HID operation is a fake, including enumeration."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import deck_probe as probe


class FakeDevice:
    def __init__(self, layers=2, failure=None):
        self.layers = layers
        self.failure = failure
        self.sent = []
        self.opened = []
        self.closed = False

    def open_path(self, path):
        self.opened.append(path)
        if self.failure == "open":
            raise OSError("fake HID access denied")

    def write(self, report):
        assert len(report) == 33 and report[0] == 0
        assert report[1] in (0x01, 0x11, 0x12)
        self.sent.append(report)
        return 2 if self.failure == "write" else len(report)

    def read(self, count, timeout):
        assert (count, timeout) == (33, 500)
        if self.failure == "timeout":
            return []
        if self.failure == "unsupported":
            return [0xFF] * 32
        if self.failure == "short":
            return [self.sent[-1][1]]
        if self.failure == "mismatch":
            return [0x42] * 32
        command = self.sent[-1][1]
        response = bytearray(self.sent[-1][1:])
        if command == 0x01:
            response[1:3] = (12).to_bytes(2, "big")
        elif command == 0x11:
            response[1] = self.layers
        else:
            offset = int.from_bytes(response[1:3], "big")
            size = response[3]
            response[4:4 + size] = bytes((index % 256 for index in range(offset, offset + size)))
            if self.failure == "offset":
                response[2] ^= 1
        return bytes(response)

    def close(self):
        self.closed = True


def interface(page, product=probe.PID, vendor=probe.VID, usage=1):
    return {"vendor_id": vendor, "product_id": product, "usage_page": page,
            "usage": usage, "interface_number": 3, "path": b"fake-hid-path"}


def fake_hid(interfaces, device):
    def enumerate_hid(vid, pid):
        assert (vid, pid) == (probe.VID, 0)
        return interfaces
    return SimpleNamespace(enumerate=enumerate_hid, device=lambda: device)


def test_probe_unknown_interfaces_never_open():
    device = FakeDevice()
    interfaces = [interface(page) for page in (1, 12, 0xFF00)]
    interfaces += [interface(0xFF60, product=0x1234), interface(0xFF60, vendor=0x3837),
                   interface(0xFF60, usage=2)]
    output = []
    with patch.dict(sys.modules, {"hid": fake_hid(interfaces, device)}):
        assert probe.probe(output=output.append) == 0
    assert len([line for line in output if line.startswith("interface=")]) == len(interfaces)
    assert any("usage_page=0xFF00" in line for line in output)
    assert any("no reports were sent" in line for line in output)
    assert device.opened == [] and device.sent == [] and not device.closed


def test_probe_readonly_keymap():
    device, output = FakeDevice(), []
    with patch.dict(sys.modules, {"hid": fake_hid([interface(0xFF60)], device)}):
        assert probe.probe(rows=3, cols=5, output=output.append) == 0
    assert device.closed and device.opened == [b"fake-hid-path"]
    assert [packet[1] for packet in device.sent] == [1, 0x11, 0x12, 0x12, 0x12]
    assert [(int.from_bytes(p[2:4], "big"), p[4]) for p in device.sent[2:]] == [
        (0, 28), (28, 28), (56, 4)]
    keys = [line for line in output if line.startswith("layer=")]
    assert len(keys) == 30
    assert keys[0] == "layer=0 row=0 col=0 keycode=0x0001"
    assert keys[-1] == "layer=1 row=2 col=4 keycode=0x3A3B"


def test_probe_standard_qmk_usage():
    device, output = FakeDevice(), []
    with patch.dict(sys.modules, {"hid": fake_hid([interface(0xFF60, usage=0x61)], device)}):
        assert probe.probe(rows=1, cols=1, output=output.append) == 0
    assert device.closed and device.opened == [b"fake-hid-path"]
    assert any("layer=1 row=0 col=0 keycode=0x0203" in line for line in output)


def test_probe_transport_rejects_writes_and_bad_responses():
    for command in (0, 2, 4, 5, 0x13, 0xFF):
        device = FakeDevice()
        try:
            probe.ReadOnlyVIA(device).query(command)
            assert False, "write/non-allowlisted query accepted"
        except probe.ProbeError:
            assert device.sent == []
    for command, args in ((1, (0,)), (0x11, (0,)), (0x12, (0, 0, 29)),
                          (0x12, (0xFF, 0xFF, 2)), (0x12, ())):
        device = FakeDevice()
        try:
            probe.ReadOnlyVIA(device).query(command, args)
            assert False, "invalid arguments accepted"
        except probe.ProbeError:
            assert not device.sent
    for failure, message in (("timeout", "timed out"), ("unsupported", "does not support"),
                             ("short", "short"), ("mismatch", "does not match"),
                             ("write", "incomplete"), ("offset", "does not match")):
        device = FakeDevice(failure=failure)
        try:
            probe.ReadOnlyVIA(device).query(0x12, (0, 0, 2))
            assert False, "bad response accepted"
        except probe.ProbeError as error:
            assert message in str(error)
    device = FakeDevice()
    reader = device.read
    device.read = lambda *args: b"\0" + reader(*args)
    assert probe.ReadOnlyVIA(device).version() == 12


def test_probe_failures_close_and_exit_cleanly():
    for failure in ("open", "timeout", "unsupported", "short", "mismatch", "write"):
        device, output = FakeDevice(failure=failure), []
        with patch.dict(sys.modules, {"hid": fake_hid([interface(0xFF60)], device)}):
            assert probe.probe(rows=1, cols=6, output=output.append) == 0
        assert device.closed
        assert any("VIA read unavailable:" in line for line in output)
    output = []
    fake = SimpleNamespace(enumerate=lambda *args: (_ for _ in ()).throw(OSError("fake sandbox denial")))
    with patch.dict(sys.modules, {"hid": fake}):
        assert probe.probe(output=output.append) == 0
    assert "fake sandbox denial" in output[0]
    with patch.dict(sys.modules, {"hid": fake_hid([], FakeDevice())}):
        assert probe.probe(output=output.append) == 0
    assert any("No VID_4132 interfaces" in line for line in output)


def test_probe_matrix_definition_and_missing_dimensions():
    assert probe.matrix_dimensions() is None
    assert probe.matrix_dimensions(1, 6) == (1, 6)
    for rows, cols in ((None, 3), (3, None), (0, 2), (True, 2), (256, 2)):
        try:
            probe.matrix_dimensions(rows, cols)
            assert False, "invalid matrix accepted"
        except probe.ProbeError:
            pass
    with tempfile.TemporaryDirectory() as temp:
        definition = Path(temp) / "keyboard.json"
        data = {"vendorId": "0x4132", "productId": "0x2107", "matrix": {"rows": 1, "cols": 6}}
        definition.write_text(json.dumps(data), encoding="utf-8")
        assert probe.matrix_dimensions(definition=definition) == (1, 6)
        try:
            probe.matrix_dimensions(2, 3, definition)
            assert False, "conflicting definition accepted"
        except probe.ProbeError:
            pass
        data["productId"] = "0x1234"
        definition.write_text(json.dumps(data), encoding="utf-8")
        try:
            probe.matrix_dimensions(definition=definition)
            assert False, "wrong product definition accepted"
        except probe.ProbeError:
            pass
    device, output = FakeDevice(), []
    with patch.dict(sys.modules, {"hid": fake_hid([interface(0xFF60)], device)}):
        assert probe.probe(output=output.append) == 0
    assert [packet[1] for packet in device.sent] == [1, 0x11]
    assert any("does not report matrix dimensions" in line for line in output)
    assert device.closed
    for layers in (0, 255):
        device, output = FakeDevice(layers=layers), []
        with patch.dict(sys.modules, {"hid": fake_hid([interface(0xFF60)], device)}):
            probe.probe(rows=255, cols=255, output=output.append)
        assert device.closed and len(device.sent) == 2
        assert any("VIA read unavailable:" in line for line in output)


def test_probe_old_protocol_and_invalid_definition():
    device, output = FakeDevice(), []
    reader = device.read

    def old_protocol(*args):
        response = bytearray(reader(*args))
        if response[0] == 1:
            response[1:3] = (7).to_bytes(2, "big")
        return response

    device.read = old_protocol
    with patch.dict(sys.modules, {"hid": fake_hid([interface(0xFF60)], device)}):
        assert probe.probe(rows=1, cols=6, output=output.append) == 0
    assert device.closed and [packet[1] for packet in device.sent] == [1]
    assert any("protocol < 8" in line for line in output)
    device, output = FakeDevice(), []
    with patch.dict(sys.modules, {"hid": fake_hid([interface(0xFF60)], device)}):
        assert probe.probe(rows=1, output=output.append) == 0
    assert device.closed and [packet[1] for packet in device.sent] == [1, 0x11]
    assert any("provide both --rows and --cols" in line for line in output)


def main():
    tests = [value for key, value in sorted(globals().items()) if key.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("deck probe offline tests: %d groups passed" % len(tests))


if __name__ == "__main__":
    main()
