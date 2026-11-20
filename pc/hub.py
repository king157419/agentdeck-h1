"""AgentDeck Hub: local hook decisions and shared HTTP, USB and desktop actions.

Run ``python pc/hub.py --backend none``; see hub_README.md for setup.
No device, window, or user configuration is accessed just by importing this file.
"""
import argparse
from collections import deque
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import math
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import re
import secrets
import select
import shlex
import socket
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid
from session_titles import event_title, session_label, transcript_title

import agent_lcd
import daemon
from deck import normalize_key
from focus_lock import focus_lock
from hub_audit import AuditError, AuditLog
from hub_risk import PROTECTED_BRANCHES


HOST = "127.0.0.1"
PORT = 47800
APPROVE_TIMEOUT = 110.0
CONFIRM_SECONDS = 1.5
SWITCH_GUARD_SECONDS = 0.3
GATE_CONFIRMED_SECONDS = 30.0
VOICE_NOTICE_SECONDS = 5.0
SESSION_IDLE_SECONDS = 24 * 60 * 60
CYCLE_BURST_SECONDS = 5.0  # a pause longer than this re-anchors the knob to the session open in Claude
# /state keeps the last few removed sessions: codex exec fires SessionEnd right after
# Stop, so its done state and reply would otherwise never be visible.
RECENT_ENDED_LIMIT = 8
MAX_BODY = 8 * 1024 * 1024
WAIT_SLICE = 0.25            # how often a waiting decision checks its hook client
INPUT_NOTICE_SECONDS = 2.0
UNHELD_SETTLE_SECONDS = 1.0  # deck must stay disconnected this long before held requests are released
# Claude Code: "allow" alone does not answer these; the native UI must handle them.
NEEDS_ANSWER_TOOLS = ("AskUserQuestion", "ExitPlanMode")
TOOL_PROGRESS_EVENTS = ("PreToolUse", "PostToolUse", "PostToolUseFailure")
MOVED_ON_EVENTS = TOOL_PROGRESS_EVENTS + ("UserPromptSubmit", "Stop", "StopFailure", "Interrupt")
EVENT_STATES = {
    "SessionStart": "idle", "UserPromptSubmit": "think", "PreToolUse": "tool",
    "PostToolUse": "think", "PostToolUseFailure": "error", "Stop": "done",
    "Interrupt": "idle", "StopFailure": "error",
}
EVENTS = set(EVENT_STATES) | {"PermissionRequest", "Notification", "SessionEnd"}
LAST_TEXT_LIMIT = 4000
ACTIVITY_LIMIT = 60
SCROLL_LIMIT = 20
SCROLL_END = 100             # "scroll end": far enough to reach the bottom
NAV_KEYS = ("up", "down", "enter")
# Raw Input cannot stop the key itself from typing into the focused window, so a
# paste/Enter action would send e.g. "m继续". Only USB direct reads may use these.
RAW_INPUT_BLOCKED = ("prompt", "nav", "voice_down", "voice", "screenshot", "app", "window")
LEAK_TEXT = "按键会漏进窗口：先用 Zadig 把接口 0 换成 WinUSB"
log = logging.getLogger("agentdeck.hub")
keylog = logging.getLogger("agentdeck.hub.keys")
UNKNOWN_EVENTS = set()
UNKNOWN_EVENTS_LOCK = threading.Lock()
SESSION_FIELDS = ("agent", "session_id", "slot", "cwd", "name", "title", "state", "hwnd",
                  "window_exe", "last_text", "last_updated", "last_kind", "last_text_at")
# Measured positions shared by key feedback and the tray's keymap window.
KEY_ROWS = (
    (("E", "hid:0x08"), ("B", "hid:0x05"), ("Ctrl+Z", "ctrl+hid:0x1D"), ("Space", "hid:0x2C")),
    (("G", "hid:0x0A"), ("Ctrl+F", "ctrl+hid:0x09"), ("H", "hid:0x0B"), ("Alt", None)),
    (("L", "hid:0x0F"), ("M", "hid:0x10"), ("Ctrl+T", "ctrl+hid:0x17"), ("Ctrl+D", "ctrl+hid:0x07")),
    (("Ctrl", None), ("Shift", None), ("U", "hid:0x18"), ("X", "hid:0x1B")),
    (("Tab", "hid:0x2B"), ("Ctrl+C", "ctrl+hid:0x06"), ("Ctrl+V", "ctrl+hid:0x19"), ("P", "hid:0x13")),
)
KNOBS = (("hid:0x09", "hid:0x16", "hid:0x0F"), ("hid:0x15", "hid:0x13", "hid:0x14"),
         ("hid:0x2D", "hid:0x2E", "hid:0x19"), ("hid:0x30", "hid:0x2F", "hid:0x06"))
CONTROL_NAMES = {}
for _row, _keys in enumerate(KEY_ROWS, 1):
    for _column, (_, _binding) in enumerate(_keys, 1):
        if _binding is not None:
            CONTROL_NAMES[_binding] = "第 %d 排第 %d 颗" % (_row, _column)
for _knob, _keys in enumerate(KNOBS, 1):
    for _direction, _binding in zip(("顺时针", "逆时针", "按下"), _keys):
        _name = "旋钮 %d %s" % (_knob, _direction)
        CONTROL_NAMES[_binding] = " / ".join(filter(None, (CONTROL_NAMES.get(_binding), _name)))

from hub_risk import (  # noqa: F401  (re-exported: hub.classify stays public)
    AUTHORIZED_KEYS, CRITICAL_RULES, KEY_PATH, RISK_RULES, SENSITIVE_PATH, SHELL_WRITE,
    WRITE_TOOL, _production_ssh, classify)


from hub_relay import escape_log_text, scrub_surrogates, tool_input_hash  # noqa: E402,F401


def hub_marker(home=None):
    """Lets the relay skip a dead hub in ~0 ms instead of a 2 s refused connect."""
    return (Path.home() if home is None else Path(home)) / ".agentdeck" / "hub.json"


