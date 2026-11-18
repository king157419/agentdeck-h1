"""Numeric geometry regressions; no Tk window or native desktop access."""
import ctypes
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from hub_overlay import NoActivateWindow, Overlay


class Desktop:
    def __init__(self, areas):
        self.areas = areas
        self.bounds = None

    def work_areas(self):
        return list(self.areas)

    def place(self, x, y, width, height):
        self.bounds = (x, y, width, height)

    def remember(self):
        pass

    def restore(self):
        pass

    def apply(self, child):
        pass

    def show(self):
        pass

    def close(self):
        pass


class PositionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.desktop = Desktop([(-1600, -100, 0, 860), (0, 0, 1920, 1040),
                                (1920, 0, 4480, 1400)])
        self.hub = Mock()
        self.hub.state.return_value = {}
        self.overlay = Overlay(self.hub, window=self.desktop, home=self.temp.name)
        self.root = self.overlay.root = Mock()
        self.root.winfo_x.return_value = 100
        self.root.winfo_y.return_value = 100
        self.root.winfo_reqheight.return_value = 40
        self.root.winfo_screenwidth.return_value = 1920
        self.root.winfo_screenheight.return_value = 1080
        self.overlay._height = 40

    def assert_inside_work_area(self):
        x, y, width, height = self.desktop.bounds
        self.assertTrue(any(left <= x and top <= y and x + width <= right
                            and y + height <= bottom
                            for left, top, right, bottom in self.desktop.areas),
                        self.desktop.bounds)

    def test_drag_supports_negative_desktop_coordinates_and_persists(self):
        self.overlay._start_drag(types.SimpleNamespace(x_root=120, y_root=110))
        self.overlay._move(types.SimpleNamespace(x_root=-700, y_root=-30))
        self.overlay._end_drag()
        self.assert_inside_work_area()
        self.assertEqual(self.desktop.bounds[:2], (-720, -40))
        restored = Overlay(self.hub, home=self.temp.name)
        restored._load_prefs()
        self.assertEqual(restored._pos, (-720, -40))

    def test_restore_right_monitor_keeps_its_position(self):
        self.overlay._place(2300, 100, 40)
        self.assertEqual(self.desktop.bounds[:2], (2300, 100))
        self.assert_inside_work_area()

    def test_taskbar_and_outer_edges_clamp_entire_window(self):
        self.desktop.areas = [(0, 0, 1920, 1040)]
        self.overlay._place(1900, 1030, 240)
        self.assert_inside_work_area()
        self.assertEqual(self.desktop.bounds, (1560, 800, 360, 240))

    def test_monitor_removed_reclamps_without_height_change(self):
        self.overlay._place(2300, 100, 40)
        self.desktop.areas = [(0, 0, 1920, 1040)]
        with patch.object(self.overlay, "_render"):
            self.overlay._poll()
        self.assert_inside_work_area()
        self.assertLess(self.desktop.bounds[0], 1920)

    def test_expansion_stays_on_negative_monitor(self):
        self.overlay._place(-1000, -90, 40)
        self.root.winfo_reqheight.return_value = 520
        with patch.object(self.overlay, "_render"):
            self.overlay._poll()
        self.assert_inside_work_area()
        self.assertLess(self.desktop.bounds[0], 0)
        self.assertEqual(self.desktop.bounds[3], 520)

    def test_changed_scaled_work_area_keeps_visible_bounds(self):
        self.overlay._place(4000, 1000, 500)
        self.desktop.areas = [(0, 0, 1536, 824), (1536, -200, 3456, 880)]
        self.root.winfo_reqheight.return_value = 500
        with patch.object(self.overlay, "_render"):
            self.overlay._poll()
        self.assert_inside_work_area()

    def test_startup_restores_right_monitor_position(self):
        self.overlay._pos = (2300, 100)
        self.overlay._save_prefs()
        self.root.winfo_id.return_value = 100
        with patch.dict(sys.modules, {"tkinter": types.SimpleNamespace(Tk=lambda: self.root)}), \
                patch.object(self.overlay, "_build"), patch.object(self.overlay, "_poll"):
            self.overlay.run()
        self.assertEqual(self.desktop.bounds, (2300, 100, 360, 40))
        self.assert_inside_work_area()


class NativeFunction:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


@unittest.skipUnless(sys.platform == "win32", "Win32 adapter contract")
class NativePositionTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        funcs = {
            "GetWindowLongPtrW": lambda *args: 0,
            "SetWindowLongPtrW": lambda *args: 0,
            "GetAncestor": lambda *args: 101,
            "GetForegroundWindow": lambda: 202,
            "SetForegroundWindow": lambda *args: True,
            "IsChild": lambda *args: False,
            "CallWindowProcW": lambda *args: 0,
            "SetWindowPos": lambda *args: self.calls.append(args) or True,
            "ShowWindow": lambda *args: True,
            "SetThreadDpiAwarenessContext": lambda context: self.calls.append(context) or 42,
        }
        self.user = types.SimpleNamespace(**{name: NativeFunction(callback)
                                            for name, callback in funcs.items()})
        self.window = NoActivateWindow(self.user)

    def test_native_placement_keeps_negative_absolute_coordinates_without_activation(self):
        self.window.hwnd = 101
        self.window.place(-1200, -50, 360, 400)
        hwnd, insert_after, x, y, width, height, flags = self.calls[-1]
        self.assertEqual((hwnd, x, y, width, height), (101, -1200, -50, 360, 400))
        self.assertTrue(flags & 0x10)  # SWP_NOACTIVATE
        self.assertTrue(flags & 0x04)  # SWP_NOZORDER

    def test_enumeration_uses_signed_work_areas(self):
        def enumerate_monitors(dc, clip, callback, data):
            callback(101, None, None, data)
            callback(202, None, None, data)
            return True

        def info(monitor, pointer):
            value = pointer._obj
            self.assertEqual(value.cbSize, ctypes.sizeof(value))
            bounds = (-1920, -100, 0, 940) if monitor == 101 else (0, 0, 1920, 1040)
            value.rcWork.left, value.rcWork.top, value.rcWork.right, value.rcWork.bottom = bounds
            return True

        self.user.EnumDisplayMonitors = NativeFunction(enumerate_monitors)
        self.user.GetMonitorInfoW = NativeFunction(info)
        self.assertEqual(self.window.work_areas(), [(-1920, -100, 0, 940), (0, 0, 1920, 1040)])

    def test_thread_dpi_context_is_restored(self):
        self.window.begin_dpi()
        self.assertEqual(self.calls[-1].value, ctypes.c_void_p(-4).value)
        self.window.close()
        self.assertEqual(self.calls[-1], 42)


if __name__ == "__main__":
    unittest.main(verbosity=2)
