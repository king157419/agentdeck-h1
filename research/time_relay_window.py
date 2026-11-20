"""Compare 50 real relay processes per mode against an isolated loopback HTTP hub."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import threading
import time


PYTHON = Path("D:/conda/miniconda3/python.exe")
ROOT = Path(__file__).resolve().parents[1]
SAMPLES = 50
TOKEN = "relay-window-timing-only"


def main():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            valid = (self.path == "/event?agent=cc"
                     and self.headers.get("X-AgentDeck-Token") == TOKEN
                     and body.get("hook_event_name") == "Stop"
                     and body.get("session_id") == "timing")
            received.append(valid)
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    samples = {True: [], False: []}
    try:
        with tempfile.TemporaryDirectory(prefix="relay-window-timing-") as directory:
            home = Path(directory)
            data = home / ".agentdeck"
            data.mkdir()
            (data / "token").write_text(TOKEN, encoding="utf-8")
            (data / "hub.json").write_text(json.dumps(
                {"pid": os.getpid(), "port": server.server_port}), encoding="utf-8")
            command = [str(PYTHON), str(ROOT / "pc" / "hub_relay.py"), "--agent", "cc",
                       "--port", str(server.server_port), "--home", str(home)]
            payload = json.dumps({"hook_event_name": "Stop", "session_id": "timing"}).encode("ascii")
            for index in range(SAMPLES):
                # Alternate each pair's order to reduce bias from warm caches and load drift.
                for enabled in ((False, True) if index % 2 == 0 else (True, False)):
                    environment = os.environ.copy()
                    environment.pop("AGENTDECK_NO_WINDOW", None)
                    if not enabled:
                        environment["AGENTDECK_NO_WINDOW"] = "1"
                    began = time.perf_counter()
                    result = subprocess.run(command, cwd=ROOT, env=environment, input=payload,
                                            capture_output=True, timeout=10,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    elapsed = (time.perf_counter() - began) * 1000
                    if (result.returncode, result.stdout, result.stderr) != (0, b"{}", b""):
                        raise RuntimeError("relay failed: %r" % ((result.returncode, result.stdout,
                                                                 result.stderr),))
                    samples[enabled].append(elapsed)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
    if len(received) != SAMPLES * 2 or not all(received):
        raise RuntimeError("fake hub did not receive all authenticated events")
    with_window = statistics.median(samples[True])
    without_window = statistics.median(samples[False])
    paired_delta = statistics.median(on - off for on, off in zip(samples[True], samples[False]))
    print("with_window: n=%d median=%.3f ms" % (SAMPLES, with_window))
    print("without_window: n=%d median=%.3f ms" % (SAMPLES, without_window))
    print("median_difference: %.3f ms" % (with_window - without_window))
    print("paired_median_delta: %.3f ms" % paired_delta)
    passed = with_window - without_window <= 30 and paired_delta <= 30
    print("window_lookup_overhead <= 30 ms: %s" % ("PASS" if passed else "FAIL"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