def write_hub_marker(home, port):
    try:
        if type(port) is not int:
            return None
        path = hub_marker(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name("hub.json.%d.tmp" % os.getpid())
        temporary.write_text(json.dumps({"pid": os.getpid(), "port": port}) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        return path
    except Exception as error:
        log.warning("Cannot write %s: %s", hub_marker(home), error)
        return None


def remove_hub_marker(path):
    try:
        if path is not None and json.loads(path.read_text(encoding="utf-8")).get("pid") == os.getpid():
            path.unlink()
    except Exception:
        pass


INPUT_ERRORS = (  # (substring of HubError text, overlay text, LCD ASCII text)
    ("no session in that slot", "槽位 {slot} 没有会话", "Slot {slot} empty"),
    ("select a session first", "先选一个会话", "Select a session"),
    ("release voice", "先松开语音键", "Release voice"),
    ("desktop output disabled", "桌面操作已关闭", "Desktop off"),
    ("switch_guard", "请求刚切换，稍后再按", "Wait, press again"),
    ("stale_nonce", "请求已变，看屏幕再按", "Request changed"),
    ("displayed request changed", "请求已变，看屏幕再按", "Request changed"),
    ("nonce_required", "请求已变，看屏幕再按", "Request changed"),
    ("audit unavailable", "审计不可用，请在终端确认", "Use terminal"),
    ("unknown prompt template", "没有这个预设", "No such prompt"),
    ("hub is shutting down", "正在退出", "Shutting down"),
    ("keys leak into the window", LEAK_TEXT, "Need WinUSB"),
    ("use approve/deny", "有待批请求：用 ✓/✗ 处理", "Use approve/deny"),
    ("only while the agent asks", "只有 agent 提问时才能用", "No question"),
    ("没找到 Claude 桌面版窗口", "没找到 Claude 桌面版窗口", "Claude not found"),
)
INPUT_RESULTS = {"allowed": "已批准", "denied": "已拒绝", "confirm": "再按一次确认",
                 "locked": "需在终端确认", "no_request": "现在没有要批准的请求",
                 "no_waiting_session": "没有等你的会话", "unavailable": "此操作不可用",
                 "focus": "去窗口里回答", "shown": "已显示浮窗"}
INPUT_SENT = {"prompt": "已发送预设", "screenshot": "已截图并粘贴路径", "voice_down": "开始说话",
              "voice": "语音已切换", "voice_up": "停止说话", "interrupt": "已打断",
              "nav up": "已按 ↑", "nav down": "已按 ↓", "nav enter": "已回车",
              "scroll end": "已翻到底", "scroll": "已滚动",
              "app next": "Claude：下一个会话", "app prev": "Claude：上一个会话",
              "window next": "切到下一个窗口", "window prev": "切到上一个窗口"}
EVENT_KINDS = {"Stop": "回复", "StopFailure": "错误", "Notification": "提醒", "UserPromptSubmit": "你"}


def tool_summary(tool_input, limit=ACTIVITY_LIMIT):
    """The same command/description/file_path/path summary a request shows."""
    summary = (tool_input.get("command") or tool_input.get("description") or
               tool_input.get("file_path") or tool_input.get("path")) if isinstance(tool_input, dict) else tool_input
    if not isinstance(summary, str):
        return ""
    return " ".join(summary.split())[:limit]


def question_text(tool_input):
    """AskUserQuestion: each question with its option labels."""
    lines = []
    questions = tool_input.get("questions") if isinstance(tool_input, dict) else None
    if isinstance(questions, list):
        for question in questions:
            if not isinstance(question, dict):
                continue
            if isinstance(question.get("question"), str):
                lines.append(question["question"])
            options = question.get("options")
            labels = [option.get("label") for option in options if isinstance(option, dict)
                      and isinstance(option.get("label"), str)] if isinstance(options, list) else []
            if labels:
                lines.append(" / ".join(labels))
    if lines:
        return "\n".join(lines)
    try:
        return json.dumps(tool_input, ensure_ascii=False)[:300]
    except (TypeError, ValueError):
        return ""


def event_text(name, event):
    """(text, kind) worth showing as the session's latest line, else (None, None)."""
    if name in ("Stop", "StopFailure"):
        text = event.get("last_assistant_message")
    elif name == "Notification":
        text = event.get("message")
        title = event.get("title")
        if isinstance(text, str) and isinstance(title, str) and title.strip():
            text = title.strip() + "：" + text
    elif name == "UserPromptSubmit":
        text = event.get("prompt")
    elif name == "PreToolUse" and event.get("tool_name") == "AskUserQuestion":
        return question_text(event.get("tool_input")) or None, "提问"
    else:
        return None, None
    if not isinstance(text, str) or not text.strip():
        return None, None
    return text, EVENT_KINDS[name]


def describe_input(action, result=None, error=None):
    """Short Chinese feedback for a physical key, plus ASCII LCD text for failures."""
    parts = str(action).split()
    slot = parts[1] if len(parts) > 1 else "?"
    if error is not None:
        text = str(error)
        for needle, message, lcd in INPUT_ERRORS:
            if needle in text:
                return message.format(slot=slot), False, lcd.format(slot=slot)
        return "操作失败：" + text[:40], False, "Key failed"
    result = result if isinstance(result, dict) else {}
    if isinstance(result.get("message"), str):
        return result["message"], result.get("switched") is not False, None
    status = result.get("status")
    if status == "selected":
        text = "已选槽位 %s" % result.get("slot")
        if result.get("window") not in (None, "focused"):
            text += "（没找到窗口）"
        elif result.get("shared_window"):
            text += "（同窗：只能调到前台）"
        return text, True, None
    if status == "sent":
        if parts in (["voice"], ["voice_down"]) and result.get("mode") == "tap":
            return "语音键：已点一下" + result["shortcut"], True, None
        if parts == ["screenshot"] and result.get("paste") == "image":
            return "截图已贴进输入框", True, None
        return (INPUT_SENT.get(" ".join(parts[:2])) or INPUT_SENT.get(parts[0] if parts else "", "已发送"),
                True, None)
    return INPUT_RESULTS.get(status, str(status or "完成")), True, None


def gate_denial(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": "Blocked by AgentDeck gate: " + reason}}


def session_key(agent, session_id):
    """Exactly the key convention used by agent_lcd.hook_line."""
    return agent + "-" + session_id.replace("-", "")[:6]


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def token_file(home=None):
    return (Path.home() if home is None else Path(home)) / ".agentdeck" / "token"


def load_token(home=None):
    """Create a token once, using exclusive creation to avoid overwriting one."""
    path = token_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="ascii") as stream:
            stream.write(secrets.token_urlsafe(32) + "\n")
    except FileExistsError:
        pass
    token = path.read_text(encoding="ascii").strip()
    if not token:
        raise ValueError("AgentDeck token file is empty")
    return token


class HubError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@dataclass
class Pending:
    id: str
    session: tuple
    tool_name: str
    summary: str
    risk: str
    created_at: float
    deadline: float
    command: str = ""
    project: str = ""
    status: str = "pending"
    ready: threading.Event = field(default_factory=threading.Event)
    response: dict = field(default_factory=dict)
    armed_at: object = None
    gate: bool = False
    gate_confirmed: bool = False
    input_hash: str = ""
    agent_id: str = ""
    nonce: int = field(kw_only=True)

    def public(self):
        return {"id": self.id, "nonce": self.nonce, "agent": self.session[0], "session_id": self.session[1],
                "tool_name": self.tool_name, "summary": self.summary, "risk": self.risk,
                "created_at": self.created_at, "armed": self.armed_at is not None,
                "status": self.status, "gate": self.gate,
                "gate_confirmed": self.gate_confirmed,
                "gate_confirmed_message": "已在闸门确认" if self.gate_confirmed else ""}


class Hub:
    """State machine. All external effects and both clocks can be substituted."""

    def __init__(self, *, approve_timeout=APPROVE_TIMEOUT, sender=None, desktop=None,
                 focus_guard=None, hold_path=None, monotonic=None, wall_time=None,
                 risk_rules=None, critical_rules=None, prompts=None, home=None, audit=None,
                 lcd_enabled=True, desktop_enabled=True, gate_mode="high", require_nonce=False,
                 lcd_async=None, hold_mode="always", sessions_path=None, window_alive=None,
                 production_hosts=(), protected_branches=PROTECTED_BRANCHES, mcp_write_tools=()):
        if not math.isfinite(approve_timeout) or approve_timeout <= 0:
            raise ValueError("approve timeout must be positive and finite")
        self.approve_timeout = approve_timeout
        if hold_mode not in ("auto", "always", "never"):
            raise ValueError("hold_mode must be auto, always, or never")
        self.hold_mode = hold_mode
        if not isinstance(require_nonce, bool):
            raise ValueError("require_nonce must be a boolean")
        self.require_nonce = require_nonce
        if gate_mode not in ("high", "low", "off"):
            raise ValueError("gate_mode must be high, low, or off")
        self.gate_mode = gate_mode
        for name, values in (("production_hosts", production_hosts),
                             ("protected_branches", protected_branches), ("mcp_write_tools", mcp_write_tools)):
            if not isinstance(values, (list, tuple)) or any(not isinstance(value, str) or not value for value in values):
                raise ValueError(name + " must be a list of nonempty strings")
            setattr(self, name, tuple(values))
        self.sender = agent_lcd.send if sender is None else sender
        # Real serial I/O never runs while holding the state-machine lock.
        # Synchronous injected senders remain useful for protocol-only tests.
        self.lcd_async = sender is None if lcd_async is None else lcd_async
        self.lcd_jobs = SimpleQueue()
        self.lcd_thread = None
        self.lcd_retry_at = float('inf')
        self.desktop = desktop
        self.lcd_enabled = lcd_enabled
        self.desktop_enabled = desktop_enabled
        self.focus_guard = focus_lock if focus_guard is None else focus_guard
        self.hold_path = Path(daemon.DECK_HOLD if hold_path is None else hold_path)
        self.monotonic = time.monotonic if monotonic is None else monotonic
        self.wall_time = time.time if wall_time is None else wall_time
        self.risk_rules = RISK_RULES if risk_rules is None else list(risk_rules)
        self.critical_rules = CRITICAL_RULES if critical_rules is None else list(critical_rules)
        for pattern in self.risk_rules + self.critical_rules:
            re.compile(pattern)
        self.home = Path.home() if home is None else Path(home)
        self.audit = AuditLog(token_file(home).with_name("audit.jsonl")) if audit is None else audit
        self.prompts = load_json(Path(__file__).with_name("hub_prompts.json")) if prompts is None else prompts
        self.lock = threading.RLock()
        self.sessions = {}
        self.pending = {}
        self.issued_nonces = set()
        self.gate_passed = {}
        self.locked = {}
        self.agents_seen = {"cc": None, "cx": None}
        self.recent_ended = deque(maxlen=RECENT_ENDED_LIMIT)
        self.selected = None
        self.displayed_request_id = None
        self.display_switched_at = float("-inf")
        self.rendered_request = {"request_id": None, "nonce": None}
        self.rendered_source = None
        self.rendered_by_source = {}
        self.rendered_at = {}
        self.active_displays = set()
        self.render_history = ()
        self.confirm_target = None
        self.confirm_until = float('-inf')
        self.last_focus = float("-inf")
        self.closed = False
        self.voice_events = SimpleQueue()
        self.voice_generation = 0
        self.voice_target = None
        self.voice_notice = None
        self.input_notice = None      # (ASCII text, expiry) shown in the LCD name field
        self.last_input = None        # last physical key result, published in state()
        self.input_seq = 0
        self.show_requests = 0        # "show" key presses; the overlay un-hides on change
        self.last_cycle = float("-inf")
        self.cycle_order = []
        self.cycle_generation = 0
        self.cycle_reader = None
        self.overlay_pinned = False
        self.overlay_corner_requests = 0
        self.input_reader = None      # callable -> "usb" / "raw" / None (set by main)
        self.sessions_path = Path(sessions_path) if sessions_path is not None else None
        self.window_alive = window_alive or self._window_alive
        self.sessions_io_lock = threading.Lock()
        self.sessions_saved_content = None
        self.sessions_write_at = float("-inf")
        self.sessions_warnings = set()
        self.unheld_since = None
        self._load_sessions()

    @staticmethod
    def _window_alive(hwnd):
        if sys.platform != "win32":
            return True
        import ctypes
        from ctypes import wintypes
        is_window = ctypes.WinDLL("user32").IsWindow
        is_window.argtypes, is_window.restype = [wintypes.HWND], wintypes.BOOL
        return bool(is_window(hwnd))

    def _input_reader(self):
        try:
            return self.input_reader() if callable(self.input_reader) else None
        except Exception:
            return None

    def deck_connected(self):
        return self._input_reader() in ("usb", "raw")

    def hold_active(self):
        return self.hold_mode == "always" or (self.hold_mode == "auto" and self.deck_connected())

    def _load_sessions(self):
        if self.sessions_path is None:
            return
        try:
            entries = load_json(self.sessions_path)
            if isinstance(entries, dict):
                entries = entries["sessions"]
            if not isinstance(entries, list):
                raise ValueError("sessions must be a list")
            self.sessions_saved_content = json.dumps(entries, ensure_ascii=True, sort_keys=True)
            used = set()
            for entry in entries:
                try:
                    if not isinstance(entry, dict):
                        continue
                    agent, sid, slot = entry["agent"], entry["session_id"], entry["slot"]
                    updated = entry["last_updated"]
                    if (agent not in ("cc", "cx") or not isinstance(sid, str) or not 0 < len(sid) <= 256
                            or type(slot) is not int or not 1 <= slot <= 6 or slot in used
                            or type(updated) not in (int, float) or not math.isfinite(updated)
                            or self.wall_time() - updated > SESSION_IDLE_SECONDS):
                        continue
                    key = session_key(agent, sid)
                    identity = (agent, sid)
                    if not re.fullmatch(r"[A-Za-z0-9_-]+", key) or identity in self.sessions:
                        continue
                    if any(not isinstance(entry.get(field, ""), str)
                           for field in ("cwd", "name", "title", "state", "window_exe", "last_text", "last_kind")):
                        continue
                    session = {field: entry[field] for field in SESSION_FIELDS if field in entry}
                    session.update(key=key, cwd=entry.get("cwd", ""), name=entry.get("name", "agent"),
                                   project=entry.get("name", "agent"), last_text=entry.get("last_text", "")[-LAST_TEXT_LIMIT:])
                    state = session.get("state", "idle")
                    session["state"] = state if state in set(EVENT_STATES.values()) | {"wait", "locked"} else "idle"
                    if state in ("wait", "locked"):
                        session.update(state="wait", native_wait=True, label="在应用里批准")
                    hwnd = session.get("hwnd")
                    alive = False
                    if type(hwnd) is int and 0 < hwnd < 2**64:
                        try:
                            alive = bool(self.window_alive(hwnd))
                        except Exception:
                            pass
                    if not alive:
                        session.pop("hwnd", None)
                        session.pop("window_exe", None)
                    if agent == "cc" and not session.get("title") and session["cwd"]:
                        # Claude keeps <home>/.claude/projects/<cwd, non-alnum -> '-'>/<sid>.jsonl
                        found = transcript_title(self.home / ".claude" / "projects" / re.sub(
                            r"[^A-Za-z0-9]", "-", session["cwd"]) / (sid + ".jsonl"))
                        if found:
                            session["title"] = found
                    self.sessions[identity] = session
                    used.add(slot)
                except (KeyError, TypeError, ValueError):
                    continue
            self.selected = min(self.sessions, key=lambda identity: self.sessions[identity]["slot"], default=None)
            if len(self.sessions) < len(entries):  # stale or invalid rows were dropped: persist the cleanup
                self._save_sessions(force=True)
        except Exception as error:
            log.warning("Cannot load sessions from %s: %s", self.sessions_path, error)

    def _save_sessions(self, force=False):
        if self.sessions_path is None:
            return
        # Disk work never holds the state lock. Serialize writers separately so
        # close() cannot be overtaken by an older maintenance snapshot.
        with self.sessions_io_lock:
            now = self.monotonic()
            if not force and now - self.sessions_write_at < 2:
                return
            self.sessions_write_at = now
            temporary = None
            try:
                with self.lock:
                    entries = [{field: session.get(field, "" if field in ("cwd", "name", "title", "window_exe", "last_text") else None)
                                for field in SESSION_FIELDS if field in session or field not in ("last_kind", "last_text_at", "title")}
                               for session in sorted(self.sessions.values(), key=lambda item: item["slot"])]
                content = json.dumps(entries, ensure_ascii=True, sort_keys=True)
                if content == self.sessions_saved_content:
                    return
                self.sessions_path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.sessions_path.parent,
                                                 prefix="sessions-", suffix=".tmp", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(content + "\n")
                os.replace(temporary, self.sessions_path)
                self.sessions_saved_content = content
            except Exception as error:
                # OSError text may contain a fresh temporary filename on every
                # attempt; use the stable cause so one disk failure logs once.
                warning = (type(error).__name__, getattr(error, "errno", None),
                           getattr(error, "winerror", None), getattr(error, "strerror", None) or str(error))
                if warning not in self.sessions_warnings:
                    self.sessions_warnings.add(warning)
                    log.warning("Cannot save sessions to %s: %s", self.sessions_path, error)
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass

    def note_input(self, text, ok=True, lcd=None):
        """Make every key press visible: overlay header (state) and LCD for failures."""
        with self.lock:
            self.input_seq += 1
            self.last_input = {"text": str(text), "ok": bool(ok), "at": self.wall_time(),
                               "seq": self.input_seq}
            if lcd and self.lcd_enabled and not self.closed:
                self.input_notice = (str(lcd), self.monotonic() + INPUT_NOTICE_SECONDS)
                if self.selected in self.sessions:
                    self._show()

    def note_action(self, action, result=None, error=None, control=None):
        """Publish the same feedback metadata for keyboard and global hotkeys."""
        text, ok, lcd = describe_input(action, result, error)
        compact = ((isinstance(result, dict) and result.get("status") == "no_request")
                   or (action.startswith("nav ") and error is not None
                       and "only while the agent asks" in str(error)))
        with self.lock:
            self.note_input(text if compact or not control else control + " → " + text, ok, lcd)
            if self.last_input is not None:
                self.last_input.update(compact=compact, action=action)

    def _send(self, lines, focus=False, rendered=None):
        if not self.lcd_enabled:
            return False
        if self.lcd_async:
            self.lcd_jobs.put((list(lines), focus, rendered))
            if self.lcd_thread is None:
                self.lcd_thread = threading.Thread(target=self._lcd_worker,
                                                   name='AgentDeck serial output', daemon=True)
                self.lcd_thread.start()
            self.last_focus = self.monotonic()
            return False
        return self._transmit(lines, focus)

    def _lcd_worker(self):
        while True:
            job = self.lcd_jobs.get()
            if job is None:
                return
            lines, focus, snapshot = job
            with self.lock:
                if self.closed:
                    continue
            success = self._transmit(lines, focus)
            with self.lock:
                if self.closed:
                    continue
                if success and focus and snapshot is not None:
                    self.record_rendered(snapshot['request_id'], snapshot['nonce'], 'lcd')
                if focus:
                    self.lcd_retry_at = float('inf') if success else self.monotonic() + .5

    def _transmit(self, lines, focus=False):
        try:
            if focus:
                with self.focus_guard(timeout=1.0):
                    self.hold_path.touch()
                    expected = ["ok " + " ".join(line.split()[:3] if line.startswith("set ")
                                               else line.split()) for line in lines]
                    options = {'expected_replies': expected} if self.sender is agent_lcd.send else {}
                    reply = self.sender(lines, retry_for=0.0, wait_reply=0.15, **options)
                    self.last_focus = self.monotonic()
                    # Real serial output is acknowledged; injected synchronous
                    # senders may return None. An empty/partial reply is not a render.
                    if reply is not None:
                        acknowledgements = reply.splitlines()
                        if any(line not in acknowledgements for line in expected):
                            self.lcd_retry_at = self.monotonic() + .5
                            return False
            else:
                self.sender(lines, retry_for=0.0)
            self._lcd_last_error = None
            return True
        except Exception as error:
            if str(error) != getattr(self, "_lcd_last_error", None):  # log each new failure once, not every retry
                log.warning("LCD unavailable: %s", error)
            self._lcd_last_error = str(error)
            # A missing LCD must not cause a tight serial retry loop.
            self.last_focus = self.monotonic()
            self.lcd_retry_at = self.monotonic() + .5
            return False

    def _refresh_input_snapshot(self):
        snapshots = [self.rendered_by_source[source] for source in sorted(self.active_displays)
                     if source in self.rendered_by_source]
        if snapshots:
            snapshot = snapshots[0]
            if any(item != snapshot for item in snapshots[1:]):
                snapshot = {'request_id': None, 'nonce': None}
            source = ','.join(sorted(self.active_displays))
        elif self.rendered_by_source:
            # Hiding the only display retains the request the user actually saw.
            # New unseen requests cannot inherit this binding.
            source = next(reversed(self.rendered_by_source))
            snapshot = self.rendered_by_source[source]
        else:
            # Explicit headless/native-terminal mode. This is a logical input
            # binding, not evidence that physical LCD pixels have been rendered.
            request = self._displayed()
            snapshot = {'request_id': request.id if request else None,
                        'nonce': request.nonce if request else None}
            source = 'headless'
        snapshot = dict(snapshot)
        if snapshot != self.rendered_request:
            if snapshot['request_id'] == self.displayed_request_id:
                self.display_switched_at = self.monotonic()
            self.render_history = (*self.render_history[-4095:], (self.monotonic(), snapshot))
        self.rendered_request = snapshot
        self.rendered_source = source

    def input_snapshot(self, received_at=None):
        # Copy-on-write tuples/dicts allow readers to capture before lock waits.
        if received_at is None:
            return dict(self.rendered_request)
        history = tuple(self.render_history)
        for timestamp, snapshot in reversed(history):
            if timestamp <= received_at:
                return dict(snapshot)
        return {'request_id': None, 'nonce': None}

    def hide_display(self, source):
        with self.lock:
            self.active_displays.discard(source)
            self._refresh_input_snapshot()

    def record_rendered(self, request_id, nonce, source="overlay"):
        """Publish an immutable snapshot only after a display has rendered it.

        Input readers copy this without waiting for the Hub lock: a render or
        queue change while dispatch is blocked must not retarget that key press.
        """
        with self.lock:
            snapshot = {"request_id": request_id, "nonce": nonce}
            if self.rendered_by_source.get(source) != snapshot:
                self.rendered_at[source] = self.monotonic()
                if request_id is not None and request_id == self.displayed_request_id:
                    self.display_switched_at = self.monotonic()
            self.rendered_by_source[source] = snapshot
            self.active_displays.add(source)
            self._refresh_input_snapshot()

    def _set_displayed(self, request_id):
        if self.displayed_request_id != request_id:
            self.displayed_request_id = request_id
            self.display_switched_at = self.monotonic()
            self._refresh_input_snapshot()

    def _show(self):
        session = self.sessions.get(self.selected)
        if session is None:
            if self._send(["focus -"], focus=True, rendered={'request_id': None, 'nonce': None}):
                self.record_rendered(None, None, "lcd")
            return
        name = self._display_name(session)
        state = "wait" if session["state"] == "locked" else session["state"]
        request = self._displayed()
        snapshot = {'request_id': request.id if request else None,
                    'nonce': request.nonce if request else None}
        if self._send(["set %s %s %s" % (session["key"], state, name),
                       "focus " + session["key"]], focus=True, rendered=snapshot):
            self.record_rendered(request.id if request else None,
                                 request.nonce if request else None, "lcd")

    def _displayed(self):
        return self.pending.get(self.displayed_request_id) or self.locked.get(self.displayed_request_id)

    def _new_nonce(self):
        # Keep expired/decided values reserved for this Hub lifetime too: a
        # random 32-bit collision must not revive an old nonce-only decision.
        nonce = secrets.randbits(32)
        while nonce in self.issued_nonces:
            nonce = secrets.randbits(32)
        self.issued_nonces.add(nonce)
        return nonce

    def _display_name(self, session):
        # The board can contain eight sessions including non-Hub writers.
        # Its guaranteed four-cell budget cannot fit a label plus nonce.
        # Keep the label unchanged; desktop displays carry the suffix.
        return self._display_label(session)

    def _display_label(self, session):
        request = self._displayed()
        identity = (session["agent"], session["session_id"])
        if session["state"] == "locked" or (request and request.session == identity and request.status == "locked"):
            return "LOCKED: use terminal"
        if request and request.session == identity and request.armed_at is not None:
            return "GATE! press again" if request.gate else "HOLD! press again"
        if request and request.session == identity and request.gate:
            return "GATE: " + session["name"]
        if request and request.session == identity and request.gate_confirmed:
            return "Gate confirmed: " + session["name"]
        if self.voice_notice:
            return self.voice_notice[1]
        if self.input_notice and identity == self.selected:
            return "KEY: " + self.input_notice[0]
        if session.get("needs_answer"):
            return "ANSWER: " + session["name"]
        if session.get("native_wait"):
            return "APP: " + session["name"]
        return session["name"]

    def _update_voice(self):
        """Consume callbacks queued by the guard without acquiring Hub locks there."""
        changed = False
        while True:
            try:
                generation, result = self.voice_events.get_nowait()
            except Empty:
                break
            if generation != self.voice_generation:
                continue
            closed = result.get("closed", True)
            if closed:
                self.voice_target = None
                if self.voice_notice:
                    self.voice_notice = None
                    changed = True
            target = result["session"]
            identity = (target["agent"], target["session_id"])
            message = {"timeout": "VOICE: timeout", "window_lost": "VOICE: target lost",
                       "focus_failed": "VOICE: focus lost", "error": "VOICE: stopped"}.get(result["reason"])
            if not closed:
                message = "VOICE: stop failed"
            if message is None and result["restores"]:
                message = "VOICE: kept target"
            if message and not self.closed and identity in self.sessions:
                self.voice_notice = (identity, message, self.monotonic() + VOICE_NOTICE_SECONDS)
                changed = True
        if self.voice_notice and self.monotonic() >= self.voice_notice[2]:
            self.voice_notice = None
            changed = True
        if self.input_notice and self.monotonic() >= self.input_notice[1]:
            self.input_notice = None
            changed = True
        if changed:
            self._show()

    def _publish(self, session):
        state = "wait" if session["state"] == "locked" else session["state"]
        self._send(["set %s %s %s" % (session["key"], state, self._display_name(session))])

    def _next_request(self):
        self._set_displayed(next(iter(self.pending), None) or next(iter(self.locked), None))
        request = self._displayed()
        if request is not None:
            self.selected = request.session
        self._show()

    def _audit(self, request, decision, source, **details):
        fields = {"agent": request.session[0], "session_id": request.session[1],
                  "project": request.project, "tool_name": request.tool_name,
                  "command": request.command[:500], "risk": request.risk,
                  "request_id": request.id, "nonce": request.nonce} if request else {
                      'agent': None, 'session_id': None, 'project': None, 'tool_name': None,
                      'command': '', 'risk': None, "request_id": None, "nonce": None}
        try:
            self.audit.append(dict(fields, timestamp=self.wall_time(), decision=decision,
                                   source=source, **details))
        except (OSError, AuditError) as error:
            log.error("Cannot audit %s for %s: %s", decision, request.id if request else None, error)
            if decision in ("allow", "deny"):
                raise HubError("audit unavailable; use terminal approval", 503) from error

    def _resolve(self, request, behavior=None, source="timeout", *, decision=None, moved_on=False):
        """``moved_on``: the agent no longer waits (client gone or later event)."""
        self._audit(request, decision or behavior or "timeout",
                    "gate" if request.gate and not moved_on else source,
                    **({"moved_on": True} if moved_on else {}))
        if request.gate:
            if behavior == "allow":
                request.response = {}
                self.gate_passed[(request.session, request.input_hash)] = self.monotonic()
            else:
                reason = "denied by user" if behavior == "deny" else "confirmation timed out or request cancelled"
                request.response = gate_denial(reason)
        elif behavior is not None:
            decision = {"behavior": behavior}
            if behavior == "deny":
                decision["message"] = "Denied from AgentDeck"
            request.response = {"hookSpecificOutput": {
                "hookEventName": "PermissionRequest", "decision": decision}}
        self.pending.pop(request.id, None)
        session = self.sessions.get(request.session)
        if session is not None:
            remaining = any(p.session == request.session for p in self.pending.values())
            locked = any(p.session == request.session for p in self.locked.values())
            native = behavior is None and not request.gate and not moved_on
            if native:
                # The agent's own permission dialog now has the question; Enter
                # there would approve it without AgentDeck's confirmations.
                session["native_wait"] = True
                if decision == "passthrough":
                    session["label"] = "在应用里批准"
            elif moved_on:
                session.pop("native_wait", None)
                session.pop("label", None)
            session["state"] = ("locked" if locked and not remaining else "wait" if remaining or native
                                else "tool" if behavior == "allow" else "idle")
            session["last_updated"] = self.wall_time()
            self._publish(session)
        request.ready.set()
        if self.displayed_request_id == request.id:
            self._next_request()

    def _abandon_requests(self, identity, name, agent_id=""):
        """Progress releases native permissions only for the same subagent.

        Ordinary tool telemetry and new prompts never cancel a gate; terminal
        events cancel all requests because the session/turn has ended.
        """
        released = 0
        for request in list(self.pending.values()):
            if request.session != identity:
                continue
            if name in TOOL_PROGRESS_EVENTS + ("UserPromptSubmit",) and request.gate:
                continue
            if name in TOOL_PROGRESS_EVENTS and request.agent_id != agent_id:
                continue
            self._resolve(request, source="event", decision="abandoned", moved_on=True)
            released += 1
        if released:
            log.info("%s session %s released %d abandoned request(s)", name, identity[1][:8], released)

    def _release_unheld(self, settle=0.0):
        """``settle``: maintenance waits out a reader briefly reporting none (USB -> Raw Input)."""
        if self.hold_active():
            self.unheld_since = None
            return
        now = self.monotonic()
        if self.unheld_since is None:
            self.unheld_since = now
        if now - self.unheld_since < settle:
            return
        released = 0
        for request in list(self.pending.values()):
            if not request.gate:
                self._resolve(request, source="hold", decision="passthrough")
                released += 1
        if released:
            log.info("Hold %s released %d request(s) to native approval", self.hold_mode, released)

    def _remove_session(self, identity, event_name=None, ended_by="", reason=""):
        """Share SessionEnd cleanup with slot eviction and idle expiry."""
        if event_name:
            self._abandon_requests(identity, event_name)
        cleared_display = False
        for request in list(self.locked.values()):
            if request.session == identity:
                self.locked.pop(request.id)
                if self.displayed_request_id == request.id:
                    self._set_displayed(None)
                    cleared_display = True
        self.gate_passed = {key: passed for key, passed in self.gate_passed.items() if key[0] != identity}
        if self.voice_target == identity:
            try:
                self._desktop().voice_up()
            except Exception as error:
                log.warning("Voice session end failed: %s", error)
            finally:
                self._update_voice()
        removed = self.sessions.pop(identity, None)
        for request in list(self.pending.values()):
            if request.session == identity:
                self._resolve(request)
        if removed is not None:
            self._remember_ended(removed, ended_by or event_name or "", reason)
            self._send(["end " + removed["key"]])
        if self.selected == identity:
            self.selected = next(iter(self.sessions), None)
            self._next_request()
        elif cleared_display:
            self._next_request()

    def _remember_ended(self, session, ended_by, reason):
        """Keep the final state and reply of a removed session for /state."""
        entry = {key: session.get(key) for key in (
            "agent", "session_id", "slot", "name", "title", "cwd", "state", "last_event",
            "last_text", "last_kind", "last_text_at", "label", "last_updated")}
        entry.update(ended_by=ended_by, reason=reason[:64] if isinstance(reason, str) else "",
                     ended_at=self.wall_time())
        self.recent_ended.append(entry)

    def _reclaimable_sessions(self):
        busy = {request.session for requests in (self.pending, self.locked) for request in requests.values()}
        return [(identity, session) for identity, session in self.sessions.items()
                if identity not in busy and identity != self.voice_target]

    def _expire(self):
        now = self.monotonic()
        self.gate_passed = {key: passed for key, passed in self.gate_passed.items()
                            if now - passed < GATE_CONFIRMED_SECONDS}
        for request in list(self.pending.values()):
            if now >= request.deadline:
                self._resolve(request)
            elif request.armed_at is not None and now - request.armed_at > CONFIRM_SECONDS:
                request.armed_at = None
                if self.displayed_request_id == request.id:
                    self._show()
        wall_now = self.wall_time()
        for identity, session in self._reclaimable_sessions():
            if wall_now - session["last_updated"] > SESSION_IDLE_SECONDS:
                self._remove_session(identity, ended_by="idle")

    def event(self, agent, event, *, gate=False, received_at=None, disconnected=None):
        """Handle a hook; permission and intercepted gate requests wait outside the lock.

        ``received_at`` (monotonic) starts the approval budget at HTTP receipt, so a
        lock wait cannot outlive the relay. ``disconnected()`` reports a hook client
        that has gone away (killed relay, native decision, Esc); its request is dropped.
        """
        received_at = self.monotonic() if received_at is None else received_at
        if agent not in ("cc", "cx") or not isinstance(event, dict):
            raise HubError("agent must be cc or cx; event must be an object")
        name = event.get("hook_event_name")
        sid = event.get("session_id") or event.get("thread_id") or event.get("conversation_id")
        if isinstance(name, str) and name not in EVENTS:
            short_name = escape_log_text(name, 64)
            with UNKNOWN_EVENTS_LOCK:
                if short_name not in UNKNOWN_EVENTS and len(UNKNOWN_EVENTS) < 256:
                    UNKNOWN_EVENTS.add(short_name)
                    log.warning("Unsupported hook_event_name: %s", short_name)
        if not isinstance(name, str) or name not in EVENTS or not isinstance(sid, str) or not sid or len(sid) > 256:
            raise HubError("a supported hook_event_name and session_id are required")
        if "cwd" in event and not isinstance(event["cwd"], str):
            raise HubError("cwd must be a string")
        if (name == "PermissionRequest" or gate) and not isinstance(event.get("tool_name", ""), str):
            raise HubError("tool_name must be a string")
        if gate and name != "PreToolUse":
            raise HubError("gate requires a PreToolUse event")
        key = session_key(agent, sid)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            raise HubError("session_id contains invalid display key characters")
        identity = (agent, sid)
        tool_name = event.get("tool_name", "")
        tool_input = event.get("tool_input", {})
        risk = None
        if name == "PermissionRequest" or gate:
            risk = classify(tool_name, tool_input, self.risk_rules, self.critical_rules,
                            production_hosts=self.production_hosts, protected_branches=self.protected_branches,
                            mcp_write_tools=self.mcp_write_tools)
        # Unheld gate requests skip here too: no passthrough audit for every low-risk tool call.
        if gate and (self.gate_mode == "off" or (self.gate_mode == "high" and risk == "low")):
            return {}
        # Transcript reads can be slow or fail; neither holds the state lock.
        title = event_title(event) if agent == "cc" else ""
        with self.lock:
            if self.closed:
                return gate_denial("hub is shutting down") if gate else {}
            self._update_voice()
            self.agents_seen[agent] = self.wall_time()
            self._expire()
            if name == "SessionEnd":
                self._remove_session(identity, event_name=name, reason=event.get("reason"))
                return {}
            if name in MOVED_ON_EVENTS and not gate:
                agent_id = event.get("agent_id")
                self._abandon_requests(identity, name, agent_id if isinstance(agent_id, str) else "")
            cleared_display = False
            if name not in ("PermissionRequest", "Notification"):
                for request in list(self.locked.values()):
                    if request.session == identity:
                        self.locked.pop(request.id)
                        if self.displayed_request_id == request.id:
                            self._set_displayed(None)
                            cleared_display = True
            if identity not in self.sessions:
                used = {s["slot"] for s in self.sessions.values()}
                slot = next((i for i in range(1, 7) if i not in used), None)
                if slot is None:
                    candidates = self._reclaimable_sessions()
                    if not candidates:
                        raise HubError("all six session slots are occupied", 409)
                    oldest, removed = min(candidates, key=lambda item: item[1]["last_updated"])
                    slot = removed["slot"]
                    self._remove_session(oldest, ended_by="evicted")
                self.sessions[identity] = {"agent": agent, "session_id": sid, "key": key,
                                           "cwd": "", "name": "agent", "project": "agent",
                                           "state": "idle", "slot": slot}
            session = self.sessions[identity]
            cwd = event.get("cwd", session["cwd"])
            session.update(cwd=cwd, name=agent_lcd.ascii_name(cwd),
                           project=agent_lcd.ascii_name(cwd), last_updated=self.wall_time(),
                           last_event=name)
            if title:
                session["title"] = title
            window = event.get("agentdeck_window")
            if isinstance(window, dict):
                # The relay's top-level window of the agent process: focus by handle,
                # not by guessing from a title Claude Code keeps rewriting.
                hwnd, exe = window.get("hwnd"), window.get("exe")
                if type(hwnd) is int and 0 < hwnd < 2**64:
                    session["hwnd"] = hwnd
                    session["window_exe"] = exe[:260] if isinstance(exe, str) else ""
            if name not in ("PermissionRequest", "Notification"):
                session.pop("needs_answer", None)
                session.pop("native_wait", None)
                session.pop("label", None)
            if self.selected is None:
                self.selected = identity
            if name == "PermissionRequest" and not gate and tool_name in NEEDS_ANSWER_TOOLS:
                # A bare allow cannot answer a question or accept a plan; the native
                # UI does it. The approve key focuses this session's window instead.
                session["needs_answer"] = tool_name
                session["state"] = "wait"
                self._publish(session)
                if self.selected == identity:
                    self._show()
                return {}
            if name == "PermissionRequest" or gate:
                summary = (tool_input.get("command") or tool_input.get("description") or
                           tool_input.get("file_path") or tool_input.get("path")) if isinstance(tool_input, dict) else tool_input
                if not isinstance(summary, str):
                    summary = json.dumps(tool_input, ensure_ascii=False)
                request = Pending(uuid.uuid4().hex, identity, tool_name,
                                  " ".join(summary.split())[:240],
                                  risk,
                                  self.wall_time(), received_at + self.approve_timeout,
                                  command=summary, project=session["project"], gate=gate,
                                  input_hash=tool_input_hash(tool_input), nonce=self._new_nonce(),
                                  agent_id=event.get("agent_id") if isinstance(event.get("agent_id"), str) else "")
                if not self.hold_active():
                    self._audit(request, "passthrough", "hold")
                    if not gate:
                        session.update(state="wait", native_wait=True, label="在应用里批准")
                        self._publish(session)
                        if self.selected == identity:
                            self._show()
                    return {}
                session.pop("native_wait", None)
                session.pop("label", None)
                request.gate_confirmed = not gate and (identity, request.input_hash) in self.gate_passed
                if request.risk == "critical" and not gate:
                    request.status = "locked"
                    request.ready.set()
                    self.locked[request.id] = request
                    session["state"] = "wait" if any(p.session == identity for p in self.pending.values()) else "locked"
                    self._audit(request, "locked", "http")
                    self._publish(session)
                    if self.displayed_request_id is None:
                        self._next_request()
                    return {}
                self.pending[request.id] = request
                session["state"] = "wait"
                self._publish(session)
                if self.displayed_request_id is None or self.displayed_request_id in self.locked:
                    self._next_request()
            else:
                text, kind = event_text(name, event)
                if text:
                    session.update(last_text=text[-LAST_TEXT_LIMIT:], last_kind=kind,
                                   last_text_at=self.wall_time())
                if name in ("Stop", "StopFailure", "SessionStart", "Interrupt"):
                    session.pop("activity", None)
                elif name == "PreToolUse" and isinstance(tool_name, str) and tool_name:
                    summary = tool_summary(tool_input)
                    session["activity"] = (tool_name + (" " + summary if summary else ""))[:ACTIVITY_LIMIT]
                if name == "Notification":
                    notification = event.get("notification_type")
                    notification = notification[:64] if isinstance(notification, str) else ""
                    if not notification and "permission" in str(event.get("message") or "").lower():
                        notification = "permission_prompt"
                    session["wait_kind"] = notification
                else:
                    session.pop("wait_kind", None)
                state = EVENT_STATES.get(name)
                if name == "StopFailure":
                    error = event.get("error")
                    session["label"] = "出错：" + (error[:40] if isinstance(error, str) else "unknown")
                if name == "Notification":
                    kind = event.get("notification_type", "")
                    message = str(event.get("message") or "").lower()
                    if kind in agent_lcd.WAIT_NOTIFICATIONS or (not kind and "permission" in message):
                        state = "wait"
                    elif kind == "idle_prompt" and session["state"] in ("tool", "think"):
                        state = "idle"
                if name == "PreToolUse" and event.get("tool_name") == "AskUserQuestion":
                    state = "wait"
                if any(p.session == identity for p in self.pending.values()):
                    state = "wait"
                elif any(p.session == identity for p in self.locked.values()):
                    state = "locked"
                if state:
                    session["state"] = state
                self._publish(session)
                if cleared_display:
                    self._next_request()
                return {}
        # Concurrent HTTP action requests can now acquire the lock and decide.
        abandoned = False
        budget = max(0, request.deadline - self.monotonic())
        if disconnected is None:
            request.ready.wait(budget)
        else:
            end = time.monotonic() + budget  # real-time bound also covers injected clocks
            while True:
                remaining = min(request.deadline - self.monotonic(), end - time.monotonic())
                if remaining <= 0 or request.ready.wait(min(remaining, WAIT_SLICE)):
                    break
                if disconnected():
                    abandoned = True
                    break
        with self.lock:
            if request.id in self.pending:
                if abandoned:
                    log.info("Hook client left; dropping request %s (%s)", request.id, request.tool_name)
                    self._resolve(request, source="client", decision="abandoned", moved_on=True)
                else:
                    self._resolve(request)
            return request.response

    def state(self):
        with self.lock:
            self._update_voice()
            self._expire()
            sessions = []
            for session in sorted(self.sessions.values(), key=lambda s: s["slot"]):
                item = dict(session)
                identity = (session["agent"], session["session_id"])
                item["pending_requests"] = [p.public() for p in self.pending.values() if p.session == identity]
                item["locked_requests"] = [p.public() for p in self.locked.values() if p.session == identity]
                sessions.append(item)
            selected = self.sessions.get(self.selected)
            reader = self._input_reader()
            connected = reader in ("usb", "raw")
            return {"sessions": sessions, "pending": [p.public() for p in self.pending.values()],
                    "last_input": dict(self.last_input) if self.last_input else None,
                    "input_reader": reader if reader in ("usb", "raw", "absent") else None,
                    "deck_connected": connected, "hold_mode": self.hold_mode,
                    "hold_active": self.hold_mode == "always" or (self.hold_mode == "auto" and connected),
                    "show_requests": self.show_requests,
                    "overlay_pinned": self.overlay_pinned,
                    "overlay_corner_requests": self.overlay_corner_requests,
                    "last_cycle_age": (max(0.0, self.monotonic() - self.last_cycle)
                                       if math.isfinite(self.last_cycle) else None),
                    "display_order": [self.sessions[identity]["slot"] for identity in self._session_order()],
                    "locked": [p.public() for p in self.locked.values()],
                    "agents_seen": dict(self.agents_seen),
                    "recent_ended": [dict(entry) for entry in self.recent_ended],
                    "nonce_required": self.require_nonce,
                    "input_mode": self.rendered_source or 'headless',
                    "input_request": dict(self.rendered_request),
                    "displayed_request_id": self.displayed_request_id,
                    "selected_slot": selected["slot"] if selected else None}

    def _validate_decision(self, payload, command, source, received_at):
        """Reject stale input before timeout/voice maintenance can mutate state."""
        request = self._displayed()
        if (request is None and payload.get('request_id') is None
                and payload.get('nonce') is None and source in ('key', 'hotkey')):
            return
        reason = None
        if "nonce" in payload:
            nonce = payload["nonce"]
            if (type(nonce) is not int or not 0 <= nonce < 2**32 or request is None
                    or (request.id not in self.pending and request.id not in self.locked)
                    or nonce != request.nonce or (request.status != 'locked' and self.monotonic() >= request.deadline)
                    or (payload.get("request_id") is not None and payload["request_id"] != request.id)):
                reason = "stale_nonce"
        elif command == "approve" and self.require_nonce:
            reason = "nonce_required"
        display_source = payload.get('display_source', 'overlay' if source == 'overlay' and 'nonce' in payload else None)
        if reason is None and display_source is not None:
            if (not isinstance(display_source, str) or display_source not in self.active_displays
                    or self.rendered_by_source.get(display_source) != {
                        'request_id': payload.get('request_id'), 'nonce': payload.get('nonce')}):
                reason = 'stale_nonce'
            elif command == 'approve' and received_at - self.rendered_at[display_source] < SWITCH_GUARD_SECONDS:
                reason = 'switch_guard'
        if reason is None and "nonce" not in payload and payload.get("request_id") is not None:
            if request is None or payload["request_id"] != request.id:
                raise HubError("displayed request changed", 409)
        if (reason is None and command == "approve" and request is not None
                and request.status == "pending" and self.monotonic() < request.deadline
                and received_at - self.display_switched_at < SWITCH_GUARD_SECONDS):
            reason = "switch_guard"
        if (reason is None and command == 'approve' and source in ('key', 'hotkey')
                and request is not None and request.risk == 'low'
                and self.confirm_target != request.id
                and received_at < self.confirm_until):
            reason = 'switch_guard'
        if reason:
            supplied = payload.get("nonce")
            if supplied is not None and type(supplied) is not int:
                # Malformed JSON values (including NaN) must not break the
                # strict JSON audit encoder and turn a stale nonce into a 500.
                supplied = repr(supplied)[:160]
            self._audit(request, reason, source, reason=reason, action=command,
                        supplied_nonce=supplied,
                        supplied_request_id=payload.get("request_id"))
            raise HubError(reason, 409)

    def action(self, payload, source="http", *, received_at=None):
        """The single action path used by both HTTP and the physical device.

        State changes happen under ``self.lock``; window focus, paste, screenshot
        and dictation run after it is released, so hook events never wait on them.
        """
        # This timestamp is an internal argument, never read from HTTP JSON.
        # A press inside the guard must stay blocked while waiting for the lock.
        received_at = self.monotonic() if received_at is None else received_at
        if not isinstance(payload, dict) or not isinstance(payload.get("action"), str):
            raise HubError("action must be a string")
        parts = payload["action"].strip().split(maxsplit=1)
        if not parts:
            raise HubError("action must not be empty")
        command = parts[0]
        argument = parts[1] if len(parts) == 2 else None
        if command not in ("slot", "cycle", "next_wait", "approve", "deny", "interrupt", "voice",
                           "voice_down", "voice_up", "screenshot", "prompt", "show", "scroll", "nav", "hold", "app", "window", "overlay"):
            raise HubError("unknown action")
        if command not in ("slot", "cycle", "prompt", "scroll", "nav", "hold", "app", "window", "overlay") and argument is not None:
            raise HubError("unexpected action argument")
        if command == "scroll":
            if argument == "end":
                argument = SCROLL_END
            else:
                try:
                    argument = int(argument)
                except (TypeError, ValueError):
                    argument = 0
                if not argument or abs(argument) > SCROLL_LIMIT:
                    raise HubError("scroll needs a nonzero step up to %d, or end" % SCROLL_LIMIT)
        if command == "nav" and argument not in NAV_KEYS:
            raise HubError("nav needs up, down or enter")
        if command == "app" and argument not in ("next", "prev"):
            raise HubError("app needs next or prev")
        if command == "window" and argument not in ("next", "prev"):
            raise HubError("window needs next or prev")
        if command == "hold" and argument not in ("auto", "always", "never"):
            raise HubError("hold needs auto, always or never")
        if command == "overlay" and argument not in ("toggle", "corner"):
            raise HubError("overlay needs toggle or corner")
        if command != "window" and self.desktop is not None:
            release = getattr(self.desktop, "release_window_switch", None)
            if callable(release) and release() is False:
                raise HubError("could not release window-switch keys", 409)
        start_reader = False
        with self.lock:
            self.cycle_generation += 1
            generation = self.cycle_generation
            if command == "cycle":
                start_reader = received_at - self.last_cycle >= CYCLE_BURST_SECONDS
                if start_reader:
                    self.cycle_order = self._session_order(frozen=False)
                self.last_cycle = received_at
            else:
                self.last_cycle = float("-inf")
            outcome = self._action_locked(payload, command, argument, source, received_at)
        if start_reader:
            self._start_cycle_origin(generation)
        if callable(outcome):
            return outcome()
        return outcome

    def _session_order(self, frozen=True):
        """Keep rotation and the overlay in the same order for a whole burst."""
        recent = sorted(self.sessions, key=lambda identity: (
            -self.sessions[identity]["last_updated"], self.sessions[identity]["slot"]))
        if frozen and self.monotonic() - self.last_cycle < CYCLE_BURST_SECONDS:
            self.cycle_order = ([identity for identity in self.cycle_order if identity in self.sessions]
                                + [identity for identity in recent if identity not in self.cycle_order])
            return list(self.cycle_order)
        return recent

    def _start_cycle_origin(self, generation):
        """Read UIA once in the background; a second step invalidates the result."""
        with self.lock:
            if self.closed or (self.cycle_reader is not None and self.cycle_reader.is_alive()):
                return
            candidates = [dict(session) for session in self.sessions.values() if session.get("title")
                          and str(session.get("window_exe", "")).replace("\\", "/").rsplit("/", 1)[-1].lower() == "claude.exe"]
            if not candidates or not self.desktop_enabled:
                return

            def read():
                try:
                    method = getattr(self._desktop(), "current_session_title", None)
                    title = method(candidates) if callable(method) else None
                    with self.lock:
                        if (self.closed or self.cycle_generation != generation
                                or self.monotonic() - self.last_cycle >= CYCLE_BURST_SECONDS):
                            return
                        matches = [session for session in candidates if session["title"] == title
                                   and (session["agent"], session["session_id"]) in self.sessions]
                        if matches:
                            chosen = min(matches, key=lambda session: (-session["last_updated"], session["slot"]))
                            self._select_session((chosen["agent"], chosen["session_id"]))
                except Exception as error:
                    log.warning("Cannot read current Claude session: %s", error)

            self.cycle_reader = threading.Thread(target=read, name="AgentDeck current session", daemon=True)
            self.cycle_reader.start()

    def _select_session(self, selected):
        previous = self.pending.get(self.displayed_request_id)
        if previous is not None:
            previous.armed_at = None
        self.selected = selected
        self.confirm_target = None
        self.confirm_until = float('-inf')
        self._set_displayed(next((p.id for p in self.pending.values() if p.session == selected), None) or next(
            (p.id for p in self.locked.values() if p.session == selected), None))
        self._show()

    def _focus_effect(self, command, selected, result):
        """Snapshot under the lock; the returned callable focuses without it."""
        session = dict(self.sessions[selected])
        sessions = [dict(item) for item in self.sessions.values()]
        # Shared relay handles may still resolve to a distinct session window.
        hwnd = session.get("hwnd")
        shared = type(hwnd) is int and sum(1 for item in sessions if item.get("hwnd") == hwnd) > 1
        try:
            desktop, unavailable = self._desktop(), None
        except HubError as error:
            desktop, unavailable = None, error

        def focus():
            shared_window = shared
            try:
                if unavailable is not None:
                    raise unavailable
                show = getattr(desktop, "show_session", None) if command == "show" else None
                focused = show(session, sessions) if callable(show) else desktop.focus(session, sessions)
                if isinstance(focused, dict) and focused.get("claude_sidebar"):
                    label = session_label(session)
                    switched = focused.get("switched") is True
                    message = ("已切到：" if switched else "Claude 侧栏里没找到：") + label
                    log.info("%s", escape_log_text(message, 160))
                    return dict(result, slot=session["slot"], window="focused", switched=switched,
                                title=session.get("title", ""), message=message)
                if isinstance(focused, tuple) and len(focused) == 3:
                    shared_window = shared and focused[0] == hwnd
                window = "window focus unavailable" if focused is False else "focused"
            except Exception as error:
                log.warning("Window focus unavailable: %s", error)
                window = str(error)
            extra = {"shared_window": True} if shared_window and window == "focused" else {}
            return dict(result, slot=session["slot"], window=window, **extra)
        return focus

    def _action_locked(self, payload, command, argument, source, received_at):
        if self.closed:
            raise HubError("hub is shutting down", 503)
        if command in ("approve", "deny"):
            self._validate_decision(payload, command, source, received_at)
        self._update_voice()
        self._expire()
        if command == "overlay":
            if argument == "toggle":
                self.overlay_pinned = not self.overlay_pinned
            else:
                self.overlay_corner_requests += 1
            return {"action": command, "status": "ok", "pinned": self.overlay_pinned,
                    "corner_requests": self.overlay_corner_requests}
        if command == "hold":
            self.hold_mode = argument
            self._release_unheld()
            return {"status": "ok", "hold_mode": self.hold_mode}
        if command == "show":
            self.show_requests += 1
            if self.selected in self.sessions:
                return self._focus_effect(command, self.selected, {"action": command, "status": "shown"})
            return {"action": command, "status": "shown"}
        if command == "voice_up":
            desktop = self.desktop
            if desktop is None:
                return {"action": command, "status": "sent"}
            if getattr(desktop, "dictation_shortcut", {}).get("mode") == "tap":
                return {"action": command, "status": "ignored"}

            def stop_voice():
                try:
                    completed = desktop.voice_up()
                except Exception as error:
                    raise HubError(str(error), 409) from error
                finally:
                    with self.lock:
                        self._update_voice()
                if sys.platform == "darwin" and completed is False:
                    return {"action": command, "status": "unavailable"}
                return {"action": command, "status": "sent"}
            return stop_voice
        voice_active = self.desktop is not None and self.desktop.voice_active
        if voice_active and command not in ("voice_down", "deny", "interrupt"):
            raise HubError("release voice before approving, changing sessions or sending input", 409)
        if voice_active and command == "voice_down":
            return {"action": command, "status": "sent"}
        if command in ("approve", "deny", "interrupt"):
            if command == "interrupt" and self.displayed_request_id is None and self.pending:
                self._next_request()
            request = self._displayed()
            expected = payload.get("request_id")
            if 'request_id' in payload and expected != self.displayed_request_id:
                raise HubError("displayed request changed", 409)
            if request is not None:
                result = {"action": command, "request_id": request.id}
                if request.status == "locked":
                    return dict(result, status="locked")
                if command == "approve" and ((request.gate and request.risk in ("high", "critical")) or
                                              (request.risk == "high" and not request.gate_confirmed)):
                    now = self.monotonic()
                    if request.armed_at is None or now - request.armed_at > CONFIRM_SECONDS:
                        request.armed_at = now
                        self.confirm_target = request.id
                        self.confirm_until = now + CONFIRM_SECONDS
                        self._show()
                        return dict(result, status="confirm", message="GATE! press again" if request.gate else "HOLD! press again")
                self._resolve(request, "allow" if command == "approve" else "deny", source)
                if command == 'approve':
                    self.confirm_target = None
                    self.confirm_until = float('-inf')
                return dict(result, status="allowed" if command == "approve" else "denied")
            if command == "approve":
                # Questions and plans are answered in the agent's own window.
                ordered = sorted(self.sessions.items(), key=lambda pair: pair[1]["slot"])
                asking = [identity for identity, s in ordered if s.get("needs_answer")]
                if asking:
                    selected = self.selected if self.selected in asking else asking[0]
                    self.selected = selected
                    self._show()
                    return self._focus_effect(command, selected,
                                              {"action": command, "request_id": None, "status": "focus"})
            if command != "interrupt":
                return {"action": command, "request_id": None, "status": "no_request"}
            if voice_active:
                raise HubError("release voice before sending input", 409)
        if command in ("slot", "cycle", "next_wait"):
            sessions = ([(identity, self.sessions[identity]) for identity in self._session_order()]
                        if command == "cycle" else sorted(self.sessions.items(), key=lambda pair: pair[1]["slot"]))
            if command == "next_wait":
                identities = [identity for identity, _ in sessions]
                index = identities.index(self.selected) if self.selected in identities else -1
                selected = next(
                    (sessions[(index + step) % len(sessions)][0]
                     for step in range(1, len(sessions) + 1)
                     if sessions[(index + step) % len(sessions)][1]["state"] in ("wait", "locked")),
                    None,
                )
                if selected is None:
                    return {"action": command, "status": "no_waiting_session",
                            "slot": None, "request_id": self.displayed_request_id}
            else:
                raw = argument if argument is not None else payload.get("slot" if command == "slot" else "delta")
                if isinstance(raw, bool) or not isinstance(raw, (str, int)):
                    raise HubError("slot/cycle needs an integer")
                try:
                    number = int(raw)
                except ValueError as error:
                    raise HubError("slot/cycle needs an integer") from error
                if command == "slot":
                    selected = next((identity for identity, s in sessions if s["slot"] == number), None)
                    expected = payload.get("session")
                    if (selected is not None and expected is not None
                            and list(expected) != list(selected)):
                        raise HubError("that session has ended", 409)
                else:
                    if number == 0:
                        raise HubError("cycle delta must not be zero")
                    identities = [identity for identity, _ in sessions]
                    index = identities.index(self.selected) if self.selected in identities else (-1 if number > 0 else 0)
                    selected = identities[(index + number) % len(identities)] if identities else None
                if selected is None:
                    raise HubError("no session in that slot", 404)
            self._select_session(selected)
            result = {"action": command, "status": "selected", "request_id": self.displayed_request_id,
                      "slot": self.sessions[selected]["slot"]}
            return result if command == "cycle" else self._focus_effect(command, selected, result)
        session = self.sessions.get(self.selected)
        if session is None and command not in ("app", "window"):
            raise HubError("select a session first", 409)
        if command == "nav":
            identity = self.selected
            if (any(p.session == identity for p in self.pending.values())
                    or any(p.session == identity for p in self.locked.values())
                    or session.get("wait_kind") == "permission_prompt" or session.get("native_wait")):
                # Enter in the agent's own permission dialog would skip the
                # high-risk double press and the critical-risk lock.
                raise HubError("a permission request is open: use approve/deny", 409)
            if argument in ("up", "down") and session["state"] != "wait":
                # Idle arrows recall old prompts; a later Enter would resend one.
                raise HubError("nav up/down works only while the agent asks a question", 409)
        desktop = self._desktop()
        sessions = [dict(item) for item in self.sessions.values()]
        session = dict(session) if session is not None else None
        text = generation = None
        if command == "prompt":
            template = argument if argument is not None else payload.get("name")
            if not isinstance(template, str) or not isinstance(self.prompts.get(template), str):
                raise HubError("unknown prompt template")
            text = self.prompts[template]
        elif command in ("voice", "voice_down"):
            self.voice_notice = None
            self.voice_generation += 1
            generation = self.voice_generation
            self.voice_target = self.selected
            if sys.platform != "darwin":
                for request in self.pending.values():
                    request.armed_at = None

        def run_effect():
            try:
                completed = None
                if command == "prompt":
                    completed = desktop.prompt(session, sessions, text)
                elif command in ("scroll", "nav", "app", "window"):
                    method = getattr(desktop, command, None)
                    completed = False if method is None else method(session, sessions, argument)
                    if completed is False:
                        return {"action": command, "status": "unavailable"}
                elif command == "screenshot":
                    path = desktop.screenshot(session, sessions)
                    if path is False:
                        return {"action": command, "status": "unavailable"}
                    if isinstance(path, dict):
                        return {"action": command, "status": "sent", **path}
                    return {"action": command, "status": "sent", "path": path}
                elif command in ("voice", "voice_down"):
                    completed = desktop.voice_down(session, sessions,
                                                   on_stop=lambda result: self.voice_events.put((generation, result)))
                    with self.lock:
                        unavailable = sys.platform == "darwin" and completed is False
                        if unavailable and self.voice_generation == generation:
                            self.voice_target = None
                        if sys.platform == "darwin" and not unavailable:
                            for request in self.pending.values():
                                request.armed_at = None
                        self._show()
                    if unavailable:
                        return {"action": command, "status": "unavailable"}
                    if isinstance(completed, dict) and completed.get("mode") == "tap":
                        return {"action": command, "status": "sent", **completed}
                    if command == "voice":
                        completed = desktop.voice_up()
                else:
                    completed = getattr(desktop, command)(session, sessions)
                if sys.platform == "darwin" and completed is False:
                    return {"action": command, "status": "unavailable"}
            except HubError:
                raise
            except Exception as error:
                log.warning("Desktop action failed: %s", error)
                raise HubError(str(error), 409) from error
            finally:
                if command in ("voice", "voice_down"):
                    with self.lock:
                        self._update_voice()
                        if not desktop.voice_active and self.voice_generation == generation:
                            self.voice_target = None
            return {"action": command, "status": "sent"}
        return run_effect

    def _desktop(self):
        with self.lock:
            if self.closed:
                raise HubError("hub is shutting down", 503)
            if not self.desktop_enabled:
                raise HubError("desktop output disabled", 409)
            if self.desktop is None:
                from hub_desktop import DesktopEffects
                self.desktop = DesktopEffects(monotonic=self.monotonic)
            return self.desktop

    def maintain(self):
        with self.lock:
            self._update_voice()
            self._expire()
            self._release_unheld(settle=UNHELD_SETTLE_SECONDS)
            if self.lcd_enabled and self.selected is not None and self.monotonic() - self.last_focus >= daemon.HEARTBEAT:
                self._show()
            elif self.lcd_enabled and self.selected is not None and self.monotonic() >= self.lcd_retry_at:
                self.lcd_retry_at = float('inf')
                self._show()
        self._save_sessions()

    def close(self):
        with self.lock:
            self.closed = True
            self.cycle_generation += 1
            reader = self.cycle_reader
            for request in list(self.pending.values()):
                self._resolve(request)
            self.locked.clear()
            self.displayed_request_id = None
            if self.lcd_thread is not None:
                self.lcd_jobs.put(None)
        if self.desktop is not None:
            try:
                self.desktop.close()
            except Exception as error:
                log.warning("Desktop shutdown failed: %s", error)
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=3.5)
        self._save_sessions(force=True)


class HubServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64  # bursts of parallel hooks must not be refused by the backlog

    def __init__(self, hub, token, port=PORT):
        if not isinstance(token, str) or not token.strip():
            raise ValueError("a nonempty token is required")
        self.hub, self.token = hub, token
        super().__init__((HOST, port), HubHandler)


class HubHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5.0)

    def log_message(self, message, *args):
        log.debug(message, *args)

    def _reply(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise HubError("invalid Content-Length") from error
        if not 0 < size <= MAX_BODY:
            raise HubError("JSON body required (maximum 8 MiB)")
        try:
            body = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeError) as error:
            raise HubError("invalid JSON") from error
        if not isinstance(body, dict):
            raise HubError("JSON body must be an object")
        # Agents cut strings by UTF-16 units; a lone surrogate would break every
        # later UTF-8 encode (hash, audit, reply).
        return scrub_surrogates(body)

    def _client_gone(self):
        """True once the hook client closed or reset its connection."""
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            if not readable:
                return False
            return self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    def _handle(self):
        received_at = self.server.hub.monotonic()
        try:
            route = urlsplit(self.path)
            if self.command == "GET" and route.path == "/health":
                self._reply(200, {"ok": True})
                return
            supplied = self.headers.get("X-AgentDeck-Token", "")
            if not hmac.compare_digest(supplied.encode("utf-8"), self.server.token.encode("utf-8")):
                self._reply(401, {"error": "unauthorized"})
                return
            if self.command == "GET" and route.path == "/state":
                result = self.server.hub.state()
            elif self.command == "GET" and route.path == "/audit":
                values = parse_qs(route.query, keep_blank_values=True).get("limit", ["50"])
                try:
                    if len(values) != 1:
                        raise ValueError("one limit is required")
                    limit = int(values[0])
                    if not 1 <= limit <= 1000:
                        raise ValueError("limit out of range")
                except ValueError as error:
                    raise HubError("audit limit must be between 1 and 1000") from error
                try:
                    result = self.server.hub.audit.recent(limit)
                except (OSError, AuditError) as error:
                    raise HubError("audit unavailable or chain invalid", 503) from error
            elif self.command == "POST" and route.path == "/event":
                query = parse_qs(route.query, keep_blank_values=True)
                agents = query.get("agent", [])
                if len(agents) != 1:
                    raise HubError("one agent query parameter is required")
                gates = query.get("gate", [])
                if gates not in ([], ["1"]):
                    raise HubError("gate must be a single 1")
                result = self.server.hub.event(agents[0], self._body(), gate=bool(gates),
                                               received_at=received_at, disconnected=self._client_gone)
            elif self.command == "POST" and route.path == "/action":
                result = self.server.hub.action(self._body())
            elif self.command == 'POST' and route.path == '/rendered':
                body = self._body()
                if body.get('source') != 'virtual' or type(body.get('visible', True)) is not bool:
                    raise HubError('render source must be virtual with boolean visibility')
                engine = self.server.hub
                with engine.lock:
                    if not body.get('visible', True):
                        engine.hide_display('virtual')
                    else:
                        request_id, nonce = body.get('request_id'), body.get('nonce')
                        request = engine.pending.get(request_id) or engine.locked.get(request_id) if isinstance(request_id, str) else None
                        if not ((request_id is None and nonce is None) or (
                                request is not None and type(nonce) is int and nonce == request.nonce)):
                            raise HubError('stale_nonce', 409)
                        engine.record_rendered(request_id, nonce, 'virtual')
                result = {'status': 'rendered'}
            else:
                self._reply(404, {"error": "unknown endpoint or method"})
                return
            self._reply(200, result)
        except HubError as error:
            self._reply(error.status, {"error": str(error)})
        except (ConnectionError, TimeoutError):  # includes aborted (WinError 10053) clients
            log.debug("Hook client disconnected")
        except Exception:
            log.exception("Hub request failed")
            self._reply(500, {"error": "hub request failed"})

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = do_TRACE = do_CONNECT = _handle


