"""Windows notifier wakes and render acknowledgement ordering regressions.

All Hub state lives in temporary directories; no serial or keyboard I/O is used.
The Windows tests briefly create real Tk windows and call GetMessageW directly.
"""
import ctypes
import io
import logging
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hub
import hub_overlay
import hub_virtual_device
from hub_overlay import Overlay
from hub_watchdog import Watchdog


class FakeHub:
    def __init__(self):
        self.lock = threading.RLock()
        self.home = None
        self.value = {"sessions": []}
        self.record_rendered = Mock()
        self.hide_display = Mock()

    def state(self):
        return dict(self.value)

    def monotonic(self):
        return time.monotonic()


class TkWakerTests(unittest.TestCase):
    def test_periodic_posts_and_idempotent_stop(self):
        post = Mock(return_value=True)
        with patch.object(hub_overlay.os, "name", "nt"):
            waker = hub_overlay.TkWaker(1234, interval=.05, post=post)
            threads = []
            waker.start()
            waker.start()
            try:
                deadline = time.monotonic() + .5
                while post.call_count < 3 and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertGreaterEqual(post.call_count, 3)
                threads = [thread for thread in threading.enumerate()
                           if thread.name == "AgentDeck UI wake"]
                self.assertEqual(len(threads), 1)
                self.assertTrue(threads[0].daemon)
                for call in post.call_args_list:
                    self.assertEqual(call.args, (1234, 0, 0, 0))
            finally:
                waker.stop()
                waker.stop()
            self.assertFalse(threads[0].is_alive())
            count = post.call_count
            time.sleep(.12)
            self.assertEqual(post.call_count, count)

    def test_missing_handle_and_non_windows_do_not_post(self):
        post = Mock()
        for platform, hwnd in (("nt", None), ("nt", 0), ("posix", 1234)):
            with self.subTest(platform=platform, hwnd=hwnd):
                with patch.object(hub_overlay.os, "name", platform):
                    waker = hub_overlay.TkWaker(hwnd, post=post)
                    self.assertFalse(waker.wake())
                    waker.stop()
        post.assert_not_called()

    def test_post_exception_does_not_end_thread(self):
        calls = []
        continued = threading.Event()

        def post(*args):
            calls.append(args)
            if len(calls) == 1:
                raise OSError("injected PostMessage failure")
            continued.set()
            return True

        with patch.object(hub_overlay.os, "name", "nt"):
            waker = hub_overlay.TkWaker(1234, interval=.05, post=post)
            with self.assertLogs("agentdeck.hub.overlay", "DEBUG") as logs:
                waker.start()
                try:
                    self.assertTrue(continued.wait(.5))
                finally:
                    waker.stop()
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(any("injected PostMessage failure" in line for line in logs.output))

    def test_overlay_without_waker_returns_false(self):
        self.assertFalse(Overlay(FakeHub()).wake())


class WatchdogWakeTests(unittest.TestCase):
    def test_stalled_target_wakes_on_every_check_and_stops_on_recovery(self):
        clock = [0.]
        watchdog = Watchdog(monotonic=lambda: clock[0])
        wake = Mock()
        healthy_wake = Mock()
        watchdog.watch("UI", wake=wake)
        watchdog.watch("healthy", wake=healthy_wake)
        clock[0] = 2.
        watchdog.check()
        wake.assert_not_called()
        clock[0] = 3.6
        watchdog.beat("healthy")
        with self.assertLogs("agentdeck.hub.watchdog", "WARNING") as logs:
            watchdog.check()
            watchdog.check()
        self.assertEqual(wake.call_count, 2)
        healthy_wake.assert_not_called()
        self.assertEqual(sum("UI 卡顿" in line for line in logs.output), 1)
        self.assertIn("已发送唤醒", "\n".join(logs.output))
        with self.assertLogs("agentdeck.hub.watchdog", "INFO") as recovered:
            watchdog.beat("UI")
        self.assertIn("UI 已恢复", "\n".join(recovered.output))
        watchdog.check()
        self.assertEqual(wake.call_count, 2)

    def test_wake_runs_outside_lock_and_exceptions_preserve_warning(self):
        clock = [0.]
        watchdog = Watchdog(monotonic=lambda: clock[0])
        calls = []

        def wake():
            acquired = watchdog._lock.acquire(blocking=False)
            calls.append(acquired)
            if acquired:
                watchdog._lock.release()
            raise RuntimeError("injected watchdog wake failure")

        watchdog.watch("UI", wake=wake)
        clock[0] = 3.6
        with self.assertLogs("agentdeck.hub.watchdog", "DEBUG") as logs:
            watchdog.check()
            watchdog.check()
        self.assertEqual(calls, [True, True])
        text = "\n".join(logs.output)
        self.assertIn("UI 卡顿", text)
        self.assertIn("injected watchdog wake failure", text)
        self.assertEqual(sum("WARNING" in line for line in logs.output), 1)


