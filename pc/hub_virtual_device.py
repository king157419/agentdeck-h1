"""Software twin of the AgentDeck v2 hardware (tkinter), for pitch demos.

The drawing model is pure: ``build_scene(state, ui, now)`` returns a list of draw
ops in 1:1 body coordinates (900x420); ``--scale`` is applied by the renderer.
Actions go through the Hub's HTTP ``/action`` with the token, state comes from
``/state``. Importing this module never creates a window.
"""
import argparse
import json
import logging
import os
import queue
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("agentdeck.hub.virtual")

BODY_W, BODY_H = 900, 420
STRIP = (130, 26, 640, 172)            # x, y, w, h of the black display
ZONE_W = STRIP[2] / 6.0
LINE_H = 34                             # bottom request line inside the strip
KEY_Y, KEY_H = 222, 62
BOTTOM_Y, BOTTOM_H = 312, 78
WHEEL = (816, 50, 56, 300)
PRESS_SECONDS = 0.12
POLL_SECONDS = 0.2
SWITCH_GUARD_SECONDS = 0.3
BLINK_HZ = 2.0

COLORS = {"RUN": "#2BC864", "ASK": "#F5A524", "DONE": "#3B82F6", "ERR": "#E5484D",
          "IDLE": "#6B7280", "GATE": "#E5484D", "LOCKED": "#E5484D"}
STATES = {"think": "RUN", "tool": "RUN", "wait": "ASK", "locked": "ASK",
          "done": "DONE", "error": "ERR", "idle": "IDLE"}
DARK = "#1B1F27"
CTRL_PROMPTS = {1: "continue", 2: "tests", 3: "summary", 4: "commit", 5: "tests", 6: "summary"}


# ---------------------------------------------------------------- layout

def layout():
    """Control name -> (x, y, w, h) in body coordinates."""
    rects = {}
    key_w = 96.0
    gap = (STRIP[2] - 6 * key_w) / 5.0
    for number in range(1, 7):
        rects["slot %d" % number] = (STRIP[0] + (number - 1) * (key_w + gap), KEY_Y, key_w, KEY_H)
    rects["approve"] = (130, BOTTOM_Y, 150, BOTTOM_H)
    rects["deny"] = (296, BOTTOM_Y, 150, BOTTOM_H)
    rects["mic"] = (462, BOTTOM_Y, 150, BOTTOM_H)
    rects["ctrl"] = (632, BOTTOM_Y + 18, 62, 42)
    rects["camera"] = (708, BOTTOM_Y + 18, 62, 42)
    rects["wheel_up"] = (WHEEL[0], WHEEL[1], WHEEL[2], WHEEL[3] / 2.0)
    rects["wheel_down"] = (WHEEL[0], WHEEL[1] + WHEEL[3] / 2.0, WHEEL[2], WHEEL[3] / 2.0)
    rects["close"] = (866, 6, 24, 24)
    return rects


def hit_test(x, y):
    """Return the control under body point (x, y), or None."""
    for name, (rx, ry, rw, rh) in layout().items():
        if rx <= x < rx + rw and ry <= y < ry + rh:
            return name
    return None


# ---------------------------------------------------------------- actions

_MISSING = object()


def control_action(control, ctrl=False, phase="down", request_id=None, nonce=_MISSING):
    """Map a control event to ``(payload or None, ctrl_after)``.

    ``ctrl`` is the toggled modifier. It is consumed by the next action key.
    """
    if control == "ctrl":
        return (None, not ctrl) if phase == "down" else (None, ctrl)
    if control == "mic":
        return ({"action": "voice_down" if phase == "down" else "voice_up"}, ctrl)
    if phase != "down":
        return None, ctrl
    if control.startswith("slot "):
        number = int(control.split()[1])
        if ctrl:
            return {"action": "prompt " + CTRL_PROMPTS[number]}, False
        return {"action": control}, False
    if control == "approve":
        payload = {"action": "approve"}
        if request_id is not None:
            payload["request_id"] = request_id
        if nonce is not _MISSING:
            payload["nonce"] = nonce
        return payload, False
    if control == "deny":
        if ctrl:
            return {"action": "interrupt"}, False
        payload = {"action": "deny"}
        if request_id is not None:
            payload["request_id"] = request_id
        if nonce is not _MISSING:
            payload["nonce"] = nonce
        return payload, False
    if control == "camera":
        return {"action": "screenshot"}, False
    if control == "wheel_up":
        return {"action": "cycle -1"}, ctrl
    if control == "wheel_down":
        return {"action": "cycle +1"}, ctrl
    return None, ctrl


