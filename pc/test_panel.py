"""Management panel: login, cookie/Origin checks, state, key editing, Edge launch.

Only a temporary home and loopback HTTP are real. Desktop, registry, process start
and the browser are fakes, so nothing here types keys or opens a window.
"""
from contextlib import nullcontext
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import agentdeck_app as app
import hub
import panel
import panel_launch


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class Windows:
    def __init__(self, items=()):
        self.items = list(items)
        self.activated = []

    def windows(self):
        return list(self.items)

    def activate(self, hwnd):
        self.activated.append(hwnd)
        return True


class Desktop:
    voice_active = False

    def __init__(self):
        self.calls = []
        self.title = "现状讨论"

    def focus(self, session, sessions):
        self.calls.append(("focus", session["session_id"]))
        return (1, "claude.exe", "x")

    def current_session_title(self, sessions):
        self.calls.append(("title", len(sessions)))
        return self.title

    def close(self):
        pass


class Registry:
    HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER = "HKLM", "HKCU"

    def __init__(self, values):
        self.values = values

    def OpenKey(self, root, path):
        if (root, path) not in self.values:
            raise FileNotFoundError(path)
        return nullcontext((root, path))

    def QueryValueEx(self, key, name):
        return self.values[key], 1


class PanelBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.clock = Clock()
        self.desktop = Desktop()
        self.engine = hub.Hub(sender=lambda *a, **k: None, desktop=self.desktop,
                              focus_guard=lambda **k: nullcontext(), home=self.temp.name,
                              hold_path=self.home / "hold", monotonic=self.clock, approve_timeout=5,
                              hold_mode="always")
        self.addCleanup(self.engine.close)
        self.engine.usb_keys = hub.USBKeys(self.engine, hub.load_json(Path(hub.__file__).with_name("hub_keys.json")))
        self.server = hub.HubServer(self.engine, "test-secret", port=0)
        thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()

        def close():
            self.server.shutdown()
            self.server.server_close()
            thread.join(2)
        self.addCleanup(close)
        self.port = self.server.server_port
        self.panel = self.server.panel

    def request(self, method, path, body=None, headers=None, raw=None, host=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = dict(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"
        if host is not True:
            connection.putrequest(method, path, skip_host=True)
            if host:
                connection.putheader("Host", host)
            for name, value in headers.items():
                connection.putheader(name, value)
            connection.putheader("Content-Length", str(len(data or b"")))
            connection.endheaders(data)
        else:
            connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        text = response.read()
        result = (response.status, response, text)
        connection.close()
        return result

    def login(self):
        status, response, _ = self.request("POST", "/panel/login", {"code": self.panel.new_login_code()})
        self.assertEqual(status, 200)
        return response.getheader("Set-Cookie").split(";")[0]

    def api(self, method, path, body=None, cookie=None, **kw):
        headers = {"Cookie": cookie or self.cookie}
        status, response, text = self.request(method, path, body, headers, **kw)
        return status, json.loads(text) if text else None

    def session(self, sid="s1", title="第一个会话", command=None):
        self.engine.event("cc", dict(hook_event_name="SessionStart", session_id=sid, cwd="C:/work/webip",
                                     session_title=title))
        if command:
            threading.Thread(target=lambda: self.engine.event("cc", dict(
                hook_event_name="PermissionRequest", session_id=sid, cwd="C:/work/webip", tool_name="Bash",
                tool_input={"command": command})), daemon=True).start()
            deadline = time.monotonic() + 2
            while not self.engine.state()["pending"]:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.005)


class AuthTests(unittest.TestCase):
    def test_code_is_one_time_expires_and_wrong_codes_die(self):
        clock = Clock()
        auth = panel.PanelAuth(clock)
        code = auth.new_code()
        token = auth.redeem(code)
        self.assertTrue(token and auth.check(token))
        self.assertIsNone(auth.redeem(code))            # used once
        self.assertIsNone(auth.redeem("wrong"))
        self.assertIsNone(auth.redeem(""))
        late = auth.new_code()
        clock.value += panel.CODE_SECONDS + 1
        self.assertIsNone(auth.redeem(late))            # expired
        self.assertFalse(auth.check("nope"))
        fresh = auth.new_code()
        for _ in range(panel.MAX_CODE_FAILURES):
            auth.redeem("guess")
        self.assertIsNone(auth.redeem(fresh))           # guessing burned every live code


class HTTPTests(PanelBase):
    def test_login_sets_strict_httponly_cookie_and_code_cannot_repeat(self):
        code = self.panel.new_login_code()
        status, response, _ = self.request("POST", "/panel/login", {"code": code})
        self.assertEqual(status, 200)
        cookie = response.getheader("Set-Cookie")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Path=/panel", cookie)
        self.assertNotIn(code, cookie)
        self.assertEqual(self.request("POST", "/panel/login", {"code": code})[0], 401)
        self.assertEqual(self.request("POST", "/panel/login", {"code": "bad"})[0], 401)
        clock = Clock()
        self.panel.auth.monotonic = clock
        expired = self.panel.new_login_code()
        clock.value += 61
        self.assertEqual(self.request("POST", "/panel/login", {"code": expired})[0], 401)

    def test_login_url_keeps_code_in_fragment(self):
        url = self.panel.login_url("abc", self.port)
        self.assertEqual(url, "http://127.0.0.1:%d/panel#code=abc" % self.port)

    def test_api_needs_cookie_matching_origin_host_and_json(self):
        self.cookie = self.login()
        self.assertEqual(self.request("GET", "/panel/api/state")[0], 401)
        self.assertEqual(self.request("GET", "/panel/api/state", headers={"Cookie": "agentdeck_panel=forged"})[0], 401)
        self.assertEqual(self.api("GET", "/panel/api/state")[0], 200)
        good = "http://127.0.0.1:%d" % self.port
        self.assertEqual(self.request("GET", "/panel/api/state", headers={"Cookie": self.cookie, "Origin": good})[0], 200)
        self.assertEqual(self.request("GET", "/panel/api/state",
                                      headers={"Cookie": self.cookie, "Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/panel/api/state", headers={"Cookie": self.cookie},
                                      host="evil.example")[0], 403)
        self.assertEqual(self.request("POST", "/panel/api/hold", raw=b'{"mode":"never"}',
                                      headers={"Cookie": self.cookie, "Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", "/panel/api/hold", {"mode": "never"},
                                      headers={"Cookie": self.cookie, "Origin": "null"})[0], 403)
        self.assertEqual(self.engine.hold_mode, "always")   # nothing above got through
        self.assertEqual(self.api("POST", "/panel/api/hold", {"mode": "never"})[0], 200)
        self.assertEqual(self.engine.hold_mode, "never")
        self.assertEqual(self.api("POST", "/panel/api/hold", {"mode": "x"})[0], 400)

    def test_token_routes_are_unchanged(self):
        self.assertEqual(self.request("GET", "/health")[0], 200)
        self.assertEqual(self.request("GET", "/state")[0], 401)
        status, _, text = self.request("GET", "/state", headers={"X-AgentDeck-Token": "test-secret"})
        self.assertEqual(status, 200)
        self.assertIn("sessions", json.loads(text))
        self.cookie = self.login()
        self.assertEqual(self.request("GET", "/state", headers={"Cookie": self.cookie})[0], 401)  # cookie is no token

    def test_page_files_are_served_without_login_and_list_is_closed(self):
        for path, kind in (("/panel", "text/html"), ("/panel/", "text/html"), ("/panel/panel.css", "text/css"),
                           ("/panel/panel.js", "javascript")):
            status, response, text = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertIn(kind, response.getheader("Content-Type"))
            self.assertTrue(text)
        _, response, text = self.request("GET", "/panel")
        self.assertIn("script-src 'self'", response.getheader("Content-Security-Policy"))
        self.assertIn("<title>AgentDeck</title>", text.decode())
        self.assertEqual(self.request("GET", "/panel/../hub.py")[0], 404)
        self.assertEqual(self.request("GET", "/panel/hub.py")[0], 404)
        self.assertEqual(self.request("POST", "/panel/panel.js", {})[0], 405)

    def test_state_structure_sessions_and_claude_marker(self):
        self.session("s1", "第一个会话")
        self.session("s2", "现状讨论")
        self.panel.claude_interval = 0.01
        self.cookie = self.login()
        deadline = time.monotonic() + 2
        while True:
            status, state = self.api("GET", "/panel/api/state")
            if state["claude_open_title"] or time.monotonic() > deadline:
                break
            time.sleep(0.02)
        self.assertEqual(status, 200)
        for key in ("device", "hold", "layer", "sessions", "layout", "bindings", "editor", "keys", "can_edit"):
            self.assertIn(key, state)
        self.assertEqual(state["hold"]["mode"], "always")
        self.assertEqual(len(state["layout"]["rows"]), 5)
        self.assertTrue(all(len(row) == 4 for row in state["layout"]["rows"]))
        self.assertEqual(len(state["layout"]["knobs"]), 4)
        self.assertEqual(set(state["bindings"]), set(panel.LAYERS))
        by_title = {s["title"]: s for s in state["sessions"]}
        self.assertTrue(by_title["现状讨论"]["open"])
        self.assertFalse(by_title["第一个会话"]["open"])
        self.assertEqual(by_title["第一个会话"]["project"], "webip")
        self.assertEqual(by_title["第一个会话"]["agent_name"], "Claude")
        agent_labels = [state["bindings"]["agent"][c["code"]]["label"] for c in state["layout"]["rows"][1]]
        self.assertEqual(agent_labels, ["发“继续”", "发“跑测试”", "发“总结”", "到最新"])
        browser_labels = [state["bindings"]["browser"][c["code"]]["label"] for c in state["layout"]["rows"][1]]
        self.assertEqual(browser_labels, ["后退", "地址栏", "关标签", "刷新"])
        self.assertEqual(state["bindings"]["default"][state["layout"]["rows"][0][0]["code"]]["label"], "Claude / Codex")
        self.assertEqual(state["bindings"]["default"][state["layout"]["rows"][4][0]["code"]]["label"], "批准")

    def test_claude_reader_runs_only_while_page_polls(self):
        self.session("s1", "现状讨论")
        self.panel.claude_interval, self.panel.idle_seconds = 0.01, 0.15
        self.cookie = self.login()
        time.sleep(0.2)
        self.assertEqual([c for c in self.desktop.calls if c[0] == "title"], [])  # never polled: never read
        self.api("GET", "/panel/api/state")
        time.sleep(0.1)
        self.assertTrue(any(c[0] == "title" for c in self.desktop.calls))
        time.sleep(0.4)
        before = len(self.desktop.calls)
        time.sleep(0.2)
        self.assertEqual(len(self.desktop.calls), before)
        self.assertFalse(self.panel._watcher.is_alive())

    def test_key_buffer_has_increasing_sequence_and_result_kinds(self):
        self.cookie = self.login()
        self.engine.note_key("ctrl+hid:0x09", "ctx 2", {"status": "sent"})
        self.engine.note_key("hid:0x0A", "ctx 1", {"status": "noop", "noop": "没东西可做"})
        self.engine.note_key("hid:0x2B", "approve", error=hub.HubError("boom"))
        _, state = self.api("GET", "/panel/api/state")
        events = state["keys"]["events"]
        self.assertEqual([e["seq"] for e in events], [1, 2, 3])
        self.assertEqual(state["keys"]["last_seq"], 3)
        self.assertEqual([e["kind"] for e in events], ["success", "noop", "error"])
        self.assertEqual(events[0]["position"], "第 2 排第 2 颗")
        self.assertEqual(events[1]["text"], "没东西可做")
        self.assertIn("age", events[0])

    def test_physical_press_reaches_buffer_through_usbkeys(self):
        usb = self.engine.usb_keys
        usb._dispatch("hid:0x1B", "clear", {}, self.clock.value)       # desktop fake has no clear: an error is also a result
        usb._dispatch("hid:0x2B", "voice_up", {}, self.clock.value)    # releases are not recorded
        events = list(self.engine.key_events)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["code"], hub.normalize_binding("hid:0x1B"))
        self.assertEqual(events[0]["position"], "第 4 排第 4 颗")

    def test_decision_acts_on_that_request_only(self):
        self.session("s1", "第一个会话", command="echo hi")
        pending = self.engine.state()["pending"][0]
        self.cookie = self.login()
        self.assertEqual(self.api("POST", "/panel/api/decision",
                                  {"decision": "approve", "request_id": pending["id"], "nonce": pending["nonce"] + 1})[0], 409)
        self.assertEqual(self.api("POST", "/panel/api/decision", {"decision": "maybe", "request_id": pending["id"],
                                                                  "nonce": pending["nonce"]})[0], 400)
        _, state = self.api("GET", "/panel/api/state")
        request = state["sessions"][0]["request"]
        self.assertEqual(request["command"], "echo hi")
        self.assertEqual(request["tool"], "Bash")
        self.clock.value += 1
        status, answer = self.api("POST", "/panel/api/decision", {"decision": "deny", "request_id": pending["id"],
                                                                  "nonce": pending["nonce"]})
        self.assertEqual((status, answer["result"]), (200, "denied"))
        deadline = time.monotonic() + 2
        while self.engine.state()["pending"]:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.005)
        self.assertEqual(self.api("POST", "/panel/api/decision", {"decision": "deny", "request_id": pending["id"],
                                                                  "nonce": pending["nonce"]})[0], 409)

    def test_hub_accepts_custom_exe_app_action(self):
        calls = []
        self.desktop.app = lambda session, sessions, direction: calls.append(direction) or True
        result = self.engine.action({"action": "app exe:C:\\Tools\\my app\\notes.exe"})
        self.assertEqual(result["status"], "sent")
        self.assertEqual(calls, ["exe:C:\\Tools\\my app\\notes.exe"])
        with self.assertRaises(hub.HubError):
            self.engine.action({"action": "app nonsense"})

    def test_open_session_uses_focus_path(self):
        self.session("s1", "第一个会话")
        self.cookie = self.login()
        self.assertEqual(self.api("POST", "/panel/api/open", {"agent": "cc", "session_id": "nope"})[0], 404)
        self.assertEqual(self.api("POST", "/panel/api/open", {"agent": "cc", "session_id": "s1"})[0], 200)
        self.assertIn(("focus", "s1"), self.desktop.calls)


class EditTests(PanelBase):
    def setUp(self):
        super().setUp()
        self.cookie = self.login()
        _, state = self.api("GET", "/panel/api/state")
        self.layout = state["layout"]
        self.keys_file = self.home / ".agentdeck" / "hub_keys.json"

    def edit(self, control, action, layer="agent"):
        return self.api("POST", "/panel/api/key", {"id": control, "layer": layer, "action": action})

    def test_fixed_keys_and_knobs_refuse_changes(self):
        for control in ("r3c1", "r3c4", "r4c2", "r5c1", "r5c4", "k1cw", "k2press", "k3ccw"):
            status, answer = self.edit(control, "copy")
            self.assertEqual(status, 403, control)
            self.assertIn("固定键", answer["error"])
        self.assertFalse(self.keys_file.exists())

    def test_row2_edit_is_per_layer_and_takes_effect_at_once(self):
        status, state = self.edit("r2c1", "prompt 提交", "agent")
        self.assertEqual(status, 200)
        data = json.loads(self.keys_file.read_text(encoding="utf-8"))
        self.assertEqual(data["layers"]["agent"], {"hid:0x0A": "prompt 提交"})
        self.assertEqual(data["layers"]["browser"], {})
        self.assertTrue(data["user_modified"])
        self.assertEqual(data["bindings"]["hid:0x0A"], "ctx 1")
        code = self.layout["rows"][1][0]["code"]
        self.assertEqual(state["bindings"]["agent"][code]["label"], "发“提交”")
        self.assertEqual(state["bindings"]["browser"][code]["label"], "后退")
        self.assertTrue(state["bindings"]["agent"][code]["user"])
        usb = self.engine.usb_keys
        self.engine.controls.layers.current = "agent"
        self.assertEqual(usb.lookup(code), "prompt 提交")
        self.engine.controls.layers.current = "browser"
        self.assertEqual(usb.lookup(code), "ctx 1")
        self.assertEqual(self.edit("r2c2", "none", "browser")[0], 200)
        self.assertIsNone(usb.lookup(self.layout["rows"][1][1]["code"]))

    def test_row1_app_and_custom_exe(self):
        self.assertEqual(self.edit("r1c3", "app browser")[0], 200)
        data = json.loads(self.keys_file.read_text(encoding="utf-8"))
        self.assertEqual(data["bindings"]["ctrl+hid:0x1D"], "app browser")
        self.assertEqual(self.engine.usb_keys.lookup(hub.normalize_binding("ctrl+hid:0x1D")), "app browser")
        self.assertEqual(self.edit("r1c4", "app exe:C:\\Tools\\notes app\\notes.exe")[0], 200)
        _, state = self.api("GET", "/panel/api/state")
        self.assertEqual(state["bindings"]["default"][hub.normalize_binding("hid:0x2C")]["label"], "notes")
        for bad in ("app exe:notes.exe", "app exe:C:\\x\\run.bat", "app exe:", "app exe:C:\\a\"b.exe", "copy", "prompt 提交"):
            self.assertEqual(self.edit("r1c4", bad)[0], 400, bad)
        self.assertEqual(self.edit("r1c4", "default")[0], 200)
        data = json.loads(self.keys_file.read_text(encoding="utf-8"))
        self.assertEqual(data["bindings"]["hid:0x2C"], "app browser")  # shipped default for that key

    def test_restore_default_and_validation(self):
        self.edit("r2c3", "copy", "video")
        self.assertEqual(self.edit("r2c3", "default", "video")[0], 200)
        data = json.loads(self.keys_file.read_text(encoding="utf-8"))
        self.assertEqual(data["layers"]["video"], {})
        self.assertEqual(self.edit("r2c3", "rm -rf", "video")[0], 400)
        self.assertEqual(self.edit("r2c3", "copy", "nowhere")[0], 400)
        self.assertEqual(self.edit("nope", "copy")[0], 404)
        status, state = self.edit("k4cw", "ctx prev", "default")
        self.assertEqual(status, 200)
        self.assertEqual(state["bindings"]["default"][hub.normalize_binding("hid:0x30")]["label"], "上方向键")

    def test_user_file_is_never_upgraded_over(self):
        self.edit("r2c1", "copy", "chat")
        shipped = Path(hub.__file__).with_name("hub_keys.json")
        before = self.keys_file.read_bytes()
        self.assertFalse(app.upgrade_keymap(self.keys_file, shipped))
        self.assertEqual(self.keys_file.read_bytes(), before)
        # Even a file that looks like an untouched old default stays when it carries the flag.
        old = {key: value for key, value in hub.load_json(shipped).items() if key not in ("layers", "_instructions")}
        old.update(version=8, bindings=dict(app.V8_BINDINGS), user_modified=True)
        self.keys_file.write_text(json.dumps(old), encoding="utf-8")
        self.assertFalse(app.upgrade_keymap(self.keys_file, shipped))
        del old["user_modified"]
        self.keys_file.write_text(json.dumps(old), encoding="utf-8")
        self.assertTrue(app.upgrade_keymap(self.keys_file, shipped))   # unflagged old default still upgrades

    def test_read_only_profile_refuses(self):
        self.panel.read_only = True
        self.assertEqual(self.edit("r2c1", "copy")[0], 403)


class LaunchTests(unittest.TestCase):
    EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

    def fake_panel(self, sessions=True):
        class Auth:
            def has_session(self_inner):
                return sessions

        class Fake:
            auth = Auth()
            codes = 0

            def new_login_code(self_inner):
                self_inner.codes += 1
                return "CODE"

            def login_url(self_inner, code, port):
                return "http://127.0.0.1:%d/panel#code=%s" % (port, code)
        return Fake()

    def test_find_edge_prefers_hklm_then_hkcu_and_checks_file(self):
        path = panel_launch.APP_PATHS
        both = Registry({("HKLM", path): self.EDGE, ("HKCU", path): "C:\\other\\msedge.exe"})
        self.assertEqual(panel_launch.find_edge(both, lambda p: True), self.EDGE)
        user = Registry({("HKCU", path): "C:\\other\\msedge.exe"})
        self.assertEqual(panel_launch.find_edge(user, lambda p: True), "C:\\other\\msedge.exe")
        self.assertIsNone(panel_launch.find_edge(Registry({}), lambda p: True))
        self.assertIsNone(panel_launch.find_edge(both, lambda p: False))

    def test_launch_starts_edge_in_app_mode_with_code_in_fragment(self):
        started = []
        fake = self.fake_panel()
        result = panel_launch.open_panel(fake, 47800, windows=Windows(), registry=Registry(
            {("HKLM", panel_launch.APP_PATHS): self.EDGE}), exists=lambda p: True,
            popen=lambda command: started.append(command))
        self.assertEqual(result, "edge")
        self.assertEqual(started, [[self.EDGE, "--app=http://127.0.0.1:47800/panel#code=CODE", "--window-size=1180,760"]])

    def test_already_open_window_is_raised_not_duplicated(self):
        started, browser = [], []
        windows = Windows([(5, "C:\\x\\notepad.exe", "AgentDeck"), (7, "C:\\Edge\\msedge.exe", "AgentDeck"),
                           (8, "C:\\Edge\\msedge.exe", "other - Microsoft Edge")])
        fake = self.fake_panel()
        result = panel_launch.open_panel(fake, 1, windows=windows, registry=Registry({}), popen=started.append,
                                         browser_open=browser.append)
        self.assertEqual((result, windows.activated, started, browser, fake.codes), ("activated", [7], [], [], 0))

    def test_open_window_without_live_login_gets_a_fresh_window(self):
        started = []
        windows = Windows([(7, "C:\\Edge\\msedge.exe", "AgentDeck")])
        result = panel_launch.open_panel(self.fake_panel(sessions=False), 1, windows=windows,
                                         registry=Registry({("HKCU", panel_launch.APP_PATHS): self.EDGE}),
                                         exists=lambda p: True, popen=started.append)
        self.assertEqual((result, windows.activated, len(started)), ("edge", [], 1))

    def test_no_edge_falls_back_to_default_browser(self):
        opened = []
        result = panel_launch.open_panel(self.fake_panel(), 47800, windows=Windows(), registry=Registry({}),
                                         popen=lambda c: self.fail("no edge"), browser_open=opened.append)
        self.assertEqual((result, opened), ("browser", ["http://127.0.0.1:47800/panel#code=CODE"]))


class PackagingTests(unittest.TestCase):
    def test_ui_dir_from_source_and_frozen(self):
        self.assertTrue((panel.ui_dir() / "panel.html").is_file())
        with tempfile.TemporaryDirectory() as bundle:
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", bundle, create=True):
                self.assertEqual(panel.ui_dir(), Path(bundle) / "ui")

    def test_spec_ships_ui_files_into_ui(self):
        spec = (Path(__file__).resolve().parent.parent / "agentdeck.spec").read_text(encoding="utf-8")
        self.assertIn('"ui"', spec)
        self.assertIn('pc / "ui"', spec)

    def test_tray_menu_opens_panel_first(self):
        from test_agentdeck_app import Menu, MenuItem
        from types import SimpleNamespace
        from unittest.mock import Mock
        engine = Mock(home=Path("."))
        application = app.TrayApplication(engine, commands=__import__("queue").SimpleQueue(), prefs=Mock(),
                                          keys_path=Path("."), autostart=Mock(), overlay=Mock(hidden=False))
        rows = [r for r in application.menu(SimpleNamespace(Menu=Menu, MenuItem=MenuItem)).children()
                if isinstance(r, MenuItem)]
        self.assertEqual(rows[0].text, "管理面板")
        self.assertTrue(rows[0].options["default"])
        self.assertEqual([r.text for r in rows if isinstance(r.text, str)][:2], ["管理面板", "会话"])
        self.assertTrue(callable(rows[1].text))


if __name__ == "__main__":
    unittest.main()