def binding_label(binding):
    """Describe HID bindings for diagnostics; malformed input must never raise."""
    try:
        parts = binding.split("+")
        code = parts[-1]
        if code.lower().startswith("hid:0x"):
            usage = int(code[4:], 16)
            if 0x04 <= usage <= 0x1D:
                code = chr(ord("A") + usage - 0x04)
            elif 0x1E <= usage <= 0x27:
                code = "1234567890"[usage - 0x1E]
            elif 0x3A <= usage <= 0x45:
                code = "F%d" % (usage - 0x3A + 1)
            elif 0x68 <= usage <= 0x73:
                code = "F%d" % (usage - 0x68 + 13)
            else:
                code = {0x28: "Enter", 0x29: "Esc", 0x2A: "Backspace", 0x2B: "Tab",
                        0x2C: "Space", 0x2D: "-", 0x2E: "=", 0x2F: "[", 0x30: "]",
                        0x31: "\\", 0x33: ";", 0x34: "'", 0x35: "`", 0x36: ",",
                        0x37: ".", 0x38: "/"}.get(usage, "0x%02X" % usage)
        modifiers = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "win": "Win"}
        return "+".join([modifiers.get(part.lower(), part) for part in parts[:-1]] + [code])
    except Exception:
        return binding if isinstance(binding, str) else "?"


