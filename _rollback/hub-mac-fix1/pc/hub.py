"""AgentDeck Hub: local hook decisions and shared HTTP, USB and desktop actions.

Run ``python pc/hub.py --backend none``; see hub_README.md for setup.
No device, window, or user configuration is accessed just by importing this file.
"""
import argparse
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import math
from pathlib import Path
from queue import Empty, SimpleQueue
import re
import secrets
import shlex
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid

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
GATE_CONFIRMED_SECONDS = 30.0
VOICE_NOTICE_SECONDS = 5.0
MAX_BODY = 1024 * 1024
EVENT_STATES = {
    "SessionStart": "idle", "UserPromptSubmit": "think", "PreToolUse": "tool",
    "PostToolUse": "think", "PostToolUseFailure": "error", "Stop": "done",
    "Interrupt": "idle",
}
EVENTS = set(EVENT_STATES) | {"PermissionRequest", "Notification", "SessionEnd"}
log = logging.getLogger("agentdeck.hub")

from hub_risk import (  # noqa: F401  (re-exported: hub.classify stays public)
    AUTHORIZED_KEYS, CRITICAL_RULES, KEY_PATH, RISK_RULES, SENSITIVE_PATH, SHELL_WRITE,
    WRITE_TOOL, _production_ssh, classify)


