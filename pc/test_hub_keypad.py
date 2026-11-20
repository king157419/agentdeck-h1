"""Keypad-only operation (P0/F1/F2/F3): Raw Input guard, window by handle,
latest message preview, scroll and arrow/Enter keys.

Offline: fake desktop, fake windows and a fake user32; the real Hub, relay body,
default keymap and USB report decoder. No real window, key or mouse input.
"""
import ctypes
import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import agentdeck_app as app
from deck_usb import ReportState
import hub
import hub_desktop
from hub_desktop import DesktopEffects, HubWindowControl
import hub_overlay
from hub_overlay import display_model, wrap_tail
import hub_relay

HERE = Path(__file__).resolve().parent
SID = "abc-123"
PER_MONITOR_V2 = ctypes.c_void_p(-4).value


class Desktop:
    """Records the desktop effects the Hub asks for."""

    def __init__(self):
        self.calls = []
        self.voice_active = False

    def focus(self, session, sessions):
        self.calls.append(("focus", session["session_id"]))
        return (session.get("hwnd") or 1, "WindowsTerminal.exe", "x")

    def prompt(self, session, sessions, text):
        self.calls.append(("prompt", session["session_id"], text))

    def screenshot(self, session, sessions):
        self.calls.append(("screenshot", session["session_id"]))
        return "C:/fake.png"

    def voice_down(self, session, sessions, *, on_stop=None):
        self.calls.append(("voice_down", session["session_id"]))

    def voice_up(self):
        return None

    def nav(self, session, sessions, key):
        self.calls.append(("nav", session["session_id"], key))
        return True

    def scroll(self, session, sessions, notches):
        self.calls.append(("scroll", session["session_id"], notches))
        return True

    def close(self):
        pass


class HubCase(unittest.TestCase):
    approve_timeout = 3.0

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.desktop = Desktop()
        self.engine = hub.Hub(desktop=self.desktop, home=self.home, lcd_enabled=False,
                              approve_timeout=self.approve_timeout)
        self.addCleanup(self.engine.close)

    def event(self, name, sid=SID, **fields):
        return self.engine.event("cc", dict(hook_event_name=name, session_id=sid,
                                            cwd="D:\\tmp\\alpha", **fields))

    def session(self, sid=SID):
        return self.engine.sessions[("cc", sid)]

    def permission(self, sid=SID, command="git status"):
        result = {}
        thread = threading.Thread(target=lambda: result.update(response=self.event(
            "PermissionRequest", sid, tool_name="Bash", tool_input={"command": command})))
        thread.start()
        deadline = time.monotonic() + 2
        while not self.engine.pending and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.engine.pending)
        return thread, result

    def act(self, action, source="key"):
        return self.engine.action({"action": action}, source=source)


class RawInputGuardTests(HubCase):
    """P0: under Raw Input the key also types; paste/Enter actions must not run."""

    def dispatch(self, action, reader):
        notes = []
        self.engine.note_input = lambda text, ok=True, lcd=None: notes.append((text, ok))
        keys = hub.USBKeys(self.engine, {"bindings": {}})
        accepted = keys._dispatch("hid:0x10", action, {"request_id": None, "nonce": None},
                                  self.engine.monotonic(), reader)
        return accepted, notes

    def test_paste_enter_voice_screenshot_refused_with_the_banner_text(self):
        self.event("SessionStart")
        for action in ("prompt continue", "nav enter", "nav down", "voice_down", "voice", "screenshot"):
            with self.subTest(action=action):
                accepted, notes = self.dispatch(action, "Raw Input")
                self.assertFalse(accepted)
                self.assertEqual(notes, [("第 3 排第 2 颗 → " + hub.LEAK_TEXT, False)])
        self.assertEqual(self.desktop.calls, [])
        self.assertEqual(hub.LEAK_TEXT, hub_overlay.DRIVER_NOTICE)

    def test_usb_reads_and_harmless_raw_actions_still_work(self):
        self.event("SessionStart")
        self.assertTrue(self.dispatch("prompt continue", "USB")[0])
        self.assertEqual(self.desktop.calls, [("prompt", SID, self.engine.prompts["continue"])])
        for action in ("slot 1", "cycle +1", "scroll 1", "show"):
            with self.subTest(action=action):
                self.assertTrue(self.dispatch(action, "Raw Input")[0])

    def test_overlay_banner_for_raw_input_is_red_and_at_the_top(self):
        model = display_model({"input_reader": "raw"})
        self.assertEqual(model["notice"], hub.LEAK_TEXT)
        self.assertEqual(display_model({"input_reader": "usb"})["notice"], "")

    def test_dangerous_keys_are_marked_in_keymap_window_docs_and_manual(self):
        self.assertEqual(set(app.DANGER_KEYS), {"Ctrl+C", "Ctrl+D", "Ctrl+V"})
        names = {name for row in app.KEY_ROWS for name, _ in row}
        self.assertLessEqual(set(app.DANGER_KEYS), names)
        keys_md = (HERE / "hub_keys.md").read_text(encoding="utf-8")
        manual = (HERE.parent / "agentdeck" / "使用说明书.md").read_text(encoding="utf-8")
        for text in (keys_md, manual):
            for key in ("Ctrl+C", "Ctrl+D", "Ctrl+V"):
                self.assertRegex(text, re.escape(key) + r"[^\n]*危险")

    def test_docs_follow_the_measured_layout(self):
        keys_md = (HERE / "hub_keys.md").read_text(encoding="utf-8")
        manual = (HERE.parent / "agentdeck" / "使用说明书.md").read_text(encoding="utf-8")
        self.assertNotIn("Ctrl+0", manual)
        self.assertNotIn("印的字母就是", manual)
        self.assertIn("按位置", manual)
        for text in (keys_md, manual):
            self.assertRegex(text, r"旋钮 4 按下 \| C")
            self.assertNotRegex(text, r"旋钮 4 按下 \| Ctrl\+0")
            self.assertNotIn("无信号", text)
            for row, key in (("第 2 排第 4 颗", "Alt"), ("第 4 排第 1 颗", "Ctrl"), ("第 4 排第 2 颗", "Shift")):
                if text is manual:
                    self.assertRegex(text, re.escape(row) + r" \| " + key + r"（只发修饰键[^\n]*不绑定")
        self.assertIn("第 4 排第 3 颗 | U", manual)
        self.assertIn("第 4 排第 4 颗 | X", manual)