def wheel_action(delta):
    """Mouse-wheel delta (tk/Windows: positive = up) -> cycle payload."""
    if not delta:
        return None
    return {"action": "cycle -1" if delta > 0 else "cycle +1"}


# ---------------------------------------------------------------- state -> model

def gate_phase(now):
    """True during the lit half of the 2 Hz GATE blink."""
    return int(now * BLINK_HZ * 2) % 2 == 0


def displayed_request(state):
    shown = state.get("displayed_request_id")
    if shown is None:
        return None
    for item in list(state.get("pending", ())) + list(state.get("locked", ())):
        if item.get("id") == shown:
            return item
    return None


def _is_locked(request):
    return request.get("status") == "locked" or (
        request.get("risk") == "critical" and not request.get("gate"))


def zone_models(state, now=0.0):
    """Six zone dicts: number, name (<=8), label, color (blink applied), selected."""
    sessions = {s.get("slot"): s for s in state.get("sessions", ())}
    request = displayed_request(state)
    lit = gate_phase(now)
    zones = []
    for number in range(1, 7):
        session = sessions.get(number)
        if session is None:
            zones.append({"number": number, "name": "--", "label": "IDLE", "color": COLORS["IDLE"],
                          "occupied": False, "selected": state.get("selected_slot") == number})
            continue
        label = STATES.get(session.get("state"), "IDLE")
        if request is not None and (request.get("agent"), request.get("session_id")) == (
                session.get("agent"), session.get("session_id")):
            if _is_locked(request):
                label = "LOCKED"
            elif request.get("gate"):
                label = "GATE"
        color = COLORS[label]
        if label == "GATE" and not lit:
            color = DARK
        name = str(session.get("name") or session.get("project") or "?")[:8]
        zones.append({"number": number, "name": name, "label": label, "color": color,
                      "occupied": True, "selected": state.get("selected_slot") == number})
    return zones


def request_line(state):
    """Bottom strip line -> (text, color); text is '' when nothing is displayed."""
    request = displayed_request(state)
    if request is None:
        return "", COLORS["IDLE"]
    summary = " ".join(str(request.get("summary", "")).split())
    # Reserve room for risk, gate label and the nonce. Full-width characters
    # consume twice the budget; the renderer also measures the actual font.
    shortened = ""
    width = 0
    for char in summary:
        amount = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if width + amount > 53:
            shortened += "…"
            break
        shortened += char
        width += amount
    summary = shortened
    risk = request.get("risk", "low")
    nonce = request.get("nonce")
    suffix = " #%04x" % (nonce & 0xffff) if type(nonce) is int else ""
    if _is_locked(request):
        return "LOCKED: use terminal" + suffix, COLORS["LOCKED"]
    red = risk in ("high", "critical")
    head = "GATE " if request.get("gate") else ""
    return "%s%s [%s]" % (head, summary, risk.upper()) + suffix, COLORS["ERR"] if red else COLORS["ASK"]


# ---------------------------------------------------------------- draw ops

def _rr(x, y, w, h, fill, outline="", radius=8, tag="", width=1):
    return {"op": "rrect", "x": x, "y": y, "w": w, "h": h, "fill": fill, "outline": outline,
            "radius": radius, "tag": tag, "width": width}


def _text(x, y, text, fill, size=10, bold=False, anchor="center", tag=""):
    return {"op": "text", "x": x, "y": y, "text": text, "fill": fill, "size": size,
            "bold": bold, "anchor": anchor, "tag": tag}


def _shade(color, k):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(r * k), int(g * k), int(b * k))


