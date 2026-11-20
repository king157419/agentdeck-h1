"""Offline CLI lifecycle checks; no native inputs, windows or serial ports."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hub


class RuntimeTests(unittest.TestCase):
    def test_cli_defaults_to_auto_hold_and_enables_session_persistence(self):
        class Constructed(Exception):
            pass

        with tempfile.TemporaryDirectory() as directory:
            for mode in (None, "auto", "always", "never"):
                argv = ["--backend", "none", "--no-lcd", "--no-desktop", "--home", directory]
                if mode is not None:
                    argv += ["--hold-mode", mode]
                with self.subTest(mode=mode), patch("hub.logging.basicConfig"), patch(
                        "hub.Hub", side_effect=Constructed) as factory, self.assertRaises(Constructed):
                    hub.main(argv)
                self.assertEqual(factory.call_args.kwargs["hold_mode"], mode or "auto")
                self.assertEqual(factory.call_args.kwargs["sessions_path"],
                                 Path(directory) / ".agentdeck" / "sessions.json")

    def test_windows_reads_voice_shortcut_from_default_or_explicit_config(self):
        shortcut = {"key_codes": [0xA5], "modifiers": [], "mode": "hold"}
        class Constructed(Exception):
            pass
        with tempfile.TemporaryDirectory() as directory:
            for explicit in (False, True):
                config = Path(directory) / ("custom.json" if explicit else ".agentdeck/config.json")
                config.parent.mkdir(parents=True, exist_ok=True)
                config.write_text(json.dumps({"dictation_shortcut": shortcut}), encoding="utf-8")
                argv = ["--backend", "none", "--no-lcd", "--home", directory]
                if explicit:
                    argv += ["--config", str(config)]
                with self.subTest(explicit=explicit), patch("hub.logging.basicConfig"), patch(
                        "hub_desktop.DesktopEffects") as factory, patch(
                        "hub.Hub", side_effect=Constructed), self.assertRaises(Constructed):
                    hub.main(argv)
                factory.assert_called_once_with(shots_dir=Path(directory) / ".agentdeck/shots",
                                                dictation_shortcut=shortcut)

    def test_macos_imports_when_wintypes_is_unavailable(self):
        script = '''
import builtins
import sys
# Load installed dependencies using the host platform before simulating macOS.
import serial
from serial.tools import list_ports
import zstandard
sys.platform = "darwin"
original_import = builtins.__import__
def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "ctypes.wintypes" or (name == "ctypes" and "wintypes" in (fromlist or ())):
        raise ValueError("_type_ 'v' not supported")
    return original_import(name, globals, locals, fromlist, level)
builtins.__import__ = guarded_import
import hub
import hub_desktop_mac
import hub_hotkey
import hub_overlay
print("macOS imports OK without ctypes.wintypes")
'''
        result = subprocess.run([sys.executable, "-c", script],
                                cwd=Path(__file__).resolve().parent,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("macOS imports OK", result.stdout)

    def test_backend_combinations_and_rejections(self):
        self.assertEqual(hub.parse_backends("none"), ("none",))
        self.assertEqual(hub.parse_backends("hotkey"), ("hotkey",))
        self.assertEqual(hub.parse_backends(" USB, hotkey "), ("usb", "hotkey"))
        self.assertEqual(hub.parse_backends("hotkey,usb"), ("hotkey", "usb"))
        for value in ("", "none,hotkey", "usb,usb", "usb,", "rawinput", "auto"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                hub.parse_backends(value)

    def test_invalid_backend_exits_before_any_effect(self):
        with patch("hub.Hub", side_effect=AssertionError("must not construct")), patch(
                "sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit) as error:
            hub.main(["--backend", "usb,none"])
        self.assertEqual(error.exception.code, 2)

    def run_cli(self, backends, overlay_enabled=True, fail_overlay=False):
        inputs = []
        overlays = []
        owner = threading.get_ident()

        class Input:
            def __init__(self, *args, **kwargs):
                self.started = threading.Event()
                self.stopped = threading.Event()
                self.owner = None
                inputs.append(self)

            def run(self):
                self.owner = threading.get_ident()
                self.started.set()
                if not self.stopped.wait(3):
                    raise AssertionError("input was not stopped")

            def stop(self):
                self.stopped.set()

        class Server:
            server_port = 12345

            def __init__(self, *args):
                self.started = threading.Event()
                self.stopped = threading.Event()
                self.closed = False

            def serve_forever(self, **kwargs):
                self.started.set()
                if not overlay_enabled:
                    for reader in inputs:
                        if not reader.started.wait(2):
                            raise AssertionError("input did not start")
                    raise KeyboardInterrupt
                if not self.stopped.wait(3):
                    raise AssertionError("HTTP server was not stopped")

            def shutdown(self):
                self.stopped.set()

            def server_close(self):
                self.closed = True

        server = Server()
        test = self

        class Overlay:
            def __init__(self, engine):
                self.engine = engine
                self.stopped = False
                overlays.append(self)

            def run(self):
                test.assertEqual(threading.get_ident(), owner)
                test.assertTrue(server.started.wait(2))
                for reader in inputs:
                    test.assertTrue(reader.started.wait(2))
                    test.assertNotEqual(reader.owner, owner)
                if fail_overlay:
                    raise RuntimeError("fake Tk initialization failed")

            def stop(self):
                self.stopped = True

        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {
                "hub_hotkey": SimpleNamespace(HotkeyInput=Input),
                "hub_overlay": SimpleNamespace(Overlay=Overlay)}), patch(
                "hub_keyboard.KeyboardInput", Input), patch("hub.HubServer", return_value=server), patch(
                "hub_desktop.DesktopEffects", side_effect=AssertionError("native output")):
            argv = ["--backend", backends, "--no-lcd", "--no-desktop", "--home", directory]
            if overlay_enabled:
                argv.append("--overlay")
            if fail_overlay:
                with self.assertRaisesRegex(RuntimeError, "fake Tk initialization"):
                    hub.main(argv)
            else:
                self.assertEqual(hub.main(argv), 0)
            self.assertTrue((Path(directory) / ".agentdeck" / "token").exists())
        self.assertTrue(server.closed)
        self.assertTrue(all(reader.stopped.is_set() for reader in inputs))
        self.assertTrue(all(overlay.stopped for overlay in overlays))
        self.assertFalse(any(thread.name in ("AgentDeck HTTP", "AgentDeck USB", "AgentDeck hotkeys",
                                            "AgentDeck LCD hold") for thread in threading.enumerate()))
        return len(inputs)

    def test_overlay_alone_and_with_each_backend(self):
        for backend, count in (("none", 0), ("usb", 1), ("hotkey", 1), ("usb,hotkey", 2)):
            with self.subTest(backend=backend):
                self.assertEqual(self.run_cli(backend), count)

    def test_combined_readers_without_overlay_stop_on_interrupt(self):
        self.assertEqual(self.run_cli("usb,hotkey", overlay_enabled=False), 2)

    def test_overlay_startup_failure_stops_http_and_all_readers(self):
        self.assertEqual(self.run_cli("usb,hotkey", fail_overlay=True), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