class WindowBindingTests(HubCase):
    """F1: the relay's hwnd is stored and focus prefers it over title guessing."""

    def test_event_stores_and_refreshes_a_valid_handle_only(self):
        self.event("SessionStart", agentdeck_window={"hwnd": 0x1234, "pid": 50, "exe": "WindowsTerminal.exe"})
        self.assertEqual((self.session()["hwnd"], self.session()["window_exe"]), (0x1234, "WindowsTerminal.exe"))
        self.event("UserPromptSubmit", agentdeck_window={"hwnd": 0x5678, "pid": 51, "exe": "Code.exe"})
        self.assertEqual(self.session()["hwnd"], 0x5678)
        for bad in (-1, 0, True, 2**64, "12", None, 1.5):
            with self.subTest(hwnd=bad):
                self.event("PostToolUse", agentdeck_window={"hwnd": bad, "exe": "x.exe"})
                self.assertEqual(self.session()["hwnd"], 0x5678)
        self.event("PostToolUse", agentdeck_window="not a dict")
        self.assertEqual(self.engine.state()["sessions"][0]["hwnd"], 0x5678)

    def test_slot_in_a_shared_window_says_it_can_only_bring_it_forward(self):
        """Acceptance 2026-11-19: every Claude Code session hosted in the Claude desktop
        app binds to its one window, so E/B 'did nothing'. The key feedback says why."""
        desktop_app = {"hwnd": 0x4209, "pid": 70, "exe": "claude.exe"}
        self.event("SessionStart", "alpha", agentdeck_window=desktop_app)
        self.event("SessionStart", "beta", agentdeck_window=desktop_app)
        self.event("SessionStart", "gamma", agentdeck_window={"hwnd": 0x1234, "pid": 50, "exe": "WindowsTerminal.exe"})
        shared = self.act("slot 1")
        self.assertEqual((shared["window"], shared.get("shared_window")), ("focused", True))
        self.assertEqual(hub.describe_input("slot 1", shared)[0], "已选槽位 1（同窗：只能调到前台）")
        alone = self.act("slot 3")
        self.assertNotIn("shared_window", alone)
        self.assertEqual(hub.describe_input("slot 3", alone)[0], "已选槽位 3")
        self.desktop.focus = lambda session, sessions: False
        missing = self.act("slot 2")
        self.assertNotIn("shared_window", missing)
        self.assertEqual(hub.describe_input("slot 2", missing)[0], "已选槽位 2（没找到窗口）")

    def test_shared_binding_with_a_distinct_focused_window_has_normal_feedback(self):
        desktop_app = {"hwnd": 0x4209, "pid": 70, "exe": "claude.exe"}
        self.event("SessionStart", "alpha", agentdeck_window=desktop_app)
        self.event("SessionStart", "beta", agentdeck_window=desktop_app)
        self.desktop.focus = lambda session, sessions: (0x1234, "WindowsTerminal.exe", "alpha - Claude Code")
        result = self.act("slot 1")
        self.assertEqual(result["window"], "focused")
        self.assertNotIn("shared_window", result)
        self.assertEqual(hub.describe_input("slot 1", result)[0], "已选槽位 1")

    def test_shared_binding_with_a_boolean_focus_result_keeps_shared_feedback(self):
        desktop_app = {"hwnd": 0x4209, "pid": 70, "exe": "claude.exe"}
        self.event("SessionStart", "alpha", agentdeck_window=desktop_app)
        self.event("SessionStart", "beta", agentdeck_window=desktop_app)
        self.desktop.focus = lambda session, sessions: True
        result = self.act("slot 1")
        self.assertTrue(result["shared_window"])
        self.assertEqual(hub.describe_input("slot 1", result)[0], "已选槽位 1（同窗：只能调到前台）")


