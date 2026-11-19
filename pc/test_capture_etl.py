"""Offline capture checks: synthetic tracerpt XML and stubbed logman; no devices."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


CAPTURE = Path(__file__).resolve().parents[1] / "research" / "capture"
spec = importlib.util.spec_from_file_location("agentdeck_parse_etl", CAPTURE / "parse_etl.py")
etl = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = etl
spec.loader.exec_module(etl)


def event(second, fields, provider="UCX", nested=False):
    node = ET.Element("Event")
    system = ET.SubElement(node, "System")
    ET.SubElement(system, "Provider", Name="Microsoft-Windows-USB-" + provider)
    ET.SubElement(system, "TimeCreated", SystemTime="2026-11-18T12:00:%06.3fZ" % second)
    section = ET.SubElement(node, "UserData" if nested else "EventData")
    if nested:
        section = ET.SubElement(section, "UcxEvent")
    for name, value in fields.items():
        item = ET.SubElement(section, name) if nested else ET.SubElement(section, "Data", Name=name)
        item.text = str(value)
    return node


def save_xml(path, nodes):
    root = ET.Element("Events", xmlns="http://schemas.microsoft.com/win/2004/08/events/event")
    root.extend(nodes)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def transfer(second, **extra):
    fields = {"fid_UsbDevice": "0x123", "fid_PipeHandle": "0x456",
              "fid_URB_TransferFlags": "0x0", "fid_URB_TransferBufferLength": 4,
              "fid_URB_TransferData": "0x01 0xFF 0x00 0x10"}
    fields.update(extra)
    return event(second, fields)


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "light.xml"

    def parse(self, nodes):
        save_xml(self.path, nodes)
        return etl.parse_xml(self.path)

    def rundown(self):
        return [event(0, {"fid_UsbDevice": "0x123", "fid_idVendor": "0x4132",
                          "fid_idProduct": "0x2107"}, provider="USBHUB3", nested=True),
                event(0.1, {"fid_UsbDevice": "0x123", "fid_PipeHandle": "0x456",
                            "fid_bEndpointAddress": "0x02"}, nested=True)]

    def test_six_bursts_use_rundown_identity_and_endpoint_and_sort(self):
        nodes = self.rundown()
        for index in range(6):
            nodes.extend([transfer(index * 3 + 1.1), transfer(index * 3 + 1)])
        rows = self.parse(nodes)
        groups = etl.group_transfers(rows)
        self.assertEqual([len(group) for group in groups], [2] * 6)
        self.assertTrue(all(row.location == "端点 0x02" for row in rows))
        self.assertEqual(rows[0].data, b"\x01\xff\x00\x10")
        output = io.StringIO()
        etl.print_transfers(rows, output=output)
        self.assertIn("组 6：亮度：最高", output.getvalue())
        self.assertIn("长度=4 捕获=4  01 FF 00 10", output.getvalue())

    def test_excludes_other_devices_input_and_unknown_direction(self):
        nodes = self.rundown() + [transfer(1), transfer(2, fid_URB_TransferFlags="0x1"),
                transfer(3, fid_UsbDevice="0x999"),
                event(4, {"VID": "0x1234", "PID": "0x5678", "EndpointAddress": "0x02",
                          "Length": 1, "Payload": "FF"}),
                event(5, {"VID": "0x4132", "PID": "0x2107", "Length": 1, "Payload": "AA"})]
        self.assertEqual(len(self.parse(nodes)), 1)

    def test_set_report_uses_setup_direction_interface_and_partial_length(self):
        rows = self.parse(self.rundown() + [transfer(1, SetupPacket="21 09 00 03 02 00 40 00",
                          fid_URB_TransferBufferLength=64),
                          transfer(2, SetupPacket="A1 01 00 03 02 00 40 00")])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].set_report)
        self.assertEqual((rows[0].location, rows[0].length, len(rows[0].data)), ("接口 2", 64, 4))

    def test_field_setup_and_non_hid_request_nine(self):
        fields = {"fid_idVendor": "16690", "fid_idProduct": "8455",
                  "fid_URB_Setup_bmRequestType": "0x21", "fid_URB_Setup_bRequest": "0x09",
                  "fid_URB_Setup_wIndex": 1, "fid_URB_TransferData": "00 10",
                  "fid_URB_TransferBufferLength": 2}
        rows = self.parse([event(1, fields, nested=True),
                          event(2, dict(fields, fid_URB_Setup_bmRequestType="0x40"))])
        self.assertEqual([row.set_report for row in rows], [True, False])

    def test_usbport_nested_fields_and_device_path(self):
        rows = self.parse([event(1, {"DeviceInterfacePath": r"\\?\usb#vid_4132&pid_2107#abc",
                          "fid_bEndpointAddress": "0x03", "TransferData": "01FF",
                          "TransferBufferLength": 2}, provider="USBPORT", nested=True)])
        self.assertEqual((rows[0].data, rows[0].location), (b"\x01\xff", "端点 0x03"))

    def test_missing_payload_is_not_an_empty_packet(self):
        rows = self.parse(self.rundown() + [event(1, {"fid_UsbDevice": "0x123",
                          "fid_URB_TransferFlags": 0, "fid_URB_TransferBufferLength": 32})])
        self.assertIsNone(rows[0].data)
        output = io.StringIO()
        etl.print_transfers(rows, output=output)
        self.assertIn("[未捕获数据]", output.getvalue())
        self.assertIn("操作待确认", output.getvalue())

    def test_duplicate_outer_and_inner_pipe_fields_still_correlate(self):
        rows = self.parse(self.rundown() + [transfer(1, fid_URB_PipeHandle="0x456")])
        self.assertEqual(rows[0].location, "端点 0x02")

    def test_invalid_bytes_and_bad_setup_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "hexadecimal"):
            self.parse(self.rundown() + [transfer(1, fid_URB_TransferData="not hex")])
        with self.assertRaisesRegex(ValueError, "eight"):
            self.parse(self.rundown() + [transfer(1, SetupPacket="21 09")])

    def test_hex_byte_arrays_preserve_unpadded_byte_boundaries(self):
        self.assertEqual(etl.hex_bytes("0x1 0x2"), b"\x01\x02")
        self.assertEqual(etl.hex_bytes("[0x1, 0xff, 0x0]"), b"\x01\xff\x00")
        self.assertEqual(etl.hex_bytes("01FF00"), b"\x01\xff\x00")
        self.assertEqual(etl.hex_bytes("0x01FF00"), b"\x01\xff\x00")
        with self.assertRaises(ValueError):
            etl.hex_bytes("0x100 0x2")

    def test_empty_trace_does_not_invent_six_groups(self):
        rows = self.parse(self.rundown())
        self.assertEqual(etl.group_transfers(rows), [])
        output = io.StringIO()
        etl.print_transfers(rows, output=output)
        self.assertIn("共 0 条传输，0 组", output.getvalue())

    def test_xml_cli_and_help(self):
        self.parse(self.rundown() + [transfer(1)])
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(etl.main([str(self.path)]), 0)
        self.assertIn("01 FF 00 10", output.getvalue())
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            etl.main(["--help"])
        self.assertEqual(stopped.exception.code, 0)

    def test_etl_cli_runs_only_tracerpt_in_temporary_directory(self):
        source = Path(self.temporary.name) / "light.etl"
        source.write_bytes(b"synthetic placeholder")

        def convert(command, **kwargs):
            self.assertEqual(command[0], "tracerpt.exe")
            self.assertEqual(command[1], str(source))
            self.assertEqual(command[4:], ["-of", "XML", "-y"])
            self.assertEqual(Path(kwargs["cwd"]), Path(command[3]).parent)
            save_xml(command[3], self.rundown() + [transfer(1)])
            return subprocess.CompletedProcess(command, 0, stdout="ok")

        with patch.object(etl.subprocess, "run", side_effect=convert) as run, redirect_stdout(io.StringIO()):
            self.assertEqual(etl.main([str(source)]), 0)
        self.assertEqual(run.call_count, 1)

    def test_conversion_failure_and_missing_file_are_actionable(self):
        with redirect_stderr(io.StringIO()) as output:
            self.assertEqual(etl.main([str(self.path)]), 1)
        self.assertIn("parse_etl:", output.getvalue())
        source = self.path.with_suffix(".etl")
        source.touch()
        with patch.object(etl.subprocess, "run", side_effect=FileNotFoundError("tracerpt missing")), \
                redirect_stderr(io.StringIO()) as output:
            self.assertEqual(etl.main([str(source)]), 1)
        self.assertIn("tracerpt missing", output.getvalue())

    def test_invalid_gap(self):
        for gap in ("0", "-1", "nan", "inf"):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                etl.main(["--gap", gap])
            self.assertEqual(stopped.exception.code, 2)


@unittest.skipUnless(sys.platform == "win32", "Windows batch interpreter")
class BatchTests(unittest.TestCase):
    def run_batch(self, folder, failure="", elevate=False):
        # Only the admin check and logman are replaced. Finalization runs against
        # temporary paths, with no UAC, real ETW session, registry or USB access.
        lines = (CAPTURE / "抓包.bat").read_text(encoding="utf-8").splitlines()
        prepared = []
        for line in lines:
            if line.startswith("powershell.exe") and "IsInRole" in line:
                line = "cmd.exe /d /c exit 1" if elevate else "ver >nul"
            elif line.startswith("powershell.exe") and "Start-Process" in line:
                # Keep cmd->PowerShell quote handling, replace the process API.
                fake = ("function FakeStart { param($FilePath,$ArgumentList,$Verb,"
                        "[switch]$Wait,[switch]$PassThru,$ErrorAction); "
                        "[IO.File]::WriteAllText((Join-Path $env:AGENTDECK_CAPTURE_DIR 'elevation.txt'),"
                        "$FilePath + [Environment]::NewLine + $ArgumentList); "
                        "[pscustomobject]@{ExitCode=0} }; ")
                line = line.replace("Start-Process", "FakeStart").replace('-Command "', '-Command "' + fake)
            elif line.startswith("logman "):
                line = line.replace("logman ", 'call "' + str(folder / "fake_logman.bat") + '" ')
            prepared.append(line)
        (folder / "抓包.bat").write_text("\n".join(prepared) + "\n", encoding="utf-8")
        (folder / "fake_logman.bat").write_text(
            '@echo off\n>>"%AGENTDECK_CAPTURE_DIR%calls.txt" echo %*\n'
            + (f'if "%~1"=="{failure}" exit /b 1\n' if failure else '')
            + 'if "%~1"=="stop" echo synthetic>"%AGENTDECK_CAPTURE_STEM%_000001.etl"\n'
              'exit /b 0\n', encoding="utf-8")
        (folder / "light.etl").write_bytes(b"previous capture")
        command = '"%s" /d /s /c ""%s""' % (
            os.environ.get("COMSPEC", "cmd.exe"), folder / "抓包.bat")
        return subprocess.run(command, input="\n\n", capture_output=True,
                              encoding="utf-8", errors="replace", timeout=20)

    def test_batch_success_uses_six_providers_preserves_old_capture(self):
        with tempfile.TemporaryDirectory(prefix="capture 空格 & ") as temporary:
            folder = Path(temporary)
            result = self.run_batch(folder)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stderr, "")
            self.assertIn(b"synthetic", (folder / "light.etl").read_bytes())
            backups = list(folder.glob("light-previous-*.etl"))
            self.assertEqual([p.read_bytes() for p in backups], [b"previous capture"])
            calls = (folder / "calls.txt").read_text(encoding="utf-8")
            self.assertEqual(calls.count("update trace"), 6)
            self.assertEqual(calls.count("Default,PartialDataBusTrace"), 3)
            self.assertIn("-nb 128 640 -bs 128", calls)
            self.assertIn("delete -n", calls)

    def test_batch_configuration_failure_cleans_only_its_session(self):
        with tempfile.TemporaryDirectory(prefix="capture 空格 & ") as temporary:
            folder = Path(temporary)
            result = self.run_batch(folder, failure="update")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual((folder / "light.etl").read_bytes(), b"previous capture")
            calls = (folder / "calls.txt").read_text(encoding="utf-8")
            self.assertIn("stop -n", calls)
            self.assertIn("delete -n", calls)
            self.assertNotIn("start -n", calls)

    def test_stop_failure_does_not_delete_live_session_or_publish_capture(self):
        with tempfile.TemporaryDirectory(prefix="capture 空格 & ") as temporary:
            folder = Path(temporary)
            result = self.run_batch(folder, failure="stop")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual((folder / "light.etl").read_bytes(), b"previous capture")
            self.assertNotIn("delete -n", (folder / "calls.txt").read_text(encoding="utf-8"))

    def test_elevation_passes_quoted_script_to_cmd_without_starting_a_process(self):
        with tempfile.TemporaryDirectory(prefix="capture 空格 & ") as temporary:
            folder = Path(temporary)
            result = self.run_batch(folder, elevate=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            invocation = (folder / "elevation.txt").read_text(encoding="utf-8")
            self.assertEqual(invocation.splitlines()[1], '/d /s /c ""' + str(folder / "抓包.bat") + '""')
            self.assertFalse((folder / "calls.txt").exists())


if __name__ == "__main__":
    unittest.main()
