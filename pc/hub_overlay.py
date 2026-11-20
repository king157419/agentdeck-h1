"""Small Hub desktop display; importing this module never creates a window."""
import ctypes
import json
import logging
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import sys
import threading
import time

import agentdeck_theme as theme

if sys.platform == "win32":
    from ctypes import wintypes


log = logging.getLogger("agentdeck.hub.overlay")
POLL_MS = 300
WIDTH = 360
TRANSLUCENT_ALPHA = 0.85
OPAQUE_ALPHA = 1.0
COLORS = theme.STATUS
STATES = {"think": "RUN", "tool": "RUN", "wait": "ASK", "locked": "ASK",
          "done": "DONE", "error": "ERR", "idle": "IDLE"}
BACKGROUND = theme.BG
FOREGROUND = theme.TEXT
INPUT_NOTICE_SECONDS = 2.0
DOT_STEP = 14
EMPTY_TEXT = "还没有会话：新开 Claude/Codex 会话后出现"
DRIVER_NOTICE = "按键会漏进窗口：先用 Zadig 把接口 0 换成 WinUSB"
ABSENT_NOTICE = "没检测到宏键盘"
ANSWER_HINTS = {"AskUserQuestion": "需回答", "ExitPlanMode": "确认计划"}
PREVIEW_COLS = 46
PREVIEW_ROWS = 8
ACTIVITY_CHARS = 20


class TkWaker:
    """Post native messages so Windows Tcl cannot sleep past its Tk timers."""

    def __init__(self, hwnd, interval=.25, post=None):
        if interval <= 0:
            raise ValueError("wake interval must be positive")
        self.hwnd, self.interval = hwnd, interval
        self._post = post
        if self._post is None and os.name == "nt" and hwnd:
            self._post = ctypes.WinDLL("user32", use_last_error=True).PostMessageW
            self._post.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                   ctypes.c_size_t, ctypes.c_ssize_t]
            self._post.restype = ctypes.c_int
        self._stop = threading.Event()
        self._thread = None

    def wake(self):
        """Safe from any thread: never call Tk, including winfo_id()."""
        if os.name != "nt" or not self.hwnd:
            return False
        try:
            return bool(self._post(self.hwnd, 0, 0, 0))  # WM_NULL
        except Exception as error:
            log.debug("UI wake failed: %s", error)
            return False

    def _run(self):
        while not self._stop.wait(self.interval):
            self.wake()

    def start(self):
        if os.name != "nt" or not self.hwnd:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="AgentDeck UI wake", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.)


def overlay_config_file(home=None):
    return (Path.home() if home is None else Path(home)) / ".agentdeck" / "overlay.json"


def _char_width(char):
    import unicodedata
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def _text_width(text):
    return sum(_char_width(char) for char in text)


def wrap_tail(text, cols=PREVIEW_COLS, rows=PREVIEW_ROWS):
    """The last ``rows`` display lines of ``text``, each at most ``cols`` columns.

    Wide (W/F) characters count as two columns. Code fences and repeated blank
    lines are dropped; "…" starts the first line when earlier text was cut.
    """
    lines = []
    for raw in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        raw = "".join(char for char in raw.expandtabs(4) if char >= " " or char == "\t").rstrip()
        if raw.lstrip().startswith("```"):
            continue
        if not raw.strip():
            if lines and lines[-1] != "":
                lines.append("")
            continue
        current, width = "", 0
        for char in raw:
            size = _char_width(char)
            if current and width + size > cols:
                lines.append(current)
                current, width = "", 0
            current += char
            width += size
        lines.append(current)
    while lines and lines[-1] == "":
        lines.pop()
    truncated = len(lines) > rows
    lines = lines[-rows:]
    while lines and lines[0] == "":
        lines.pop(0)
    if truncated and lines:
        first = lines[0]
        while first and _text_width("…" + first) > cols:
            first = first[1:]
        lines[0] = "…" + first
    return lines