class FakeUI:
    def __init__(self, engine, *, stall=False):
        self.engine = engine
        self.heartbeat = None
        self.wake = Mock()
        self.stall = stall
        self.stopped = threading.Event()

    def run(self):
        for index in range(4):
            if self.stopped.is_set():
                break
            self.heartbeat()
            self.engine.state()
            if self.stall and index == 1:
                time.sleep(3.6)
            time.sleep(.1)

    def stop(self):
        self.stopped.set()


class WatchdogWiringTests(unittest.TestCase):
    def run_main(self, *, stall, wrapped=False):
        uis = []

        def factory(engine):
            ui = FakeUI(engine, stall=stall)
            uis.append(ui)
            if wrapped:
                # TrayApplication exposes the real Overlay on .overlay.
                return type("FakeTray", (), {"overlay": ui, "run": lambda self: ui.run(),
                                               "stop": lambda self: ui.stop()})()
            return ui

        with tempfile.TemporaryDirectory() as home:
            code = hub.main(["--backend", "none", "--overlay", "--no-lcd", "--no-desktop",
                             "--port", "0", "--home", home], ui_factory=factory)
        self.assertEqual(code, 0)
        return uis[0]

    def test_main_wakes_stalled_direct_overlay(self):
        with self.assertLogs("agentdeck.hub.watchdog", "INFO") as logs:
            ui = self.run_main(stall=True)
        self.assertGreater(ui.wake.call_count, 0)
        self.assertIn("UI 卡顿", "\n".join(logs.output))
        self.assertIn("UI 已恢复", "\n".join(logs.output))

    def test_main_wakes_stalled_tray_overlay(self):
        with self.assertLogs("agentdeck.hub.watchdog", "WARNING"):
            ui = self.run_main(stall=True, wrapped=True)
        self.assertGreater(ui.wake.call_count, 0)

    def test_main_does_not_wake_healthy_overlay(self):
        with self.assertNoLogs("agentdeck.hub.watchdog", "WARNING"):
            ui = self.run_main(stall=False)
        ui.wake.assert_not_called()


