"""Offline only: synthetic geometry, fake HID and fake configuration backend.

These fixtures do not establish the connected keyboard's protocol or layout.
"""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import deck_keymap as km


def snapshot():
    # Deliberately synthetic: col 0 models four encoder push switches.
    return {"schema_version": 1, "device": {"vendor_id": km.VID, "product_id": km.PID},
            "matrix": {"rows": 4, "cols": 6},
            "ordinary_keys": [[row, col] for row in range(4) for col in range(1, 6)],
            "keymap": [[[4 + layer * 32 + row * 6 + col for col in range(6)]
                        for row in range(4)] for layer in range(3)],
            "encoders": [[{"cw": 0x00A8, "ccw": 0x00A9, "press": 0x0028}
                          for _ in range(4)] for _ in range(3)]}


class FakeBackend:
    def __init__(self, failure=None):
        self.state = snapshot()
        self.writes = []
        self.failure = failure
        self.failed = False
        self.reads = 0

    def snapshot(self):
        self.reads += 1
        if self.failure == "read" and not self.failed and self.writes:
            self.failed = True
            raise OSError("fake read timeout")
        return copy.deepcopy(self.state)

    def write(self, location, value):
        self.writes.append((location, value))
        if self.failure == "ignore" and not self.failed:
            self.failed = True
            return
        kind, layer, first, second = location
        if kind == "key":
            self.state["keymap"][layer][first][second] = value
        else:
            self.state["encoders"][layer][first][second] = value
        if len(self.writes) == 3 and self.failure in ("ack", "interrupt") and not self.failed:
            self.failed = True
            if self.failure == "interrupt":
                raise KeyboardInterrupt("fake interruption after write")
            raise OSError("fake lost ACK after write")
        if len(self.writes) == 10 and self.failure == "collateral":
            self.state["keymap"][0][0][0] = 0x1234
        if self.failure == "rollback" and len(self.writes) >= 10:
            self.state["keymap"][0][0][1] = 0x5678

    def set_key(self, layer, row, col, value):
        self.write(("key", layer, row, col), value)

    def set_encoder(self, layer, index, direction, value):
        self.write(("encoder", layer, index, direction), value)


class FakeDevice:
    def __init__(self, failure=None):
        self.sent = []
        self.failure = failure

    def write(self, report):
        self.sent.append(bytes(report))
        return 1 if self.failure == "write" else len(report)

    def read(self, size, timeout):
        assert (size, timeout) == (33, 1000)
        if self.failure == "timeout":
            return []
        response = bytearray(self.sent[-1][1:])
        if response[0] == 0x0B:
            response[1:3] = b"\x00\x09"
        elif response[0] == 0x0A:
            response[4:6] = b"\x01\x1D"
        if self.failure == "echo":
            response[1] ^= 1
        return response


def expect_error(function, *args, contains=None, **kwargs):
    try:
        function(*args, **kwargs)
    except (ValueError, OSError) as error:
        if contains:
            assert contains in str(error), str(error)
        return str(error)
    raise AssertionError("expected an error")


def test_vendor_report_encoding():
    assert km.encode_report(0x0B) == bytes([0, 11] + [0] * 31)
    assert km.encode_report(0x0A, (2, 3, 4)) == bytes([0, 10, 2, 3, 4] + [0] * 28)
    assert km.encode_report(0x10, (0, 1, 2, 0, 0x68)) == bytes([0, 16, 0, 1, 2, 0, 104] + [0] * 26)
    assert km.encode_report(7, (0x01, 0x20, 28))[:5] == bytes([0, 7, 1, 32, 28])
    for command, args in ((1, ()), (4, ()), (0x11, ()), (12, ()), (0x0A, (1, 2)),
                          (0x10, (1, 2, 3)), (7, (0, 0, 0)), (7, (0, 0, 29)),
                          (7, (255, 255, 2))):
        expect_error(km.encode_report, command, args)