def build_scene(state, ui=None, now=0.0):
    """Pure: state + ui ({'ctrl': bool, 'pressed': {control: until_time}}) -> draw ops."""
    ui = ui or {}
    pressed = {name for name, until in ui.get("pressed", {}).items() if until > now}
    rects = layout()
    ops = [_rr(0, 0, BODY_W, BODY_H, "#B8BCC4", "#8A8F99", 36, "body", 3),
           _rr(8, 8, BODY_W - 16, BODY_H - 16, "#2A2E36", "", 30, "body")]
    ops.append(_text(878, 18, "×", "#9AA3B2", 12, True, tag="close"))
    sx, sy, sw, sh = STRIP
    ops.append(_rr(sx - 6, sy - 6, sw + 12, sh + 12, "#0A0B0D", "#3A3F49", 10, "strip", 1))
    zones = zone_models(state, now)
    for zone in zones:
        zx = sx + (zone["number"] - 1) * ZONE_W
        zh = sh - LINE_H
        if zone["selected"]:
            ops.append({"op": "rect", "x": zx + 1, "y": sy + 1, "w": ZONE_W - 2, "h": zh - 2,
                        "fill": "#161B24", "outline": "#3B4658", "tag": "zone"})
        ops.append(_text(zx + 8, sy + 8, str(zone["number"]), "#7C8798", 9, True, "nw", "zone"))
        ops.append(_text(zx + ZONE_W / 2, sy + 52, zone["name"],
                         "#EDF1F7" if zone["occupied"] else "#4A5260", 13, True, tag="zone"))
        ops.append(_rr(zx + 12, sy + 84, ZONE_W - 24, 26, zone["color"], "", 6, "chip"))
        chip_fg = "#0A0B0D" if zone["color"] != DARK else "#E5484D"
        ops.append(_text(zx + ZONE_W / 2, sy + 97, zone["label"], chip_fg, 9, True, tag="chip"))
        if zone["number"] > 1:
            ops.append({"op": "line", "x": zx, "y": sy + 6, "x2": zx, "y2": sy + zh - 6,
                        "fill": "#222731", "tag": "sep"})
    text, color = request_line(state)
    ops.append({"op": "line", "x": sx + 8, "y": sy + sh - LINE_H, "x2": sx + sw - 8,
                "y2": sy + sh - LINE_H, "fill": "#222731", "tag": "sep"})
    request_op = _text(sx + 12, sy + sh - LINE_H / 2, text or "no pending request",
                       color if text else "#4A5260", 10, bool(text), "w", "request")
    request_op["max_width"] = sw - 24
    ops.append(request_op)
    for zone in zones:
        name = "slot %d" % zone["number"]
        x, y, w, h = rects[name]
        down = name in pressed
        glow = zone["color"] if zone["occupied"] else "#262B33"
        ops.append(_rr(x, y + h - 8, w, 7, glow, "", 3, "glow"))
        ops.append(_rr(x, y, w, h - 12, "#14171C" if down else "#252A33", "#3A404B", 10, name))
        ops.append(_text(x + w / 2, y + (h - 12) / 2, str(zone["number"]), "#D6DCE6", 16, True, tag=name))
    ctrl_on = bool(ui.get("ctrl"))
    for name, fill, label, fg in (("approve", "#1F9D55", "✓", "#EAFBF1"),
                                  ("deny", "#C53B41", "✗", "#FDECEC"),
                                  ("mic", "#2B3039", "MIC", "#D6DCE6")):
        x, y, w, h = rects[name]
        shown = _shade(fill, 0.6) if name in pressed else fill
        ops.append(_rr(x, y, w, h, shown, "#3A404B", 16, name))
        ops.append(_text(x + w / 2, y + h / 2, label, fg, 28 if name != "mic" else 16, True, tag=name))
    for name, label in (("ctrl", "Ctrl"), ("camera", "截图")):
        x, y, w, h = rects[name]
        on = name == "ctrl" and ctrl_on
        fill = "#F5A524" if on else ("#14171C" if name in pressed else "#252A33")
        ops.append(_rr(x, y, w, h, fill, "#3A404B", 10, name))
        ops.append(_text(x + w / 2, y + h / 2, label, "#0A0B0D" if on else "#D6DCE6", 11, True, tag=name))
    wx, wy, ww, wh = WHEEL
    ops.append(_rr(wx, wy, ww, wh, "#4A4F59", "#8A8F99", 24, "wheel", 2))
    for i in range(14):
        ly = wy + 18 + i * (wh - 36) / 13.0
        ops.append({"op": "line", "x": wx + 8, "y": ly, "x2": wx + ww - 8, "y2": ly,
                    "fill": "#2A2E36", "tag": "knurl"})
    ops.append(_text(wx + ww / 2, wy + 20, "▲", "#C9CFDA", 10, tag="wheel_up"))
    ops.append(_text(wx + ww / 2, wy + wh - 20, "▼", "#C9CFDA", 10, tag="wheel_down"))
    return ops


# ---------------------------------------------------------------- hub client

def read_token(home=None):
    path = (Path.home() if home is None else Path(home)) / ".agentdeck" / "token"
    return path.read_text(encoding="ascii").strip()