def _ago(seconds):
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return "%d分钟前" % (seconds // 60)
    if seconds < 86400:
        return "%d小时前" % (seconds // 3600)
    return "%d天前" % (seconds // 86400)


def _preview(state, sessions, request, now):
    """Latest line of the selected session, else of the first one waiting for you."""
    chosen = sessions.get(state.get("selected_slot"))
    if chosen is None:
        chosen = next((sessions[number] for number in sorted(sessions)
                       if sessions[number].get("state") in ("wait", "locked")), None)
    if chosen is None or not isinstance(chosen.get("last_text"), str) or not chosen["last_text"].strip():
        return None
    if request is not None and (request.get("agent"), request.get("session_id")) == (
            chosen.get("agent"), chosen.get("session_id")):
        return None  # the approval detail for this session takes the space
    name = str(chosen.get("name") or chosen.get("project") or "Unnamed")
    parts = ["#%s %s" % (chosen.get("slot"), name)]
    if isinstance(chosen.get("last_kind"), str) and chosen["last_kind"]:
        parts.append(chosen["last_kind"])
    at = chosen.get("last_text_at")
    if now is not None and isinstance(at, (int, float)) and not isinstance(at, bool):
        parts.append(_ago(max(0, now - at)))
    return {"title": " · ".join(parts), "lines": wrap_tail(chosen["last_text"])}


def display_model(state, now=None):
    """Convert a /state snapshot to plain display data without mutating it.

    ``now`` (wall clock) decides whether the last key result is still shown.
    """
    sessions = {session["slot"]: session for session in state.get("sessions", ())}
    windows = {}
    for session in sessions.values():
        if type(session.get("hwnd")) is int:
            windows[session["hwnd"]] = windows.get(session["hwnd"], 0) + 1
    slots = []
    for number in range(1, 7):
        session = sessions.get(number)
        label = STATES.get(session.get("state"), "IDLE") if session else "IDLE"
        activity = ""
        if session and session.get("state") in ("think", "tool") and isinstance(session.get("activity"), str):
            activity = " ".join(session["activity"].split())
            if len(activity) > ACTIVITY_CHARS:
                activity = activity[:ACTIVITY_CHARS - 1] + "…"
        slots.append({"number": number,
                      "name": str(session.get("name") or session.get("project") or "Unnamed")
                      if session else "",
                      "label": label, "color": COLORS[label],
                      "occupied": session is not None,
                      "hint": ANSWER_HINTS.get(session.get("needs_answer"), "") if session else "",
                      "needs_input": bool(session) and session.get("state") in ("wait", "locked"),
                      "activity": activity,
                      # Several sessions in one window (terminal tabs): focus cannot pick the tab.
                      "same_window": bool(session) and windows.get(session.get("hwnd"), 0) > 1,
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
    last = state.get("last_input")
    feedback = None
    if (isinstance(last, dict) and isinstance(last.get("text"), str) and now is not None
            and isinstance(last.get("at"), (int, float)) and 0 <= now - last["at"] <= INPUT_NOTICE_SECONDS):
        feedback = {"text": last["text"], "ok": last.get("ok") is not False}
    reader = state.get("input_reader")
    return {
        "slots": slots,
        "request": detail,
        "preview": _preview(state, sessions, request, now),
        "session_count": session_count,
        "pending_count": pending_count,
        "summary_text": "%d 待批" % pending_count if pending_count else "%d 个会话" % session_count,
        # The session list is always shown; the request block is extra.
        "expanded": True,
        "empty_text": EMPTY_TEXT if not session_count else "",
        "feedback": feedback,
        "notice": (DRIVER_NOTICE if reader == "raw" else ABSENT_NOTICE if reader == "absent" else ""),
        "notice_action": reader == "raw",
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
            "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.user, name, None)
            if function is None:
                continue
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

    def reapply(self):
        """Restore TOOLWINDOW | NOACTIVATE (Tk's -alpha rewrites the extended style).

        Without WS_EX_TOOLWINDOW an unowned window gets a taskbar button, which
        users mistake for the tray icon. Taskbar membership is decided at show
        time, so a visible window is hidden and re-shown without activation.
        """
        if not self.hwnd:
            return False
        style = self.get_long(self.hwnd, -20)
        wanted = (style | 0x08000000 | 0x80) & ~0x40000
        if wanted == style:
            return False
        self._set(-20, wanted)
        visible = getattr(self.user, "IsWindowVisible", None)
        shown = bool(visible(self.hwnd)) if callable(visible) else False
        if shown:
            self.user.ShowWindow(self.hwnd, 0)  # SW_HIDE
        self.user.SetWindowPos(self.hwnd, None, 0, 0, 0, 0, 0x37)  # NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED
        if shown:
            self.user.ShowWindow(self.hwnd, 4)  # SW_SHOWNOACTIVATE
        return True

    def set_alpha(self, alpha):
        """Window opacity without Tk's -alpha, which would drop the tool-window bits."""
        if not self.hwnd:
            return False
        style = self.get_long(self.hwnd, -20)
        wanted = (style | 0x80000 | 0x08000000 | 0x80) & ~0x40000  # LAYERED + tool + noactivate
        if wanted != style:
            self._set(-20, wanted)
        layered = getattr(self.user, "SetLayeredWindowAttributes", None)
        if layered is None:
            return False
        layered.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD]
        layered.restype = wintypes.BOOL
        return bool(layered(self.hwnd, 0, max(0, min(255, int(round(alpha * 255)))), 2))  # LWA_ALPHA

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
        self._waker = None
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
        self.dots = None
        self.alpha_button = None
        self.body = None
        self.rows = []
        self.detail = None
        self.preview_box = None
        self.preview_title = None
        self.preview = None
        self._preview_shown = None
        self.risk = None
        self.summary = None
        self.decisions = None
        self.decision_buttons = {}
        self.note = None
        self.empty_label = None
        self.notice_label = None
        self.menu_button = None
        self.heartbeat = None      # set by hub.main: the UI watchdog's beat
        self.menu_items = None     # callable -> [(label, callback) | None]; tray app supplies it
        self.on_driver_help = None
        self._show_seen = None
        self.state = {}
        self._tasks = self._completed = self._worker = None
        self._worker_stop = threading.Event()
        self._state_pending = False

    def _start_background(self):
        """Keep Hub locks and native desktop work out of Tk callbacks."""
        self._tasks, self._completed = SimpleQueue(), SimpleQueue()
        self._worker_stop.clear()

        def work():
            while not self._worker_stop.is_set():
                job = self._tasks.get()
                if job is None or self._worker_stop.is_set():
                    break
                callback, done, failed = job
                try:
                    value = callback()
                except Exception as error:
                    log.exception("Overlay background operation failed")
                    self._completed.put((failed, error))
                else:
                    self._completed.put((done, value))

        self._worker = threading.Thread(target=work, name="AgentDeck UI tasks", daemon=True)
        self._worker.start()

    def _stop_background(self):
        self._worker_stop.set()
        if self._tasks is not None:
            self._tasks.put(None)
        if self._worker is not None:
            self._worker.join(timeout=.2)

    def defer(self, callback, done=None, failed=None):
        """Completion callbacks run on Tk when _poll consumes the result."""
        if self._tasks is None:
            try:
                value = callback()
            except Exception as error:
                if failed is None:
                    raise
                failed(error)
            else:
                if done is not None:
                    done(value)
            return
        if not self._worker_stop.is_set():
            self._tasks.put((callback, done, failed))

    def _drain_completed(self):
        if self._completed is None:
            return
        for _ in range(50):
            try:
                callback, value = self._completed.get_nowait()
            except Empty:
                break
            if callback is not None:
                callback(value)

    def _display_call(self, callback):
        # These two Hub operations only publish display metadata. Skip a busy
        # lock and retry from the next Tk poll so acknowledgements describe the
        # pixels currently visible, never an old queued render.
        if self._tasks is None:
            callback()
            return
        if self.hub.lock.acquire(blocking=False):
            try:
                callback()
            finally:
                self.hub.lock.release()

    @staticmethod
    def _request_ids(state):
        return {item["id"] for item in list(state.get("pending", ())) + list(state.get("locked", ()))
                if isinstance(item, dict) and isinstance(item.get("id"), str)}

    def stop(self):
        """May be called by another thread; Tk observes it on the next poll."""
        self.stopped.set()

    def wake(self):
        waker = self._waker
        return waker.wake() if waker is not None else False

    def hide(self):
        """Hide the overlay without stopping Hub or ending the Tk loop."""
        self._dismissed_requests = set(self._active_ids)
        request = self.model.get("request")
        if request and isinstance(request.get("id"), str):
            self._dismissed_requests.add(request["id"])
        self.hidden = True
        self._pressed_decisions.clear()
        self._display_call(lambda: self.hub.hide_display('overlay'))
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
        alpha = TRANSLUCENT_ALPHA if self.translucent else OPAQUE_ALPHA
        # Type check: a plain Mock window must not claim native support.
        if (callable(getattr(type(self.window), "set_alpha", None))
                and getattr(self.window, "hwnd", None)):
            try:
                if self.window.set_alpha(alpha):
                    return
            except Exception as error:
                log.debug("Native overlay alpha unavailable: %s", error)
        if self.root is not None:
            try:
                self.root.attributes("-alpha", alpha)
            except Exception as error:
                log.debug("Overlay alpha unavailable: %s", error)
        if callable(getattr(type(self.window), "reapply", None)):
            try:
                self.window.reapply()
            except Exception as error:
                log.debug("Overlay window style restore failed: %s", error)

    def toggle_translucent(self):
        self.translucent = not self.translucent
        self._apply_alpha()
        if self.alpha_button is not None:
            self.alpha_button.configure(fg=FOREGROUND if self.translucent else theme.FAINT)
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
        if self._tasks is not None:
            if received_at is None:
                received_at = self.hub.monotonic()

            def done(result):
                self.message = result.get("message") or result.get("status", "")

            def failed(error):
                self.message = str(error)

            self.defer(lambda: self.hub.action(payload, source="overlay", received_at=received_at),
                       done, failed)
            return None
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

    def _menu_entries(self):
        entries = None
        if callable(self.menu_items):
            try:
                entries = self.menu_items()
            except Exception as error:
                log.warning("Overlay menu unavailable: %s", error)
        return entries or [("隐藏浮窗", self.hide)]

    def open_menu(self, event=None):
        """The tray menu without the tray: right-click anywhere or the ≡ button."""
        import tkinter as tk
        if self.root is None:
            return None
        menu = tk.Menu(self.root, tearoff=False, bg=theme.SURFACE, fg=FOREGROUND,
                       activebackground=theme.RAISED, activeforeground=FOREGROUND,
                       font=theme.font(10))
        for entry in self._menu_entries():
            if entry is None:
                menu.add_separator()
            else:
                label, callback = entry
                menu.add_command(label=label, command=callback)
        if event is not None and hasattr(event, "x_root"):
            x, y = event.x_root, event.y_root
        else:
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty() + self.root.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()
        return menu

    def _dot_slot(self, x):
        """Header dot under x (canvas pixels) -> slot number, or None."""
        occupied = [slot for slot in self.model["slots"] if slot["occupied"]]
        if isinstance(x, bool) or not isinstance(x, (int, float)) or x < 0:
            return None
        index = int(x // DOT_STEP)
        return occupied[index]["number"] if index < len(occupied) else None

    def _dots_release(self, event):
        clicked = self._drag is not None and not self._dragged
        self._end_drag(event)
        if clicked:
            number = self._dot_slot(getattr(event, "x", None))
            if number is not None:
                self._select(number)

    def _driver_help(self, event=None):
        if callable(self.on_driver_help):
            self.on_driver_help()

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
        pad, gap = theme.S3, theme.S2
        self.root.title("AgentDeck")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=theme.BORDER)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        # Toplevel binding: a right-click on any overlay widget opens the menu.
        self.root.bind("<ButtonRelease-3>", self.open_menu)
        # The 1px hairline border is the outer frame showing around the inner one.
        outer = tk.Frame(self.root, bg=theme.BORDER, padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        self.frame = tk.Frame(outer, bg=BACKGROUND, padx=pad, pady=gap, width=WIDTH)
        self.frame.pack(fill="both", expand=True)
        self.frame.columnconfigure(0, weight=1)
        self._bind_drag(self.frame)
        self.header = tk.Frame(self.frame, bg=BACKGROUND)
        self.header.grid(row=0, column=0, sticky="ew")
        self._bind_drag(self.header)
        self.status_label = tk.Label(self.header, text="", bg=BACKGROUND, fg=FOREGROUND,
                                     anchor="w", font=theme.font(9, True), takefocus=False)
        self.status_label.pack(side="left")
        self._bind_drag(self.status_label)
        self.dots = tk.Canvas(self.header, height=10, width=1, bg=BACKGROUND,
                              highlightthickness=0, bd=0)
        self.dots.pack(side="left", padx=(gap, 0))
        self._bind_drag(self.dots)
        # A click (not a drag) on a dot selects that session.
        self.dots.bind("<ButtonRelease-1>", self._dots_release)
        self.dots.configure(cursor="hand2")
        self._button(self.header, "×", self.hide, bg=BACKGROUND, fg=theme.MUTED,
                     padx=4, font=theme.font(13, latin=True)).pack(side="right")
        self.menu_button = self._button(self.header, "≡", self.open_menu, bg=BACKGROUND,
                                        fg=theme.MUTED, padx=4, font=theme.font(12, latin=True))
        self.menu_button.pack(side="right")
        self.alpha_button = self._button(
            self.header, "◐", self.toggle_translucent, bg=BACKGROUND,
            fg=FOREGROUND if self.translucent else theme.FAINT,
            padx=4, font=theme.font(11, latin=True))
        self.alpha_button.pack(side="right")
        # Always at the top: while keys also type into windows, nothing else matters more.
        self.notice_label = tk.Label(self.frame, text="", bg=BACKGROUND, fg=COLORS["ERR"], anchor="w",
                                     justify="left", wraplength=WIDTH - 2 * pad - 2,
                                     takefocus=False, font=theme.font(9, True), cursor="hand2")
        self.notice_label.grid(row=1, column=0, sticky="ew", pady=(gap, 0))
        self.notice_label.bind("<ButtonRelease-1>", self._driver_help)
        self.body = tk.Frame(self.frame, bg=BACKGROUND)
        self.body.grid(row=2, column=0, sticky="ew", pady=(gap, 0))
        self.body.columnconfigure(0, weight=1)
        self._bind_drag(self.body)
        self.empty_label = tk.Label(self.body, text=EMPTY_TEXT, bg=BACKGROUND, fg=theme.MUTED,
                                    anchor="w", justify="left", takefocus=False, font=theme.font(9),
                                    wraplength=WIDTH - 2 * pad - 2)
        self.empty_label.grid(row=9, column=0, sticky="ew")
        self._bind_drag(self.empty_label)
        self.rows = []
        for number in range(1, 7):
            row = tk.Frame(self.body, bg=BACKGROUND, padx=gap, pady=gap - 1)
            row.grid(row=number - 1, column=0, sticky="ew", pady=1)
            row.columnconfigure(2, weight=1)
            number_label = self._button(row, str(number), lambda n=number: self._select(n),
                                        bg=BACKGROUND, fg=theme.FAINT, width=2,
                                        font=theme.font(9, True, latin=True))
            number_label.grid(row=0, column=0)
            name = self._button(row, "", lambda n=number: self._select(n), bg=BACKGROUND,
                                fg=FOREGROUND, anchor="w", font=theme.font(10))
            name.grid(row=0, column=1, sticky="w", padx=(gap, 0))
            activity = self._button(row, "", lambda n=number: self._select(n), bg=BACKGROUND,
                                    fg=theme.MUTED, anchor="w", font=theme.font(9))
            activity.grid(row=0, column=2, sticky="ew", padx=(gap, gap))
            dot = self._button(row, "●", lambda n=number: self._select(n),
                               bg=BACKGROUND, fg=COLORS["IDLE"], font=theme.font(9, latin=True))
            dot.grid(row=0, column=3)
            self.rows.append((row, number_label, name, dot, activity))
        # The selected session's latest message: what you would otherwise switch windows to read.
        self.preview_box = tk.Frame(self.body, bg=theme.SURFACE, padx=gap, pady=gap)
        self.preview_box.grid(row=6, column=0, sticky="ew", pady=(gap, 0))
        self._bind_drag(self.preview_box)
        self.preview_title = tk.Label(self.preview_box, text="", bg=theme.SURFACE, fg=theme.MUTED,
                                      anchor="w", takefocus=False, font=theme.font(8))
        self.preview_title.pack(fill="x")
        self._bind_drag(self.preview_title)
        self.preview = tk.Label(self.preview_box, text="", bg=theme.SURFACE, fg=FOREGROUND,
                                anchor="w", justify="left", takefocus=False, font=theme.font(9),
                                wraplength=WIDTH - 2 * pad - 2 * gap - 2)
        self.preview.pack(fill="x")
        self._bind_drag(self.preview)
        self._preview_shown = ()  # not a valid value: the first render always applies
        self.detail = tk.Frame(self.body, bg=BACKGROUND)
        self.detail.grid(row=7, column=0, sticky="ew", pady=(pad, 0))
        self.risk = tk.Label(self.detail, bg=BACKGROUND, anchor="w", takefocus=False,
                             font=theme.font(9, True))
        self.risk.pack(fill="x")
        self.summary = tk.Label(self.detail, bg=theme.SURFACE, fg=FOREGROUND, anchor="w",
                                justify="left", wraplength=WIDTH - 2 * pad - 2 * gap - 2,
                                padx=gap, pady=gap, takefocus=False,
                                font=theme.font(9, mono=True))
        self.summary.pack(fill="x", pady=(gap - 2, pad))
        self.decisions = tk.Frame(self.detail, bg=BACKGROUND)
        self.decisions.pack(fill="x")
        self.decisions.columnconfigure(0, weight=3, uniform="decision")
        self.decisions.columnconfigure(1, weight=2, uniform="decision")
        self.decision_buttons = {}
        for column, (action, text, fg) in enumerate((("approve", "✓", BACKGROUND),
                                                     ("deny", "✗", COLORS["ERR"]))):
            label = tk.Label(self.decisions, text=text, takefocus=False, cursor="hand2",
                             fg=fg, pady=gap, font=theme.font(13, True, latin=True))
            label.bind("<ButtonPress-1>", lambda event, a=action: self._decision_press(event, a))
            label.bind("<ButtonRelease-1>", lambda event, a=action: self._decision_release(a))
            label.grid(row=0, column=column, sticky="ew", padx=(0, gap) if column == 0 else 0)
            self.decision_buttons[action] = label
        self.note = tk.Label(self.body, text="", bg=BACKGROUND, fg=theme.MUTED, anchor="w",
                             wraplength=WIDTH - 2 * pad - 2, takefocus=False,
                             font=theme.font(8))
        self.note.grid(row=8, column=0, sticky="ew", pady=(gap, 0))

    def _render(self):
        feedback = self.model.get("feedback")
        if self.status_label is not None:
            if feedback:
                # Every key press shows its result here for about two seconds.
                self.status_label.configure(text=feedback["text"],
                                            fg=FOREGROUND if feedback["ok"] else COLORS["ASK"])
            else:
                self.status_label.configure(
                    text=self.model["summary_text"],
                    fg=COLORS["ASK"] if self.model["pending_count"] else FOREGROUND)
        if self.alpha_button is not None:
            self.alpha_button.configure(fg=FOREGROUND if self.translucent else theme.FAINT)
        if self.dots is not None:
            occupied = [slot for slot in self.model["slots"] if slot["occupied"]]
            self.dots.delete("all")
            self.dots.configure(width=max(1, 14 * len(occupied) - 4))
            for index, slot in enumerate(occupied):
                self.dots.create_oval(14 * index, 1, 14 * index + 9, 10, fill=slot["color"], width=0)
        if self.body is not None:
            if self.model["expanded"]:
                self.body.grid()
            else:
                self.body.grid_remove()
        for data, widgets in zip(self.model["slots"], self.rows):
            row, number, name, badge = widgets[:4]
            activity = widgets[4] if len(widgets) > 4 else None
            background = theme.RAISED if data["selected"] else BACKGROUND
            if data["occupied"]:
                row.grid()
            else:
                row.grid_remove()  # empty slots take no space; the number key still maps
            row.configure(bg=background)
            number.configure(bg=background, fg=FOREGROUND if data["selected"] else theme.FAINT)
            # Bound the text so a long project name cannot expand the panel.
            text = data["name"]
            text = text if len(text) <= 27 else text[:26] + "…"
            if data.get("same_window"):
                text += " · 同窗"
            if data.get("hint"):
                text += " · " + data["hint"]
            elif data.get("needs_input"):
                text += " · 等你"
            name.configure(text=text, bg=background,
                           fg=COLORS["ASK"] if data.get("needs_input") else FOREGROUND)
            if activity is not None:
                activity.configure(text=data.get("activity", ""), bg=background)
            badge.configure(bg=background, fg=data["color"])
        self._render_preview()
        request = self.model["request"]
        if request is None:
            if self.detail is not None:
                self.detail.grid_remove()
        else:
            if self.detail is not None:
                self.detail.grid()
            self.risk.configure(text=request["label"], fg=request["color"])
            self.summary.configure(text=request["summary"])
            for action, key, color, ink in (("approve", "can_approve", COLORS["RUN"], BACKGROUND),
                                            ("deny", "can_deny", theme.RAISED, COLORS["ERR"])):
                enabled = request[key]
                self.decision_buttons[action].configure(
                    bg=color if enabled else theme.RAISED, fg=ink if enabled else theme.FAINT,
                    cursor="hand2" if enabled else "arrow")
        if self.note is not None:
            self.note.configure(text=self.message)
            if self.message:
                self.note.grid()
            else:
                self.note.grid_remove()
        if self.empty_label is not None:
            if self.model.get("empty_text"):
                self.empty_label.configure(text=self.model["empty_text"])
                self.empty_label.grid()
            else:
                self.empty_label.grid_remove()
        if self.notice_label is not None:
            notice = self.model.get("notice")
            if notice:
                action = self.model.get("notice_action")
                self.notice_label.configure(text=notice + ("（点这里看步骤）" if action else ""),
                                            fg=COLORS["ERR"] if action else theme.MUTED,
                                            cursor="hand2" if action else "arrow")
                self.notice_label.grid()
            else:
                self.notice_label.grid_remove()

    def _render_preview(self):
        """Touch the preview widgets only when its text changes (every poll is 300 ms)."""
        if self.preview is None:
            return
        preview = self.model.get("preview")
        shown = (preview["title"], "\n".join(preview["lines"])) if preview else None
        if shown == self._preview_shown:
            return
        self._preview_shown = shown
        if shown is None:
            self.preview_box.grid_remove()
            return
        self.preview_title.configure(text=shown[0])
        self.preview.configure(text=shown[1])
        self.preview_box.grid()

    def _poll(self):
        # First, so the watchdog sees the Tk loop alive even if a refresh fails.
        if self.heartbeat is not None:
            try:
                self.heartbeat()
            except Exception as error:
                log.debug("UI heartbeat failed: %s", error)
        if self.stopped.is_set():
            self.root.quit()
            return
        previous_model = self.model
        previous_active = set(self._active_ids)
        previous_dismissed = set(self._dismissed_requests)
        try:
            if self._tasks is None:
                state = self.hub.state()
            else:
                self._drain_completed()
                state = self.state
            active_ids = self._request_ids(state)
            self._active_ids = active_ids
            self._dismissed_requests &= active_ids
            reappear = self.hidden and bool(active_ids - self._dismissed_requests)
            shows = state.get("show_requests")
            if type(shows) is int:
                # The macropad "show" key un-hides the overlay without a mouse.
                reappear |= self.hidden and self._show_seen is not None and shows != self._show_seen
                self._show_seen = shows
            self.model = display_model(state, now=time.time())
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
                self._display_call(lambda: self.hub.record_rendered(
                    request["id"] if request else None,
                    request.get("nonce") if request else None, source="overlay"))
            elif self.hidden:
                self._display_call(lambda: self.hub.hide_display('overlay'))
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
        finally:
            # Publish this render before our own next state() can take hub.lock.
            # Refresh failures must still let the background state fetch retry.
            if (self._tasks is not None and not self._state_pending
                    and not self.stopped.is_set() and not self._worker_stop.is_set()):
                def received(value):
                    self.state = value
                    self._state_pending = False

                def failed(error):
                    self._state_pending = False
                    self.message = "Hub state unavailable"

                self._state_pending = True
                try:
                    self.defer(self.hub.state, received, failed)
                except Exception as error:
                    failed(error)
                    log.warning("Overlay state request failed: %s", error)
        self.root.after(POLL_MS, self._poll)

    def run(self, *, on_ready=None):
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
            if os.name == "nt":
                self._waker = TkWaker(int(self.root.winfo_id()))
                self._waker.start()
            self._build()
            self._start_background()
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
            if callable(getattr(type(self.window), "reapply", None)):
                self.window.reapply()  # tool-window bits must be in place before first show
            self.root.deiconify()
            self._apply_alpha()
            if self.window is not None:
                self.window.show()
            if on_ready is not None:
                on_ready()
            self.root.mainloop()
            if self._interrupted:
                raise KeyboardInterrupt
        finally:
            self.stopped.set()
            if self._waker is not None:
                self._waker.stop()
                self._waker = None
            self._stop_background()
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
