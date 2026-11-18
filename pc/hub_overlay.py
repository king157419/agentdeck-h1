"""Small Hub desktop display; importing this module never creates a window."""
import ctypes
import json
import logging
import os
from pathlib import Path
import sys
import threading

if sys.platform == "win32":
    from ctypes import wintypes


log = logging.getLogger("agentdeck.hub.overlay")
POLL_MS = 300
WIDTH = 360
TRANSLUCENT_ALPHA = 0.85
OPAQUE_ALPHA = 1.0
COLORS = {"RUN": "#48b879", "ASK": "#e5ad46", "DONE": "#609ce3",
          "ERR": "#ed6969", "IDLE": "#9299a5"}
STATES = {"think": "RUN", "tool": "RUN", "wait": "ASK", "locked": "ASK",
          "done": "DONE", "error": "ERR", "idle": "IDLE"}
BACKGROUND = "#171c24"
FOREGROUND = "#edf1f7"


def overlay_config_file(home=None):
    return (Path.home() if home is None else Path(home)) / ".agentdeck" / "overlay.json"


def display_model(state):
    """Convert a /state snapshot to plain display data without mutating it."""
    sessions = {session["slot"]: session for session in state.get("sessions", ())}
    slots = []
    for number in range(1, 7):
        session = sessions.get(number)
        label = STATES.get(session.get("state"), "IDLE") if session else "IDLE"
        slots.append({"number": number,
                      "name": str(session.get("name") or session.get("project") or "Unnamed")
                      if session else "No session",
                      "label": label, "color": COLORS[label],
                      "occupied": session is not None,
                      "selected": state.get("selected_slot") == number})
    pending_list = list(state.get("pending", ()))
    locked_list = list(state.get("locked", ()))
    displayed = state.get("displayed_request_id")
    request = next((item for item in pending_list + locked_list
                    if displayed is not None and item.get("id") == displayed), None)
    detail = None
    if request is not None:
        summary = " ".join(str(request.get("summary", "")).split())
        if len(summary) > 80:
            summary = summary[:79] + "…"
        risk = request.get("risk", "low")
        gate = request.get("gate", False)
        locked = request.get("status") == "locked" or (risk == "critical" and not gate)
        label = "LOCKED: use terminal" if locked else risk.upper()
        if not locked and risk in ("high", "critical") and request.get("armed"):
            label += " · press again"
        if gate:
            label = "GATE · " + label
        if request.get("gate_confirmed"):
            label += " · 已在闸门确认"
        nonce = request.get("nonce")
        if type(nonce) is int:
            label += " · #%04x" % (nonce & 0xffff)
        detail = {"nonce": nonce, "id": request["id"], "summary": summary, "risk": risk,
                  "label": label,
                  "color": COLORS["ERR"] if risk in ("high", "critical") or locked else COLORS["ASK"],
                  "can_approve": not locked, "can_deny": not locked}
    session_count = len(sessions)
    pending_count = len(pending_list)
    return {
        "slots": slots,
        "request": detail,
        "session_count": session_count,
        "pending_count": pending_count,
        "summary_text": "%d 个会话 / %d 个待批" % (session_count, pending_count),
        "expanded": bool(pending_count or detail is not None),
    }


