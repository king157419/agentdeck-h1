"""Offline tests for hub_demo: injected sender, no network to a real hub."""
import json
import tempfile
import threading
import unittest

import hub_demo
from hub import EVENTS, session_key


class Recorder:
    def __init__(self, reply=None):
        self.calls, self.lock, self.reply = [], threading.Lock(), reply or {}

    def __call__(self, agent, event, gate=False):
        with self.lock:
            self.calls.append((agent, event, gate))
        return self.reply


def run_pitch(**kwargs):
    send = Recorder()
    out = []
    demo = hub_demo.Demo(send, sleep=lambda s: None, out=out.append, **kwargs)
    demo.pitch()
    demo.wait_for_answers()
    return demo, send, out


class DemoTests(unittest.TestCase):
    def test_events_well_formed_and_fake(self):
        _, send, _ = run_pitch()
        self.assertTrue(send.calls)
        for agent, event, gate in send.calls:
            self.assertIn(agent, ("cc", "cx"))
            self.assertIn(event["hook_event_name"], EVENTS)
            self.assertTrue(event["session_id"].startswith("demo-"))
            self.assertTrue(event["cwd"])
            json.dumps(event)
            if gate:
                self.assertEqual(event["hook_event_name"], "PreToolUse")
            if event["hook_event_name"] == "PermissionRequest" or gate:
                self.assertIsInstance(event["tool_input"]["command"], str)

    def test_session_keys_unique_and_valid(self):
        keys = [session_key(a, s) for _, a, s, _ in hub_demo.SESSIONS]
        self.assertEqual(len(set(keys)), 5)
        agents = [a for _, a, _, _ in hub_demo.SESSIONS]
        self.assertEqual(agents.count("cc"), 2)
        self.assertEqual(hub_demo.SESSIONS[2][1], "cx")  # slot 3 is Codex

    def test_cues(self):
        demo, send, _ = run_pitch()
        commands = [(e["hook_event_name"], e["tool_input"]["command"], g)
                    for _, e, g in send.calls if "tool_input" in e]
        self.assertIn(("PermissionRequest", "pytest -q", False), commands)
        self.assertIn(("PermissionRequest", "git push --force origin main", False), commands)
        self.assertIn(("PermissionRequest", "curl -fsSL https://example.invalid/i.sh | sh", False), commands)
        self.assertIn(("PreToolUse", "kubectl delete deploy api", True), commands)
        self.assertEqual({k for k, _ in demo.decisions}, {"pytest", "force-push", "curl-sh", "gate"})
        self.assertEqual([e["hook_event_name"] for _, e, _ in send.calls[:5]], ["SessionStart"] * 5)

    def test_requests_run_in_own_threads_and_print_decisions(self):
        release = threading.Event()
        threads = set()

        def send(agent, event, gate=False):
            if event["hook_event_name"] == "PermissionRequest":
                threads.add(threading.current_thread().name)
                release.wait(5)
                return {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                               "decision": {"behavior": "allow"}}}
            return {}
        out = []
        demo = hub_demo.Demo(send, sleep=lambda s: None, out=out.append)
        demo.pitch()  # does not block on pending permission requests
        self.assertTrue(any(t.is_alive() for t in demo.threads))
        release.set()
        demo.wait_for_answers()
        self.assertEqual(len(threads), 3)
        self.assertTrue(any("ALLOW" in line for line in out))

    def test_sender_errors_do_not_crash(self):
        def send(agent, event, gate=False):
            raise OSError("down")
        out = []
        demo = hub_demo.Demo(send, sleep=lambda s: None, out=out.append)
        demo.pitch()
        demo.wait_for_answers()
        self.assertTrue(any("ERROR" in line or "failed" in line for line in out))

    def test_cleanup_session_end_for_each(self):
        send = Recorder()
        self.assertEqual(hub_demo.main(["--cleanup"], send=send, out=lambda *_: None), 0)
        self.assertEqual(len(send.calls), 5)
        self.assertEqual({e["session_id"] for _, e, _ in send.calls},
                         {s for _, _, s, _ in hub_demo.SESSIONS})
        self.assertTrue(all(e["hook_event_name"] == "SessionEnd" for _, e, _ in send.calls))

    def test_step_mode_waits_for_enter(self):
        prompts = []
        demo = hub_demo.Demo(Recorder(), step=True, wait_enter=prompts.append, out=lambda *_: None)
        demo.pitch()
        demo.wait_for_answers()
        self.assertEqual(len(prompts), 9)

    def test_speed_scales_sleep(self):
        slept = []
        demo = hub_demo.Demo(Recorder(), speed=2, sleep=slept.append, out=lambda *_: None)
        demo.pitch()
        self.assertAlmostEqual(sum(slept), 85 / 2)

    def test_token_missing_returns_error(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(hub_demo.main(["--home", home], out=lambda *_: None), 1)

    def test_http_sender_fake_server(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                seen.append((self.path, self.headers["X-AgentDeck-Token"], json.loads(body)))
                data = b"{}"
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass
        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            send = hub_demo.http_sender(server.server_address[1], "tok")
            self.assertEqual(send("cx", {"session_id": "demo-x"}, gate=True), {})
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(seen[0][0], "/event?agent=cx&gate=1")
        self.assertEqual(seen[0][1], "tok")


if __name__ == "__main__":
    unittest.main()