def test_vendor_response_decoding():
    request = km.encode_report(0x0A, (0, 1, 2))
    response = bytes([10, 0, 1, 2, 0, 104] + [0] * 26)
    assert km.decode_response(request, response) == response
    assert km.decode_response(request, b"\0" + response) == response
    for bad in (b"", response[:-1], b"\1" + response, bytes([0xFF]) + response[1:],
                response[:2] + b"\x02" + response[3:]):
        expect_error(km.decode_response, request, bad)
    request = km.encode_report(0x10, (0, 1, 2, 0, 104))
    expect_error(km.decode_response, request, response[:5] + b"\x69" + response[6:])


def test_vendor_transport_read_only_and_errors():
    device = FakeDevice()
    via = km.VendorVIA(device)
    assert via.word(0x0B) == 9
    assert via.key(0, 1, 2) == 0x011D
    count = len(device.sent)
    expect_error(via.set_key, 0, 1, 2, 0x68, contains="not enabled")
    assert len(device.sent) == count
    via.write_enabled = True
    via.set_key(0, 1, 2, 0x68)
    for failure in ("write", "timeout", "echo"):
        expect_error(km.VendorVIA(FakeDevice(failure)).key, 0, 1, 2)


def test_plan_changes_exactly_eight_keys_and_first_encoder():
    original = snapshot()
    target = km.plan_remap(original)
    assert original == snapshot()
    delta = list(km.changes(original, target))
    assert len(delta) == 10
    assert [pos for pos, _, _ in delta[:8]] == [
        ("key", 0, row, col) for row, col in original["ordinary_keys"][:8]]
    assert [new for _, _, new in delta[:8]] == [104, 105, 106, 107, 108, 109, 112, 113]
    assert [(pos, new) for pos, _, new in delta[8:]] == [
        (("encoder", 0, 0, "cw"), 110), (("encoder", 0, 0, "ccw"), 111)]
    assert target["keymap"][1:] == original["keymap"][1:]
    assert [row[0] for row in target["keymap"][0]] == [row[0] for row in original["keymap"][0]]
    assert target["encoders"][0][1:] == original["encoders"][0][1:]
    assert target["encoders"][0][0]["press"] == original["encoders"][0][0]["press"]
    assert target["encoders"][1:] == original["encoders"][1:]


def test_snapshot_validation_rejects_incomplete_or_guessed_geometry():
    for mutate in (lambda s: s.update(schema_version=True),
                   lambda s: s["device"].update(product_id=0x1234),
                   lambda s: s.update(matrix=[]),
                   lambda s: s["matrix"].update(rows=True),
                   lambda s: s["keymap"][1].pop(),
                   lambda s: s["keymap"][0][0].__setitem__(0, True),
                   lambda s: s["encoders"].pop(),
                   lambda s: s["encoders"][1].pop(),
                   lambda s: s["encoders"][0][0].pop("cw"),
                   lambda s: s["encoders"][0][0].update(cw=65536),
                   lambda s: s["ordinary_keys"].reverse(),
                   lambda s: s["ordinary_keys"].__setitem__(0, [99, 0]),
                   lambda s: s["ordinary_keys"].__setitem__(0, [0, 2])):
        data = snapshot()
        mutate(data)
        expect_error(km.validate_snapshot, data)
    data = snapshot()
    data["ordinary_keys"] = []
    expect_error(km.plan_remap, data)
    data = snapshot()
    data["encoders"] = [[] for _ in data["keymap"]]
    expect_error(km.plan_remap, data)


def test_backup_complete_exclusive_original_and_no_overwrite():
    with tempfile.TemporaryDirectory() as temp:
        before = snapshot()
        first = km.save_backup(before, temp, output=lambda _: None)
        original = Path(temp) / "_rollback/deck-v0/keymap-original.json"
        raw = original.read_bytes()
        assert raw == first.read_bytes()
        assert km.configuration(json.loads(raw)) == km.configuration(before)
        second = km.save_backup(km.plan_remap(before), temp, output=lambda _: None)
        assert second != first
        assert original.read_bytes() == raw
        assert km.configuration(json.loads(second.read_text(encoding="utf-8"))) == km.configuration(km.plan_remap(before))