def control_name(binding):
    """All known physical positions that send this exact binding."""
    return CONTROL_NAMES.get(normalize_key(binding), binding_label(binding))


class USBKeys:
    """Dispatch bindings and pair releases with the accepted physical press."""

    def __init__(self, hub, mapping=None, monotonic=None, profile="default", knob_divider=None):
        from hub_keyboard import KnobDetents
        self.hub = hub
        self.detents = KnobDetents(knob_divider)
        config = load_json(Path(__file__).with_name("hub_keys.json")) if mapping is None else mapping
        if profile != "default":
            config = config.get(profile)
        if not isinstance(config, dict) or not isinstance(config.get("bindings"), dict):
            raise ValueError("key profile %r needs a bindings object" % profile)
        self.mapping = {normalize_key(key): action for key, action in config["bindings"].items()}
        for actions in self.mapping.values():
            if isinstance(actions, str):
                continue
            if (not isinstance(actions, dict) or not actions or set(actions) - {"down", "up"}
                    or any(not isinstance(action, str) or not action.strip()
                           for action in actions.values())):
                raise ValueError("bindings need an action string or down/up action strings")
        self.held = {}
        self.monotonic = getattr(hub, 'monotonic', time.monotonic) if monotonic is None else monotonic

    def snapshot(self):
        return self.hub.input_snapshot() if hasattr(self.hub, 'input_snapshot') else dict(self.hub.rendered_request)

    def snapshot_at(self, received_at):
        return (self.hub.input_snapshot(received_at) if hasattr(self.hub, 'input_snapshot')
                else self.snapshot())

    def __call__(self, event):
        reader = event.get("reader", "USB")
        keylog.debug("Keyboard event entered hub reader=%s keys=%s controls=%s down=%s",
                     reader, event.get("keys", ()),
                     " / ".join(control_name(key) for key in event.get("keys", ())), event.get("down"))
        received_at = event.get('t', self.monotonic())
        if (isinstance(received_at, bool) or not isinstance(received_at, (int, float))
                or not math.isfinite(received_at)):
            return
        shown = dict(event['shown']) if isinstance(event.get('shown'), dict) else self.snapshot()
        if event.get("modifier"):
            return
        # Releases may have no pressed keys, different modifiers or an aged
        # timestamp. An accepted voice press must still be stopped in each case.
        physical = event.get("usage")
        if physical is None:
            keys = event.get("keys", ())
            physical = normalize_key(keys[-1]).split("+")[-1] if keys else None
        if not event.get("down"):
            held = self.held.pop(physical, None)
            if held is not None:
                binding, action = held
                if action == "voice_up" or 0 <= self.monotonic() - event.get("t", float("-inf")) <= 1.0:
                    self._dispatch(binding, action, shown, received_at, reader)
            return
        if not 0 <= self.monotonic() - event.get("t", float("-inf")) <= 1.0:
            return
        if len(event.get("pressed", ())) != 1:
            return
        if physical in self.held:
            return
        for key in event.get("keys", ()):
            binding = normalize_key(key)
            actions = self.mapping.get(binding)
            if actions is None:
                continue
            modifiers = tuple(binding.split("+")[:-1])
            if tuple(event.get("modifiers", ())) != modifiers:
                continue
            if modifiers and tuple(event.get("new_modifiers", ())) != modifiers:
                continue
            if not self.detents.accept(binding, received_at):
                return
            action = actions.get("down") if isinstance(actions, dict) else actions
            if action is None or self._dispatch(binding, action, shown, received_at, reader):
                if isinstance(actions, dict) and "up" in actions:
                    self.held[physical] = (binding, actions["up"])
            return

    def _dispatch(self, binding, action, shown, received_at, reader="USB"):
        try:
            if reader == "Raw Input" and action.split()[0] in RAW_INPUT_BLOCKED:
                # The key has already typed its letter into the focused window.
                raise HubError("keys leak into the window under Raw Input; install WinUSB", 409)
            payload = {"action": action}
            if action in ("approve", "deny"):
                payload.update(shown)
            elif action == "interrupt":
                payload["request_id"] = shown["request_id"]
            result = self.hub.action(payload, source="key", received_at=received_at)
            keylog.debug("Keyboard action reader=%s binding=%s control=%s action=%s result=%s",
                         reader, binding, control_name(binding), action, result)
            log.info("%s %s (%s) -> %s", reader, binding, control_name(binding), result)
            if not isinstance(result, dict) or result.get("status") != "ignored":
                self._note(binding, action, result=result)
            return True
        except (HubError, ValueError) as error:
            keylog.debug("Keyboard action reader=%s binding=%s control=%s action=%s result=blocked: %s",
                         reader, binding, control_name(binding), action, error)
            log.warning("%s %s (%s; %s) %s blocked: %s",
                        reader, binding, binding_label(binding), control_name(binding), action, error)
            self._note(binding, action, error=error)
            return False

    def _note(self, binding, action, result=None, error=None):
        """A key press must never look dead: publish its result to the displays."""
        note = getattr(self.hub, "note_input", None)
        if not callable(note):
            return
        try:
            if isinstance(self.hub, Hub):
                self.hub.note_action(action, result, error, control_name(binding))
            else:
                text, ok, lcd = describe_input(action, result, error)
                note(control_name(binding) + " → " + text, ok, lcd)
        except Exception as failure:
            log.debug("Key feedback unavailable: %s", failure)


