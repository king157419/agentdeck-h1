"""Overlay and UI-loop regressions (F1, F2, F3, F5 show key, F6).

Pure tests use substitutes. The marked live tests open a real Tk overlay for a
few seconds and read Raw Input from the macropad (read-only, never USB/0xFF00).
They use a temporary home and a random port, never the running AgentDeck.
Set AGENTDECK_SOAK_SECONDS to lengthen the soak (default 6).
"""
import ctypes
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hub  # noqa: E402
from hub_overlay import (ABSENT_NOTICE, DRIVER_NOTICE, EMPTY_TEXT, NoActivateWindow, Overlay,  # noqa: E402
                         display_model)
from hub_watchdog import Watchdog  # noqa: E402

SOAK_SECONDS = float(os.environ.get("AGENTDECK_SOAK_SECONDS", "6"))


class FakeHub:
    def __init__(self, state=None):
        self.lock = threading.RLock()
        self.home = None
        self.value = state or {"sessions": []}
        self.actions = []

    def state(self):
        return dict(self.value)

    def monotonic(self):
        return time.monotonic()

    def record_rendered(self, *args, **kwargs):
        pass

    def hide_display(self, source):
        pass

    def action(self, payload, **kwargs):
        self.actions.append(payload)
        return {"status": "selected"}


class ModelTests(unittest.TestCase):
    def test_sessions_are_listed_without_pending_and_empty_state_is_explained(self):
        model = display_model({"sessions": [{"slot": 2, "name": "api", "state": "think"}]})
        self.assertTrue(model["expanded"])
        self.assertEqual([slot["number"] for slot in model["slots"] if slot["occupied"]], [2])
        self.assertEqual(model["empty_text"], "")
        self.assertEqual(display_model({})["empty_text"], EMPTY_TEXT)

    def test_key_feedback_lasts_two_seconds(self):
        state = {"last_input": {"text": "槽位 1 没有会话", "ok": False, "at": 100.0}}
        self.assertEqual(display_model(state, now=101.0)["feedback"], {"text": "槽位 1 没有会话", "ok": False})
        self.assertIsNone(display_model(state, now=102.5)["feedback"])
        self.assertIsNone(display_model(state)["feedback"])

    def test_reader_notice_only_for_raw_input(self):
        self.assertEqual(display_model({"input_reader": "raw"})["notice"], DRIVER_NOTICE)
        self.assertTrue(display_model({"input_reader": "raw"})["notice_action"])
        self.assertEqual(display_model({"input_reader": "usb"})["notice"], "")
        self.assertEqual(display_model({"input_reader": "absent"})["notice"], ABSENT_NOTICE)
        self.assertEqual(display_model({})["notice"], "")

    def test_needs_answer_hint(self):
        model = display_model({"sessions": [{"slot": 1, "name": "app", "state": "wait",
                                             "needs_answer": "AskUserQuestion"}]})
        self.assertEqual(model["slots"][0]["hint"], "需回答")


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.hub = FakeHub()
        self.overlay = Overlay(self.hub, window=Mock())
        for name in ("status_label", "feedback_label", "alpha_button", "body", "note", "empty_label", "notice_label"):
            setattr(self.overlay, name, Mock())
        self.overlay.rows = []

    def test_feedback_notice_and_empty_state_render(self):
        self.overlay.model = display_model({"input_reader": "raw", "last_input": {
            "text": "槽位 2 没有会话", "ok": False, "at": time.time()}}, now=time.time())
        self.overlay._render()
        self.assertEqual(self.overlay.status_label.configure.call_args.kwargs["text"], "0 个会话")
        self.assertEqual(self.overlay.feedback_label.configure.call_args.kwargs["text"], "槽位 2 没有会话")
        self.overlay.feedback_label.grid.assert_called_once_with()
        self.overlay.notice_label.grid.assert_called_once_with()
        self.assertIn(DRIVER_NOTICE, self.overlay.notice_label.configure.call_args.kwargs["text"])
        self.overlay.empty_label.grid.assert_called_once_with()
        self.overlay.model = display_model({"input_reader": "usb", "sessions": [{"slot": 1, "name": "a"}]})
        self.overlay._render()
        self.overlay.notice_label.grid_remove.assert_called_once_with()
        self.overlay.empty_label.grid_remove.assert_called_once_with()
        self.overlay.feedback_label.grid_remove.assert_called_once_with()

    def test_clicking_a_header_dot_selects_that_session(self):
        self.overlay.model = display_model({"sessions": [{"slot": 2, "name": "a"}, {"slot": 5, "name": "b"}]})
        self.assertEqual([self.overlay._dot_slot(x) for x in (0, 9, 15, 30, -1)], [2, 2, 5, None, None])
        self.overlay.root = Mock()
        with patch.object(self.overlay, "dispatch") as dispatch:
            self.overlay._drag, self.overlay._dragged = (0, 0), False
            self.overlay._dots_release(Mock(x=16))
            dispatch.assert_called_once_with("slot 5")
            dispatch.reset_mock()
            self.overlay._drag, self.overlay._dragged = (0, 0), True  # a drag never selects
            self.overlay._pos, self.overlay._height = (0, 0), 50
            with patch.object(self.overlay, "_place"), patch.object(self.overlay, "_save_prefs"):
                self.overlay._dots_release(Mock(x=16))
            dispatch.assert_not_called()