class Windows:
    def __init__(self, items):
        self.items = list(items)
        self.foreground = (99, "explorer.exe", "desktop")
        self.keys, self.combos, self.wheels, self.activated = [], [], [], []

    def __call__(self):
        return self.foreground

    def windows(self):
        return self.items

    def activate(self, hwnd):
        self.activated.append(hwnd)
        window = next((item for item in self.items if item[0] == hwnd), None)
        if window is not None:
            # Claude Code rewrites its title all the time: same handle, new text.
            self.foreground = (window[0], window[1], "✳ " + window[2])
        return window is not None

    def send_key(self, key, expected):
        assert self.foreground[0] == expected[0]
        self.keys.append(key)
        return True

    def send_combo(self, keys, expected):
        self.combos.append(keys)
        return True

    def wheel(self, hwnd, notches, expected):
        assert self.foreground[0] == hwnd == expected[0]
        self.wheels.append((hwnd, notches))
        return True


SESSION = {"key": "cc-abc123", "name": "alpha", "state": "think", "slot": 1}
TERMINAL = (0x1234, "C:\\Program Files\\WindowsApps\\WindowsTerminal.exe", "✳ Fixing the login bug")


class DesktopFocusTests(unittest.TestCase):
    def effects(self, items):
        self.windows = Windows(items)
        return DesktopEffects(self.windows, clipboard=lambda text: None, sleeper=lambda seconds: None)

    def test_handle_focuses_a_window_whose_title_lacks_the_project(self):
        effects = self.effects([TERMINAL])
        session = dict(SESSION, hwnd=0x1234, window_exe="WindowsTerminal.exe")
        self.assertEqual(effects.focus(session, [session]), TERMINAL)
        self.assertTrue(effects.nav(session, [session], "down"))
        self.assertEqual(self.windows.keys, [0x28])

    def test_shared_host_prefers_each_sessions_unique_terminal(self):
        host = (0x4209, "claude.exe", "Claude")
        alpha = (0x1234, "WindowsTerminal.exe", "alpha - Claude Code")
        beta = (0x5678, "WindowsTerminal.exe", "beta - Codex")
        effects = self.effects([host, alpha, beta])
        sessions = [dict(SESSION, hwnd=host[0], window_exe=host[1]),
                    dict(SESSION, key="cx-beta", name="beta", hwnd=host[0], window_exe=host[1])]
        for session, window in zip(sessions, (alpha, beta)):
            with self.subTest(key=session["key"]):
                self.assertEqual(effects.focus(session, sessions), window)
        self.assertEqual(self.windows.activated, [alpha[0], beta[0]])

    def test_shared_host_without_a_unique_match_keeps_bound_window(self):
        host = (0x4209, "claude.exe", "Claude")
        alpha = (0x1234, "WindowsTerminal.exe", "alpha - Claude Code")
        sessions = [dict(SESSION, hwnd=host[0], window_exe=host[1]),
                    dict(SESSION, key="cx-beta", name="beta", hwnd=host[0], window_exe=host[1])]
        for matches in ([], [alpha, (0x5678, alpha[1], alpha[2])]):
            with self.subTest(matches=matches):
                effects = self.effects([host, *matches])
                self.assertEqual(effects.focus(sessions[0], sessions), host)
                self.assertEqual(self.windows.activated, [host[0]])

    def test_shared_binding_matching_its_own_handle_keeps_bound_window(self):
        titled = (0x1234, "WindowsTerminal.exe", "alpha - Claude Code")
        effects = self.effects([titled])
        sessions = [dict(SESSION, hwnd=titled[0]),
                    dict(SESSION, key="cx-beta", name="beta", hwnd=titled[0])]
        self.assertEqual(effects.focus(sessions[0], sessions), titled)
        self.assertEqual(self.windows.activated, [titled[0]])

    def test_unshared_binding_never_tries_title_matching(self):
        titled = (0x77, "WindowsTerminal.exe", "alpha - Claude Code")
        effects = self.effects([TERMINAL, titled])
        session = dict(SESSION, hwnd=TERMINAL[0], window_exe="WindowsTerminal.exe")
        with patch("deck.window_for_session", side_effect=AssertionError("unexpected title matching")):
            self.assertEqual(effects.focus(session, [session]), TERMINAL)
        self.assertEqual(self.windows.activated, [TERMINAL[0]])

    def test_only_integer_handles_count_as_a_shared_binding(self):
        host = (1, "claude.exe", "Claude")
        effects = self.effects([host, (0x77, "WindowsTerminal.exe", "alpha - Claude Code")])
        session = dict(SESSION, hwnd=host[0], window_exe=host[1])
        for invalid in (True, 1.0, "1", None):
            with self.subTest(hwnd=invalid):
                other = dict(SESSION, key="cx-beta", name="beta", hwnd=invalid)
                with patch("deck.window_for_session", side_effect=AssertionError("unexpected title matching")):
                    self.assertEqual(effects.focus(session, [session, other]), host)

    def test_closed_handle_falls_back_to_title_matching(self):
        titled = (0x77, "WindowsTerminal.exe", "alpha - Claude")
        effects = self.effects([titled])
        session = dict(SESSION, hwnd=0x1234, window_exe="WindowsTerminal.exe")
        self.assertEqual(effects.focus(session, [session]), titled)

    def test_reused_handle_of_another_program_is_not_trusted(self):
        effects = self.effects([(0x1234, "C:\\Windows\\notepad.exe", "notes")])
        session = dict(SESSION, hwnd=0x1234, window_exe="WindowsTerminal.exe")
        with self.assertRaisesRegex(RuntimeError, "窗口已关闭或找不到"):
            effects.focus(session, [session])
        self.assertEqual(self.windows.activated, [])

    def test_both_paths_failing_reports_closed_window(self):
        effects = self.effects([(0x55, "WindowsTerminal.exe", "something else")])
        with self.assertRaisesRegex(RuntimeError, "窗口已关闭或找不到"):
            effects.focus(dict(SESSION), [dict(SESSION)])

    def test_nav_keys_and_scroll_go_through_focus(self):
        effects = self.effects([TERMINAL])
        session = dict(SESSION, hwnd=0x1234)
        for key, code in (("up", 0x26), ("down", 0x28), ("enter", 0x0D)):
            effects.nav(session, [session], key)
            self.assertEqual(self.windows.keys[-1], code)
        self.assertTrue(effects.scroll(session, [session], -3))
        self.assertEqual(self.windows.wheels, [(0x1234, -3)])
        with self.assertRaises(ValueError):
            effects.scroll(session, [session], 0)


