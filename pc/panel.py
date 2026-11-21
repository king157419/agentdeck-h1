"""Management panel: one-time login, state for the page, key editing.

``HubServer`` hands every ``/panel`` request to ``Panel.handle``. The panel never
sees the hub token: a tray click makes a one-time code that the page trades for an
HttpOnly cookie. Importing this module touches no window, file or registry entry.
"""
import copy
from http.cookies import SimpleCookie
import hmac
import json
import logging
import ntpath
import os
from pathlib import Path
import secrets
import sys
import threading
import time

CODE_SECONDS = 60.0
SESSION_SECONDS = 30 * 24 * 3600.0
MAX_CODE_FAILURES = 5
COOKIE = "agentdeck_panel"
CLAUDE_INTERVAL = 3.0         # how often "open in Claude" is read while the page is polling
POLL_IDLE_SECONDS = 4.0       # no state request for this long means the page is closed or hidden
STATIC = {"": ("panel.html", "text/html; charset=utf-8"), "/": ("panel.html", "text/html; charset=utf-8"),
          "/panel.css": ("panel.css", "text/css; charset=utf-8"),
          "/panel.js": ("panel.js", "text/javascript; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

AGENTS = {"cc": "Claude", "cx": "Codex"}
STATE_TEXT = {"idle": "空闲", "think": "思考中", "tool": "运行中", "wait": "等你批准",
              "locked": "请在终端确认", "error": "出错", "done": "完成"}
LAYERS = ("agent", "chat", "browser", "video", "default")
LAYER_NAMES = {"agent": "Agent", "chat": "聊天", "browser": "浏览器", "video": "视频", "default": "默认"}
# What row 2 (ctx 1..4) and knob 4 (ctx next / prev / select) do in each layer when the
# user has not changed them. Mirrors agentdeck/键位方案-v9.md and DesktopEffects.context.
LAYER_ROW2 = {
    "agent": ("发“继续”", "发“跑测试”", "发“总结”", "到最新"),
    "chat": ("下一个未读", "找人", "填入“收到”", "到最新"),
    "browser": ("后退", "地址栏", "关标签", "刷新"),
    "video": ("播放/暂停", "上一条", "下一条", "全屏"),
    "default": ("后退", "Tab", "关闭", "到底"),
}
LAYER_KNOB4 = {  # clockwise, counterclockwise, press
    "agent": ("下一个选项", "上一个选项", "回车（列表开着时确认）"),
    "chat": ("下一个聊天", "上一个聊天", "回车（列表开着时确认）"),
    "browser": ("下一个标签", "上一个标签", "回车（列表开着时确认）"),
    "video": ("快进 5 秒", "快退 5 秒", "播放/暂停"),
    "default": ("下方向键", "上方向键", "回车（列表开着时确认）"),
}
KNOB_NAMES = ("窗口", "会话", "滚动", "列表")
ACTION_LABELS = {
    "window back": "上个窗口", "window next": "下个窗口", "window prev": "上个窗口",
    "copy": "复制", "paste": "粘贴", "overlay": "浮窗/帮助", "interrupt": "打断", "screenshot": "截图",
    "send": "发送", "clear": "清空输入", "approve": "批准", "deny": "拒绝", "voice": "语音",
    "session next": "下个会话", "session prev": "上个会话", "session select": "选定会话",
    "scroll 1": "向下滚", "scroll -1": "向上滚", "scroll end": "滚到底", "pane next": "下一栏",
    "next_wait": "下个待批", "ctx next": "列表下一个", "ctx prev": "列表上一个", "ctx select": "回车（列表开着时确认）",
    "app claude": "Claude / Codex", "app wechat": "微信", "app feishu": "飞书", "app browser": "浏览器",
    "none": "空",
}
APP_OPTIONS = (("app claude", "Claude / Codex"), ("app wechat", "微信"), ("app feishu", "飞书"),
               ("app browser", "浏览器"))
ACTION_OPTIONS = (("copy", "复制"), ("paste", "粘贴"), ("send", "发送"), ("clear", "清空输入框"),
                  ("interrupt", "打断 / Esc"), ("screenshot", "截图"), ("window back", "上一个窗口"),
                  ("next_wait", "跳到下一个等你的会话"))
KNOB_OPTIONS = (("ctx next", "列表：下一个"), ("ctx prev", "列表：上一个"), ("ctx select", "回车（列表开着时确认）"))
PROMPT_LABELS = ("继续", "跑测试", "总结进度", "提交")


class PanelError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def ui_dir():
    """Panel files: pc/ui from source, <bundle>/ui when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "ui"
    return Path(__file__).resolve().parent / "ui"


class PanelAuth:
    """One-time login codes and the session tokens they are traded for."""

    def __init__(self, monotonic=time.monotonic, *, home=None, wall_time=time.time):
        self.monotonic = monotonic
        self.wall_time = wall_time
        self.home = Path.home() if home is None else Path(home)
        self.record_path = self.home / ".agentdeck" / "panel.json"
        self.lock = threading.Lock()
        self.codes = {}
        self.failures = 0

    def _prune(self, now):
        for key in [key for key, expires in self.codes.items() if expires <= now]:
            del self.codes[key]

    def _signature(self, issued):
        from hub import load_token
        key = hmac.new(load_token(self.home).encode("ascii"), b"agentdeck-panel-v1", "sha256").digest()
        return hmac.new(key, ("panel|" + issued).encode("ascii"), "sha256").hexdigest()

    def _live(self, issued):
        return type(issued) is int and 0 <= self.wall_time() - issued < SESSION_SECONDS

    def new_code(self):
        with self.lock:
            now = self.monotonic()
            self._prune(now)
            code = secrets.token_urlsafe(24)
            self.codes[code] = now + CODE_SECONDS
            return code

    def redeem(self, code):
        """Return a session token for a live code (used up at once), else None."""
        if not isinstance(code, str) or not code or len(code) > 200:
            return None
        with self.lock:
            now = self.monotonic()
            self._prune(now)
            match = next((known for known in self.codes
                          if hmac.compare_digest(known.encode(), code.encode("utf-8", "replace"))), None)
            if match is None:
                self.failures += 1
                if self.failures >= MAX_CODE_FAILURES:
                    self.codes.clear()  # somebody is guessing: every outstanding code dies
                return None
            del self.codes[match]
            self.failures = 0
            issued = int(self.wall_time())
            token = "v1.%d.%s" % (issued, self._signature(str(issued)))
            temporary = self.record_path.with_suffix(".json.tmp")
            try:
                temporary.write_text(json.dumps({"issued_at": issued}) + "\n", encoding="utf-8")
                os.replace(temporary, self.record_path)
            except OSError as error:  # only a launch hint: login still succeeds
                logging.getLogger("agentdeck.panel").warning("panel.json not written: %s", error)
            finally:
                temporary.unlink(missing_ok=True)
            return token

    def check(self, token):
        if not isinstance(token, str) or not token or len(token) > 200:
            return False
        parts = token.split(".")
        if (len(parts) != 3 or parts[0] != "v1" or not parts[1].isascii()
                or not parts[1].isdecimal() or not self._live(int(parts[1]))):
            return False
        try:
            return hmac.compare_digest(self._signature(parts[1]).encode("ascii"), parts[2].encode("utf-8"))
        except (OSError, ValueError, UnicodeError):
            return False

    def has_session(self):
        with self.lock:
            try:
                record = json.loads(self.record_path.read_text(encoding="utf-8"))
                key_stat = self.record_path.with_name("token").stat()
                # The key is read before the atomic record write on login. A newer
                # key means rotation: the tray must open a fresh login window.
                # This is a launch hint; cookie signatures remain authoritative if
                # filesystem timestamps are preserved or have coarse resolution.
                return (isinstance(record, dict) and self._live(record.get("issued_at"))
                        and key_stat.st_mtime_ns <= self.record_path.stat().st_mtime_ns)
            except (OSError, ValueError):
                return False


def first_line(text, limit=200):
    line = next((part.strip() for part in str(text or "").splitlines() if part.strip()), "")
    return line if len(line) <= limit else line[:limit - 1] + "…"


class Panel:
    def __init__(self, hub, *, keys_path=None, shipped_path=None, ui_path=None, monotonic=None,
                 claude_interval=CLAUDE_INTERVAL, idle_seconds=POLL_IDLE_SECONDS):
        self.hub = hub
        self.auth = PanelAuth(monotonic or time.monotonic, home=hub.home, wall_time=hub.wall_time)
        self.monotonic = monotonic or time.monotonic
        self.keys_path = Path(keys_path) if keys_path is not None else None
        self.shipped_path = Path(shipped_path) if shipped_path is not None else Path(__file__).with_name("hub_keys.json")
        self.ui_path = Path(ui_path) if ui_path is not None else None
        self.read_only = False
        self._port = None
        self.edit_lock = threading.Lock()
        self._config = None
        self.claude_interval = claude_interval
        self.idle_seconds = idle_seconds
        self.claude_title = None
        self._last_poll = float("-inf")
        self._watcher = None
        self._watch_lock = threading.Lock()
        self._stop = threading.Event()
        try:
            hub.panel = self
        except AttributeError:
            pass

    # ---- login -------------------------------------------------------------
    def new_login_code(self):
        return self.auth.new_code()

    def login_url(self, code, port):
        return "http://127.0.0.1:%d/panel#code=%s" % (port, code)

    @property
    def port(self):
        return self._port

    def close(self):
        self._stop.set()

    # ---- HTTP --------------------------------------------------------------
    def handle(self, handler, route):
        port = handler.server.server_port
        origin_ok = "http://127.0.0.1:%d" % port
        try:
            self._port = port
            path = route.path[len("/panel"):]
            if handler.headers.get("Host", "") != "127.0.0.1:%d" % port:
                raise PanelError("bad host", 403)
            origin = handler.headers.get("Origin")
            if origin is not None and origin != origin_ok:
                raise PanelError("bad origin", 403)
            if path in STATIC:
                if handler.command != "GET":
                    raise PanelError("method not allowed", 405)
                self._static(handler, *STATIC[path])
                return
            if handler.command == "POST" and path == "/login":
                self._json_request(handler)
                body = handler._body()
                token = self.auth.redeem(body.get("code"))
                if token is None:
                    raise PanelError("invalid or expired code", 401)
                cookie = "%s=%s; HttpOnly; SameSite=Strict; Path=/panel; Max-Age=%d" % (
                    COOKIE, token, int(SESSION_SECONDS))
                self._reply(handler, 200, {"ok": True}, [("Set-Cookie", cookie)])
                return
            if not path.startswith("/api/"):
                raise PanelError("unknown endpoint", 404)
            jar = SimpleCookie()
            try:
                jar.load(handler.headers.get("Cookie", ""))
            except Exception:
                jar = SimpleCookie()
            morsel = jar.get(COOKIE)
            if morsel is None or not self.auth.check(morsel.value):
                raise PanelError("login required", 401)
            if handler.command == "GET" and path == "/api/state":
                self._reply(handler, 200, self.state(touch=True))
            elif handler.command == "POST":
                self._json_request(handler)
                self._reply(handler, 200, self._post(path, handler._body()))
            else:
                raise PanelError("unknown endpoint or method", 404)
        except PanelError as error:
            self._reply(handler, error.status, {"error": str(error)})
        except Exception as error:
            status = getattr(error, "status", None)
            if status is None:
                from hub import log
                log.exception("Panel request failed")
                self._reply(handler, 500, {"error": "panel request failed"})
            else:
                self._reply(handler, status, {"error": str(error)})

    @staticmethod
    def _json_request(handler):
        kind = handler.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if kind != "application/json":
            raise PanelError("JSON required", 415)

    def _post(self, path, body):
        if path == "/api/hold":
            mode = body.get("mode")
            if mode not in ("auto", "always", "never"):
                raise PanelError("mode must be auto, always or never")
            self.hub.action({"action": "hold " + mode}, source="panel")
        elif path == "/api/open":
            self.open_session(body.get("agent"), body.get("session_id"))
        elif path == "/api/decision":
            return {"result": self.decide(body.get("decision"), body.get("request_id"), body.get("nonce")),
                    **self.state()}
        elif path == "/api/key":
            self.edit_key(body.get("id"), body.get("layer"), body.get("action"))
        else:
            raise PanelError("unknown endpoint", 404)
        return self.state()

    def _static(self, handler, name, content_type):
        folder = self.ui_path if self.ui_path is not None else ui_dir()
        try:
            data = (folder / name).read_bytes()
        except OSError:
            raise PanelError("panel files missing", 404)
        self._send(handler, 200, data, content_type, [("Content-Security-Policy", CSP)])

    def _reply(self, handler, status, body, headers=()):
        self._send(handler, status, json.dumps(body, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", headers)

    @staticmethod
    def _send(handler, status, data, content_type, headers=()):
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Referrer-Policy", "no-referrer")
        for name, value in headers:
            handler.send_header(name, value)
        handler.end_headers()
        handler.wfile.write(data)

    # ---- actions -----------------------------------------------------------
    def open_session(self, agent, session_id):
        hub = self.hub
        with hub.lock:
            if (agent, session_id) not in hub.sessions:
                raise PanelError("这个会话已结束", 404)
        result = hub.controls._show_session((agent, session_id))
        if result.get("status") == "error":
            raise PanelError(result.get("message", "打开会话失败"), 409)
        return result

    def decide(self, decision, request_id, nonce):
        """Approve or deny exactly one pending request, through the key path (Hub.action)."""
        hub = self.hub
        if decision not in ("approve", "deny"):
            raise PanelError("decision must be approve or deny")
        with hub.lock:
            request = hub.pending.get(request_id) if isinstance(request_id, str) else None
            if request is None or type(nonce) is not int or nonce != request.nonce:
                raise PanelError("这条请求已经变了，请看最新状态", 409)
            if hub.displayed_request_id != request.id:
                hub._set_displayed(request.id)
            # A click on this very request is deliberate: no key-style switch guard.
            hub.display_switched_at = float("-inf")
        result = hub.action({"action": decision, "request_id": request.id, "nonce": nonce}, source="panel")
        return result.get("status") if isinstance(result, dict) else None

    # ---- state -------------------------------------------------------------
    def _current_config(self):
        usb = getattr(self.hub, "usb_keys", None)
        if usb is not None and isinstance(getattr(usb, "config", None), dict):
            return usb.config
        if self._config is None:
            self._config = self._read_config()
        return self._config

    def _user_path(self):
        if self.keys_path is not None:
            return self.keys_path
        return Path(self.hub.home) / ".agentdeck" / "hub_keys.json"

    def _read_config(self):
        for path in (self._user_path(), self.shipped_path):
            try:
                config = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(config, dict) and isinstance(config.get("bindings"), dict):
                    return config
            except (OSError, ValueError):
                continue
        raise PanelError("找不到键位文件", 500)

    def _layout(self):
        from hub import KEY_ROWS, KNOBS, CONTROL_NAMES, normalize_binding
        rows = []
        for row, keys in enumerate(KEY_ROWS, 1):
            cells = []
            for column, (name, code) in enumerate(keys, 1):
                kind = "app" if row == 1 else "layer" if row == 2 else "fixed"
                cells.append({"id": "r%dc%d" % (row, column), "row": row, "col": column, "name": name,
                              "code": normalize_binding(code), "kind": kind,
                              "position": "第 %d 排第 %d 颗" % (row, column)})
            rows.append(cells)
        knobs = []
        for number, codes in enumerate(KNOBS, 1):
            controls = []
            for tag, direction, code in zip(("cw", "ccw", "press"), ("顺时针", "逆时针", "按下"), codes):
                controls.append({"id": "k%d%s" % (number, tag), "knob": number, "direction": direction,
                                 "code": normalize_binding(code), "kind": "knob_layer" if number == 4 else "fixed",
                                 "position": "旋钮 %d %s" % (number, direction), "shared": CONTROL_NAMES.get(normalize_binding(code), "")})
            knobs.append({"id": "k%d" % number, "number": number, "name": KNOB_NAMES[number - 1], "controls": controls})
        return rows, knobs

    def _controls(self):
        rows, knobs = self._layout()
        return [cell for row in rows for cell in row] + [c for knob in knobs for c in knob["controls"]]

    @staticmethod
    def action_label(action, layer, code, knob4=None):
        if isinstance(action, dict):
            return "语音" if any("voice" in str(v) for v in action.values()) else "按下/松开"
        action = str(action)
        words = action.split()
        if words[:1] == ["ctx"] and len(words) == 2:
            if words[1] in ("1", "2", "3", "4"):
                return LAYER_ROW2.get(layer, LAYER_ROW2["default"])[int(words[1]) - 1]
            if words[1] in ("next", "prev", "select"):
                return LAYER_KNOB4.get(layer, LAYER_KNOB4["default"])[("next", "prev", "select").index(words[1])]
        if words[:1] == ["prompt"] and len(words) == 2:
            return "发“%s”" % words[1]
        if action.startswith("app exe:"):
            name = ntpath.basename(action[8:])
            return name[:-4] if name.lower().endswith(".exe") else name
        if action.startswith("slot "):
            return "会话 " + action[5:]
        return ACTION_LABELS.get(action, action)

    def _bindings(self, config):
        """layer -> code -> {action, label, user}; layered keys carry their own override."""
        from hub import USBKeys
        mapping, layers, _ = USBKeys.parse(config)
        controls = self._controls()
        result = {}
        for layer in LAYERS:
            table = {}
            for control in controls:
                code = control["code"]
                override = layers.get(layer, {}).get(code)
                base = mapping.get(code)
                action = override if override is not None else base
                shipped = self._shipped_action(code)
                entry = {"action": action, "label": "空" if action in (None, "none") else self.action_label(action, layer, code),
                         "user": override is not None or action != shipped, "layered": override is not None,
                         "default_action": shipped if isinstance(shipped, str) else None,
                         "default_label": "空" if base in (None, "none") else self.action_label(shipped if control["kind"] == "app" else base, layer, code)}
                table[code] = entry
            result[layer] = table
        return result

    def _shipped(self):
        try:
            return json.loads(self.shipped_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"bindings": {}}

    def _shipped_action(self, code):
        from hub import normalize_binding
        for key, value in self._shipped().get("bindings", {}).items():
            if normalize_binding(key) == code:
                return value
        return None

    def _prompt_names(self):
        prompts = getattr(self.hub, "prompts", {}) or {}
        names = [name for name in PROMPT_LABELS if name in prompts]
        return names or [name for name in prompts if any(ord(c) > 127 for c in name)]

    def editor(self):
        prompts = [("prompt " + name, "发“%s”" % name) for name in self._prompt_names()]
        return {"app": [{"value": v, "label": l} for v, l in APP_OPTIONS] + [{"value": "app exe:", "label": "自定义程序…", "custom": True},
                                                                              {"value": "none", "label": "空（不做事）"}],
                "layer": [{"value": "default", "label": "默认功能", "group": ""}]
                         + [{"value": v, "label": l, "group": "提示模板"} for v, l in prompts]
                         + [{"value": v, "label": l, "group": "快捷键动作"} for v, l in ACTION_OPTIONS]
                         + [{"value": "none", "label": "空（不做事）", "group": ""}],
                "knob_layer": [{"value": "default", "label": "默认功能"}]
                              + [{"value": v, "label": l} for v, l in KNOB_OPTIONS]
                              + [{"value": "none", "label": "空（不做事）"}]}

    def state(self, touch=False):
        hub = self.hub
        if touch:
            self._touch()
        snapshot = hub.state()
        now = hub.wall_time()
        config = self._current_config()
        rows, knobs = self._layout()
        events = []
        with hub.lock:
            for event in hub.key_events:
                events.append(dict(event, age=max(0.0, now - event["at"])))
        reader = snapshot.get("input_reader")
        sessions = []
        for item in sorted(snapshot["sessions"], key=lambda s: -s.get("last_updated", 0)):
            title = (item.get("title") or item.get("name") or item.get("project") or "未命名会话")
            requests = [r for r in item.get("pending_requests", []) if r.get("status") == "pending"]
            sessions.append({
                "agent": item["agent"], "session_id": item["session_id"], "slot": item.get("slot"),
                "agent_name": AGENTS.get(item["agent"], item["agent"]),
                "title": " ".join(str(title).split()),
                "project": item.get("project") or ntpath.basename(str(item.get("cwd") or "").rstrip("\\/")) or "",
                "state": item.get("state"), "state_text": STATE_TEXT.get(item.get("state"), str(item.get("state"))),
                "ago": max(0, int(now - item.get("last_updated", now))),
                "open": bool(item["agent"] == "cc" and self.claude_title and item.get("title") == self.claude_title),
                "selected": item.get("slot") == snapshot.get("selected_slot"),
                "needs_answer": bool(item.get("needs_answer")),
                "locked": bool(item.get("locked_requests")) or item.get("state") == "locked",
                "request": ({"id": requests[0]["id"], "nonce": requests[0]["nonce"], "tool": requests[0].get("tool_name", ""),
                             "command": first_line(requests[0].get("summary")), "risk": requests[0].get("risk"),
                             "armed": bool(requests[0].get("armed"))} if requests else None)})
        return {
            "now": now,
            "device": {"connected": bool(snapshot.get("deck_connected")), "reader": reader},
            "hold": {"mode": snapshot.get("hold_mode"), "active": bool(snapshot.get("hold_active"))},
            "layer": snapshot.get("layer", "default"),
            "layer_names": LAYER_NAMES,
            "sessions": sessions,
            "layout": {"rows": rows, "knobs": knobs},
            "bindings": self._bindings(config),
            "editor": self.editor(),
            "can_edit": not self.read_only,
            "keys": {"last_seq": hub.key_seq, "events": events},
            "claude_open_title": self.claude_title,
        }

    # ---- "open in Claude" reader ------------------------------------------
    def _touch(self):
        self._last_poll = self.monotonic()
        with self._watch_lock:
            if self._watcher is not None and self._watcher.is_alive():
                return
            if self._stop.is_set():
                return
            self._watcher = threading.Thread(target=self._watch, name="AgentDeck panel claude", daemon=True)
            self._watcher.start()

    def _read_claude(self):
        hub = self.hub
        try:
            desktop = hub._desktop()
            read = getattr(desktop, "current_session_title", None)
            if not callable(read):
                return None
            with hub.lock:
                sessions = [dict(s) for s in hub.sessions.values()]
            title = read(sessions)
            return title if isinstance(title, str) and title else None
        except Exception:
            return None

    def _watch(self):
        """Only while the page keeps polling; stops by itself a few seconds after it closes."""
        while not self._stop.is_set() and self.monotonic() - self._last_poll < self.idle_seconds:
            self.claude_title = self._read_claude()
            self._stop.wait(self.claude_interval)

    # ---- key editing -------------------------------------------------------
    @staticmethod
    def _valid_exe(value):
        path = value[8:]
        return (value.startswith("app exe:") and 5 <= len(path) <= 259 and path.lower().endswith(".exe")
                and ntpath.isabs(path) and not any(ord(c) < 32 or c in '"<>|*?' for c in path))

    def edit_key(self, control_id, layer, value):
        if self.read_only:
            raise PanelError("当前键位方案只读", 403)
        control = next((c for c in self._controls() if c["id"] == control_id), None)
        if control is None:
            raise PanelError("没有这个键", 404)
        if control["kind"] == "fixed":
            raise PanelError("固定键，任何应用里都不变", 403)
        if not isinstance(value, str) or not value.strip():
            raise PanelError("action required")
        value = value.strip()
        layered = control["kind"] in ("layer", "knob_layer")
        if layered and layer not in LAYERS:
            raise PanelError("layer must be one of " + ", ".join(LAYERS))
        allowed = {o["value"] for o in self.editor()[control["kind"]]}
        if value != "default" and value not in allowed and not (
                control["kind"] == "app" and value.startswith("app exe:") and self._valid_exe(value)):
            raise PanelError("这个功能不能放在这颗键上")
        if control["kind"] == "app" and value == "app exe:":
            raise PanelError("请填写 exe 的完整路径")
        from hub import USBKeys, normalize_binding
        with self.edit_lock:
            path = self._user_path()
            try:
                base = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(base, dict):
                    raise ValueError
            except (OSError, ValueError):
                base = self._current_config()
            config = copy.deepcopy(base)
            code = control["code"]

            def put(table, new):
                existing = next((key for key in table if normalize_binding(key) == code), None)
                if new is None:
                    if existing is not None:
                        del table[existing]
                else:
                    table[existing if existing is not None else code_text] = new

            code_text = self._raw_codes()[control_id]
            if layered:
                layers = config.setdefault("layers", {})
                if not isinstance(layers, dict):
                    raise PanelError("键位文件的 layers 格式不对", 500)
                for name in LAYERS:
                    layers.setdefault(name, {})
                put(layers[layer], None if value == "default" else value)
            else:
                put(config.setdefault("bindings", {}), self._shipped_action(code) if value == "default" else value)
            config["user_modified"] = True  # upgrade_keymap never replaces a file the user changed
            USBKeys.parse(config)           # a bad result raises before anything is written
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            try:
                temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            self._config = config
            usb = getattr(self.hub, "usb_keys", None)
            if usb is not None:
                usb.reload(config)

    @staticmethod
    def _raw_codes():
        """control id -> the exact binding text used in the key file."""
        from hub import KEY_ROWS, KNOBS
        table = {}
        for row, keys in enumerate(KEY_ROWS, 1):
            for column, (_, code) in enumerate(keys, 1):
                table["r%dc%d" % (row, column)] = code
        for number, codes in enumerate(KNOBS, 1):
            for tag, code in zip(("cw", "ccw", "press"), codes):
                table["k%d%s" % (number, tag)] = code
        return table