def tool_input_hash(tool_input):
    return hashlib.sha256(json.dumps(tool_input, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


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

    def public(self):
        return {"id": self.id, "agent": self.session[0], "session_id": self.session[1],
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
                 lcd_enabled=True, desktop_enabled=True, gate_mode="high",
                 production_hosts=(), protected_branches=PROTECTED_BRANCHES, mcp_write_tools=()):
        if not math.isfinite(approve_timeout) or approve_timeout <= 0:
            raise ValueError("approve timeout must be positive and finite")
        self.approve_timeout = approve_timeout
        if gate_mode not in ("high", "low", "off"):
            raise ValueError("gate_mode must be high, low, or off")
        self.gate_mode = gate_mode
        for name, values in (("production_hosts", production_hosts),
                             ("protected_branches", protected_branches), ("mcp_write_tools", mcp_write_tools)):
            if not isinstance(values, (list, tuple)) or any(not isinstance(value, str) or not value for value in values):
                raise ValueError(name + " must be a list of nonempty strings")
            setattr(self, name, tuple(values))
        self.sender = agent_lcd.send if sender is None else sender
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
        self.audit = AuditLog(token_file(home).with_name("audit.jsonl")) if audit is None else audit
        self.prompts = load_json(Path(__file__).with_name("hub_prompts.json")) if prompts is None else prompts
        self.lock = threading.RLock()
        self.sessions = {}
        self.pending = {}
        self.gate_passed = {}
        self.locked = {}
        self.agents_seen = {"cc": None, "cx": None}
        self.selected = None
        self.displayed_request_id = None
        self.last_focus = float("-inf")
        self.closed = False
        self.voice_events = SimpleQueue()
        self.voice_generation = 0
        self.voice_target = None
        self.voice_notice = None

    def _send(self, lines, focus=False):
        if not self.lcd_enabled:
            return
        try:
            if focus:
                with self.focus_guard(timeout=1.0):
                    self.hold_path.touch()
                    self.sender(lines, retry_for=0.0)
                    self.last_focus = self.monotonic()
            else:
                self.sender(lines, retry_for=0.0)
        except Exception as error:
            log.warning("LCD unavailable: %s", error)
            # A missing LCD must not cause a tight serial retry loop.
            self.last_focus = self.monotonic()

    def _show(self):
        session = self.sessions.get(self.selected)
        if session is None:
            self._send(["focus -"], focus=True)
            return
        name = self._display_name(session)
        state = "wait" if session["state"] == "locked" else session["state"]
        self._send(["set %s %s %s" % (session["key"], state, name),
                    "focus " + session["key"]], focus=True)

    def _displayed(self):
        return self.pending.get(self.displayed_request_id) or self.locked.get(self.displayed_request_id)

    def _display_name(self, session):
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
        if changed:
            self._show()

    def _publish(self, session):
        state = "wait" if session["state"] == "locked" else session["state"]
        self._send(["set %s %s %s" % (session["key"], state, self._display_name(session))])

    def _next_request(self):
        self.displayed_request_id = next(iter(self.pending), None) or next(iter(self.locked), None)
        request = self._displayed()
        if request is not None:
            self.selected = request.session
        self._show()

    def _audit(self, request, decision, source):
        try:
            self.audit.append({"timestamp": self.wall_time(), "agent": request.session[0],
                               "session_id": request.session[1], "project": request.project,
                               "tool_name": request.tool_name, "command": request.command[:500],
                               "risk": request.risk, "decision": decision, "source": source,
                               "request_id": request.id})
        except (OSError, AuditError) as error:
            log.error("Cannot audit %s for %s: %s", decision, request.id, error)
            if decision in ("allow", "deny"):
                raise HubError("audit unavailable; use terminal approval", 503) from error

    def _resolve(self, request, behavior=None, source="timeout"):
        self._audit(request, behavior or "timeout", "gate" if request.gate else source)
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
            session["state"] = ("locked" if locked and not remaining else "wait" if remaining or (behavior is None and not request.gate)
                                else "tool" if behavior == "allow" else "idle")
            session["last_updated"] = self.wall_time()
            self._publish(session)
        request.ready.set()
        if self.displayed_request_id == request.id:
            self._next_request()

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

    def event(self, agent, event, *, gate=False):
        """Handle a hook; permission and intercepted gate requests wait outside the lock."""
        if agent not in ("cc", "cx") or not isinstance(event, dict):
            raise HubError("agent must be cc or cx; event must be an object")
        name = event.get("hook_event_name")
        sid = event.get("session_id") or event.get("thread_id") or event.get("conversation_id")
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
        if gate and (self.gate_mode == "off" or (self.gate_mode == "high" and risk == "low")):
            return {}
        with self.lock:
            if self.closed:
                return gate_denial("hub is shutting down") if gate else {}
            self._update_voice()
            self.agents_seen[agent] = self.wall_time()
            self._expire()
            cleared_display = False
            if name not in ("PermissionRequest", "Notification"):
                for request in list(self.locked.values()):
                    if request.session == identity:
                        self.locked.pop(request.id)
                        if self.displayed_request_id == request.id:
                            self.displayed_request_id = None
                            cleared_display = True
            if name == "SessionEnd":
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
                    self._send(["end " + removed["key"]])
                if self.selected == identity:
                    self.selected = next(iter(self.sessions), None)
                    self._next_request()
                return {}
            if identity not in self.sessions:
                used = {s["slot"] for s in self.sessions.values()}
                slot = next((i for i in range(1, 7) if i not in used), None)
                if slot is None:
                    raise HubError("all six session slots are occupied", 409)
                self.sessions[identity] = {"agent": agent, "session_id": sid, "key": key,
                                           "cwd": "", "name": "agent", "project": "agent",
                                           "state": "idle", "slot": slot}
            session = self.sessions[identity]
            cwd = event.get("cwd", session["cwd"])
            session.update(cwd=cwd, name=agent_lcd.ascii_name(cwd),
                           project=agent_lcd.ascii_name(cwd), last_updated=self.wall_time())
            if self.selected is None:
                self.selected = identity
            if name == "PermissionRequest" or gate:
                summary = (tool_input.get("command") or tool_input.get("description") or
                           tool_input.get("file_path") or tool_input.get("path")) if isinstance(tool_input, dict) else tool_input
                if not isinstance(summary, str):
                    summary = json.dumps(tool_input, ensure_ascii=False)
                request = Pending(uuid.uuid4().hex, identity, tool_name,
                                  " ".join(summary.split())[:240],
                                  risk,
                                  self.wall_time(), self.monotonic() + self.approve_timeout,
                                  command=summary, project=session["project"], gate=gate,
                                  input_hash=tool_input_hash(tool_input))
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
                if name in ("Stop", "Interrupt"):
                    for request in list(self.pending.values()):
                        if request.session == identity:
                            self._resolve(request)
                state = EVENT_STATES.get(name)
                if name == "Notification":
                    kind = event.get("notification_type", "")
                    message = str(event.get("message") or "").lower()
                    if kind in agent_lcd.WAIT_NOTIFICATIONS or (not kind and "permission" in message):
                        state = "wait"
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
        request.ready.wait(max(0, request.deadline - self.monotonic()))
        with self.lock:
            if request.id in self.pending:
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
            return {"sessions": sessions, "pending": [p.public() for p in self.pending.values()],
                    "locked": [p.public() for p in self.locked.values()],
                    "agents_seen": dict(self.agents_seen),
                    "displayed_request_id": self.displayed_request_id,
                    "selected_slot": selected["slot"] if selected else None}

    def action(self, payload, source="http"):
        """The single action path used by both HTTP and the physical device."""
        if not isinstance(payload, dict) or not isinstance(payload.get("action"), str):
            raise HubError("action must be a string")
        parts = payload["action"].strip().split(maxsplit=1)
        if not parts:
            raise HubError("action must not be empty")
        command = parts[0]
        argument = parts[1] if len(parts) == 2 else None
        if command not in ("slot", "cycle", "approve", "deny", "interrupt", "voice", "voice_down", "voice_up", "screenshot", "prompt"):
            raise HubError("unknown action")
        if command not in ("slot", "cycle", "prompt") and argument is not None:
            raise HubError("unexpected action argument")
        with self.lock:
            if self.closed:
                raise HubError("hub is shutting down", 503)
            self._update_voice()
            self._expire()
            if command == "voice_up":
                try:
                    if self.desktop is not None:
                        if self.desktop.voice_up() is False:
                            return {"action": command, "status": "unavailable"}
                except Exception as error:
                    raise HubError(str(error), 409) from error
                finally:
                    self._update_voice()
                return {"action": command, "status": "sent"}
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
                if expected is not None and (request is None or request.id != expected):
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
                            self._show()
                            return dict(result, status="confirm", message="GATE! press again" if request.gate else "HOLD! press again")
                    self._resolve(request, "allow" if command == "approve" else "deny", source)
                    return dict(result, status="allowed" if command == "approve" else "denied")
                if command != "interrupt":
                    return {"action": command, "request_id": None, "status": "no_request"}
                if voice_active:
                    raise HubError("release voice before sending input", 409)
            if command in ("slot", "cycle"):
                raw = argument if argument is not None else payload.get("slot" if command == "slot" else "delta")
                if isinstance(raw, bool) or not isinstance(raw, (str, int)):
                    raise HubError("slot/cycle needs an integer")
                try:
                    number = int(raw)
                except ValueError as error:
                    raise HubError("slot/cycle needs an integer") from error
                sessions = sorted(self.sessions.items(), key=lambda pair: pair[1]["slot"])
                if command == "slot":
                    selected = next((identity for identity, s in sessions if s["slot"] == number), None)
                else:
                    if number == 0:
                        raise HubError("cycle delta must not be zero")
                    identities = [identity for identity, _ in sessions]
                    index = identities.index(self.selected) if self.selected in identities else (-1 if number > 0 else 0)
                    selected = identities[(index + number) % len(identities)] if identities else None
                if selected is None:
                    raise HubError("no session in that slot", 404)
                previous = self.pending.get(self.displayed_request_id)
                if previous is not None:
                    previous.armed_at = None
                self.selected = selected
                self.displayed_request_id = next((p.id for p in self.pending.values() if p.session == selected), None) or next(
                    (p.id for p in self.locked.values() if p.session == selected), None)
                self._show()
                session = self.sessions[selected]
                try:
                    focused = self._desktop().focus(session, list(self.sessions.values()))
                    window = "window focus unavailable" if focused is False else "focused"
                except Exception as error:
                    log.warning("Window focus unavailable: %s", error)
                    window = str(error)
                return {"action": command, "status": "selected", "slot": session["slot"],
                        "request_id": self.displayed_request_id, "window": window}
            session = self.sessions.get(self.selected)
            if session is None:
                raise HubError("select a session first", 409)
            desktop = self._desktop()
            sessions = list(self.sessions.values())
            try:
                completed = None
                if command == "prompt":
                    template = argument if argument is not None else payload.get("name")
                    if not isinstance(template, str) or not isinstance(self.prompts.get(template), str):
                        raise HubError("unknown prompt template")
                    completed = desktop.prompt(session, sessions, self.prompts[template])
                elif command == "screenshot":
                    path = desktop.screenshot(session, sessions)
                    if path is False:
                        return {"action": command, "status": "unavailable"}
                    return {"action": command, "status": "sent", "path": path}
                elif command in ("voice", "voice_down"):
                    self.voice_notice = None
                    self.voice_generation += 1
                    generation = self.voice_generation
                    self.voice_target = self.selected
                    for request in self.pending.values():
                        request.armed_at = None
                    completed = desktop.voice_down(session, sessions,
                                                   on_stop=lambda result: self.voice_events.put((generation, result)))
                    self._show()
                    if command == "voice" and completed is not False:
                        completed = desktop.voice_up()
                else:
                    completed = getattr(desktop, command)(session, sessions)
                if completed is False:
                    return {"action": command, "status": "unavailable"}
            except HubError:
                raise
            except Exception as error:
                log.warning("Desktop action failed: %s", error)
                raise HubError(str(error), 409) from error
            finally:
                if command in ("voice", "voice_down"):
                    self._update_voice()
                    if not desktop.voice_active:
                        self.voice_target = None
            return {"action": command, "status": "sent"}

    def _desktop(self):
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
            if self.lcd_enabled and self.selected is not None and self.monotonic() - self.last_focus >= daemon.HEARTBEAT:
                self._show()

    def close(self):
        with self.lock:
            self.closed = True
            if self.desktop is not None:
                try:
                    self.desktop.close()
                except Exception as error:
                    log.warning("Voice shutdown failed: %s", error)
            for request in list(self.pending.values()):
                self._resolve(request)
            self.locked.clear()
            self.displayed_request_id = None


class HubServer(ThreadingHTTPServer):
    daemon_threads = True

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
            raise HubError("JSON body required (maximum 1 MiB)")
        try:
            body = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeError) as error:
            raise HubError("invalid JSON") from error
        if not isinstance(body, dict):
            raise HubError("JSON body must be an object")
        return body

    def _handle(self):
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
                result = self.server.hub.event(agents[0], self._body(), gate=bool(gates))
            elif self.command == "POST" and route.path == "/action":
                result = self.server.hub.action(self._body())
            else:
                self._reply(404, {"error": "unknown endpoint or method"})
                return
            self._reply(200, result)
        except HubError as error:
            self._reply(error.status, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            log.debug("Hook client disconnected")
        except Exception:
            log.exception("Hub request failed")
            self._reply(500, {"error": "hub request failed"})

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = do_TRACE = do_CONNECT = _handle


class USBKeys:
    """Dispatch bindings and pair releases with the accepted physical press."""

    def __init__(self, hub, mapping=None, monotonic=None, profile="default"):
        self.hub = hub
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
        self.monotonic = time.monotonic if monotonic is None else monotonic

    def __call__(self, event):
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
                    self._dispatch(binding, action)
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
            action = actions.get("down") if isinstance(actions, dict) else actions
            if action is None or self._dispatch(binding, action):
                if isinstance(actions, dict) and "up" in actions:
                    self.held[physical] = (binding, actions["up"])
            return

    def _dispatch(self, binding, action):
        try:
            payload = {"action": action}
            if action in ("approve", "deny", "interrupt"):
                # Bind this transition before dispatch so a changed display
                # cannot silently retarget a previously observed request.
                with self.hub.lock:
                    payload["request_id"] = self.hub.displayed_request_id
                    result = self.hub.action(payload, source="key")
            else:
                result = self.hub.action(payload, source="key")
            log.info("USB %s -> %s", binding, result)
            return True
        except (HubError, ValueError) as error:
            log.warning("USB action failed: %s", error)
            return False


def parse_backends(value):
    """Accept one or more input backends without starting any native readers."""
    names = tuple(name.strip().lower() for name in value.split(","))
    if (not names or any(name not in ("none", "usb", "hotkey") for name in names)
            or len(set(names)) != len(names) or ("none" in names and len(names) != 1)):
        raise argparse.ArgumentTypeError("use none, usb, hotkey, or usb,hotkey")
    return names


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("doctor",))
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--approve-timeout", type=float, default=APPROVE_TIMEOUT)
    parser.add_argument("--backend", type=parse_backends, default="none",
                        help="comma-separated inputs: usb,hotkey; default: none (HTTP only)")
    parser.add_argument("--overlay", action="store_true", help="show the floating six-session panel")
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
    options = {name: config[name] for name in ("gate_mode", "production_hosts", "protected_branches", "mcp_write_tools")
               if name in config}
    if args.gate_mode is not None:
        options["gate_mode"] = args.gate_mode
    desktop_options = {"shots_dir": home / ".agentdeck" / "shots"}
    if sys.platform == "darwin":
        desktop_options["dictation_shortcut"] = config.get("dictation_shortcut")
    hub = Hub(approve_timeout=args.approve_timeout, prompts=load_json(args.prompts),
              risk_rules=load_json(args.risk_rules) if args.risk_rules else None,
              critical_rules=load_json(args.critical_rules) if args.critical_rules else None,
              home=home, lcd_enabled=not args.no_lcd, desktop_enabled=not args.no_desktop,
              desktop=None if args.no_desktop else DesktopEffects(**desktop_options), **options)
    server = overlay = http_thread = maintenance = None
    readers = []
    stopped = threading.Event()
    server_errors = []

    def maintain():
        while not stopped.wait(0.2):
            hub.maintain()

    def run_input(reader):
        try:
            reader.run()
        except Exception:
            log.exception("Hub input stopped")

    def serve():
        try:
            server.serve_forever(poll_interval=0.2)
        except Exception as error:
            server_errors.append(error)
        finally:
            overlay.stop()

    try:
        if "usb" in args.backend:
            from deck_usb import USBInput
            readers.append((USBInput(USBKeys(hub, mapping, profile=args.profile)), "AgentDeck USB"))
        if "hotkey" in args.backend:
            from hub_hotkey import HotkeyInput
            readers.append((HotkeyInput(hub, mapping), "AgentDeck hotkeys"))
        server = HubServer(hub, load_token(args.home), args.port)
        if args.overlay:
            from hub_overlay import Overlay
            overlay = Overlay(hub)
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
            overlay.run()
            if server_errors:
                raise server_errors[0]
    except KeyboardInterrupt:
        pass
    finally:
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
        if server is not None:
            server.server_close()
        if maintenance is not None:
            maintenance.join(timeout=2)
        if http_thread is not None:
            http_thread.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