def fake_user(rect=(100, 200, 1100, 900), covered=(), cursor=(5, 6), screen=(0, 0, 1920, 1080),
              target=12, sent=None):
    calls = {"input": [], "dpi": []}

    def get_rect(hwnd, pointer):
        assert hwnd == target
        r = pointer._obj
        r.left, r.top, r.right, r.bottom = rect
        return True

    def from_point(point):
        return 0xAAAA if (point.x, point.y) in covered else 77

    def ancestor(hwnd, flag):
        assert flag == 2
        return target if hwnd == 77 else hwnd

    def cursor_pos(pointer):
        pointer._obj.x, pointer._obj.y = cursor
        return True

    def metrics(index):
        return dict(zip((76, 77, 78, 79), screen))[index]

    def send(count, events, size):
        assert size == ctypes.sizeof(hub_desktop.INPUT)
        calls["input"].append([(e.type, e.mi.dx, e.mi.dy, e.mi.mouseData, e.mi.dwFlags) for e in events])
        return count if sent is None else sent

    def dpi(context):
        calls["dpi"].append(context.value if hasattr(context, "value") else context)
        return 0x1111

    user = SimpleNamespace(GetWindowRect=get_rect, WindowFromPoint=from_point, GetAncestor=ancestor,
                           GetCursorPos=cursor_pos, GetSystemMetrics=metrics, SendInput=send,
                           SetThreadDpiAwarenessContext=dpi, GetAsyncKeyState=lambda key: 0)
    return user, calls


class Native(HubWindowControl):
    def __init__(self, user, foreground=(12, "WindowsTerminal.exe", "t")):
        self.user = user
        self.foreground = foreground

    def __call__(self):
        return self.foreground


class WheelTests(unittest.TestCase):
    """F3: one SendInput batch of exactly three mouse INPUTs."""

    def pixel(self, normalized, size):
        return normalized * size // 65536

    def test_scroll_one_moves_wheels_and_returns_in_one_batch(self):
        user, calls = fake_user()
        native = Native(user)
        self.assertTrue(native.wheel(12, 1, (12, "WindowsTerminal.exe", "new title")))
        [events] = calls["input"]
        self.assertEqual(len(events), 3)
        move = 0x0001 | 0x8000 | 0x4000
        (t0, x0, y0, d0, f0), (t1, _, _, d1, f1), (t2, x2, y2, d2, f2) = events
        self.assertEqual((t0, t1, t2), (0, 0, 0))
        self.assertEqual((f0, f1, f2), (move, 0x0800, move))
        self.assertEqual((self.pixel(x0, 1920), self.pixel(y0, 1080)), (600, 200 + int(700 * 0.6)))
        self.assertEqual(ctypes.c_int32(d1).value, -120)
        self.assertEqual((self.pixel(x2, 1920), self.pixel(y2, 1080)), (5, 6))
        self.assertEqual((d0, d2), (0, 0))
        self.assertEqual(calls["dpi"], [PER_MONITOR_V2, 0x1111])  # per-monitor aware, then restored

    def test_scroll_end_is_one_hundred_notches_and_up_is_positive(self):
        user, calls = fake_user()
        native = Native(user)
        native.wheel(12, hub.SCROLL_END, (12, "", ""))
        native.wheel(12, -1, (12, "", ""))
        self.assertEqual(ctypes.c_int32(calls["input"][0][1][3]).value, -12000)
        self.assertEqual(ctypes.c_int32(calls["input"][1][1][3]).value, 120)

    def test_covered_points_are_skipped_and_all_covered_is_an_error(self):
        first = (600, 200 + int(700 * 0.6))
        user, calls = fake_user(covered={first})
        Native(user).wheel(12, 1, (12, "", ""))
        x, y = calls["input"][0][0][1:3]
        self.assertEqual((self.pixel(x, 1920), self.pixel(y, 1080)), (600, 200 + int(700 * 0.85)))
        everything = {(100 + int(1000 * fx), 200 + int(700 * fy)) for fx, fy in hub_desktop.SCROLL_POINTS}
        user, calls = fake_user(covered=everything)
        with self.assertRaisesRegex(RuntimeError, "窗口被挡住"):
            Native(user).wheel(12, 1, (12, "", ""))
        self.assertEqual(calls["input"], [])
        self.assertEqual(calls["dpi"], [PER_MONITOR_V2, 0x1111])

    def test_negative_virtual_desktop_origin_and_foreground_change(self):
        user, calls = fake_user(rect=(-1500, 100, -500, 700), cursor=(-1900, 0),
                                screen=(-1920, 0, 3840, 1080))
        Native(user).wheel(12, 1, (12, "", ""))
        x, _ = calls["input"][0][0][1:3]
        self.assertEqual(self.pixel(x, 3840) - 1920, -1000)
        x, _ = calls["input"][0][2][1:3]
        self.assertEqual(self.pixel(x, 3840) - 1920, -1900)
        user, calls = fake_user()
        self.assertFalse(Native(user, foreground=(99, "", "")).wheel(12, 1, (12, "", "")))
        self.assertEqual(calls["input"], [])

    def test_send_key_marks_arrows_extended_and_compares_handles_only(self):
        import deck_windows
        sent = []
        native = Native(SimpleNamespace(GetAsyncKeyState=lambda key: 0,
                                        SendInput=lambda count, events, size: sent.append(
                                            [(e.ki.wVk, e.ki.dwFlags) for e in events]) or count),
                        foreground=(12, "WindowsTerminal.exe", "✳ title changed"))
        self.assertTrue(deck_windows.WindowControl.send_key(native, 0x28, (12, "WindowsTerminal.exe", "old")))
        self.assertTrue(deck_windows.WindowControl.send_key(native, 0x0D, (12, "WindowsTerminal.exe", "old")))
        self.assertEqual(sent, [[(0x28, 1), (0x28, 3)], [(0x0D, 0), (0x0D, 2)]])
        self.assertFalse(deck_windows.WindowControl.send_key(native, 0x0D, (13, "WindowsTerminal.exe", "old")))


