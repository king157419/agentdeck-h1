"""Real Hub/HTTP/VirtualDevice integration; only the Tk boundary is substituted."""
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import hub
import hub_virtual_device as vd


class VirtualNonceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = hub.Hub(home=self.temp.name, lcd_enabled=False,
                              desktop_enabled=False, require_nonce=True)
        self.server = hub.HubServer(self.engine, "virtual-integration", port=0)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.client = vd.HubClient(self.server.server_port, "virtual-integration")
        self.device = vd.VirtualDevice(self.client)
        self.device.root = Mock()
        self.device.root.state.return_value = "normal"
        self.device._draw = Mock()
        self.calls = []

    def tearDown(self):
        self.device._stop.set()
        self.engine.close()
        for thread, _ in self.calls:
            thread.join(2)
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(2)
        self.temp.cleanup()

    def permission(self, sid="virtual-one"):
        result = []
        thread = threading.Thread(target=lambda: result.append(self.engine.event("cc", {
            "hook_event_name": "PermissionRequest", "session_id": sid,
            "cwd": "D:/virtual", "tool_name": "Bash",
            "tool_input": {"command": "echo virtual"}})), daemon=True)
        self.calls.append((thread, result))
        thread.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = self.client.state()
            request = next((r for r in state["pending"] if r["session_id"] == sid), None)
            if request:
                return request, state, result
            time.sleep(.002)
        self.fail("permission did not arrive")

    def press(self, action="approve"):
        x, y, w, h = vd.layout()[action]
        self.device._press(SimpleNamespace(x=x+w/2, y=y+h/2))

    def process_jobs(self):
        worker = threading.Thread(target=self.device._worker, daemon=True)
        worker.start()
        return worker

    def test_delayed_first_draw_has_its_own_guard_and_worker_delay_cannot_approve(self):
        request, state, result = self.permission()
        time.sleep(.32)  # Hub logical selection is older than the protection window.
        self.device.state = state
        self.device._tick()
        self.press()  # Newly painted request must still reject this click.
        time.sleep(.32)  # Delaying the worker must not revive the rejected click.
        worker = self.process_jobs()
        time.sleep(.34)  # Server also guards 300 ms after receiving the render report.
        self.assertIn(request["id"], self.engine.pending)
        self.assertEqual(result, [])
        self.press()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and request["id"] in self.engine.pending:
            time.sleep(.01)
        self.device._stop.set()
        worker.join(2)
        self.assertNotIn(request["id"], self.engine.pending)
        self.assertEqual(result[0]["hookSpecificOutput"]["decision"]["behavior"], "allow")

    def test_render_http_auth_and_source_publication(self):
        request, _, _ = self.permission()
        bad = vd.HubClient(self.server.server_port, "wrong-token")
        self.assertEqual(bad.rendered(request["id"], request["nonce"])["error"], "unauthorized")
        self.assertNotIn("virtual", self.engine.rendered_by_source)
        self.assertNotIn("error", self.client.rendered(request["id"], request["nonce"]))
        self.assertEqual(self.engine.rendered_by_source["virtual"]["nonce"], request["nonce"])

    def test_worker_state_advances_before_redraw_cannot_retarget_old_click(self):
        first, state, _ = self.permission()
        self.device.state = state
        self.device._tick()
        # Publish the actual first drawing before allowing the local guard to elapse.
        worker = self.process_jobs()
        time.sleep(.34)
        self.engine.action({"action": "deny", "nonce": first["nonce"]})
        second, state, result = self.permission("virtual-two")
        self.device.state = state  # polling has changed; Tk has not drawn it yet.
        self.press()
        time.sleep(.1)
        self.assertIn(second["id"], self.engine.pending)
        self.assertEqual(result, [])
        self.device._stop.set()
        worker.join(2)

    def test_failed_draw_never_publishes_or_enables_a_request(self):
        _, state, _ = self.permission()
        self.device.state = state
        self.device._draw.side_effect = RuntimeError("paint failed")
        with self.assertRaisesRegex(RuntimeError, "paint failed"):
            self.device._tick()
        self.assertEqual(self.device._drawn_request, (None, None))
        self.assertTrue(self.device._jobs.empty())
        self.press()
        self.assertTrue(self.device._jobs.empty())

    def test_request_line_reserves_nonce_and_bounds_wide_summary(self):
        request, state, _ = self.permission()
        request = dict(request, summary="界" * 100, risk="high", gate=True)
        state["pending"] = [request]
        text, _ = vd.request_line(state)
        self.assertTrue(text.endswith("#%04x" % (request["nonce"] & 0xffff)))
        # Full-width glyphs count twice against the finite character budget.
        self.assertLessEqual(sum(2 if ord(c) > 255 else 1 for c in text), 76)
        op = next(op for op in vd.build_scene(state) if op["tag"] == "request")
        self.assertEqual(op["max_width"], vd.STRIP[2] - 24)

    def test_canvas_font_measurement_keeps_wide_line_and_nonce_inside_strip(self):
        # The renderer must obey measured pixel width even when the character
        # budget underestimates a particular font/DPI's glyph sizes.
        measure = lambda text: sum(25 if ord(c) > 255 else 13 for c in text)
        self.device.canvas = Mock()
        self.device._round = Mock()
        text = "界" * 28 + " [HIGH] #abcd"
        op = vd._text(142, 181, text, "#fff", anchor="w", tag="request")
        op["max_width"] = vd.STRIP[2] - 24
        with patch("tkinter.font.Font") as font:
            font.return_value.measure = measure
            vd.VirtualDevice._draw(self.device, [op])
        shown = self.device.canvas.create_text.call_args.kwargs["text"]
        self.assertLessEqual(measure(shown), vd.STRIP[2] - 24)
        self.assertTrue(shown.endswith("[HIGH] #abcd"))
        self.assertIn("…", shown)

    def test_press_time_precedes_window_callback_delay(self):
        request, state, _ = self.permission()
        self.device.state = state
        self.device._tick()
        # Delay a native window callback across the guard boundary.
        self.device.window = Mock()
        self.device.window.remember.side_effect = lambda: time.sleep(.32)
        self.press()
        jobs = []
        while not self.device._jobs.empty():
            jobs.append(self.device._jobs.get_nowait())
        self.assertFalse(any(isinstance(job, dict) and job.get("action") == "approve"
                             for job in jobs))
        self.assertIn(request["id"], self.engine.pending)


if __name__ == "__main__":
    unittest.main(verbosity=2)
