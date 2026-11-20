"""Screenshot attachments and feedback; all desktop/native boundaries are fake."""
import ctypes
from io import BytesIO
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import hub
from hub_desktop import DesktopEffects, HubWindowControl, set_clipboard, set_image_clipboard
from test_hub_desktop import SESSION, Windows


class Clipboard:
    def __init__(self):
        self.opened = False
        self.blocks = {}
        self.formats = {}
        self.user = SimpleNamespace(
            GetForegroundWindow=Mock(return_value=22),
            OpenClipboard=Mock(side_effect=self.open),
            EmptyClipboard=Mock(return_value=True),
            RegisterClipboardFormatW=Mock(return_value=0xC001),
            SetClipboardData=Mock(side_effect=self.set),
            CloseClipboard=Mock(side_effect=self.close))
        self.kernel = SimpleNamespace(
            GlobalAlloc=Mock(side_effect=self.allocate),
            GlobalLock=Mock(side_effect=lambda handle: ctypes.addressof(self.blocks[handle])),
            GlobalUnlock=Mock(return_value=True),
            GlobalFree=Mock(return_value=None))

    def open(self, owner):
        assert owner and not self.opened
        self.opened = True
        return True

    def close(self):
        assert self.opened
        self.opened = False
        return True

    def allocate(self, flags, size):
        assert flags == 0x0002
        handle = len(self.blocks) + 1
        self.blocks[handle] = ctypes.create_string_buffer(size)
        return handle

    def set(self, format_id, handle):
        assert self.opened
        self.formats[format_id] = self.blocks[handle].raw
        return handle

    def native(self):
        return patch("hub_desktop.ctypes.WinDLL", side_effect=lambda name, **kwargs: {
            "user32": self.user, "kernel32": self.kernel}[name])


class ScreenshotWindows(Windows):
    terminal = False

    def is_terminal(self, hwnd):
        return self.terminal


class ScreenshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clipboard = Clipboard()
        self.windows = ScreenshotWindows()
        self.text = []
        self.image = Image.new("RGBA", (3, 2), (23, 45, 67, 128))
        self.image.putpixel((0, 0), (1, 2, 3, 255))
        self.effects = DesktopEffects(self.windows, clipboard=self.text.append,
                                      capture=lambda: self.image, shots_dir=self.temp.name)

    def target(self, process, *, title="Claude", key="cc-abcdef"):
        window = (22, process, title)
        self.windows.items = [window]
        return dict(SESSION, key=key, hwnd=22, window_exe=process)

    def assert_image_formats(self):
        self.assertEqual(set(self.clipboard.formats), {8, 0xC001})
        self.clipboard.user.RegisterClipboardFormatW.assert_called_once_with("PNG")
        dib, png = self.clipboard.formats[8], self.clipboard.formats[0xC001]
        self.assertEqual(struct.unpack_from("<IiiHH", dib), (40, 3, 2, 1, 24))
        header = b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, 54)
        with Image.open(BytesIO(header + dib)) as decoded:
            self.assertEqual(decoded.tobytes(), self.image.convert("RGB").tobytes())
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(BytesIO(png)) as decoded:
            self.assertEqual(decoded.tobytes(), self.image.tobytes())
        self.assertFalse(self.clipboard.opened)
        self.clipboard.user.CloseClipboard.assert_called_once_with()
        self.clipboard.kernel.GlobalFree.assert_not_called()

    def test_claude_saves_png_and_pastes_both_image_formats_without_enter(self):
        session = self.target("C:/Program Files/Claude/CLAUDE.EXE")
        with self.clipboard.native():
            result = self.effects.screenshot(session, [session])
        self.assertEqual(result["paste"], "image")
        self.assertEqual(self.windows.activated, [22])
        self.assertTrue(Path(result["path"]).is_file())
        with Image.open(result["path"]) as saved:
            self.assertEqual(saved.tobytes(), self.image.tobytes())
        self.assert_image_formats()
        self.assertEqual(self.text, [])
        self.assertEqual(self.windows.combos, [(0x11, 0x56)])
        self.assertEqual(self.windows.keys, [])

    def test_codex_gui_uses_image_for_process_names_containing_codex(self):
        for process in ("codex.exe", "C:/apps/Codex Desktop.exe"):
            with self.subTest(process=process):
                self.clipboard = Clipboard()
                session = self.target(process, title="Codex", key="cx-abcdef")
                with self.clipboard.native():
                    result = self.effects.screenshot(session, [session])
                self.assertEqual(result["paste"], "image")
                self.assert_image_formats()
        self.assertEqual(self.text, [])
        self.assertEqual(self.windows.combos, [(0x11, 0x56)] * 2)
        self.assertEqual(self.windows.keys, [])

    def test_terminal_and_editor_titles_do_not_enable_image_paste(self):
        self.effects.image_clipboard = Mock(side_effect=AssertionError("image clipboard"))
        for process in ("WindowsTerminal.exe", "pwsh.exe", "Code.exe"):
            with self.subTest(process=process):
                session = self.target(process, title="app - Claude Codex")
                path = self.effects.screenshot(session, [session])
                self.assertIsInstance(path, str)
                self.assertTrue(Path(path).is_file())
                self.assertEqual(self.text[-1], path)
        self.assertEqual(self.windows.combos, [(0x11, 0x56)] * 3)
        self.assertEqual(self.windows.keys, [])

    def test_codex_console_window_still_pastes_path(self):
        session = self.target("codex.exe", key="cx-abcdef")
        self.windows.terminal = True
        self.effects.image_clipboard = Mock(side_effect=AssertionError("image clipboard"))
        path = self.effects.screenshot(session, [session])
        self.assertEqual(self.text, [path])
        self.assertEqual(self.windows.combos, [(0x11, 0x56)])
        self.assertEqual(self.windows.keys, [])

    def test_clipboard_open_failure_sends_no_keys_and_leaves_no_open_clipboard(self):
        session = self.target("claude.exe")
        self.clipboard.user.OpenClipboard.side_effect = None
        self.clipboard.user.OpenClipboard.return_value = False
        with self.clipboard.native(), self.assertRaises(OSError):
            self.effects.screenshot(session, [session])
        self.assertFalse(self.clipboard.opened)
        self.clipboard.user.EmptyClipboard.assert_not_called()
        self.clipboard.user.CloseClipboard.assert_not_called()
        self.clipboard.kernel.GlobalAlloc.assert_not_called()
        self.assertEqual(self.windows.combos, [])
        self.assertEqual(self.windows.keys, [])
        self.assertEqual(len(list(Path(self.temp.name).glob("*.png"))), 1)

    def test_focus_change_during_image_copy_never_pastes(self):
        session = self.target("claude.exe")
        self.effects.image_clipboard = lambda image: setattr(self.windows, "foreground", (99, "", "other"))
        with self.assertRaisesRegex(RuntimeError, "foreground changed"):
            self.effects.screenshot(session, [session])
        self.assertEqual(self.windows.combos, [])
        self.assertEqual(self.windows.keys, [])

    def test_failed_image_paste_never_sends_enter(self):
        session = self.target("claude.exe")
        self.windows.input_ok = False
        with self.clipboard.native(), self.assertRaisesRegex(RuntimeError, "key combination failed"):
            self.effects.screenshot(session, [session])
        self.assertFalse(self.clipboard.opened)
        self.assertEqual(self.windows.keys, [])