class NavScrollActionTests(HubCase):
    approve_timeout = 0.3

    def test_scroll_arguments(self):
        self.event("SessionStart")
        self.act("scroll 3")
        self.act("scroll -20")
        self.act("scroll end")
        self.assertEqual([call[2] for call in self.desktop.calls], [3, -20, 100])
        for bad in ("scroll", "scroll 0", "scroll 21", "scroll x", "scroll 1.5", "nav", "nav left"):
            with self.subTest(action=bad):
                with self.assertRaises(hub.HubError) as caught:
                    self.act(bad)
                self.assertEqual(caught.exception.status, 400)

    def test_pending_request_blocks_nav_and_desktop_is_not_called(self):
        self.event("SessionStart")
        thread, result = self.permission()
        for action in ("nav enter", "nav down", "nav up"):
            with self.subTest(action=action):
                with self.assertRaises(hub.HubError) as caught:
                    self.act(action)
                self.assertEqual(caught.exception.status, 409)
                text, ok, _ = hub.describe_input(action, error=caught.exception)
                self.assertEqual((text, ok), ("有待批请求：用 ✓/✗ 处理", False))
        self.assertEqual(self.desktop.calls, [])
        self.act("scroll 1")  # looking is still fine
        self.act("deny")
        thread.join(2)
        self.assertEqual(result["response"]["hookSpecificOutput"]["decision"]["behavior"], "deny")

    def test_nav_returns_409_over_http_while_a_request_is_pending(self):
        self.event("SessionStart")
        thread, _ = self.permission()
        server = hub.HubServer(self.engine, "secret", 0)
        serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        serving.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("POST", "/action", body=json.dumps({"action": "nav enter"}),
                               headers={"Content-Type": "application/json", "X-AgentDeck-Token": "secret"})
            response = connection.getresponse()
            self.assertEqual(response.status, 409)
            self.assertIn("use approve/deny", json.loads(response.read())["error"])
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            self.act("deny")
            thread.join(2)
        self.assertEqual(self.desktop.calls, [])

    def test_native_permission_dialog_and_permission_notification_block_nav(self):
        self.event("SessionStart")
        thread, _ = self.permission()
        thread.join(3)  # AgentDeck timed out: the agent's own dialog asks now
        self.assertTrue(self.session()["native_wait"])
        with self.assertRaisesRegex(hub.HubError, "use approve/deny"):
            self.act("nav enter")
        self.event("PostToolUse", tool_name="Bash", tool_input={"command": "git status"})
        self.assertNotIn("native_wait", self.session())
        self.act("nav enter")
        self.event("Notification", notification_type="permission_prompt", message="Claude needs your permission")
        with self.assertRaisesRegex(hub.HubError, "use approve/deny"):
            self.act("nav enter")
        self.event("Notification", message="Claude needs your permission to use Bash")  # older: no type
        with self.assertRaisesRegex(hub.HubError, "use approve/deny"):
            self.act("nav enter")
        self.assertEqual(self.desktop.calls, [("nav", SID, "enter")])

    def test_arrows_only_while_the_agent_asks(self):
        self.event("SessionStart")
        self.event("Stop", last_assistant_message="done")
        self.assertEqual(self.session()["state"], "done")
        for action in ("nav up", "nav down"):
            with self.assertRaisesRegex(hub.HubError, "only while the agent asks"):
                self.act(action)
        self.act("nav enter")  # sends dictated text
        self.event("PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": [
            {"question": "用哪个方案？", "options": [{"label": "A"}, {"label": "B"}]}]})
        self.act("nav down")
        self.act("nav enter")
        self.assertEqual(self.desktop.calls, [("nav", SID, "enter"), ("nav", SID, "down"), ("nav", SID, "enter")])
        self.event("Notification", notification_type="elicitation_dialog", message="MCP 需要输入")
        self.act("nav up")
        self.assertEqual(self.desktop.calls[-1], ("nav", SID, "up"))

    def test_voice_active_blocks_nav_and_scroll(self):
        self.event("SessionStart")
        self.desktop.voice_active = True
        for action in ("nav enter", "scroll 1"):
            with self.assertRaisesRegex(hub.HubError, "release voice"):
                self.act(action)

    def test_desktop_without_support_reports_unavailable(self):
        self.event("SessionStart")
        self.desktop.nav = lambda *args: False
        self.desktop.scroll = lambda *args: False
        self.assertEqual(self.act("nav enter")["status"], "unavailable")
        self.assertEqual(self.act("scroll 1")["status"], "unavailable")
        self.assertEqual(hub.describe_input("nav enter", {"status": "sent"})[0], "已回车")
        self.assertEqual(hub.describe_input("scroll end", {"status": "sent"})[0], "已翻到底")
        self.assertEqual(hub.describe_input("scroll -1", {"status": "sent"})[0], "已滚动")

    def test_default_keymap_knobs_three_and_four_from_usb_reports(self):
        self.event("SessionStart")
        self.event("PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": []})
        callback = hub.USBKeys(self.engine)
        parser = ReportState()

        def press(report):
            for event in parser.feed(bytes(report)):
                callback(dict(event, t=self.engine.monotonic()))
            for event in parser.feed(bytes(8)):
                callback(dict(event, t=self.engine.monotonic()))

        for usage in (0x2D, 0x2E, 0x19, 0x30, 0x2F):
            press([0, 0, usage, 0, 0, 0, 0, 0])
        press([1, 0, 0, 0, 0, 0, 0, 0])
        press([1, 0, 0x27, 0, 0, 0, 0, 0])  # alternate keypad Ctrl+0
        press([0, 0, 0x06, 0, 0, 0, 0, 0])  # measured knob 4 press: C
        self.assertEqual(self.desktop.calls, [
            ("scroll", SID, 1), ("scroll", SID, -1), ("scroll", SID, 100),
            ("nav", SID, "down"), ("nav", SID, "up"), ("nav", SID, "enter"),
            ("nav", SID, "enter")])

    def test_shipped_keymap_and_upgrade_from_v3_and_v4(self):
        shipped = json.loads((HERE / "hub_keys.json").read_text(encoding="utf-8"))
        self.assertEqual(shipped["version"], 7)
        bindings = shipped["bindings"]
        self.assertEqual({key: bindings[key] for key in app.V4_CHANGED}, {
            "hid:0x06": "nav enter", "hid:0x16": "app prev", "hid:0x09": "app next",
            "hid:0x2D": "scroll 1", "hid:0x2E": "scroll -1", "hid:0x19": "scroll end",
            "hid:0x30": "nav down", "hid:0x2F": "nav up", "ctrl+hid:0x27": "nav enter"})
        for name in ("hid:0x15", "hid:0x13", "hid:0x1B"):
            self.assertTrue(bindings[name].startswith("cycle "))
        instructions = " ".join(shipped["_instructions"])
        for text in ("scroll 1", "scroll end", "nav down", "nav enter", "Ctrl+D"):
            self.assertIn(text, instructions)
        self.assertNotIn("Ctrl+0", instructions)
        self.assertNotIn("cycle +1, counterclockwise = -> cycle -1", instructions)
        for usage in range(0xE0, 0xE8):
            self.assertNotIn("hid:0x%02X" % usage, bindings)
        for version, changed in app.OLD_DEFAULTS.items():
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "hub_keys.json"
                old_bindings = {key: value for key, value in dict(bindings, **changed).items()
                                if value is not None}
                target.write_text(json.dumps(dict(shipped, version=version,
                                                  bindings=old_bindings)), encoding="utf-8")
                old_bytes = target.read_bytes()
                self.assertTrue(app.upgrade_keymap(target, HERE / "hub_keys.json"))
                self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["bindings"], bindings)
                backup = Path(directory) / ("hub_keys.json.bak-v%d" % version)
                self.assertEqual(backup.read_bytes(), old_bytes)
                target.write_bytes(old_bytes)
                backup.write_bytes(b"keep existing backup")
                self.assertTrue(app.upgrade_keymap(target, HERE / "hub_keys.json"))
                self.assertEqual(backup.read_bytes(), b"keep existing backup")
                if version in (5, 6):
                    old_bindings["hid:0x08"] = "slot 6"
                    edited = json.dumps(dict(shipped, version=version, bindings=old_bindings), indent=3).encode("utf-8")
                    target.write_bytes(edited)
                    self.assertFalse(app.upgrade_keymap(target, HERE / "hub_keys.json"))
                    self.assertEqual(target.read_bytes(), edited)


