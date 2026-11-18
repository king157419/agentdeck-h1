"""Read-only VIA probe. Unknown vendor protocols are never opened.

VIA matrix dimensions come from a keyboard definition, not the read commands:
https://caniusevia.com/docs/specification/#matrix
Transport reference: https://github.com/the-via/app/blob/main/src/utils/keyboard-api.ts
"""
import json
from pathlib import Path

VID = 0x4132
PID = 0x2107
VIA_PAGE = 0xFF60
# QMK defaults to 0x61; some VIA variants use the application usage 0x01.
# Other usages on the vendor page may be unrelated proprietary collections.
VIA_USAGES = frozenset((0x61, 0x01))
READ_COMMANDS = frozenset((0x01, 0x11, 0x12))
REPORT_SIZE = 32
READ_TIMEOUT_MS = 500


class ProbeError(ValueError):
    pass


def matrix_dimensions(rows=None, cols=None, definition=None):
    """Use supplied dimensions or a local VIA definition; never guess a matrix."""
    if definition is not None:
        data = json.loads(Path(definition).read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ProbeError("VIA definition must be a JSON object")
        for field, expected in (("vendorId", VID), ("productId", PID)):
            value = data.get(field)
            if value is not None:
                actual = int(value, 0) if isinstance(value, str) else value
                if actual != expected:
                    raise ProbeError("VIA definition %s does not match this keyboard" % field)
        matrix = data.get("matrix", {})
        if not isinstance(matrix, dict):
            raise ProbeError("VIA definition matrix must be an object")
        defined_rows, defined_cols = matrix.get("rows"), matrix.get("cols")
        if rows is not None and rows != defined_rows or cols is not None and cols != defined_cols:
            raise ProbeError("explicit dimensions conflict with VIA definition")
        rows, cols = defined_rows, defined_cols
    if rows is None and cols is None:
        return None
    if any(type(value) is not int or not 1 <= value <= 255 for value in (rows, cols)):
        raise ProbeError("provide both --rows and --cols as integers from 1 to 255")
    return rows, cols


class ReadOnlyVIA:
    """Transport exposes only three specific read commands; no general HID writer."""

    def __init__(self, device):
        self.device = device

    def query(self, command, arguments=()):
        if command not in READ_COMMANDS:
            raise ProbeError("command 0x%02X is not allowed by the read-only probe" % command)
        arguments = bytes(arguments)
        if command in (0x01, 0x11):
            if arguments:
                raise ProbeError("version and layer queries take no arguments")
            minimum = 3 if command == 0x01 else 2
        else:
            if len(arguments) != 3 or not 1 <= arguments[2] <= 28:
                raise ProbeError("buffer read requires a 16-bit offset and 1..28 bytes")
            if int.from_bytes(arguments[:2], "big") + arguments[2] > 65536:
                raise ProbeError("buffer read exceeds VIA's 16-bit address space")
            minimum = 4 + arguments[2]
        request = bytes((command,)) + arguments
        # hidapi requires a leading report ID, even when the device uses ID zero.
        report = b"\0" + request.ljust(REPORT_SIZE, b"\0")
        if self.device.write(report) != len(report):
            raise ProbeError("incomplete HID read-query transport")
        response = bytes(self.device.read(REPORT_SIZE + 1, READ_TIMEOUT_MS))
        if not response:
            raise ProbeError("VIA response timed out after %d ms" % READ_TIMEOUT_MS)
        if len(response) == REPORT_SIZE + 1 and response[0] == 0:
            response = response[1:]
        if response[0] == 0xFF:
            raise ProbeError("firmware does not support VIA command 0x%02X" % command)
        if len(response) < minimum:
            raise ProbeError("short VIA response for command 0x%02X" % command)
        if response[0] != command or command == 0x12 and response[1:4] != arguments:
            raise ProbeError("VIA response does not match the requested command/offset")
        return response

    def version(self):
        return int.from_bytes(self.query(0x01)[1:3], "big")

    def layers(self):
        count = self.query(0x11)[1]
        if not count:
            raise ProbeError("firmware reported zero keymap layers")
        return count

    def keymap(self, rows, cols, layers):
        length = rows * cols * layers * 2
        if not 0 < length <= 65536:
            raise ProbeError("keymap dimensions exceed VIA's 16-bit address space")
        data = bytearray()
        for offset in range(0, length, 28):
            size = min(28, length - offset)
            response = self.query(0x12, (*offset.to_bytes(2, "big"), size))
            data.extend(response[4:4 + size])
        return [int.from_bytes(data[index:index + 2], "big") for index in range(0, length, 2)]


def probe(rows=None, cols=None, definition=None, output=print):
    """Enumerate all VID interfaces, then query only the known standard VIA TLC."""
    try:
        import hid
        interfaces = hid.enumerate(VID, 0)
    except Exception as error:
        output("HID probe unavailable: %s" % error)
        output("No device was opened and no keyboard configuration was changed.")
        return 0
    output("AgentDeck read-only probe: VID=0x%04X" % VID)
    for interface in interfaces:
        path = interface.get("path", b"")
        if isinstance(path, bytes):
            path = path.decode("utf-8", "replace")
        output("interface=%s PID=0x%04X usage_page=0x%04X usage=0x%04X path=%s" % (
            interface.get("interface_number", "?"), interface.get("product_id", 0),
            interface.get("usage_page", 0), interface.get("usage", 0), path))
    if not interfaces:
        output("No VID_4132 interfaces are visible (unplugged or HID access is restricted).")
    candidates = [item for item in interfaces if item.get("vendor_id") == VID
                  and item.get("product_id") == PID and item.get("usage_page") == VIA_PAGE
                  and item.get("usage") in VIA_USAGES]
    if not candidates:
        output("No standard VIA 0xFF60 interface (usage 0x0061 or 0x0001) for VID_4132&PID_2107.")
        output("0xFF00 and all other interfaces were not opened; no reports were sent.")
        output("Protocol, layers, matrix and keymap cannot be read through this unknown protocol.")
        return 0
    try:
        dimensions = matrix_dimensions(rows, cols, definition)
        dimension_error = None
    except (OSError, ValueError, TypeError) as error:
        dimensions, dimension_error = None, str(error)
    for interface in candidates:
        device = None
        try:
            device = hid.device()
            device.open_path(interface["path"])
            via = ReadOnlyVIA(device)
            version = via.version()
            output("VIA protocol version: %d (0x%04X)" % (version, version))
            if version < 8:
                output("VIA protocol < 8 does not support the allowed layer/buffer queries; keymap skipped.")
                continue
            layers = via.layers()
            output("VIA layers: %d" % layers)
            if dimensions is None:
                output("Matrix/keymap unavailable: %s" % (dimension_error or
                       "VIA does not report matrix dimensions; supply --definition keyboard.json "
                       "or the known --rows N --cols N."))
                continue
            rows_count, cols_count = dimensions
            output("Matrix: rows=%d cols=%d (from supplied dimensions/definition)" % dimensions)
            keycodes = via.keymap(rows_count, cols_count, layers)
            for layer in range(layers):
                for row in range(rows_count):
                    for col in range(cols_count):
                        index = (layer * rows_count + row) * cols_count + col
                        output("layer=%d row=%d col=%d keycode=0x%04X" % (
                            layer, row, col, keycodes[index]))
        except Exception as error:
            output("VIA read unavailable: %s" % error)
        finally:
            if device is not None:
                try:
                    device.close()
                except Exception as error:
                    output("HID close: %s" % error)
    return 0