class PollTests(unittest.TestCase):
    def test_poll_beats_first_even_when_state_fails(self):
        hub_ = FakeHub()
        hub_.state = Mock(side_effect=RuntimeError("busy"))
        overlay = Overlay(hub_, window=Mock())
        overlay.root = Mock()
        overlay.heartbeat = Mock()
        overlay._poll()
        overlay.heartbeat.assert_called_once_with()
        overlay.root.after.assert_called_once()

    def test_show_key_unhides_overlay(self):
        hub_ = FakeHub({"sessions": [], "show_requests": 3})
        overlay = Overlay(hub_, window=Mock())
        overlay.root = Mock()
        overlay.root.state.return_value = "withdrawn"
        overlay.hidden = True
        with patch.object(overlay, "_render"), patch.object(overlay, "show") as show:
            overlay._poll()  # first value is only remembered
            show.assert_not_called()
            hub_.value["show_requests"] = 4
            overlay._poll()
            show.assert_called_once_with()


class FakeUI:
    """Stands in for TrayApplication: beats like Overlay._poll every 300 ms."""

    def __init__(self, engine, polls=15, stall_after=None, stall_seconds=0):
        self.engine, self.polls = engine, polls
        self.stall_after, self.stall_seconds = stall_after, stall_seconds
        self.heartbeat = None
        self.stopped = threading.Event()
        self.states = []

    def run(self):
        for index in range(self.polls):
            if self.stopped.is_set():
                break
            if self.heartbeat is not None:
                self.heartbeat()
            self.states.append(self.engine.state())
            if index == self.stall_after:
                time.sleep(self.stall_seconds)  # a real blocked Tk loop
            time.sleep(0.3)

    def stop(self):
        self.stopped.set()


class WatchdogWiringTests(unittest.TestCase):
    def run_main(self, factory, *extra):
        with tempfile.TemporaryDirectory() as home:
            return hub.main(["--backend", "none", "--overlay", "--no-lcd", "--no-desktop", "--port", "0",
                             "--home", home, *extra], ui_factory=factory)

    def test_polling_ui_never_reports_a_stall(self):
        uis = []
        with self.assertNoLogs("agentdeck.hub.watchdog", "WARNING"):
            self.assertEqual(self.run_main(lambda engine: uis.append(FakeUI(engine)) or uis[-1]), 0)
        self.assertEqual(len(uis[0].states), 15)

    def test_real_stall_is_reported_once_and_recovery_logged(self):
        with self.assertLogs("agentdeck.hub.watchdog", "INFO") as logs:
            self.run_main(lambda engine: FakeUI(engine, polls=4, stall_after=1, stall_seconds=3.6))
        text = "\n".join(logs.output)
        self.assertEqual(text.count("UI 卡顿"), 1)
        self.assertIn("UI 已恢复", text)