class PreviewTests(HubCase):
    """F2: the latest message per session, shown without switching windows."""

    def test_stop_reply_reaches_state_and_preview(self):
        self.event("SessionStart")
        self.event("Stop", last_assistant_message="后面还要改三处，要我继续吗？")
        item = self.engine.state()["sessions"][0]
        self.assertEqual((item["last_text"], item["last_kind"]), ("后面还要改三处，要我继续吗？", "回复"))
        model = display_model(self.engine.state(), now=item["last_text_at"] + 200)
        self.assertTrue(model["preview"]["lines"][-1].endswith("要我继续吗？"))
        self.assertEqual(model["preview"]["title"], "#1 alpha · 回复 · 3分钟前")

    def test_kinds_activity_and_wait_flags(self):
        self.event("SessionStart")
        self.event("UserPromptSubmit", prompt="修一下登录")
        self.assertEqual((self.session()["last_text"], self.session()["last_kind"]), ("修一下登录", "你"))
        self.event("PreToolUse", tool_name="Bash", tool_input={"command": "pytest  -q tests/" + "x" * 80})
        self.assertEqual(self.session()["activity"], ("Bash pytest -q tests/" + "x" * 80)[:hub.ACTIVITY_LIMIT])
        slot = display_model(self.engine.state())["slots"][0]
        self.assertEqual(slot["activity"], "Bash pytest -q test…")
        self.assertFalse(slot["needs_input"])
        self.event("PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": [
            {"question": "用哪个方案？", "options": [{"label": "快"}, {"label": "稳"}]}]})
        self.assertEqual((self.session()["last_text"], self.session()["last_kind"]), ("用哪个方案？\n快 / 稳", "提问"))
        self.assertTrue(display_model(self.engine.state())["slots"][0]["needs_input"])
        self.event("Stop", last_assistant_message="好了")
        self.assertNotIn("activity", self.session())
        self.event("Notification", notification_type="elicitation_dialog", title="MCP", message="请填写")
        self.assertEqual((self.session()["last_text"], self.session()["wait_kind"]), ("MCP：请填写", "elicitation_dialog"))
        self.assertTrue(display_model(self.engine.state())["slots"][0]["needs_input"])
        self.event("Notification", notification_type="agent_needs_input", message="?")
        self.assertEqual(self.session()["state"], "wait")
        self.event("UserPromptSubmit", prompt="继续")
        self.assertNotIn("wait_kind", self.session())

    def test_long_text_is_capped_and_preview_bounded(self):
        self.event("SessionStart")
        self.event("Stop", last_assistant_message="长" * 2500 + "x" * 2500)
        self.assertEqual(len(self.session()["last_text"]), 4000)
        lines = display_model(self.engine.state())["preview"]["lines"]
        self.assertLessEqual(len(lines), 8)
        self.assertTrue(all(hub_overlay._text_width(line) <= 46 for line in lines))
        self.assertTrue(lines[0].startswith("…"))

    def test_preview_hidden_while_the_same_session_shows_a_request(self):
        self.event("SessionStart")
        self.event("Stop", last_assistant_message="要我继续吗？")
        thread, _ = self.permission()
        model = display_model(self.engine.state())
        self.assertIsNotNone(model["request"])
        self.assertIsNone(model["preview"])
        self.act("deny")
        thread.join(2)
        self.assertIsNotNone(display_model(self.engine.state())["preview"])

    def test_first_waiting_session_without_selection_and_same_window_flag(self):
        state = {"selected_slot": None, "sessions": [
            {"slot": 1, "agent": "cc", "session_id": "a", "name": "a", "state": "done", "last_text": "一", "hwnd": 7},
            {"slot": 2, "agent": "cx", "session_id": "b", "name": "b", "state": "wait", "last_text": "二", "hwnd": 7},
            {"slot": 3, "agent": "cx", "session_id": "c", "name": "c", "state": "idle", "hwnd": 8}]}
        model = display_model(state)
        self.assertEqual(model["preview"]["title"], "#2 b")
        self.assertEqual([slot["same_window"] for slot in model["slots"][:3]], [True, True, False])

    def test_wrap_tail(self):
        self.assertEqual(wrap_tail("a\n\n\n\nb\n```py\ncode\n```\n"), ["a", "", "b", "code"])
        self.assertEqual(wrap_tail("中" * 30, cols=10), ["中" * 5] * 6)
        lines = wrap_tail("\n".join("line %d" % number for number in range(20)), rows=3)
        self.assertEqual(lines, ["…line 17", "line 18", "line 19"])
        self.assertEqual(wrap_tail(""), [])


