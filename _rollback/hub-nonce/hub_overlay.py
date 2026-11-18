"""Small Hub desktop display; importing this module never creates a window."""
import ctypes
import logging
import os
import sys
import threading

if sys.platform == "win32":
    from ctypes import wintypes


log = logging.getLogger("agentdeck.hub.overlay")
POLL_MS = 300
WIDTH = 360
COLORS = {"RUN": "#48b879", "ASK": "#e5ad46", "DONE": "#609ce3",
          "ERR": "#ed6969", "IDLE": "#9299a5"}
STATES = {"think": "RUN", "tool": "RUN", "wait": "ASK", "locked": "ASK",
          "done": "DONE", "error": "ERR", "idle": "IDLE"}
BACKGROUND = "#171c24"
FOREGROUND = "#edf1f7"


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
    displayed = state.get("displayed_request_id")
    request = next((item for item in list(state.get("pending", ())) + list(state.get("locked", ()))
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
        detail = {"id": request["id"], "summary": summary, "risk": risk,
                  "label": label,
                  "color": COLORS["ERR"] if risk in ("high", "critical") or locked else COLORS["ASK"],
                  "can_approve": not locked, "can_deny": not locked}
    return {"slots": slots, "request": detail}


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


class Overlay:
    """Run tkinter on the caller's thread; share Hub's locked state/action path."""

    def __init__(self, hub, on_close=None, *, window=None):
        self.hub = hub
        self.on_close = on_close
        self.window = window
        self.stopped = threading.Event()
        self.root = None
        self.model = display_model({})
        self.message = ""
        self._drag = None
        self._height = None
        self._pressed_decisions = {}

    def stop(self):
        """May be called by another thread; Tk observes it on the next poll."""
        self.stopped.set()

    def dispatch(self, action, request_id=None):
        """Label and hotkey controls ultimately call the same Hub.action method."""
        if self.window is not None:
            self.window.restore()
        payload = {"action": action}
        if action in ("approve", "deny"):
            # None means the UI did not display a request; never approve a new one.
            if request_id is None:
                return None
            payload["request_id"] = request_id
        try:
            result = self.hub.action(payload, source="overlay")
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

    def _start_drag(self, event):
        self._press(event)
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _move(self, event):
        if self._drag is not None:
            self.root.geometry("+%d+%d" % (max(0, event.x_root - self._drag[0]),
                                          max(0, event.y_root - self._drag[1])))

    def _select(self, number):
        if self.model["slots"][number - 1]["occupied"]:
            self.dispatch("slot %d" % number)

    def _decide(self, action, request_id, enabled):
        if enabled:
            self.dispatch(action, request_id)

    def _decision_press(self, event, action):
        self._press(event)
        request = self.model["request"]
        self._pressed_decisions[action] = (request["id"], request["can_" + action]) if request else (None, False)

    def _decision_release(self, action):
        request_id, enabled = self._pressed_decisions.pop(action, (None, False))
        self._decide(action, request_id, enabled)

    def _build(self):
        import tkinter as tk
        self.root.title("AgentDeck Hub")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BACKGROUND)
        frame = tk.Frame(self.root, bg=BACKGROUND, padx=12, pady=10, width=WIDTH)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        header = tk.Frame(frame, bg=BACKGROUND)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        title = tk.Label(header, text="AGENTDECK HUB", bg=BACKGROUND, fg=FOREGROUND,
                         anchor="w", font=("Segoe UI", 10, "bold"), takefocus=False)
        title.pack(side="left", fill="x", expand=True)
        title.bind("<ButtonPress-1>", self._start_drag)
        title.bind("<B1-Motion>", self._move)
        self._button(header, "×", self.stop, bg=BACKGROUND, fg="#aab3c1",
                     font=("Segoe UI", 13)).pack(side="right")
        self.rows = []
        for number in range(1, 7):
            row = tk.Frame(frame, bg=BACKGROUND, padx=5, pady=5)
            row.grid(row=number, column=0, sticky="ew", pady=1)
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
        self.detail = tk.Frame(frame, bg=BACKGROUND)
        self.detail.grid(row=7, column=0, sticky="ew", pady=(10, 0))
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
        self.note = tk.Label(frame, text="", bg=BACKGROUND, fg="#aab3c1", anchor="w",
                             wraplength=WIDTH - 30, takefocus=False, font=("Segoe UI", 8))
        self.note.grid(row=8, column=0, sticky="ew", pady=(7, 0))

    def _render(self):
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
            self.detail.grid_remove()
        else:
            self.detail.grid()
            self.risk.configure(text=request["label"], fg=request["color"])
            self.summary.configure(text=request["summary"])
            for action, key, color in (("approve", "can_approve", COLORS["RUN"]),
                                       ("deny", "can_deny", COLORS["ERR"])):
                enabled = request[key]
                self.decision_buttons[action].configure(bg=color if enabled else "#39414e",
                                                        cursor="hand2" if enabled else "arrow")
        self.note.configure(text=self.message)

    def _poll(self):
        if self.stopped.is_set():
            self.root.quit()
            return
        try:
            self.model = display_model(self.hub.state())
            self._render()
            if self._height is not None:
                self.root.update_idletasks()
                height = self.root.winfo_reqheight()
                if height != self._height:
                    self.root.geometry("%dx%d+%d+%d" % (WIDTH, height, self.root.winfo_x(),
                                       max(0, self.root.winfo_y() + self._height - height)))
                    self._height = height
        except Exception as error:
            log.warning("Overlay refresh failed: %s", error)
            self.note.configure(text="Hub state unavailable")
        self.root.after(POLL_MS, self._poll)

    def run(self):
        """Own the main-thread Tk loop until stop, close, or startup failure."""
        if self.stopped.is_set():
            return
        try:
            import tkinter as tk
            if self.window is None and os.name == "nt":
                self.window = NoActivateWindow()
            self.root = tk.Tk()
            self.root.withdraw()
            self._build()
            self._poll()
            self.root.update_idletasks()
            height = self.root.winfo_reqheight()
            self._height = height
            self.root.geometry("%dx%d+%d+%d" % (WIDTH, height,
                               max(0, self.root.winfo_screenwidth() - WIDTH - 24),
                               max(0, self.root.winfo_screenheight() - height - 64)))
            if self.window is not None:
                self.window.apply(self.root.winfo_id())
            self.root.deiconify()
            if self.window is not None:
                self.window.show()
            self.root.mainloop()
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