@unittest.skipUnless(sys.platform == "win32", "Windows window styles")
class LiveOverlayTests(unittest.TestCase):
    """F3 + F6 with real Tk: tool-window bits survive alpha; no false stall."""

    def test_overlay_keeps_tool_window_style_and_beats(self):
        user = ctypes.WinDLL("user32", use_last_error=True)
        get_long = user.GetWindowLongPtrW
        get_long.argtypes, get_long.restype = [ctypes.c_void_p, ctypes.c_int], ctypes.c_ssize_t
        user.IsWindowVisible.argtypes = [ctypes.c_void_p]
        styles = []
        watchdog = Watchdog()
        with tempfile.TemporaryDirectory() as directory:
            overlay = Overlay(FakeHub({"sessions": [{"slot": 1, "name": "demo", "state": "think"}]}),
                              state_path=Path(directory) / "overlay.json")
            overlay.heartbeat = lambda: watchdog.beat("UI")

            def sample(label):
                hwnd = overlay.window.hwnd
                styles.append((label, get_long(hwnd, -20), bool(user.IsWindowVisible(hwnd))))

            def ready():
                root = overlay.root
                root.after(300, lambda: sample("start"))
                root.after(600, overlay.toggle_translucent)
                root.after(900, lambda: sample("opaque"))
                root.after(1200, overlay.toggle_translucent)
                root.after(1500, lambda: sample("translucent"))
                root.after(1800, overlay.hide)
                root.after(2100, overlay.show)
                root.after(2400, lambda: sample("reshown"))
                root.after(5000, overlay.stop)

            watchdog.watch("UI")
            watchdog.start()
            try:
                with self.assertNoLogs("agentdeck.hub.watchdog", "WARNING"):
                    overlay.run(on_ready=ready)
            finally:
                watchdog.stop()
        self.assertEqual([label for label, _, _ in styles], ["start", "opaque", "translucent", "reshown"])
        for label, style, visible in styles:
            with self.subTest(label=label):
                self.assertTrue(style & 0x80, "WS_EX_TOOLWINDOW lost -> taskbar button")
                self.assertTrue(style & 0x08000000, "WS_EX_NOACTIVATE lost")
                self.assertFalse(style & 0x40000, "WS_EX_APPWINDOW set")
                self.assertTrue(visible)