class RelayBodyTests(unittest.TestCase):
    """F2: the relay keeps the preview text (capped) in ordinary events."""

    def body(self, **event):
        return json.loads(hub_relay._body(dict(session_id="s", **event), None, False))

    def test_preview_fields_survive_and_are_capped(self):
        stop = self.body(hook_event_name="Stop", last_assistant_message="开头" + "尾" * 5000, transcript_path="x")
        self.assertEqual(stop["last_assistant_message"], "尾" * 4000)
        self.assertNotIn("transcript_path", stop)
        prompt = self.body(hook_event_name="UserPromptSubmit", prompt="继续")
        self.assertEqual(prompt["prompt"], "继续")
        note = self.body(hook_event_name="Notification", title="T", message="m" * 400,
                         notification_type="idle_prompt")
        self.assertEqual((note["title"], len(note["message"]), note["notification_type"]), ("T", 300, "idle_prompt"))
        ask = self.body(hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": [
            {"question": "Q?", "header": "h", "multiSelect": False,
             "options": [{"label": "A", "description": "long" * 100}]}]})
        self.assertEqual(ask["tool_input"], {"questions": [{"question": "Q?", "options": [{"label": "A"}]}]})
        bash = self.body(hook_event_name="PreToolUse", tool_name="Bash",
                         tool_input={"command": "ls " * 200, "timeout": 5})
        self.assertEqual(set(bash["tool_input"]), {"command"})
        self.assertEqual(len(bash["tool_input"]["command"]), 300)
        post = self.body(hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "ls"},
                         tool_response="x" * 100000)
        self.assertNotIn("tool_input", post)
        self.assertIn("tool_input_hash", post)
        self.assertEqual(hub_relay._body({"a": "原样"}, b'{"a":"\xe5\x8e\x9f"}', True), b'{"a":"\xe5\x8e\x9f"}')

    def test_hub_accepts_the_relay_body_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = hub.Hub(home=directory, lcd_enabled=False, desktop_enabled=False)
            try:
                for event in ({"hook_event_name": "SessionStart", "cwd": "D:\\tmp\\alpha",
                               "agentdeck_window": {"hwnd": 0x1234, "pid": 9, "exe": "WindowsTerminal.exe"}},
                              {"hook_event_name": "Stop", "last_assistant_message": "后面还要改三处，要我继续吗？"}):
                    engine.event("cc", json.loads(hub_relay._body(dict(event, session_id="s"), None, False)))
                item = engine.state()["sessions"][0]
                self.assertEqual((item["hwnd"], item["last_text"]), (0x1234, "后面还要改三处，要我继续吗？"))
            finally:
                engine.close()


