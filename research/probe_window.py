"""Live check of keypad-only control on this PC (F1 window binding, F3 scroll/nav).

    D:/conda/miniconda3/python.exe research/probe_window.py

The driver starts a private Hub (temporary home, random port, no LCD) with the
real desktop effects, then a probe process with a Tk window titled 'probe-窗口'
(no project name in it). The probe pipes a Chinese SessionStart through the
source relay (pc/hub_relay.py; the dist exe is not rebuilt here), so the relay
must find the probe's window by process. The driver then:

  1. puts its own window in front, sends {'action': 'slot 1'} over HTTP and
     checks GetForegroundWindow() == probe and no 'no matching window' log;
  2. sends scroll 1 / scroll -1 / scroll end and nav down / up / enter over HTTP;
  3. feeds the same knob 3 / knob 4 USB reports (0x2D 0x2E 0x19 0x30 0x2F Ctrl+0)
     through deck_usb.ReportState and the default keymap (virtual HID);
  4. covers the probe's first scroll point with a topmost window and scrolls again.

The probe records every KeyPress and MouseWheel it receives. It briefly moves
the mouse cursor (and puts it back) and changes the foreground window. Nothing
is written to the real ~/.agentdeck, ~/.claude or ~/.codex; the keyboard is not opened.
"""
import argparse
import ctypes
from ctypes import wintypes
import http.client
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
PC = ROOT / "pc"
SESSION = "probe-0001"
TITLE = "probe-窗口"
user = ctypes.WinDLL("user32", use_last_error=True)
user.GetForegroundWindow.restype = wintypes.HWND
user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user.GetAncestor.restype = wintypes.HWND
user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT]
user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]


def per_monitor_dpi():
    method = getattr(user, "SetThreadDpiAwarenessContext", None)
    if method is not None:
        method.argtypes, method.restype = [ctypes.c_void_p], ctypes.c_void_p
        method(ctypes.c_void_p(-4))


def root_hwnd(widget):
    return user.GetAncestor(widget.winfo_id(), 2) or widget.winfo_id()


def rect(hwnd):
    value = wintypes.RECT()
    user.GetWindowRect(hwnd, ctypes.byref(value))
    return value.left, value.top, value.right, value.bottom


def cursor():
    point = wintypes.POINT()
    user.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


# ---------------------------------------------------------------- probe process
def probe(args):
    import tkinter as tk
    per_monitor_dpi()
    out = Path(args.out)
    record = {"events": [], "hwnd": None, "relay": None}

    def save():
        temporary = out.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, out)

    root = tk.Tk()
    root.title(TITLE)
    root.geometry("640x420+%d+%d" % (args.x, args.y))
    tk.Label(root, text="AgentDeck probe：别动这个窗口，几秒后自动关闭", font=("Microsoft YaHei UI", 12)).pack(pady=40)

    def key(event):
        record["events"].append({"type": "key", "keysym": event.keysym, "vk": event.keycode, "t": time.time()})
        save()

    def wheel(event):
        record["events"].append({"type": "wheel", "delta": event.delta, "x": event.x_root,
                                 "y": event.y_root, "t": time.time()})
        save()

    root.bind_all("<KeyPress>", key)
    root.bind_all("<MouseWheel>", wheel)

    def start():
        root.update_idletasks()
        record["hwnd"] = int(root_hwnd(root))
        save()
        payload = {"hook_event_name": "SessionStart", "session_id": SESSION, "cwd": "D:\\tmp\\alpha",
                   "source": "startup", "note": "后面还有面"}
        relay = subprocess.run([sys.executable, str(PC / "hub_relay.py"), "--agent", "cc",
                                "--port", str(args.port), "--home", args.home],
                               input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                               capture_output=True, timeout=20)
        record["relay"] = {"code": relay.returncode, "stderr": relay.stderr.decode("utf-8", "replace")[-500:]}
        save()

    def watch():
        if Path(args.stop).exists():
            root.destroy()
            return
        root.after(100, watch)

    root.after(300, start)
    root.after(100, watch)
    root.after(int(args.timeout * 1000), root.destroy)
    root.mainloop()