class ClipboardTests(unittest.TestCase):
    def test_unicode_text_keeps_existing_clipboard_format(self):
        clipboard = Clipboard()
        with clipboard.native():
            set_clipboard("跑测试")
        self.assertEqual(clipboard.formats, {13: "跑测试\0".encode("utf-16-le")})
        self.assertFalse(clipboard.opened)
        clipboard.kernel.GlobalFree.assert_not_called()

    def test_failures_close_clipboard_and_free_only_untransferred_memory(self):
        failures = {"EmptyClipboard": (False, 0), "RegisterClipboardFormatW": (0, 0),
                    "GlobalAlloc": (0, 0), "GlobalLock": (0, 1), "SetClipboardData": (0, 1)}
        for name, (value, free_count) in failures.items():
            with self.subTest(name=name):
                clipboard = Clipboard()
                function = getattr(clipboard.user, name, None) or getattr(clipboard.kernel, name)
                function.side_effect, function.return_value = None, value
                with clipboard.native(), self.assertRaises(OSError):
                    set_image_clipboard(Image.new("RGB", (2, 2)))
                self.assertFalse(clipboard.opened)
                clipboard.user.CloseClipboard.assert_called_once_with()
                self.assertEqual(clipboard.kernel.GlobalFree.call_count, free_count)

    def test_second_format_failure_leaves_first_handle_owned_by_windows(self):
        clipboard = Clipboard()
        clipboard.user.SetClipboardData.side_effect = lambda fmt, handle: (
            clipboard.set(fmt, handle) if fmt == 8 else 0)
        with clipboard.native(), self.assertRaises(OSError):
            set_image_clipboard(Image.new("RGB", (2, 2)))
        self.assertEqual(set(clipboard.formats), {8})
        clipboard.kernel.GlobalFree.assert_called_once_with(2)
        self.assertFalse(clipboard.opened)

    def test_console_classes_are_distinguished_from_electron_gui(self):
        native = HubWindowControl.__new__(HubWindowControl)
        for name in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS",
                     "PseudoConsoleWindow", "Chrome_WidgetWin_1"):
            with self.subTest(name=name):
                def get_class(hwnd, buffer, length):
                    buffer.value = name
                    return len(name)
                native.user = SimpleNamespace(GetClassNameW=Mock(side_effect=get_class))
                self.assertEqual(native.is_terminal(22), name != "Chrome_WidgetWin_1")


class FeedbackTests(unittest.TestCase):
    def test_image_and_path_have_distinct_success_feedback(self):
        self.assertEqual(hub.describe_input("screenshot", {"status": "sent", "paste": "image"}),
                         ("截图已贴进输入框", True, None))
        self.assertEqual(hub.describe_input("screenshot", {"status": "sent", "path": "shot.png"}),
                         ("已截图并粘贴路径", True, None))

    def test_hub_preserves_screenshot_metadata_for_key_feedback(self):
        from test_hub import HubTests
        fixture = HubTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.event("SessionStart")
        fixture.desktop.screenshot = lambda session, sessions: {"path": "shot.png", "paste": "image"}
        result = fixture.engine.action({"action": "screenshot"})
        self.assertEqual(result, {"action": "screenshot", "status": "sent",
                                  "path": "shot.png", "paste": "image"})
        self.assertEqual(hub.describe_input("screenshot", result)[0], "截图已贴进输入框")

    def test_raw_input_screenshot_remains_blocked(self):
        from test_hub import HubTests
        fixture = HubTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.event("SessionStart")
        notes = []
        fixture.engine.note_input = lambda text, ok=True, lcd=None: notes.append((text, ok))
        keys = hub.USBKeys(fixture.engine, {"bindings": {}})
        self.assertFalse(keys._dispatch("hid:0x0F", "screenshot", {},
                                        fixture.engine.monotonic(), "Raw Input"))
        self.assertEqual(len(notes), 1)
        self.assertIn(hub.LEAK_TEXT, notes[0][0])
        self.assertFalse(notes[0][1])
        self.assertEqual(fixture.desktop.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