class PollReceiptTests(unittest.TestCase):
    def make_overlay(self):
        engine = FakeHub()
        entered = threading.Event()

        def slow_state():
            with engine.lock:
                entered.set()
                time.sleep(.1)
                return dict(engine.value)

        engine.state = slow_state
        overlay = Overlay(engine, window=Mock())
        overlay.root = Mock()
        overlay.root.state.return_value = "normal"
        overlay._render = Mock()
        overlay._start_background()
        self.addCleanup(overlay._stop_background)
        original_defer = overlay.defer

        def let_worker_take_lock(callback, done=None, failed=None):
            entered.clear()
            original_defer(callback, done, failed)
            self.assertTrue(entered.wait(1.), "real background worker did not run state()")

        # Force the scheduling interleaving that used to lose every receipt.
        # The actual worker, queue, state call and Hub lock remain real.
        overlay.defer = let_worker_take_lock
        return overlay, engine

    def test_each_poll_acknowledges_before_its_next_state_request(self):
        overlay, engine = self.make_overlay()
        counts = []
        for _ in range(4):
            overlay._poll()
            counts.append(engine.record_rendered.call_count)
            time.sleep(.2)
        self.assertEqual(counts, [1, 2, 3, 4])
        self.assertEqual(engine.record_rendered.call_args.args, (None, None))
        self.assertEqual(engine.record_rendered.call_args.kwargs, {"source": "overlay"})

    def test_hidden_poll_hides_before_its_next_state_request(self):
        overlay, engine = self.make_overlay()
        overlay.hidden = True
        counts = []
        for _ in range(3):
            overlay._poll()
            counts.append(engine.hide_display.call_count)
            time.sleep(.2)
        self.assertEqual(counts, [1, 2, 3])
        engine.record_rendered.assert_not_called()

    def test_render_failure_still_submits_next_state_request(self):
        overlay, engine = self.make_overlay()
        overlay._render.side_effect = RuntimeError("injected render failure")
        with self.assertLogs("agentdeck.hub.overlay", "WARNING"):
            overlay._poll()
        self.assertTrue(overlay._state_pending)
        time.sleep(.2)
        overlay._render.side_effect = None
        overlay._poll()
        self.assertEqual(engine.record_rendered.call_count, 1)

    def test_failed_submission_clears_pending_and_retries(self):
        overlay, engine = self.make_overlay()
        real_defer = overlay.defer
        overlay.defer = Mock(side_effect=RuntimeError("injected queue failure"))
        with self.assertLogs("agentdeck.hub.overlay", "WARNING"):
            overlay._poll()
        self.assertFalse(overlay._state_pending)
        overlay.defer = real_defer
        overlay._poll()
        self.assertTrue(overlay._state_pending)

    def test_background_state_failure_is_consumed_and_retried(self):
        engine = FakeHub()
        engine.state = Mock(side_effect=[RuntimeError("injected state failure"), engine.value])
        overlay = Overlay(engine, window=Mock())
        overlay.root = Mock()
        overlay.root.state.return_value = "normal"
        overlay._render = Mock()
        overlay._start_background()
        self.addCleanup(overlay._stop_background)

        def wait_for_completion():
            deadline = time.monotonic() + 1.
            while overlay._completed.empty() and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertFalse(overlay._completed.empty(), "state worker did not complete")

        with self.assertLogs("agentdeck.hub.overlay", "ERROR"):
            overlay._poll()
            wait_for_completion()
        overlay._poll()  # Consume failed(), clear pending, and submit the retry.
        wait_for_completion()
        overlay._drain_completed()
        self.assertFalse(overlay._state_pending)
        self.assertEqual(engine.state.call_count, 2)
        self.assertEqual(overlay.state, engine.value)
        self.assertEqual(engine.record_rendered.call_count, 2)


class VirtualDeviceWakeTests(unittest.TestCase):
    def check_lifecycle(self, fail_setup=False):
        root = Mock()
        root.winfo_id.return_value = 4321
        waker = Mock()
        events = []
        waker.start.side_effect = lambda: events.append("start")
        waker.stop.side_effect = lambda: events.append("stop")
        root.mainloop.side_effect = lambda: events.append("mainloop")
        root.destroy.side_effect = lambda: events.append("destroy")
        device = hub_virtual_device.VirtualDevice(Mock(timeout=.1), window=Mock())
        device._worker = Mock()  # No network or device I/O.
        device._tick = Mock(side_effect=RuntimeError("injected setup failure") if fail_setup else None)
        with patch.object(hub_virtual_device.os, "name", "nt"), \
                patch("tkinter.Tk", return_value=root), patch("tkinter.Canvas"), \
                patch.object(hub_overlay, "TkWaker", return_value=waker) as factory:
            if fail_setup:
                with self.assertRaisesRegex(RuntimeError, "injected setup failure"):
                    device.run()
            else:
                device.run()
        factory.assert_called_once_with(4321)
        self.assertEqual(events, ["start", "stop", "destroy"] if fail_setup
                         else ["start", "mainloop", "stop", "destroy"])
        self.assertTrue(device._stop.is_set())

    def test_waker_stops_before_destroy(self):
        self.check_lifecycle()

    def test_setup_failure_also_stops_waker_before_destroy(self):
        self.check_lifecycle(fail_setup=True)