def parse_backends(value):
    """Accept one or more input backends without starting any native readers."""
    names = tuple(name.strip().lower() for name in value.split(","))
    if (not names or any(name not in ("none", "usb", "hotkey") for name in names)
            or len(set(names)) != len(names) or ("none" in names and len(names) != 1)):
        raise argparse.ArgumentTypeError("use none, usb, hotkey, or usb,hotkey")
    return names


def main(argv=None, *, ui_factory=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("doctor",))
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--approve-timeout", type=float, default=APPROVE_TIMEOUT)
    parser.add_argument("--hold-mode", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--backend", type=parse_backends, default="none",
                        help="comma-separated inputs: usb,hotkey; default: none (HTTP only)")
    parser.add_argument("--overlay", action="store_true", help="show the floating six-session panel")
    parser.add_argument('--require-nonce', action='store_true', default=None,
                        help='reject approve actions without a request nonce')
    parser.add_argument("--home", type=Path)
    parser.add_argument("--no-lcd", action="store_true", help="disable serial output and LCD focus/hold files")
    parser.add_argument("--no-desktop", action="store_true", help="disable window focus and native input effects")
    parser.add_argument("--keys", type=Path, default=Path(__file__).with_name("hub_keys.json"))
    parser.add_argument("--profile", default="default", help="named key profile in --keys (for example v2_emulation)")
    parser.add_argument("--prompts", type=Path, default=Path(__file__).with_name("hub_prompts.json"))
    parser.add_argument("--risk-rules", type=Path, help="JSON list of high-risk regexes")
    parser.add_argument("--critical-rules", type=Path, help="JSON list of critical-risk regexes")
    parser.add_argument("--config", type=Path, help="Hub JSON config (default: ~/.agentdeck/config.json if present)")
    parser.add_argument("--gate-mode", choices=("high", "low", "off"), help="override config gate_mode")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        from hub_doctor import doctor
        return doctor(port=args.port, home=args.home)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    # Validate input maps before opening listeners or starting any reader.
    mapping = load_json(args.keys) if args.backend != ("none",) else None
    from hub_desktop import DesktopEffects
    home = Path.home() if args.home is None else args.home
    config_path = args.config or home / ".agentdeck" / "config.json"
    config = load_json(config_path) if args.config or config_path.exists() else {}
    if not isinstance(config, dict):
        raise ValueError("Hub config must be a JSON object")
    options = {name: config[name] for name in ("gate_mode", "production_hosts", "protected_branches", "mcp_write_tools", "require_nonce")
               if name in config}
    if args.gate_mode is not None:
        options["gate_mode"] = args.gate_mode
    if args.require_nonce is not None:
        options['require_nonce'] = args.require_nonce
    desktop_options = {"shots_dir": home / ".agentdeck" / "shots"}
    desktop_options["dictation_shortcut"] = config.get("dictation_shortcut")
    if "window_switch_release_ms" in config:
        desktop_options["window_switch_release_ms"] = config["window_switch_release_ms"]
    hub = Hub(approve_timeout=args.approve_timeout, prompts=load_json(args.prompts),
              risk_rules=load_json(args.risk_rules) if args.risk_rules else None,
              critical_rules=load_json(args.critical_rules) if args.critical_rules else None,
              home=home, lcd_enabled=not args.no_lcd, desktop_enabled=not args.no_desktop,
              hold_mode=args.hold_mode, sessions_path=home / ".agentdeck" / "sessions.json",
              desktop=None if args.no_desktop else DesktopEffects(**desktop_options), **options)
    server = overlay = http_thread = maintenance = marker = None
    readers = []
    stopped = threading.Event()
    server_errors = []
    from hub_watchdog import Watchdog
    watchdog = Watchdog()

    def maintain():
        while not stopped.wait(0.2):
            hub.maintain()

    def run_input(reader):
        watched = callable(getattr(reader, "heartbeat", None))
        if watched:
            watchdog.watch("keyboard")
        try:
            reader.run()
        except Exception:
            log.exception("Hub input stopped")
        finally:
            if watched:
                watchdog.unwatch("keyboard")

    def serve():
        try:
            server.serve_forever(poll_interval=0.2)
        except Exception as error:
            server_errors.append(error)
        finally:
            overlay.stop()

    try:
        if "usb" in args.backend:
            from hub_keyboard import KeyboardInput
            keyboard = KeyboardInput(USBKeys(hub, mapping, profile=args.profile,
                                            knob_divider=config.get("knob_divider")), monotonic=hub.monotonic)
            keyboard.heartbeat = lambda: watchdog.beat("keyboard")
            hub.input_reader = getattr(keyboard, "reader_mode", None)
            readers.append((keyboard, "AgentDeck USB"))
        if "hotkey" in args.backend:
            from hub_hotkey import HotkeyInput
            readers.append((HotkeyInput(hub, mapping), "AgentDeck hotkeys"))
        server = HubServer(hub, load_token(args.home), args.port)
        marker = write_hub_marker(args.home, getattr(server, "server_port", None))
        if args.overlay:
            from hub_overlay import Overlay
            overlay = (ui_factory or Overlay)(hub)
            target = getattr(overlay, "overlay", overlay)
            target.heartbeat = lambda: watchdog.beat("UI")
        watchdog.start()
        maintenance = threading.Thread(target=maintain, name="AgentDeck LCD hold", daemon=True)
        maintenance.start()
        for index, (reader, name) in enumerate(readers):
            thread = threading.Thread(target=run_input, args=(reader,), name=name, daemon=True)
            readers[index] = (reader, thread)
            thread.start()
        log.info("Hub listening on %s:%s (%s)", HOST, server.server_port, ",".join(args.backend))
        if overlay is None:
            server.serve_forever(poll_interval=0.2)
        else:
            # Tk owns the main thread; HTTP and native input keep running independently.
            http_thread = threading.Thread(target=serve, name="AgentDeck HTTP", daemon=True)
            http_thread.start()
            wake = getattr(target, "wake", None)
            watchdog.watch("UI", wake=wake if callable(wake) else None)
            overlay.run()
            if server_errors:
                raise server_errors[0]
    except KeyboardInterrupt:
        pass
    finally:
        watchdog.unwatch("UI")
        watchdog.stop()
        stopped.set()
        if overlay is not None:
            overlay.stop()
        if http_thread is not None and http_thread.is_alive():
            server.shutdown()
        for reader, _ in readers:
            reader.stop()
        for _, thread in readers:
            if isinstance(thread, threading.Thread) and thread.ident is not None:
                thread.join(timeout=3)
        hub.close()
        remove_hub_marker(marker)
        if server is not None:
            server.server_close()
        if maintenance is not None:
            maintenance.join(timeout=2)
        if http_thread is not None:
            http_thread.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