class HubClient:
    def __init__(self, port, token, timeout=2.0):
        self.base = "http://127.0.0.1:%d" % port
        self.token = token
        self.timeout = timeout

    def _call(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, headers={
            "Content-Type": "application/json", "X-AgentDeck-Token": self.token})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as reply:
                return json.loads(reply.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as error:
            try:
                return json.loads(error.read().decode("utf-8"))
            except ValueError:
                return {"error": "HTTP %d" % error.code}

    def state(self):
        return self._call("/state")

    def action(self, payload):
        return self._call("/action", payload)

    def rendered(self, request_id, nonce, visible=True):
        return self._call("/rendered", {"source": "virtual", "request_id": request_id,
                                        "nonce": nonce, "visible": visible})


# ---------------------------------------------------------------- tk app

class VirtualDevice:
    def __init__(self, client, scale=1.0, topmost=False, window=None):
        self.client = client
        self.scale = scale
        self.topmost = topmost
        self.window = window
        self.state = {}
        self.ui = {"ctrl": False, "pressed": {}}
        self.message = ""
        self._held = None
        self._drag = None
        self._stop = threading.Event()
        self._jobs = queue.Queue()
        self._last_ops = None
        self._drawn_request = (None, None)
        self._drawn_at = None
        self._queued_render = None

    # worker thread: polling and actions never block the Tk loop
    def _worker(self):
        try:
            next_poll = 0.0
            while not self._stop.is_set():
                try:
                    job = self._jobs.get(timeout=0.02)
                    try:
                        if isinstance(job, tuple):
                            result = self.client.rendered(*job[1])
                            if result.get("error"):
                                self._queued_render = None
                        else:
                            result = self.client.action(job)
                        self.message = result.get("message") or result.get("error") or result.get("status", "")
                    except Exception as error:
                        self.message = "hub unavailable: %s" % error
                        if isinstance(job, tuple):
                            self._queued_render = None
                except queue.Empty:
                    pass
                if time.monotonic() >= next_poll:
                    next_poll = time.monotonic() + POLL_SECONDS
                    try:
                        self.state = self.client.state()
                    except Exception:
                        self.state = {}
                        self.message = "hub unavailable"
        finally:
            try:
                self.client.rendered(None, None, visible=False)
            except Exception as error:
                log.warning("Could not unregister virtual display: %s", error)

    def send(self, payload):
        if payload is not None:
            self._jobs.put(payload)

    def _point(self, event):
        return event.x / self.scale, event.y / self.scale

    def _press(self, event):
        now = time.monotonic()
        if self.window is not None:
            self.window.remember()
        control = hit_test(*self._point(event))
        self._held = control
        if control is None:
            self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())
            return
        if control == "close":
            self._stop.set()
            return
        self.ui["pressed"][control] = now + PRESS_SECONDS
        request_id, nonce = self._drawn_request
        payload, self.ui["ctrl"] = control_action(
            control, self.ui["ctrl"], "down", request_id, nonce)
        if payload and payload["action"] in ("approve", "deny") and request_id is None:
            payload = None
        if payload and payload["action"] == "approve":
            # Decide at press, before queuing. A slow HTTP worker must never
            # turn a click in the first 300 ms into a later valid approval.
            if self._drawn_at is None or now - self._drawn_at < SWITCH_GUARD_SECONDS:
                self.message = "switch_guard"
                payload = None
        if payload and payload["action"] in ("approve", "deny"):
            payload["display_source"] = "virtual"
        if payload and payload["action"] == "interrupt":
            payload["request_id"] = request_id
        self.send(payload)
        if control == "mic":
            self.ui["pressed"][control] = now + 3600

    def _release(self, event):
        self._drag = None
        if self._held == "mic":
            self.ui["pressed"]["mic"] = time.monotonic() + PRESS_SECONDS
            payload, _ = control_action("mic", self.ui["ctrl"], "up")
            self.send(payload)
        self._held = None
        if self.window is not None:
            self.window.restore()

    def _move(self, event):
        if self._drag is not None:
            self.root.geometry("+%d+%d" % (event.x_root - self._drag[0], event.y_root - self._drag[1]))

    def _wheel(self, event):
        x, y = self._point(event)
        if hit_test(x, y) in ("wheel_up", "wheel_down"):
            self.send(wheel_action(event.delta))

    # rendering
    def _draw(self, ops):
        canvas, k = self.canvas, self.scale
        canvas.delete("all")
        for op in ops:
            if op["op"] == "rrect":
                self._round(op, k)
            elif op["op"] == "rect":
                canvas.create_rectangle(op["x"] * k, op["y"] * k, (op["x"] + op["w"]) * k,
                                        (op["y"] + op["h"]) * k, fill=op["fill"], outline=op["outline"])
            elif op["op"] == "line":
                canvas.create_line(op["x"] * k, op["y"] * k, op["x2"] * k, op["y2"] * k, fill=op["fill"])
            else:
                weight = "bold" if op["bold"] else "normal"
                font = ("Segoe UI", max(6, int(op["size"] * k)), weight)
                text = op["text"]
                if "max_width" in op:
                    from tkinter.font import Font
                    measure = Font(root=self.root, font=font).measure
                    limit = op["max_width"] * k
                    # Keep the risk/nonce end visible while eliding the command.
                    suffix_at = text.rfind(" [")
                    suffix = text[suffix_at:] if suffix_at >= 0 else text[-6:]
                    prefix = text[:suffix_at] if suffix_at >= 0 else text[:-6]
                    while prefix and measure(text) > limit:
                        prefix = prefix[:-1]
                        text = prefix + "…" + suffix
                    if measure(text) > limit:
                        text = suffix.strip()
                canvas.create_text(op["x"] * k, op["y"] * k, text=text, fill=op["fill"],
                                   anchor=op["anchor"],
                                   font=font)

    def _round(self, op, k):
        x, y, w, h = op["x"] * k, op["y"] * k, op["w"] * k, op["h"] * k
        r = min(op["radius"] * k, w / 2, h / 2)
        pts = [x + r, y, x + w - r, y, x + w, y, x + w, y + r, x + w, y + h - r, x + w, y + h,
               x + w - r, y + h, x + r, y + h, x, y + h, x, y + h - r, x, y + r, x, y]
        self.canvas.create_polygon(pts, smooth=True, fill=op["fill"], outline=op["outline"],
                                   width=op.get("width", 1))

    def _tick(self):
        if self._stop.is_set():
            self.root.quit()
            return
        now = time.monotonic()
        ui = {"ctrl": self.ui["ctrl"], "pressed": dict(self.ui["pressed"])}
        snapshot = self.state
        request = displayed_request(snapshot)
        drawn_request = (request["id"], request.get("nonce")) if request else (None, None)
        ops = build_scene(snapshot, ui, now)
        if ops != self._last_ops or drawn_request != self._drawn_request:
            self._draw(ops)
            self.root.update_idletasks()
            self._last_ops = ops
            if drawn_request != self._drawn_request or self._drawn_at is None:
                self._drawn_at = (time.monotonic()
                                  if self.root.state() != "withdrawn" else None)
            self._drawn_request = drawn_request
        if self.root.state() != "withdrawn" and self._queued_render != drawn_request:
            if self._drawn_at is None:
                self._drawn_at = time.monotonic()
            self._jobs.put(("rendered", drawn_request))
            self._queued_render = drawn_request
        self.root.after(40, self._tick)

    def run(self):
        import tkinter as tk
        if self.window is None and os.name == "nt":
            from hub_overlay import NoActivateWindow
            self.window = NoActivateWindow()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("AgentDeck Virtual Device")
        self.root.overrideredirect(True)
        if self.topmost:
            self.root.attributes("-topmost", True)
        width, height = int(BODY_W * self.scale), int(BODY_H * self.scale)
        self.canvas = tk.Canvas(self.root, width=width, height=height, highlightthickness=0,
                                bg="#010101", takefocus=0)
        self.canvas.pack()
        try:
            self.root.attributes("-transparentcolor", "#010101")
        except tk.TclError:
            pass
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.root.geometry("%dx%d+%d+%d" % (width, height, 80, 80))
        worker = threading.Thread(target=self._worker, daemon=True)
        worker.start()
        self._tick()
        self.root.update_idletasks()
        if self.window is not None:
            self.window.apply(self.root.winfo_id())
        self.root.deiconify()
        if self.window is not None:
            self.window.show()
        try:
            self.root.mainloop()
        finally:
            self._stop.set()
            worker.join(timeout=self.client.timeout + .1)
            if self.window is not None:
                self.window.close()
            self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="AgentDeck v2 software twin")
    parser.add_argument("--port", type=int, default=47800)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--topmost", action="store_true", help="keep the window above others")
    parser.add_argument("--home", type=Path, help="home holding .agentdeck/token")
    args = parser.parse_args(argv)
    if not 0.3 <= args.scale <= 3.0:
        parser.error("--scale must be between 0.3 and 3")
    try:
        token = read_token(args.home)
    except OSError as error:
        print("cannot read the AgentDeck token (is the hub started?): %s" % error, file=sys.stderr)
        return 1
    VirtualDevice(HubClient(args.port, token), args.scale, args.topmost).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