class NoRegistry:
    """Run key and tray records substitute: nothing registered, writes recorded."""
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.writes = []

    def OpenKey(self, *args):
        raise FileNotFoundError(args[1] if len(args) > 1 else "key")

    def CreateKeyEx(self, *args):
        return self

    def SetValueEx(self, key, name, reserved, kind, value):
        self.writes.append((name, value))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class RealTkWindowTests(unittest.TestCase):
    """The status window, driver guide and overlay menu build with real Tk."""

    def texts(self, widget):
        found = []
        for child in widget.winfo_children():
            try:
                found.append(str(child.cget("text")))
            except Exception:
                pass
            if child.winfo_class() == "Text":
                found.append(child.get("1.0", "end"))
            found.extend(self.texts(child))
        return found

    def test_status_and_guide_windows(self):
        import tkinter as tk
        from queue import SimpleQueue
        import agentdeck_app as app
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as directory:
            registry = NoRegistry()
            application = app.TrayApplication(
                Mock(home=Path(directory)), commands=SimpleQueue(), prefs=app.Preferences(Path(directory)),
                keys_path=app.resource_dir() / "hub_keys.json", autostart=app.AutoStart(
                    registry, "AgentDeck.exe", scheduler=Mock(query=Mock(return_value=None)), sid="test-sid"),
                overlay=Mock(root=root, hidden=False, state={}), registry=registry)
            application.state = {"sessions": [], "input_reader": "raw"}
            window = application.show_status()
            root.update()
            texts = " ".join(self.texts(window))
            for needle in ("开始使用", "完成", "未启用", "按键会同时打字", "装驱动说明", "右下角 ^"):
                self.assertIn(needle, texts)
            guide = application.show_driver_guide()
            root.update()
            text = " ".join(self.texts(guide))
            self.assertIn("4132 2107 00", text)
            self.assertIn("打开 Zadig 网站", text)
            self.assertEqual(registry.writes, [])
            overlay = Overlay(FakeHub())
            overlay.root = root
            overlay.menu_items = application.overlay_menu
            with patch.object(tk.Menu, "tk_popup") as popup:
                menu = overlay.open_menu()
            popup.assert_called_once()
            labels = [menu.entrycget(index, "label") for index in range(menu.index("end") + 1)
                      if menu.type(index) == "command"]
            self.assertEqual(labels[:2], ["状态", "下一个待批"])
            self.assertIn("装驱动说明", labels)

    @staticmethod
    def pump_until(root, predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            root.update()
            if predicate():
                return True
            time.sleep(0.02)
        root.update()
        return predicate()

    def test_status_window_follows_state_that_arrives_after_it_opens(self):
        """Acceptance 2026-11-19: the window opened at startup (empty state) kept showing
        '会话 0 个' and '读键方式 启动中…' minutes later, so the Raw Input row and its
        '装驱动说明' button never appeared. Real Tk, real 1 s timer."""
        import tkinter as tk
        from queue import SimpleQueue
        import agentdeck_app as app
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as directory:
            registry = NoRegistry()
            application = app.TrayApplication(
                Mock(home=Path(directory)), commands=SimpleQueue(), prefs=app.Preferences(Path(directory)),
                keys_path=app.resource_dir() / "hub_keys.json", autostart=app.AutoStart(
                    registry, "AgentDeck.exe", scheduler=Mock(query=Mock(return_value=None)), sid="test-sid"),
                overlay=Mock(root=root, hidden=False, state={}), registry=registry)
            application.state = {}
            window = application.show_status()
            root.update()
            text = lambda: " ".join(self.texts(window))
            self.assertIn("启动中", text())
            self.assertIn("0 个", text())
            self.assertNotIn("装驱动说明", text())

            application.state = {"sessions": [{"slot": 1}, {"slot": 2}], "input_reader": "raw"}
            self.assertTrue(self.pump_until(root, lambda: "装驱动说明" in text(), 3), text())
            self.assertIn("2 个", text())
            self.assertIn("按键会同时打字", text())
            self.assertNotIn("启动中", text())
            self.assertIs(application.status_window, window)
            self.assertTrue(window.winfo_exists())

            # Value-only change: same widgets, new text (a click in progress is not lost).
            paths = sorted(str(w) for w in window.winfo_children()[0].winfo_children())
            application.state = {"sessions": [{"slot": 1}, {"slot": 2}, {"slot": 3}], "input_reader": "raw"}
            self.assertTrue(self.pump_until(root, lambda: "3 个" in text(), 3), text())
            self.assertEqual(sorted(str(w) for w in window.winfo_children()[0].winfo_children()), paths)

            # Closed with the window's own button: no further refresh, no Tcl errors.
            button = next(w for w in window.winfo_children()[0].winfo_children()
                          if w.winfo_class() == "Frame" and w.winfo_children())
            done = next(w for w in button.winfo_children() if w.cget("text") == "完成")
            done.event_generate("<ButtonRelease-1>")
            root.update()
            self.assertIsNone(application.status_window)
            self.assertFalse(window.winfo_exists())
            pending = [str(root.tk.call("after", "info", timer)) for timer in root.tk.splitlist(root.tk.call("after", "info"))]
            self.assertFalse([script for script in pending if "refresh" in script], pending)
            errors = []
            root.report_callback_exception = lambda *args: errors.append(args)
            self.pump_until(root, lambda: False, 1.3)
            self.assertEqual(errors, [])

    def test_replaced_or_torn_down_status_window_leaves_no_timer(self):
        import tkinter as tk
        from queue import SimpleQueue
        import agentdeck_app as app
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as directory:
            registry = NoRegistry()
            application = app.TrayApplication(
                Mock(home=Path(directory)), commands=SimpleQueue(), prefs=app.Preferences(Path(directory)),
                keys_path=app.resource_dir() / "hub_keys.json", autostart=app.AutoStart(
                    registry, "AgentDeck.exe", scheduler=Mock(query=Mock(return_value=None)), sid="test-sid"),
                overlay=Mock(root=root, hidden=False, state={}), registry=registry)
            application.state = {"sessions": [], "input_reader": "usb"}

            def refresh_timers():
                return [timer for timer in root.tk.splitlist(root.tk.call("after", "info"))
                        if "refresh" in str(root.tk.call("after", "info", timer))]

            first = application.show_status()
            root.update()
            second = application.show_status()  # "状态" again while open
            root.update()
            self.assertFalse(first.winfo_exists())
            self.assertIs(application.status_window, second)
            self.assertEqual(len(refresh_timers()), 1)
            second.destroy()  # e.g. torn down with the app
            root.update()
            self.assertEqual(refresh_timers(), [])


@unittest.skipUnless(sys.platform == "win32", "Raw Input soak")
class SoakTests(unittest.TestCase):
    """F2: the app spawns no child processes (each spawn shows a busy cursor)."""

    def test_hub_with_real_keyboard_reader_spawns_nothing(self):
        # Real reader on purpose: it guards against driver detection spawning
        # PowerShell again. Raw Input and the registry are only read.
        spawned = []
        real_popen = subprocess.Popen

        def refuse(*args, **kwargs):
            spawned.append(args[0] if args else kwargs.get("args"))
            raise OSError("AgentDeck must not spawn processes at runtime")

        polls = max(1, int(SOAK_SECONDS / 0.3))
        uis = []
        with patch("subprocess.Popen", side_effect=refuse), self.assertNoLogs("agentdeck.hub.watchdog", "WARNING"):
            with tempfile.TemporaryDirectory() as home:
                code = hub.main(["--backend", "usb", "--overlay", "--no-lcd", "--no-desktop", "--port", "0",
                                 "--home", home], ui_factory=lambda engine: uis.append(FakeUI(engine, polls)) or uis[-1])
        self.assertIs(subprocess.Popen, real_popen)
        self.assertEqual(code, 0)
        self.assertEqual(spawned, [])
        readers = {state.get("input_reader") for state in uis[0].states}
        self.assertTrue(readers <= {None, "raw", "usb", "absent"}, readers)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    unittest.main(verbosity=2)