class OverlayRenderTests(unittest.TestCase):
    """Real Tk widgets: rows, preview and the banner (no window is shown)."""

    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        try:
            cls.root = tk.Tk()
        except tk.TclError as error:  # pragma: no cover - headless machines
            raise unittest.SkipTest("no display: %s" % error)
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def overlay(self):
        overlay = hub_overlay.Overlay(SimpleNamespace(lock=threading.RLock(), home=None))
        overlay.root = self.root
        for child in self.root.winfo_children():
            child.destroy()
        overlay._build()
        return overlay

    def state(self, **extra):
        session = {"slot": 1, "agent": "cc", "session_id": "a", "name": "alpha", "state": "wait",
                   "last_text": "后面还要改三处，要我继续吗？", "last_kind": "回复", "last_text_at": 100.0}
        session.update(extra)
        return {"selected_slot": 1, "sessions": [session], "input_reader": "raw"}

    def test_waiting_row_preview_and_red_banner(self):
        overlay = self.overlay()
        overlay.model = display_model(self.state(), now=130.0)
        overlay._render()
        row, number, name, dot, activity = overlay.rows[0]
        self.assertEqual(name.cget("text"), "alpha · 等你")
        self.assertEqual(name.cget("fg"), hub_overlay.COLORS["ASK"])
        self.assertEqual(overlay.preview.cget("text"), "后面还要改三处，要我继续吗？")
        self.assertEqual(overlay.preview_title.cget("text"), "#1 alpha · 回复 · 刚刚")
        self.assertTrue(overlay.preview_box.winfo_manager())
        self.assertIn(hub.LEAK_TEXT, overlay.notice_label.cget("text"))
        self.assertEqual(overlay.notice_label.cget("fg"), hub_overlay.COLORS["ERR"])
        self.assertEqual(overlay.notice_label.grid_info()["row"], 1)  # top: right under the header

    def test_preview_configured_only_on_change_and_hidden_for_a_request(self):
        overlay = self.overlay()
        overlay.model = display_model(self.state(), now=130.0)
        overlay._render()
        with patch.object(overlay.preview, "configure", wraps=overlay.preview.configure) as configure:
            overlay._render()
            overlay._render()
            configure.assert_not_called()
        state = self.state()
        state["pending"] = [{"id": "r1", "agent": "cc", "session_id": "a", "summary": "rm x", "risk": "low",
                             "status": "pending", "nonce": 1}]
        state["displayed_request_id"] = "r1"
        overlay.model = display_model(state, now=130.0)
        overlay._render()
        self.assertEqual(overlay.preview_box.winfo_manager(), "")
        self.assertTrue(overlay.detail.winfo_manager())

    def test_activity_shows_in_gray_while_running(self):
        overlay = self.overlay()
        overlay.model = display_model(self.state(state="tool", activity="Bash npm test"), now=130.0)
        overlay._render()
        row, number, name, dot, activity = overlay.rows[0]
        self.assertEqual((name.cget("text"), activity.cget("text")), ("alpha", "Bash npm test"))
        self.assertEqual(name.cget("fg"), hub_overlay.FOREGROUND)


if __name__ == "__main__":
    unittest.main(verbosity=2)