def test_apply_backs_up_before_any_write_and_verifies_every_layer():
    with tempfile.TemporaryDirectory() as temp:
        backend = FakeBackend()
        setter = backend.write

        def write(location, value):
            assert list((Path(temp) / "research").glob("keymap-backup-*.json"))
            assert (Path(temp) / "_rollback/deck-v0/keymap-original.json").is_file()
            setter(location, value)

        backend.write = write
        path = km.apply_verified(backend, temp, output=lambda _: None)
        assert backend.state == km.plan_remap(snapshot())
        assert len(backend.writes) == 10 and backend.reads == 2
        assert km.configuration(json.loads(path.read_text(encoding="utf-8"))) == km.configuration(snapshot())
        backend.writes.clear()
        km.apply_verified(backend, temp, output=lambda _: None)
        assert backend.writes == []  # idempotent apply still backs up and verifies


def test_apply_readback_mismatch_and_partial_failures_restore_backup():
    for failure in ("ignore", "ack", "interrupt", "read", "collateral"):
        with tempfile.TemporaryDirectory() as temp:
            backend = FakeBackend(failure)
            expect_error(km.apply_verified, backend, temp, output=lambda _: None,
                         contains="backup restored and verified")
            assert backend.state == snapshot(), failure
            assert list((Path(temp) / "research").glob("keymap-backup-*.json"))


def test_rollback_failure_is_reported_with_backup():
    with tempfile.TemporaryDirectory() as temp:
        backend = FakeBackend("rollback")
        message = expect_error(km.apply_verified, backend, temp, output=lambda _: None,
                               contains="ROLLBACK FAILED")
        assert "backup=" in message


def test_second_interrupt_during_rollback_preparation_still_restores():
    backend = FakeBackend()
    reader = backend.snapshot

    def interrupted_snapshot():
        if backend.reads == 1:
            backend.reads += 1
            raise OSError("first readback failed")
        if backend.reads == 2:
            backend.reads += 1
            raise KeyboardInterrupt("interrupted while preparing rollback")
        return reader()

    backend.snapshot = interrupted_snapshot
    with tempfile.TemporaryDirectory() as temp:
        expect_error(km.apply_verified, backend, temp, output=lambda _: None,
                     contains="backup restored and verified")
    assert backend.state == snapshot()


def test_restore_uses_complete_backup_and_rejects_geometry_mismatch():
    with tempfile.TemporaryDirectory() as temp:
        backend = FakeBackend()
        backend.state = km.plan_remap(snapshot())
        km.apply_verified(backend, temp, restore=snapshot(), output=lambda _: None)
        assert backend.state == snapshot() and len(backend.writes) == 10
        backend.writes.clear()
        wrong = snapshot()
        wrong["ordinary_keys"].pop()
        expect_error(km.apply_verified, backend, temp, restore=wrong, output=lambda _: None)
        assert backend.writes == []


def test_show_layer_zero_names_and_encoder_directions():
    output = []
    km.show_snapshot(km.plan_remap(snapshot()), output.append)
    assert "layer=0 row=0 col=1 0x0068 KC_F13" in output
    assert "layer=0 encoder=0 cw 0x006E KC_F19" in output
    assert "layer=0 encoder=0 ccw 0x006F KC_F20" in output
    assert not any("layer=1" in line for line in output)
    assert [km.keycode_name(code) for code in range(104, 116)] == ["KC_F%d" % n for n in range(13, 25)]


def test_real_cli_gate_never_opens_or_sends_even_with_fake_supported_usage():
    # Neither changing the interface nor providing a backup is a bypass for the
    # missing target definition and missing four-encoder protocol.
    for interfaces in ([], [{"interface_number": 3, "usage_page": 0xFF00, "usage": 1}],
                       [{"interface_number": 3, "usage_page": 0xFF60, "usage": 0x61}]):
        fake = SimpleNamespace(enumerate=lambda vid, pid: interfaces)
        with patch.dict(sys.modules, {"hid": fake}):
            for command in ("backup", "show", "apply"):
                with patch.object(km, "save_backup") as backup, contextlib.redirect_stdout(io.StringIO()) as out:
                    assert km.main([command]) == 2
                    assert "No HID interface opened; no reports sent" in out.getvalue()
                    backup.assert_not_called()
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "snapshot.json"
                path.write_text(json.dumps(snapshot()), encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    assert km.main(["restore", str(path)]) == 2


def main():
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("Keymap offline tests: %d groups passed" % len(tests))


if __name__ == "__main__":
    main()
