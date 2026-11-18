"""VIA-C keymap backup/remap tool for the 4132:2107 macro keyboard.

The vendor command numbers differ from standard VIA. See
research/via-c-protocol.md. The installed VIA-C does NOT support this device's
FF00 interface, so live commands fail closed without opening HID. The snapshot
and transaction helpers are tested offline; a confirmed hardware backend is
still required. Never send reset, bootloader or lighting commands.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from deck_probe import VID, PID

ROOT = Path(__file__).resolve().parent.parent
REPORT_SIZE = 32
TIMEOUT_MS = 1000
READ_COMMANDS = frozenset((0x07, 0x09, 0x0A, 0x0B, 0x20, 0x21, 0x22))


class KeymapError(ValueError):
    pass


def encode_report(command, arguments=()):
    """hidapi output: report ID zero followed by 32 vendor payload bytes."""
    arguments = bytes(arguments)
    expected = {0x07: 3, 0x09: 0, 0x0A: 3, 0x0B: 0,
                0x10: 5, 0x20: 0, 0x21: 0, 0x22: 0}
    if command not in expected or len(arguments) != expected[command]:
        raise KeymapError("unsupported command or invalid argument length")
    if command == 0x07 and (not 1 <= arguments[2] <= 28 or
                           int.from_bytes(arguments[:2], "big") + arguments[2] > 65536):
        raise KeymapError("invalid keymap buffer range")
    return b"\0" + (bytes((command,)) + arguments).ljust(REPORT_SIZE, b"\0")


def decode_response(report, response):
    response = bytes(response)
    if len(response) == REPORT_SIZE + 1 and response[0] == 0:
        response = response[1:]
    if len(response) != REPORT_SIZE:
        raise KeymapError("expected 32 response bytes, got %d" % len(response))
    command = report[1]
    prefix_length = {0x07: 4, 0x0A: 4, 0x10: 6}.get(command, 1)
    if response[:prefix_length] != report[1:1 + prefix_length]:
        raise KeymapError("response does not echo command/arguments 0x%02X" % command)
    return response


class VendorVIA:
    def __init__(self, device):
        self.device = device
        self.write_enabled = False

    def query(self, command, arguments=()):
        if command not in READ_COMMANDS and not (command == 0x10 and self.write_enabled):
            raise KeymapError("configuration writes are not enabled")
        report = encode_report(command, arguments)
        if self.device.write(report) != len(report):
            raise KeymapError("incomplete HID write for command 0x%02X" % command)
        response = self.device.read(REPORT_SIZE + 1, TIMEOUT_MS)
        if not response:
            raise KeymapError("HID response timed out for command 0x%02X" % command)
        return decode_response(report, response)

    def word(self, command):
        return int.from_bytes(self.query(command)[1:3], "big")

    def key(self, layer, row, col):
        return int.from_bytes(self.query(0x0A, (layer, row, col))[4:6], "big")

    def set_key(self, layer, row, col, code):
        self.query(0x10, (layer, row, col, *code.to_bytes(2, "big")))


def keycode_name(code):
    if 0x68 <= code <= 0x73:
        return "KC_F%d" % (code - 0x68 + 13)
    if 4 <= code <= 29:
        return "KC_" + chr(ord("A") + code - 4)
    if 0x3A <= code <= 0x45:
        return "KC_F%d" % (code - 0x3A + 1)
    names = {0: "KC_NO", 1: "KC_TRNS", 0x28: "KC_ENT", 0x29: "KC_ESC",
             0x2A: "KC_BSPC", 0x2B: "KC_TAB", 0x2C: "KC_SPC"}
    return names.get(code, "UNKNOWN(0x%04X)" % code)


def validate_snapshot(data):
    """Internal backup format; never infer matrix/encoder geometry from values."""
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise KeymapError("expected snapshot schema_version 1")
    device = data.get("device")
    if not isinstance(device, dict) or any(type(device.get(k)) is not int or device[k] != v
                                          for k, v in (("vendor_id", VID), ("product_id", PID))):
        raise KeymapError("snapshot does not belong to VID_4132&PID_2107")
    geometry = data.get("matrix", {})
    if not isinstance(geometry, dict):
        raise KeymapError("invalid matrix metadata")
    rows, cols = geometry.get("rows"), geometry.get("cols")
    if any(type(v) is not int or not 1 <= v <= 255 for v in (rows, cols)):
        raise KeymapError("invalid matrix dimensions")
    keys, encoders = data.get("keymap"), data.get("encoders")
    if not isinstance(keys, list) or not 1 <= len(keys) <= 255:
        raise KeymapError("invalid keymap layer count")
    if not isinstance(encoders, list) or len(encoders) != len(keys):
        raise KeymapError("encoder data must cover every keymap layer")
    for layer in keys:
        if not isinstance(layer, list) or len(layer) != rows or any(
                not isinstance(row, list) or len(row) != cols for row in layer):
            raise KeymapError("incomplete keymap matrix")
        for row in layer:
            if any(type(code) is not int or not 0 <= code <= 65535 for code in row):
                raise KeymapError("invalid keycode")
    count = None
    for layer in encoders:
        if not isinstance(layer, list):
            raise KeymapError("invalid encoder layer")
        if count is None:
            count = len(layer)
        if len(layer) != count:
            raise KeymapError("encoder count differs between layers")
        for encoder in layer:
            if not isinstance(encoder, dict) or not {"cw", "ccw"} <= encoder.keys() or not encoder.keys() <= {"cw", "ccw", "press"}:
                raise KeymapError("encoder must contain cw/ccw and optional press")
            if any(type(code) is not int or not 0 <= code <= 65535 for code in encoder.values()):
                raise KeymapError("invalid encoder keycode")
    positions = data.get("ordinary_keys")
    if not isinstance(positions, list):
        raise KeymapError("ordinary key positions must come from a confirmed definition")
    for pos in positions:
        if (not isinstance(pos, list) or len(pos) != 2 or
                any(type(v) is not int for v in pos) or
                not 0 <= pos[0] < rows or not 0 <= pos[1] < cols):
            raise KeymapError("invalid ordinary key matrix position")
    if positions != sorted(positions) or len({tuple(pos) for pos in positions}) != len(positions):
        raise KeymapError("ordinary keys must be unique and in row-major order")
    return data


def configuration(data):
    validate_snapshot(data)
    return {name: data[name] for name in ("device", "matrix", "ordinary_keys", "keymap", "encoders")}


def plan_remap(snapshot):
    """Pure transformation; ordinary_keys must exclude encoder push switches."""
    validate_snapshot(snapshot)
    if len(snapshot["ordinary_keys"]) < 8 or not snapshot["encoders"][0]:
        raise KeymapError("need eight confirmed ordinary keys and a confirmed first encoder")
    target = copy.deepcopy(snapshot)
    for (row, col), code in zip(snapshot["ordinary_keys"][:8], (0x68, 0x69, 0x6A, 0x6B, 0x6C, 0x6D, 0x70, 0x71)):
        target["keymap"][0][row][col] = code
    target["encoders"][0][0].update(cw=0x6E, ccw=0x6F)
    return target


def changes(before, after):
    """Yield the exact key/encoder fields whose values differ."""
    configuration(before)
    configuration(after)
    for field in ("device", "matrix", "ordinary_keys"):
        if before[field] != after[field]:
            raise KeymapError("snapshot %s does not match the connected device" % field)
    if len(before["keymap"]) != len(after["keymap"]) or any(
            len(a) != len(b) or any(x.keys() != y.keys() for x, y in zip(a, b))
            for a, b in zip(before["encoders"], after["encoders"])):
        raise KeymapError("snapshot layer/encoder geometry does not match")
    for layer, matrix in enumerate(before["keymap"]):
        for row, codes in enumerate(matrix):
            for col, old in enumerate(codes):
                new = after["keymap"][layer][row][col]
                if old != new:
                    yield ("key", layer, row, col), old, new
    for layer, encoders in enumerate(before["encoders"]):
        for index, encoder in enumerate(encoders):
            for direction, old in encoder.items():
                new = after["encoders"][layer][index][direction]
                if old != new:
                    yield ("encoder", layer, index, direction), old, new


def write_value(backend, location, value):
    kind, layer, first, second = location
    if kind == "key":
        backend.set_key(layer, first, second, value)
    else:
        backend.set_encoder(layer, first, second, value)


def save_backup(snapshot, root=ROOT, output=print):
    validate_snapshot(snapshot)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    data = dict(snapshot, captured_at_utc=stamp)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    directory = Path(root) / "research"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("keymap-backup-%s.json" % stamp)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    original = Path(root) / "_rollback/deck-v0/keymap-original.json"
    original.parent.mkdir(parents=True, exist_ok=True)
    try:
        with original.open("x", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        output("Original backup preserved: %s" % original)
    else:
        output("Original backup saved: %s" % original)
    output("Backup saved: %s" % path)
    return path


def apply_verified(backend, root=ROOT, restore=None, output=print):
    """Backend contract: complete snapshot(), set_key(), set_encoder().

    No target hardware backend is supplied until its protocol is confirmed.
    Every attempted write, including a lost ACK, is included in rollback.
    """
    before = copy.deepcopy(validate_snapshot(backend.snapshot()))
    target = plan_remap(before) if restore is None else validate_snapshot(restore)
    delta = list(changes(before, target))
    path = save_backup(before, root, output)
    attempted = []
    try:
        for location, old, new in delta:
            attempted.append((location, old))
            write_value(backend, location, new)
        if configuration(backend.snapshot()) != configuration(target):
            raise KeymapError("full readback differs from expected configuration")
    except BaseException as error:
        # Readback may reveal a change outside the intended positions. Restore
        # that too; if the read fails, use every location we attempted to write.
        rollback = dict(attempted)
        try:
            for location, _, original in changes(backend.snapshot(), before):
                rollback[location] = original
        except BaseException:
            pass
        failures = []
        for location, original in rollback.items():
            try:
                write_value(backend, location, original)
            except BaseException as failure:
                failures.append(str(failure))
        try:
            if configuration(backend.snapshot()) != configuration(before):
                failures.append("restored readback still differs from backup")
        except BaseException as failure:
            failures.append(str(failure))
        if failures:
            raise KeymapError("operation failed (%s); ROLLBACK FAILED: %s; backup=%s" %
                              (error, "; ".join(failures), path)) from error
        raise KeymapError("operation failed (%s); backup restored and verified; backup=%s" %
                          (error, path)) from error
    for location, old, new in delta:
        output("%s: 0x%04X %s -> 0x%04X %s" %
               (" ".join(map(str, location)), old, keycode_name(old), new, keycode_name(new)))
    output("Full readback verified; %d fields changed." % len(delta))
    return path


def show_snapshot(snapshot, output=print):
    validate_snapshot(snapshot)
    output("Layer 0 matrix: rows=%d cols=%d" % (snapshot["matrix"]["rows"], snapshot["matrix"]["cols"]))
    for row, codes in enumerate(snapshot["keymap"][0]):
        for col, code in enumerate(codes):
            output("layer=0 row=%d col=%d 0x%04X %s" % (row, col, code, keycode_name(code)))
    for index, encoder in enumerate(snapshot["encoders"][0]):
        for direction, code in encoder.items():
            output("layer=0 encoder=%d %s 0x%04X %s" % (index, direction, code, keycode_name(code)))


def confirmed_backend(output=print):
    """Fail BEFORE open_path/write: installed source has no target definition.

    Deliberately no --force/guessed-matrix escape hatch. A real backend must
    establish FF00 command semantics, complete geometry, encoder directions and
    persistence before replacing this gate.
    """
    import hid
    interfaces = hid.enumerate(VID, PID)
    output("Target: VID_4132&PID_2107; matching HID interfaces=%d" % len(interfaces))
    for item in interfaces:
        output("interface=%s usage_page=0x%04X usage=0x%04X" %
               (item.get("interface_number", "?"), item.get("usage_page", 0), item.get("usage", 0)))
    output("Installed VIA-C 0.3.5 only selects usage_page=0xFF60 usage=0x0061.")
    output("No 4132:2107 matrix definition or confirmed four-encoder mapping was found.")
    raise KeymapError("FF00/0001 protocol is unconfirmed. No HID interface opened; "
                      "no reports sent; no keymap backup created; no configuration changed.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("backup", "show", "apply"):
        sub.add_parser(command)
    sub.add_parser("restore").add_argument("json", type=Path)
    args = parser.parse_args(argv)
    print("AgentDeck keymap: %s" % args.command)
    try:
        restore = None
        if args.command == "restore":
            restore = validate_snapshot(json.loads(args.json.read_text(encoding="utf-8-sig")))
        backend = confirmed_backend()
        if args.command == "backup":
            save_backup(backend.snapshot())
        elif args.command == "show":
            show_snapshot(backend.snapshot())
        else:
            apply_verified(backend, restore=restore)
    except (OSError, ValueError, ImportError) as error:
        print("BLOCKED: %s" % error)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