@unittest.skipUnless(sys.platform == "win32", "Windows GetMessageW notifier regression")
class WindowsMessageWakeTests(unittest.TestCase):
    def setUp(self):
        from ctypes import wintypes
        self.MSG = wintypes.MSG
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.GetMessageW.argtypes = [ctypes.POINTER(self.MSG), wintypes.HWND,
                                         wintypes.UINT, wintypes.UINT]
        self.user.GetMessageW.restype = wintypes.BOOL
        self.user.PeekMessageW.argtypes = [ctypes.POINTER(self.MSG), wintypes.HWND,
                                          wintypes.UINT, wintypes.UINT, wintypes.UINT]
        self.user.PeekMessageW.restype = wintypes.BOOL
        self.user.TranslateMessage.argtypes = [ctypes.POINTER(self.MSG)]
        self.user.TranslateMessage.restype = wintypes.BOOL
        self.user.DispatchMessageW.argtypes = [ctypes.POINTER(self.MSG)]
        self.user.DispatchMessageW.restype = ctypes.c_ssize_t
        self.user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM]
        self.user.PostMessageW.restype = wintypes.BOOL

    def block_in_getmessage(self, root):
        hwnd = int(root.winfo_id())  # Capture on Tk's thread, never in the helper.
        cancel = threading.Event()

        def insurance():
            if not cancel.wait(4.):
                self.user.PostMessageW(hwnd, 0, 0, 0)

        thread = threading.Thread(target=insurance, name="test GetMessage insurance", daemon=True)
        thread.start()
        try:
            root.update_idletasks()
            message = self.MSG()
            # Existing paint/posted messages must not make GetMessage pass by accident.
            while self.user.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                self.user.TranslateMessage(ctypes.byref(message))
                self.user.DispatchMessageW(ctypes.byref(message))
            started = time.monotonic()
            longest = 0.
            while True:
                waiting = time.monotonic()
                result = self.user.GetMessageW(ctypes.byref(message), None, 0, 0)
                longest = max(longest, time.monotonic() - waiting)
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                message_id = message.message
                if result > 0:
                    self.user.TranslateMessage(ctypes.byref(message))
                    self.user.DispatchMessageW(ctypes.byref(message))
                if result == 0 or message_id == 0:  # WM_NULL from waker / insurance.
                    return time.monotonic() - started, longest
                # A late Tcl WM_TIMER can arrive even after PeekMessage drained
                # the queue. Dispatch it and re-enter the same unfiltered wait;
                # it must not stand in for the WM_NULL wake under test.
        finally:
            cancel.set()
            thread.join(timeout=1.)

    def test_overlay_wakes_blocked_getmessage_and_resumes_heartbeats(self):
        watchdog = Watchdog(interval=.05)
        beats, result, errors = [], {}, []
        logger = logging.getLogger("agentdeck.hub.watchdog")
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.setLevel(logging.WARNING)
        logger.addHandler(handler)
        try:
            with tempfile.TemporaryDirectory() as directory:
                overlay = Overlay(FakeHub(), state_path=Path(directory) / "overlay.json")

                def heartbeat():
                    beats.append(time.monotonic())
                    watchdog.beat("UI")

                overlay.heartbeat = heartbeat

                def block():
                    try:
                        result["elapsed"], _ = self.block_in_getmessage(overlay.root)
                        result["returned"] = time.monotonic()
                        overlay.root.after(2000, overlay.stop)
                    except BaseException as error:
                        errors.append(error)
                        overlay.stop()

                def ready():
                    overlay.root.after(300, block)

                watchdog.watch("UI")
                watchdog.start()
                try:
                    overlay.run(on_ready=ready)
                finally:
                    watchdog.stop()
            self.assertEqual(errors, [])
            self.assertLess(result["elapsed"], 1.0)
            resumed = [beat for beat in beats if result["returned"] < beat <= result["returned"] + 2.]
            self.assertGreaterEqual(len(resumed), 4)
            self.assertEqual(output.getvalue(), "", "watchdog issued a WARNING")
        finally:
            watchdog.stop()
            logger.removeHandler(handler)
            handler.close()

    def test_bare_tk_without_waker_reproduces_block(self):
        import tkinter as tk
        root = tk.Tk()
        result, errors = [], []
        root.withdraw()

        def block():
            try:
                result.append(self.block_in_getmessage(root))
            except BaseException as error:
                errors.append(error)
            finally:
                root.quit()

        root.after(300, block)
        try:
            root.mainloop()
        finally:
            root.destroy()
        self.assertEqual(errors, [])
        elapsed, longest = result[0]
        self.assertGreaterEqual(elapsed, 2.)
        self.assertGreaterEqual(longest, 2., "no single GetMessageW call reproduced the freeze")


if __name__ == "__main__":
    unittest.main(verbosity=2)