# ---------------------------------------------------------------- driver
class Log(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append("%s %s" % (record.levelname, record.getMessage()))


def driver(args):
    import tkinter as tk
    sys.path.insert(0, str(PC))
    import hub
    import hub_desktop
    from deck_usb import ReportState

    per_monitor_dpi()
    home = Path(tempfile.mkdtemp(prefix="agentdeck-probe-"))
    (home / ".agentdeck").mkdir()
    token = "probe-token"
    (home / ".agentdeck" / "token").write_text(token + "\n", encoding="ascii")
    capture = Log()
    logging.getLogger().addHandler(capture)
    logging.getLogger().setLevel(logging.INFO)
    engine = hub.Hub(home=home, lcd_enabled=False, approve_timeout=5,
                     desktop=hub_desktop.DesktopEffects(shots_dir=home / "shots"))
    server = hub.HubServer(engine, token, 0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    out, stop = home / "probe.json", home / "probe.stop"
    probe_process = subprocess.Popen([sys.executable, __file__, "probe", "--port", str(server.server_port),
                                      "--home", str(home), "--out", str(out), "--stop", str(stop),
                                      "--x", "200", "--y", "160", "--timeout", "90"])

    root = tk.Tk()
    root.title("AgentDeck probe driver")
    root.geometry("360x200+900+160")
    tk.Label(root, text="driver（会被切到后面）").pack(pady=60)
    cover = tk.Toplevel(root)
    cover.overrideredirect(True)
    cover.attributes("-topmost", True)
    cover.configure(bg="#e5ad46")
    cover.geometry("120x60+-3000+-3000")
    results = {"checks": [], "done": False}

    def check(name, ok, detail=""):
        results["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        print(("PASS " if ok else "FAIL ") + name + (" -- " + str(detail) if detail else ""), flush=True)

    def post(action):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        connection.request("POST", "/action", body=json.dumps({"action": action}),
                           headers={"Content-Type": "application/json", "X-AgentDeck-Token": token})
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        return response.status, body

    def read_probe():
        try:
            return json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"events": []}

    def wait(predicate, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = predicate()
            if value:
                return value
            time.sleep(0.05)
        return None

    def run():
        try:
            steps()
        except Exception as error:  # report, never hang
            check("driver error", False, repr(error))
        finally:
            results["done"] = True

    def steps():
        data = wait(lambda: (lambda d: d if d.get("relay") else None)(read_probe()), 25)
        check("probe relay exit 0", data and data["relay"]["code"] == 0, data and data["relay"])
        probe_hwnd = data["hwnd"] if data else None
        state = engine.state()
        session = next((item for item in state["sessions"] if item["session_id"] == SESSION), None)
        check("session registered via relay", session is not None, state["sessions"])
        if session is None:
            return
        check("relay bound the probe window (hwnd)", session.get("hwnd") == probe_hwnd,
              {"session_hwnd": session.get("hwnd"), "probe_hwnd": probe_hwnd, "exe": session.get("window_exe")})
        windows = engine.desktop.windows
        blocker = root_hwnd(root)
        windows.activate(blocker)
        time.sleep(0.3)
        check("driver window in front before slot 1", user.GetForegroundWindow() == blocker)
        status, body = post("slot 1")
        time.sleep(0.3)
        check("slot 1 focuses the probe", status == 200 and body.get("window") == "focused"
              and user.GetForegroundWindow() == probe_hwnd, (status, body))
        check("no 'no matching window' in log", not any("no matching window" in line for line in capture.lines))

        def counted():
            return len(read_probe()["events"])

        def scroll(action):
            before_cursor, before = cursor(), counted()
            status, body = post(action)
            wait(lambda: counted() > before, 2)
            time.sleep(0.15)
            return status, body, before_cursor, cursor()

        for action in ("scroll 1", "scroll -1", "scroll end"):
            status, body, before_cursor, after_cursor = scroll(action)
            check("http %s" % action, status == 200 and body.get("status") == "sent", (status, body))
            check("cursor back after %s" % action, abs(before_cursor[0] - after_cursor[0]) <= 1
                  and abs(before_cursor[1] - after_cursor[1]) <= 1, (before_cursor, after_cursor))
        status, body = post("nav down")
        check("nav down refused while not waiting", status == 409, (status, body))
        engine.event("cc", {"hook_event_name": "PreToolUse", "session_id": SESSION, "tool_name": "AskUserQuestion",
                            "tool_input": {"questions": [{"question": "选哪个？", "options": [{"label": "A"}, {"label": "B"}]}]}})
        for action in ("nav down", "nav up", "nav enter"):
            before = counted()
            status, body = post(action)
            wait(lambda: counted() > before, 2)
            check("http %s" % action, status == 200 and body.get("status") == "sent", (status, body))

        callback = hub.USBKeys(engine)
        parser = ReportState()

        def press(report):
            for event in parser.feed(bytes(report)):
                callback(dict(event, t=engine.monotonic()))
            for event in parser.feed(bytes(8)):
                callback(dict(event, t=engine.monotonic()))

        for report in ([0, 0, 0x2D], [0, 0, 0x2E], [0, 0, 0x19], [0, 0, 0x30], [0, 0, 0x2F], [1, 0, 0], [1, 0, 0x27]):
            before = counted()
            press(report + [0] * (8 - len(report)))
            if report != [1, 0, 0]:
                wait(lambda: counted() > before, 2)
                time.sleep(0.1)
        check("virtual HID path ran without errors",
              not any("USB action failed" in line for line in capture.lines),
              [line for line in capture.lines if "action failed" in line])

        # Cover the first scroll point (0.5, 0.6) of the probe with a topmost window.
        left, top, right, bottom = rect(probe_hwnd)
        x, y = left + (right - left) // 2, top + int((bottom - top) * 0.6)
        user.SetWindowPos(root_hwnd(cover), wintypes.HWND(-1), x - 60, y - 30, 120, 60, 0x0010 | 0x0040)
        time.sleep(0.4)
        before = counted()
        status, body = post("scroll 1")
        wait(lambda: counted() > before, 2)
        time.sleep(0.15)
        check("scroll with the center covered", status == 200, (status, body))
        user.SetWindowPos(root_hwnd(cover), wintypes.HWND(-1), -3000, -3000, 120, 60, 0x0010)

        events = read_probe()["events"]
        wheels = [event["delta"] for event in events if event["type"] == "wheel"]
        keys = [event["keysym"] for event in events if event["type"] == "key"]
        check("probe wheel deltas", wheels == [-120, 120, -12000, -120, 120, -12000, -120], wheels)
        check("probe keys", keys == ["Down", "Up", "Return", "Down", "Up", "Return"], keys)
        last = [event for event in events if event["type"] == "wheel"][-1] if wheels else None
        check("covered scroll used another point inside the probe",
              last is not None and left <= last["x"] < right and top <= last["y"] < bottom
              and not (x - 60 <= last["x"] < x + 60 and y - 30 <= last["y"] < y + 30),
              last and (last["x"], last["y"], "cover", (x - 60, y - 30, x + 60, y + 30)))

    worker = threading.Thread(target=run, daemon=True)
    worker.start()

    def poll():
        if results["done"]:
            root.quit()
            return
        root.after(100, poll)

    root.after(500, poll)
    root.mainloop()
    stop.write_text("stop", encoding="ascii")
    try:
        probe_process.wait(10)
    except subprocess.TimeoutExpired:
        probe_process.kill()
    server.shutdown()
    server.server_close()
    engine.close()
    root.destroy()
    failed = [item for item in results["checks"] if not item["ok"]]
    print("%d PASS / %d FAIL (temp home %s)" % (len(results["checks"]) - len(failed), len(failed), home))
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", default="driver", choices=("driver", "probe"))
    parser.add_argument("--port", type=int)
    parser.add_argument("--home")
    parser.add_argument("--out")
    parser.add_argument("--stop")
    parser.add_argument("--x", type=int, default=200)
    parser.add_argument("--y", type=int, default=160)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    if args.mode == "probe":
        probe(args)
        return 0
    return driver(args)


if __name__ == "__main__":
    raise SystemExit(main())