class NoActivateWindow:
    """Keep a Tk wrapper window out of the foreground on Windows.

    WS_EX_NOACTIVATE is set before showing the window. The wrapper also answers
    WM_MOUSEACTIVATE with MA_NOACTIVATE, preserving the click for label controls.
    """

    def __init__(self, user=None):
        self.user = ctypes.WinDLL("user32", use_last_error=True) if user is None else user
        pointer = ctypes.c_ssize_t
        self.proc_type = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
            pointer, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        suffix = "LongPtrW" if ctypes.sizeof(ctypes.c_void_p) == 8 else "LongW"
        self.get_long = getattr(self.user, "GetWindow" + suffix)
        self.set_long = getattr(self.user, "SetWindow" + suffix)
        self.get_long.argtypes, self.get_long.restype = [wintypes.HWND, ctypes.c_int], pointer
        self.set_long.argtypes, self.set_long.restype = [wintypes.HWND, ctypes.c_int, pointer], pointer
        signatures = {
            "GetAncestor": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            "GetForegroundWindow": ([], wintypes.HWND),
            "SetForegroundWindow": ([wintypes.HWND], wintypes.BOOL),
            "IsChild": ([wintypes.HWND, wintypes.HWND], wintypes.BOOL),
            "CallWindowProcW": ([ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM], pointer),
            "SetWindowPos": ([wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
            "ShowWindow": ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = args, result
        self.hwnd = None
        self.old_proc = None
        self.proc = None
        self.previous = self.user.GetForegroundWindow()
        self._dpi_context = None

    def begin_dpi(self):
        """Use one physical-pixel coordinate space for Tk, cursor and monitors."""
        method = getattr(self.user, "SetThreadDpiAwarenessContext", None)
        if method is not None:
            method.argtypes, method.restype = [ctypes.c_void_p], ctypes.c_void_p
            self._dpi_context = method(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
            if not self._dpi_context:
                log.warning("Could not enable per-monitor DPI awareness")

    def work_areas(self):
        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        callback_type = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
            wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
            ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        enumerate_monitors = self.user.EnumDisplayMonitors
        enumerate_monitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                      callback_type, wintypes.LPARAM]
        enumerate_monitors.restype = wintypes.BOOL
        monitor_info = self.user.GetMonitorInfoW
        monitor_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        monitor_info.restype = wintypes.BOOL
        areas = []

        def collect(monitor, dc, rect, data):
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if monitor_info(monitor, ctypes.byref(info)):
                work = info.rcWork
                areas.append((work.left, work.top, work.right, work.bottom))
            return True

        if not enumerate_monitors(None, None, callback_type(collect), 0) or not areas:
            raise OSError("Could not enumerate display work areas")
        return areas

    def place(self, x, y, width, height):
        # Native absolute coordinates support negative desktop origins. Tk's
        # '-X' geometry syntax instead means an offset from the right edge.
        if not self.user.SetWindowPos(self.hwnd, None, x, y, width, height,
                                      0x10 | 0x04):  # NOACTIVATE | NOZORDER
            raise ctypes.WinError(ctypes.get_last_error())

    def _set(self, index, value):
        ctypes.set_last_error(0)
        previous = self.set_long(self.hwnd, index, value)
        if not previous and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        return previous

    def apply(self, child):
        self.hwnd = self.user.GetAncestor(child, 2) or child  # GA_ROOT
        style = self.get_long(self.hwnd, -20)
        self._set(-20, (style | 0x08000000 | 0x80) & ~0x40000)
        self.proc = self.proc_type(self._message)
        self.old_proc = self._set(-4, ctypes.cast(self.proc, ctypes.c_void_p).value)
        if not self.user.SetWindowPos(self.hwnd, wintypes.HWND(-1), 0, 0, 0, 0,
                                      0x10 | 0x01 | 0x02 | 0x20):
            raise ctypes.WinError(ctypes.get_last_error())

    def _message(self, hwnd, message, wparam, lparam):
        if message == 0x21:  # WM_MOUSEACTIVATE
            self.remember()
            return 3  # MA_NOACTIVATE: deliver the click, keep foreground unchanged
        return self.user.CallWindowProcW(self.old_proc, hwnd, message, wparam, lparam)

    def _is_overlay(self, hwnd):
        return bool(hwnd and self.hwnd and
                    (hwnd == self.hwnd or self.user.IsChild(self.hwnd, hwnd)))

    def remember(self):
        foreground = self.user.GetForegroundWindow()
        if foreground and not self._is_overlay(foreground):
            self.previous = foreground

    def restore(self):
        # Do not undo an intentional slot selection or an external focus change.
        if self.previous and self._is_overlay(self.user.GetForegroundWindow()):
            if not self.user.SetForegroundWindow(self.previous):
                log.warning("Could not restore the window behind the overlay")

    def show(self):
        self.user.ShowWindow(self.hwnd, 4)  # SW_SHOWNOACTIVATE
        self.restore()

    def close(self):
        if self.old_proc is not None:
            self._set(-4, self.old_proc)
            self.old_proc = None
            self.proc = None
        if self._dpi_context:
            self.user.SetThreadDpiAwarenessContext(self._dpi_context)
            self._dpi_context = None


class Overlay:
    """Run tkinter on the caller's thread; share Hub's locked state/action path."""

    def __init__(self, hub, on_close=None, *, window=None, home=None, state_path=None):
        self.hub = hub
        self.on_close = on_close
        self.window = window
        hub_home = getattr(hub, "home", None)
        if state_path is not None:
            self.state_path = Path(state_path)
        elif home is not None:
            self.state_path = overlay_config_file(home)
        elif isinstance(hub_home, (str, os.PathLike)):
            self.state_path = overlay_config_file(hub_home)
        else:
            self.state_path = None
        self.stopped = threading.Event()
        self.hidden = False
        self._interrupted = False
        self._dismissed_requests = set()
        self._active_ids = set()
        self.translucent = True
        self._pos = None
        self._runtime_x = None
        self.root = None
        self.model = display_model({})
        self.message = ""
        self._drag = None
        self._dragged = False
        self._height = None
        self._anchor_bottom = None
        self._areas = None
        self._pressed_decisions = {}
        self.frame = None
        self.header = None
        self.status_label = None
        self.alpha_button = None
        self.body = None
        self.rows = []
        self.detail = None
        self.risk = None
        self.summary = None
        self.decisions = None
        self.decision_buttons = {}
        self.note = None

    @staticmethod
    def _request_ids(state):
        return {item["id"] for item in list(state.get("pending", ())) + list(state.get("locked", ()))
                if isinstance(item, dict) and isinstance(item.get("id"), str)}

    def stop(self):
        """May be called by another thread; Tk observes it on the next poll."""
        self.stopped.set()

    def hide(self):
        """Hide the overlay without stopping Hub or ending the Tk loop."""
        self._dismissed_requests = set(self._active_ids)
        request = self.model.get("request")
        if request and isinstance(request.get("id"), str):
            self._dismissed_requests.add(request["id"])
        self.hidden = True
        self._pressed_decisions.clear()
        self.hub.hide_display('overlay')
        if self.root is not None:
            self.root.withdraw()
        if self.window is not None:
            self.window.restore()

    def show(self):
        """Re-show a hidden overlay without stealing foreground focus."""
        self.hidden = False
        self._dismissed_requests.clear()
        if self.root is not None:
            self.root.deiconify()
            self._apply_alpha()
        if self.window is not None:
            self.window.show()

    def _apply_alpha(self):
        if self.root is not None:
            try:
                self.root.attributes(
                    "-alpha", TRANSLUCENT_ALPHA if self.translucent else OPAQUE_ALPHA)
            except Exception as error:
                log.debug("Overlay alpha unavailable: %s", error)

    def toggle_translucent(self):
        self.translucent = not self.translucent
        self._apply_alpha()
        if self.alpha_button is not None:
            self.alpha_button.configure(
                bg="#2b394d" if self.translucent else BACKGROUND,
                fg=FOREGROUND if self.translucent else "#778292")
        self._save_prefs()
        if self.window is not None:
            self.window.restore()

    def _load_prefs(self):
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as error:
            log.warning("Could not read overlay config %s: %s", self.state_path, error)
            return
        if not isinstance(data, dict):
            log.warning("Overlay config %s must be a JSON object", self.state_path)
            return
        x, y = data.get("x"), data.get("y")
        if type(x) is int and type(y) is int:
            self._pos = (x, y)
        translucent = data.get("translucent")
        if type(translucent) is bool:
            self.translucent = translucent

    def _save_prefs(self):
        if self.state_path is None:
            return
        data = {"translucent": self.translucent}
        if self._pos is not None:
            data["x"], data["y"] = int(self._pos[0]), int(self._pos[1])
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.state_path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            temp.replace(self.state_path)
        except OSError as error:
            log.warning("Could not save overlay config %s: %s", self.state_path, error)

    def _callback_exception(self, exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            self._interrupted = True
            self.stop()
            if self.root is not None:
                self.root.quit()
            return
        log.error("Overlay callback failed", exc_info=(exc_type, exc_value, exc_tb))

    def dispatch(self, action, request_id=None, nonce=None, *, received_at=None):
        """Label and hotkey controls ultimately call the same Hub.action method."""
        if self.window is not None:
            self.window.restore()
        payload = {"action": action}
        if action in ("approve", "deny"):
            # None means the UI did not display a request; never approve a new one.
            if request_id is None:
                return None
            payload["request_id"] = request_id
            payload["nonce"] = nonce
        try:
            if received_at is None:
                result = self.hub.action(payload, source="overlay")
            else:
                result = self.hub.action(payload, source="overlay", received_at=received_at)
            self.message = result.get("message") or result.get("status", "")
            return result
        except ValueError as error:
            self.message = str(error)
            log.warning("Overlay action failed: %s", error)
            return None
        finally:
            if self.window is not None:
                self.window.restore()

    def _press(self, event):
        if self.window is not None:
            self.window.remember()

    def _button(self, parent, text, callback, **kwargs):
        import tkinter as tk
        label = tk.Label(parent, text=text, takefocus=False, cursor="hand2", **kwargs)
        label.bind("<ButtonPress-1>", self._press)
        label.bind("<ButtonRelease-1>", lambda event: callback())
        return label

    def _bind_drag(self, widget):
        widget.bind("<ButtonPress-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._move)
        widget.bind("<ButtonRelease-1>", self._end_drag)

    def _work_areas(self):
        # Inspect the adapter type so a plain Mock used by legacy tests does
        # not accidentally claim native positioning support.
        if callable(getattr(type(self.window), "work_areas", None)):
            return tuple(self.window.work_areas())
        width, height = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if type(width) is int and type(height) is int:
            return ((0, 0, width, height),)
        return ()

    def _place(self, x, y, height, *, size=True):
        areas = self._work_areas()
        width = WIDTH
        if areas:
            candidates = []
            for left, top, right, bottom in areas:
                w, h = min(WIDTH, right - left), min(height, bottom - top)
                px = min(max(x, left), right - w)
                py = min(max(y, top), bottom - h)
                candidates.append(((px - x) ** 2 + (py - y) ** 2, px, py, w, h))
            _, x, y, width, actual_height = min(candidates)
        else:
            x, y = max(0, x), max(0, y)
            actual_height = height
        self._areas = areas
        self._pos = (int(x), int(y))
        self._runtime_x = int(x)
        self._anchor_bottom = int(y) + actual_height
        if callable(getattr(type(self.window), "place", None)):
            self.root.geometry("%dx%d" % (width, actual_height))
            self.root.update_idletasks()
            self.window.place(int(x), int(y), width, actual_height)
        elif size:
            self.root.geometry("%dx%d+%d+%d" % (width, actual_height, x, y))
        else:
            self.root.geometry("+%d+%d" % (x, y))
        self._height = height

    def _start_drag(self, event):
        self._press(event)
        base_x = self._pos[0] if self._pos is not None else self.root.winfo_x()
        base_y = self._pos[1] if self._pos is not None else self.root.winfo_y()
        # Prefer live window coordinates when Tk returns concrete integers.
        live_x, live_y = self.root.winfo_x(), self.root.winfo_y()
        if type(live_x) is int and type(live_y) is int and not self._dragged:
            base_x, base_y = live_x, live_y
        self._drag = (event.x_root - base_x, event.y_root - base_y)
        self._dragged = False

    def _move(self, event):
        if self._drag is not None:
            x = event.x_root - self._drag[0]
            y = event.y_root - self._drag[1]
            self._place(x, y, self._height or self.root.winfo_reqheight(), size=False)
            self._dragged = True

    def _end_drag(self, event=None):
        if self._drag is not None:
            moved = self._dragged
            self._drag = None
            self._dragged = False
            if moved:
                self._place(*self._pos, self._height)
                self._save_prefs()
        if self.window is not None:
            self.window.restore()

    def _select(self, number):
        if self.model["slots"][number - 1]["occupied"]:
            self.dispatch("slot %d" % number)

    def _decide(self, action, request_id, enabled, nonce=None):
        if enabled:
            self.dispatch(action, request_id, nonce)

    def _decision_press(self, event, action):
        pressed_at = self.hub.monotonic()
        request = self.model['request']
        captured = (request['id'], request['can_' + action], request.get('nonce'), pressed_at) if request else (None, False, None, pressed_at)
        self._press(event)
        self._pressed_decisions[action] = captured

    def _decision_release(self, action):
        request_id, enabled, nonce, pressed_at = self._pressed_decisions.pop(action, (None, False, None, None))
        if enabled:
            self.dispatch(action, request_id, nonce, received_at=pressed_at)

    def _build(self):
        import tkinter as tk
        self.root.title("AgentDeck Hub")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BACKGROUND)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.frame = tk.Frame(self.root, bg=BACKGROUND, padx=12, pady=6, width=WIDTH)
        self.frame.pack(fill="both", expand=True)
        self.frame.columnconfigure(0, weight=1)
        self._bind_drag(self.frame)
        self.header = tk.Frame(self.frame, bg=BACKGROUND)
        self.header.grid(row=0, column=0, sticky="ew")
        self._bind_drag(self.header)
        self.status_label = tk.Label(self.header, text="0 个会话 / 0 个待批", bg=BACKGROUND,
                                     fg=FOREGROUND, anchor="w",
                                     font=("Segoe UI", 9, "bold"), takefocus=False)
        self.status_label.pack(side="left", fill="x", expand=True)
        self._bind_drag(self.status_label)
        self._button(self.header, "×", self.hide, bg=BACKGROUND, fg="#aab3c1",
                     padx=4, font=("Segoe UI", 12)).pack(side="right")
        self.alpha_button = self._button(
            self.header, "半透明", self.toggle_translucent,
            bg="#2b394d" if self.translucent else BACKGROUND,
            fg=FOREGROUND if self.translucent else "#778292",
            padx=6, pady=1, font=("Segoe UI", 8))
        self.alpha_button.pack(side="right", padx=(0, 4))
        self.body = tk.Frame(self.frame, bg=BACKGROUND)
        self.body.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.body.columnconfigure(0, weight=1)
        self.rows = []
        for number in range(1, 7):
            row = tk.Frame(self.body, bg=BACKGROUND, padx=5, pady=5)
            row.grid(row=number - 1, column=0, sticky="ew", pady=1)
            row.columnconfigure(1, weight=1)
            number_label = self._button(row, str(number), lambda n=number: self._select(n),
                                        bg=BACKGROUND, fg="#9aa6b8", width=2,
                                        font=("Segoe UI", 10, "bold"))
            number_label.grid(row=0, column=0)
            name = self._button(row, "", lambda n=number: self._select(n), bg=BACKGROUND,
                                fg=FOREGROUND, anchor="w", font=("Segoe UI", 10))
            name.grid(row=0, column=1, sticky="ew", padx=6)
            badge = self._button(row, "IDLE", lambda n=number: self._select(n),
                                 bg=COLORS["IDLE"], fg=BACKGROUND, width=5,
                                 font=("Segoe UI", 8, "bold"))
            badge.grid(row=0, column=2)
            self.rows.append((row, number_label, name, badge))
        self.detail = tk.Frame(self.body, bg=BACKGROUND)
        self.detail.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        self.risk = tk.Label(self.detail, bg=BACKGROUND, anchor="w", takefocus=False,
                             font=("Segoe UI", 9, "bold"))
        self.risk.pack(fill="x")
        self.summary = tk.Label(self.detail, bg=BACKGROUND, fg=FOREGROUND, anchor="w",
                                justify="left", wraplength=WIDTH - 30, takefocus=False,
                                font=("Segoe UI", 10))
        self.summary.pack(fill="x", pady=(5, 8))
        self.decisions = tk.Frame(self.detail, bg=BACKGROUND)
        self.decisions.pack(fill="x")
        self.decision_buttons = {}
        for action, text in (("approve", "✓"), ("deny", "✗")):
            label = tk.Label(self.decisions, text=text, takefocus=False, cursor="hand2",
                             fg=FOREGROUND, width=7, padx=4, pady=3,
                             font=("Segoe UI", 13, "bold"))
            label.bind("<ButtonPress-1>", lambda event, a=action: self._decision_press(event, a))
            label.bind("<ButtonRelease-1>", lambda event, a=action: self._decision_release(a))
            label.pack(side="left", padx=(0, 8))
            self.decision_buttons[action] = label
        self.note = tk.Label(self.body, text="", bg=BACKGROUND, fg="#aab3c1", anchor="w",
                             wraplength=WIDTH - 30, takefocus=False, font=("Segoe UI", 8))
        self.note.grid(row=7, column=0, sticky="ew", pady=(7, 0))

    def _render(self):
        if self.status_label is not None:
            self.status_label.configure(
                text=self.model["summary_text"],
                fg=COLORS["ASK"] if self.model["pending_count"] else FOREGROUND)
        if self.alpha_button is not None:
            self.alpha_button.configure(
                bg="#2b394d" if self.translucent else BACKGROUND,
                fg=FOREGROUND if self.translucent else "#778292")
        if self.body is not None:
            if self.model["expanded"]:
                self.body.grid()
            else:
                self.body.grid_remove()
        for data, (row, number, name, badge) in zip(self.model["slots"], self.rows):
            background = "#273344" if data["selected"] else BACKGROUND
            row.configure(bg=background)
            number.configure(bg=background)
            # Bound the text so a long project name cannot expand the panel.
            text = data["name"]
            name.configure(text=text if len(text) <= 27 else text[:26] + "…", bg=background,
                           fg=FOREGROUND if data["occupied"] else "#778292")
            badge.configure(text=data["label"], bg=data["color"])
        request = self.model["request"]
        if request is None:
            if self.detail is not None:
                self.detail.grid_remove()
        else:
            if self.detail is not None:
                self.detail.grid()
            self.risk.configure(text=request["label"], fg=request["color"])
            self.summary.configure(text=request["summary"])
            for action, key, color in (("approve", "can_approve", COLORS["RUN"]),
                                       ("deny", "can_deny", COLORS["ERR"])):
                enabled = request[key]
                self.decision_buttons[action].configure(bg=color if enabled else "#39414e",
                                                        cursor="hand2" if enabled else "arrow")
        if self.note is not None:
            self.note.configure(text=self.message)

    def _poll(self):
        if self.stopped.is_set():
            self.root.quit()
            return
        previous_model = self.model
        previous_active = set(self._active_ids)
        previous_dismissed = set(self._dismissed_requests)
        try:
            state = self.hub.state()
            active_ids = self._request_ids(state)
            self._active_ids = active_ids
            self._dismissed_requests &= active_ids
            reappear = self.hidden and bool(active_ids - self._dismissed_requests)
            self.model = display_model(state)
            self._render()
            self.root.update_idletasks()
            if self._height is not None:
                height = self.root.winfo_reqheight()
                if height != self._height or self._work_areas() != self._areas:
                    anchor = (self.root.winfo_y() + self._height
                              if self._anchor_bottom is None else self._anchor_bottom)
                    x = self._runtime_x if self._runtime_x is not None else self.root.winfo_x()
                    self._place(x, anchor - height, height)
            if reappear:
                self.show()
            request = self.model["request"]
            # Startup and hidden states keep the window withdrawn; acknowledge only visible pixels.
            if not self.hidden and self.root.state() != "withdrawn":
                self.hub.record_rendered(request["id"] if request else None,
                                         request.get("nonce") if request else None, source="overlay")
        except KeyboardInterrupt:
            self._interrupted = True
            self.stop()
            self.root.quit()
            return
        except Exception as error:
            self.model = previous_model
            self._active_ids = previous_active
            self._dismissed_requests = previous_dismissed
            log.warning("Overlay refresh failed: %s", error)
            if self.note is not None:
                self.note.configure(text="Hub state unavailable")
        self.root.after(POLL_MS, self._poll)

    def run(self):
        """Own the main-thread Tk loop until stop, interrupt, or startup failure."""
        if self.stopped.is_set():
            return
        self._load_prefs()
        try:
            import tkinter as tk
            if self.window is None and os.name == "nt":
                self.window = NoActivateWindow()
            if callable(getattr(type(self.window), "begin_dpi", None)):
                self.window.begin_dpi()
            self.root = tk.Tk()
            self.root.report_callback_exception = self._callback_exception
            self.root.withdraw()
            self._build()
            self._poll()
            self.root.update_idletasks()
            height = self.root.winfo_reqheight()
            if self.window is not None:
                self.window.apply(self.root.winfo_id())
            areas = self._work_areas()
            if self._pos is not None:
                x, y = self._pos
            else:
                _, _, right, bottom = next((a for a in areas if a[0] <= 0 < a[2]
                                           and a[1] <= 0 < a[3]), areas[0])
                x, y = right - WIDTH - 24, bottom - height - 64
            self._place(x, y, height)
            self._apply_alpha()
            self.root.deiconify()
            self._apply_alpha()
            if self.window is not None:
                self.window.show()
            self.root.mainloop()
            if self._interrupted:
                raise KeyboardInterrupt
        finally:
            self.stopped.set()
            try:
                if self.window is not None:
                    self.window.close()
            finally:
                try:
                    if self.root is not None:
                        self.root.destroy()
                        self.root = None
                finally:
                    if self.on_close is not None:
                        self.on_close()
