"""Inspect the built bundle and smoke-test only the short-lived offline relay.

Never starts the main application, opens a device, or reads the real user's home.
"""
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import threading

from PyInstaller.archive.readers import CArchiveReader


def main():
    root = Path(__file__).resolve().parents[1]
    bundle = root / "dist" / "AgentDeck"
    result = {}
    for name, subsystem in (("AgentDeck.exe", 2), ("AgentDeck-relay.exe", 3)):
        path = bundle / name
        data = path.read_bytes()
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        assert data[pe:pe + 4] == b"PE\0\0", name
        actual = struct.unpack_from("<H", data, pe + 24 + 68)[0]
        assert actual == subsystem, (name, actual)
        result[name] = {"path": str(path), "size": len(data), "subsystem": actual,
                        "sha256": hashlib.sha256(data).hexdigest()}
    required = ["hub_keys.json", "hub_prompts.json", "agentdeck.ico", "python313.dll",
                "_tkinter.pyd", "_tcl_data/init.tcl", "_tk_data/tk.tcl",
                "libusb_package/libusb-1.0.dll"]
    for filename in required:
        path = bundle / "_internal" / filename
        assert path.is_file(), filename
        if filename.endswith(".json"):
            assert isinstance(json.loads(path.read_text(encoding="utf-8-sig")), dict), filename
    result["bundled_assets"] = required
    archive = CArchiveReader(str(bundle / "AgentDeck.exe"))
    embedded = next(name for name in archive.toc if name.endswith(".pyz"))
    modules = ["agentdeck_icon", "hub", "hub_overlay", "hub_install", "hub_doctor", "hub_hotkey", "hub_desktop",
               "hub_risk", "usb.backend.libusb1", "libusb_package", "pystray", "pystray._win32",
               "tkinter", "PIL.Image"]
    contents = archive.open_embedded_archive(embedded)
    for module in modules:
        assert module in contents.toc, module
    result["main_bundled_modules"] = modules
    with tempfile.TemporaryDirectory(prefix="agentdeck-relay-exe-") as home:
        completed = subprocess.run(
            [str(bundle / "AgentDeck-relay.exe"), "--agent", "cx", "--home", home],
            input=b'{"hook_event_name":"SessionStart","session_id":"offline"}',
            capture_output=True, timeout=15)
        assert completed.returncode == 0, (completed.returncode, completed.stderr)
        assert completed.stdout == b"" and completed.stderr == b"", (completed.stdout, completed.stderr)
        result["relay_offline"] = {"exit_code": completed.returncode, "stdout_bytes": 0,
                                   "stderr_bytes": 0, "temporary_home": True}
        token = "package-check-temporary-token"
        folder = Path(home) / ".agentdeck"
        folder.mkdir()
        (folder / "token").write_text(token + "\n", encoding="utf-8")
        event = {"hook_event_name": "PermissionRequest", "session_id": "package-check",
                 "cwd": home, "tool_name": "Bash", "tool_input": {"command": "pytest -q"}}
        decision = (b'{ "hookSpecificOutput": { "hookEventName": "PermissionRequest", '
                    b'"decision": {"behavior": "allow"} } }\n')
        observed = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                observed.update(path=self.path, token=self.headers.get("X-AgentDeck-Token"),
                                event=json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(decision)))
                self.end_headers()
                self.wfile.write(decision)

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            server.timeout = 5
            worker = threading.Thread(target=server.handle_request, daemon=True)
            worker.start()
            try:
                completed = subprocess.run(
                    [str(bundle / "AgentDeck-relay.exe"), "--agent", "cx", "--home", home,
                     "--port", str(server.server_port)],
                    input=json.dumps(event).encode("utf-8"), capture_output=True, timeout=15)
            finally:
                worker.join(timeout=6)
            assert not worker.is_alive(), "temporary HTTP fixture did not stop"
        assert completed.returncode == 0, (completed.returncode, completed.stderr)
        assert completed.stdout == decision, (completed.stdout, decision)
        assert completed.stderr == b"", completed.stderr
        assert observed == {"path": "/event?agent=cx", "token": token, "event": event}, observed
        result["relay_http"] = {"exit_code": 0, "request_path": observed["path"],
                                "token_header_verified": True, "event_payload_verified": True,
                                "original_decision_bytes_preserved": True,
                                "response_bytes": len(decision), "temporary_loopback_fixture": True}
    result["bundle_bytes"] = sum(p.stat().st_size for p in bundle.rglob("*") if p.is_file())
    result["validation_groups"] = {"pe_subsystems": 2, "bundled_assets": len(required),
                                    "archived_modules": len(modules), "relay_scenarios": 2}
    report = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    (root / "research" / "app-exe-package-check.json").write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
