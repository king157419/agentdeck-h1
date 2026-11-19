#!/usr/bin/env python3
# Dependencies: Python 3.10+ standard library; Windows tracerpt.exe for .etl input.
# XML input works offline on any OS. No USB/HID library or device access is used.
"""Read USB ETW captures for 4132:2107; print OUT transfers and time-based groups.

Default input: light.etl beside this script. Accepts tracerpt XML directly too.
PartialDataBusTrace can truncate payloads. Unknown identities/directions are
excluded, and missing payloads remain explicitly marked. This is an initial
decoder tested with synthetic XML, not a validated decoder for a real capture.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


VID, PID = 0x4132, 0x2107
STEPS = ("第 1 颗键：红", "第 1 颗键：绿", "第 1 颗键：蓝",
         "第 2 颗键：红", "亮度：最低", "亮度：最高")


def local(tag):
    return tag.rsplit("}", 1)[-1]


def key(name):
    name = re.sub(r"[^a-z0-9]", "", name.lower())
    return name.removeprefix("fid").removeprefix("urb")


def number(value):
    if value is None:
        return None
    try:
        value = value.strip()
        return int(value, 16 if value.lower().startswith("0x") else 10)
    except ValueError:
        return None


def hex_bytes(value):
    """Decode rendered byte arrays, never pointer-valued TransferBuffer fields."""
    if value is None:
        return None
    value = re.sub(r"[\s,;\[\]{}():-]+", " ", value).strip()
    tokens = value.split()
    if len(tokens) > 1 or (tokens and re.fullmatch(r"0x[0-9a-f]{1,2}", tokens[0], re.I)):
        if not all(re.fullmatch(r"(?:0x)?[0-9a-f]{1,2}", token, re.I) for token in tokens):
            raise ValueError("invalid hexadecimal byte array")
        return bytes(int(token, 16) for token in tokens)
    value = value.removeprefix("0x").removeprefix("0X")
    if len(value) % 2 or re.search(r"[^0-9a-fA-F]", value):
        raise ValueError("invalid hexadecimal byte array")
    return bytes.fromhex(value)


def events(path):
    """Stream both EventData/Data and nested UserData without loading the ETL XML."""
    root = None
    for action, node in ET.iterparse(path, events=("start", "end")):
        if root is None:
            root = node
        if action != "end" or local(node.tag) != "Event":
            continue
        fields = {}
        for section in node:
            if local(section.tag) not in ("EventData", "UserData"):
                continue
            for item in section.iter():
                if item is section:
                    continue
                if local(item.tag) == "Data" and "Name" in item.attrib:
                    name = item.attrib["Name"]
                    value = " ".join(item.itertext()).strip()
                elif len(item) == 0:
                    name, value = local(item.tag), (item.text or "").strip()
                else:
                    continue
                name = key(name)
                if name in fields and (name == "transferdata" or fields[name] != value):
                    fields[name] += " " + value
                else:
                    fields[name] = value
        system = next((x for x in node if local(x.tag) == "System"), None)
        provider, stamp = "", ""
        if system is not None:
            for item in system:
                if local(item.tag) == "Provider":
                    provider = item.get("Name", "")
                elif local(item.tag) == "TimeCreated":
                    stamp = item.get("SystemTime", "")
        yield provider, stamp, fields
        node.clear()
        if root is not node:
            root.clear()


def get(fields, *names):
    return next((fields[key(name)] for name in names if key(name) in fields), None)


def identity(fields):
    vendor = number(get(fields, "idVendor", "VendorId", "VID"))
    product = number(get(fields, "idProduct", "ProductId", "PID"))
    if vendor is not None and product is not None:
        return vendor, product
    for value in fields.values():
        match = re.search(r"VID_([0-9a-f]{4})[&+#\\].*?PID_([0-9a-f]{4})", value, re.I)
        if match:
            return tuple(int(x, 16) for x in match.groups())
    return None


def handle(value):
    parsed = number(value)
    return None if parsed in (None, 0) else parsed


@dataclass(frozen=True)
class Transfer:
    time: datetime
    location: str
    length: int
    data: bytes | None
    set_report: bool = False


def parse_xml(path):
    devices, pipes = {}, {}
    rows = []
    for provider, stamp, fields in events(path):
        if not provider.startswith("Microsoft-Windows-USB-"):
            continue
        # USBPORT handles belong to the USB2 stack; USB3 rundown spans HUB3/UCX.
        stack = "usb2" if provider.endswith(("USBPORT", "USBHUB")) else "usb3"
        device = handle(get(fields, "UsbDevice", "DeviceHandle", "Hdr_UsbdDeviceHandle"))
        pipe = handle(get(fields, "PipeHandle", "Endpoint"))
        found = identity(fields)
        if found is not None and device is not None:
            devices[stack, device] = found
        endpoint = number(get(fields, "bEndpointAddress", "EndpointAddress"))
        if device is not None and pipe is not None and endpoint is not None:
            pipes[stack, pipe] = (device, endpoint)
        if pipe is not None and (stack, pipe) in pipes:
            pipe_device, pipe_endpoint = pipes[stack, pipe]
            if device is None:
                device = pipe_device
            if device == pipe_device and endpoint is None:
                endpoint = pipe_endpoint
        if (found or devices.get((stack, device))) != (VID, PID):
            continue
        setup = hex_bytes(get(fields, "SetupPacket"))
        request_type = number(get(fields, "Setup_bmRequestType", "bmRequestType"))
        request = number(get(fields, "Setup_bRequest", "bRequest"))
        interface = number(get(fields, "Setup_wIndex", "wIndex", "InterfaceNumber"))
        if setup is not None:
            if len(setup) != 8:
                raise ValueError("USB setup packet must contain eight bytes")
            request_type, request = setup[:2]
            interface = int.from_bytes(setup[4:6], "little")
        flags = number(get(fields, "TransferFlags"))
        direction = (get(fields, "Direction", "TransferDirection") or "").upper()
        if request_type is not None:
            outgoing = not request_type & 0x80
        elif flags is not None:
            outgoing = not flags & 1
        elif direction in ("OUT", "HOST_TO_DEVICE", "IN", "DEVICE_TO_HOST"):
            outgoing = direction in ("OUT", "HOST_TO_DEVICE")
        else:
            outgoing = endpoint is not None and endpoint != 0 and not endpoint & 0x80
        if not outgoing:
            continue
        data = hex_bytes(get(fields, "TransferData", "Payload"))
        length = number(get(fields, "TransferBufferLength", "TransferLength", "Length"))
        if length is None and data is None:
            continue  # rundown/descriptors are not transfers
        length = len(data) if length is None else length
        if length < 0 or (data is not None and len(data) > length):
            raise ValueError("payload exceeds the reported transfer length")
        if not stamp:
            raise ValueError("matching transfer is missing SystemTime")
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        set_report = request_type == 0x21 and request == 0x09
        if request_type is not None:
            location = "接口 %s" % (interface if interface is not None else "?")
        elif endpoint is not None:
            location = "端点 0x%02X" % endpoint
        else:
            location = "端点 ? (pipe %s)" % ("0x%X" % pipe if pipe else "?")
        rows.append(Transfer(moment, location, length, data, set_report))
    return sorted(rows, key=lambda row: row.time)


def group_transfers(rows, gap=2.0):
    """Infer bursts from silence, without forcing noisy/missing traces into six."""
    groups = []
    for row in sorted(rows, key=lambda item: item.time):
        if not groups or (row.time - groups[-1][-1].time).total_seconds() >= gap:
            groups.append([])
        groups[-1].append(row)
    return groups


def print_transfers(rows, gap=2.0, output=None):
    output = sys.stdout if output is None else output
    groups = group_transfers(rows, gap)
    print("4132:2107 OUT；按空闲间隔 >= %g 秒分组（操作名称仅按顺序推测）" % gap, file=output)
    for index, group in enumerate(groups):
        label = STEPS[index] if len(groups) == 6 else "操作待确认"
        print("\n组 %d：%s" % (index + 1, label), file=output)
        for row in group:
            payload = "[未捕获数据]" if row.data is None else row.data.hex(" ").upper()
            captured = 0 if row.data is None else len(row.data)
            print("%s  %s%s  长度=%d 捕获=%d  %s" % (
                row.time.isoformat(timespec="microseconds"), row.location,
                " SET_REPORT" if row.set_report else " OUT", row.length, captured, payload), file=output)
    print("\n共 %d 条传输，%d 组；预期 6 组。" % (len(rows), len(groups)), file=output)
    if len(groups) != 6:
        print("未识别到完整六组：可调整 --gap；检查设备 rundown、解码字段或背景流量。", file=output)
    print("PartialDataBusTrace 可能截断载荷；未捕获数据不代表零长度报文。", file=output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path,
                        default=Path(__file__).with_name("light.etl"), help="ETL or tracerpt XML")
    parser.add_argument("--gap", type=float, default=2.0, help="seconds of silence between operations (default: 2)")
    args = parser.parse_args(argv)
    if not math.isfinite(args.gap) or args.gap <= 0:
        parser.error("--gap must be a finite positive number")
    try:
        path = args.path.resolve(strict=True)
        if path.suffix.lower() == ".xml":
            rows = parse_xml(path)
        elif path.suffix.lower() == ".etl":
            with tempfile.TemporaryDirectory(prefix="agentdeck-etl-") as temporary:
                xml_path = Path(temporary) / "light.xml"
                result = subprocess.run(["tracerpt.exe", str(path), "-o", str(xml_path),
                                         "-of", "XML", "-y"], cwd=temporary,
                                        capture_output=True, text=True, errors="replace", check=True)
                if not xml_path.is_file():
                    raise ValueError("tracerpt did not create XML: " + result.stdout)
                rows = parse_xml(xml_path)
        else:
            raise ValueError("input must be .etl or .xml")
        print_transfers(rows, args.gap)
    except (OSError, ValueError, ET.ParseError, subprocess.CalledProcessError) as error:
        print("parse_etl: %s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
