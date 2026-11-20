"""AgentDeck 离线断言：串口、Win32、HID、进程和单实例锁全部使用替身。"""
import contextlib
import ctypes
import io
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
from unittest.mock import patch

import deck
import deck_windows

REPLY = "boot\nok list n=4\n  cc-a wait app\n  cx-b think app-server\n  cc-c wait notes\n  cx-d done project with spaces"


class Windows:
    def __init__(self, window=(1, "Code.exe", "app - Claude")):
        self.window = window
        self.items = [window, (2, "WindowsTerminal.exe", "app-server - Codex"),
                      (3, "pwsh.exe", "notes - Claude")]
        self.keys = []
        self.activated = []
        self.key_ok = True
        self.activate_ok = True

    def __call__(self):
        return self.window

    def windows(self):
        return self.items

    def activate(self, hwnd):
        self.activated.append(hwnd)
        return self.activate_ok

    def send_key(self, key, expected):
        assert expected == self.window
        self.keys.append(key)
        return self.key_ok


class Sender:
    def __init__(self, reply=REPLY):
        self.reply = reply
        self.calls = []
        self.on_list = lambda: None

    def __call__(self, lines, **kwargs):
        self.calls.extend(lines)
        if lines == ["list"]:
            assert kwargs["wait_reply"] > 0
            self.on_list()
            return self.reply
        return "ok " + lines[0]


def make_controller(windows, sender=None, **kwargs):
    kwargs.setdefault("focus_guard", lambda timeout: contextlib.nullcontext())
    return deck.Controller(windows, sender, **kwargs)


def execute(controller, action):
    if action in ("approve", "deny"):
        usage = 0x0A if action == "approve" else 0x09
        modifiers = () if action == "approve" else ("ctrl",)
        event = {"hwnd": controller.windows()[0], "window": controller.windows(), "t": controller.monotonic(),
                 "usage": usage, "pressed": frozenset((usage,)),
                 "modifiers": modifiers, "new_modifiers": modifiers}
        binding = "hid:0x0A" if action == "approve" else "ctrl+hid:0x09"
        return controller.execute(action, event=event, binding=binding)
    return controller.execute(action)


def raises(error, call):
    try:
        call()
    except error:
        return
    raise AssertionError("expected " + error.__name__)


def test_mapping():
    mapping = deck.load_map(backend="rawinput")
    assert mapping == {
        "vk:0x45": "slot 1", "vk:0x42": "slot 2", "ctrl+vk:0x5A": "slot 3",
        "vk:0x20": "slot 4", "vk:0x47": "approve", "ctrl+vk:0x46": "deny",
        "vk:0x48": "next_wait", "vk:0x4C": "auto", "vk:0xDD": "cycle +1", "vk:0xDB": "cycle -1"}
    fallback = json.loads(deck.DEFAULT_MAP.read_text(encoding="utf-8"))["_f13_f22_bindings"]
    assert [fallback["vk:0x%02X" % key] for key in range(0x7C, 0x86)] == [
        "slot 1", "slot 2", "slot 3", "slot 4", "approve", "deny",
        "cycle +1", "cycle -1", "next_wait", "auto"]
    for key in ("wheel:+1", "consumer:0x00E9"):
        assert fallback[key] == "cycle +1"
    for key in ("wheel:-1", "consumer:0x00EA"):
        assert fallback[key] == "cycle -1"
    assert deck.normalize_key("VK:0x7c") == "vk:0x7C"
    assert deck.normalize_key("scan:0x64:2") == "scan:0x0064:2"
    assert deck.normalize_key("ALT+Ctrl+VK:0x5a") == "ctrl+alt+vk:0x5A"
    assert deck.normalize_key("win+shift+scan:0x64:2") == "shift+win+scan:0x0064:2"
    assert deck.parse_action(" cycle -1 ") == ("cycle", -1)
    for tool in ("cc", "cx", "ds"):
        assert deck.parse_action(" tool %s " % tool) == ("tool", tool)
    for action in ("slot 0", "slot 9", "cycle 2", "cycle 1", "approve now", "exec cmd", [], None,
                   "tool", "tool CC", "tool unknown", "tool cc-a", "tool cc extra"):
        raises(ValueError, lambda: deck.parse_action(action))
    for key in ("vk:0x100", "vk:0x0", "scan:0x64:1", "wheel:0", "F13", None,
                "ctrl+ctrl+vk:0x5A", "meta+vk:0x5A", "+vk:0x5A", "ctrl+consumer:0x00E9", "alt+wheel:+1"):
        raises(ValueError, lambda: deck.normalize_key(key))
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "map.json"
        for text in ('{"version":1,"bindings":{"vk:0x7c":"auto","vk:0x7C":"deny"}}',
                     '{"version":1,"bindings":{"ctrl+alt+vk:0x5a":"auto","ALT+CTRL+vk:0x5A":"deny"}}',
                     '{"version":1,"bindings":{"vk:0x7C":"auto","vk:0x7C":"deny"}}',
                     '{"version":2,"bindings":{}}', '{"version":1,"bindings":[]}'):
            path.write_text(text, encoding="utf-8")
            raises(ValueError, lambda: deck.load_map(path))
        path.write_text(json.dumps({"version": 1, "bindings": {"scan:0x64:0": "auto"}}), encoding="utf-8")
        assert deck.load_map(path) == {"scan:0x0064:0": "auto"}


def test_list_and_selection():
    sessions = deck.parse_sessions(REPLY)
    assert [s.key for s in sessions] == ["cc-a", "cx-b", "cc-c", "cx-d"]
    assert sessions[-1].name == "project with spaces"
    assert deck.parse_sessions("ok list n=0") == []
    for reply in ("", "cc-a wait app", "ok list n=2\ncc-a wait app", "ok list n=0\nok list n=0",
                  "ok list n=1\ncc-a unknown app", "ok list n=2\ncc-a wait app\ncc-a wait notes",
                  "ok list n=1\nx;bad wait app"):
        raises(ValueError, lambda: deck.parse_sessions(reply))
    assert deck.select_session(sessions, "slot 2").key == "cx-b"
    assert deck.select_session(sessions, "slot 8") is None
    assert deck.select_session(sessions, "cycle +1").key == "cc-a"
    assert deck.select_session(sessions, "cycle -1").key == "cx-d"
    assert deck.select_session(sessions, "cycle +1", "cx-d").key == "cc-a"
    assert deck.select_session(sessions, "cycle -1", "cc-a").key == "cx-d"
    assert deck.select_session(sessions, "next_wait", "cc-a").key == "cc-c"
    assert deck.select_session(sessions, "next_wait", "cc-c").key == "cc-a"
    assert deck.select_session(sessions, "next_wait", "missing").key == "cc-a"
    assert deck.select_session([s for s in sessions if s.state != "wait"], "next_wait") is None
    assert deck.select_session([], "cycle +1") is None


def test_tool_selection_count_prefix_and_rotation():
    for tool in ("cc", "cx", "ds"):
        action = "tool " + tool
        assert deck.select_session([], action) is None
        unrelated = [deck.Session(tool, "wait", "bare"),
                     deck.Session(tool + "x-other", "wait", "wrong-prefix")]
        assert deck.select_session(unrelated, action) is None
        first = deck.Session(tool + "-first", "idle", "first")
        second = deck.Session(tool + "-second", "wait", "second")
        third = deck.Session(tool + "-third", "think", "third")
        assert deck.select_session(unrelated + [first], action) == first
        assert deck.select_session([first], action, first.key) == first
        sessions = [first, unrelated[0], second, unrelated[1], third]
        assert deck.select_session(sessions, action) == second
        assert deck.select_session(sessions, action, first.key) == second
        assert deck.select_session(sessions, action, second.key) == third
        assert deck.select_session(sessions, action, third.key) == first
        assert deck.select_session(sessions, action, "missing") == second


def test_tool_priority_and_newest_tie():
    states = ("wait", "error", "tool", "think", "done", "idle")
    for tool in ("cc", "cx", "ds"):
        action = "tool " + tool
        for higher_index, higher in enumerate(states):
            first = deck.Session(tool + "-first", higher, "first")
            newer = deck.Session(tool + "-newer", higher, "newer")
            assert deck.select_session([first, newer], action) == newer
            assert deck.select_session([newer, first], action) == first
            for lower in states[higher_index + 1:]:
                other = deck.Session(tool + "-other", lower, "other")
                assert deck.select_session([first, other], action) == first
                assert deck.select_session([other, first], action) == first
        # An urgent session belonging to another tool cannot win this selection.
        outsider = deck.Session("other-urgent", "wait", "outsider")
        assert deck.select_session([first, outsider], action, outsider.key) == first


def test_tool_actions_hold_and_cycle_origin():
    with tempfile.TemporaryDirectory() as folder:
        hold = Path(folder) / ".deck_hold"
        windows, sender = Windows((0, "", "")), Sender()
        windows.items = [(1, "Code.exe", "app Claude"), (2, "Code.exe", "app-server Codex"),
                         (3, "Code.exe", "notes Claude")]
        controller = make_controller(windows, sender, hold_path=hold)
        assert not hold.exists()
        assert execute(controller, "tool cc") == "focus cc-c; foreground ok"
        assert controller.selected == "cc-c" and windows.activated == [3]
        assert sender.calls == ["list", "focus cc-c"] and hold.exists()
        for action, expected in (("cycle +1", "cx-d"), ("cycle -1", "cc-c"),
                                 ("tool cc", "cc-a"), ("cycle -1", "cx-d"),
                                 ("cycle +1", "cc-a"), ("tool cx", "cx-b")):
            os.utime(hold, (1, 1))
            assert execute(controller, action).startswith("focus " + expected + ";")
            assert controller.selected == expected and hold.stat().st_mtime > 1
        # A missing tool clears the old selected key, renews hold, and never activates a window.
        activated = windows.activated[:]
        os.utime(hold, (1, 1))
        assert execute(controller, "tool ds") == "focus ds; no session"
        assert sender.calls[-2:] == ["list", "focus ds"]
        assert controller.selected is None and windows.activated == activated
        assert hold.stat().st_mtime > 1
        assert execute(controller, "auto") == "focus -"
        assert not hold.exists() and controller.selected is None
        assert execute(controller, "auto") == "focus -"  # No hold is also valid.
        # Empty list still focuses the requested tool instead of retaining an older tool.
        sender.reply = "ok list n=0"
        for tool in ("cc", "cx", "ds"):
            assert execute(controller, "tool " + tool) == "focus %s; no session" % tool
            assert sender.calls[-1] == "focus " + tool
            assert hold.exists() and controller.selected is None
        # Invalid list is blocked, rather than mistaken for a tool with zero sessions.
        hold.unlink()
        sender.reply = "ok list n=1"
        assert execute(controller, "tool cc").startswith("blocked:")
        assert sender.calls[-1] == "list" and not hold.exists()
        sender.reply = "ok list n=1\ncc-only idle solo"
        windows.items = []
        for unused in range(2):
            assert execute(controller, "tool cc") == "focus cc-only; no matching window"
            assert controller.selected == "cc-only" and hold.exists()


def test_tool_focus_resists_daemon_follow():
    with tempfile.TemporaryDirectory() as folder:
        hold = Path(folder) / ".deck_hold"
        windows, sender = Windows(), Sender()
        controller = make_controller(windows, sender, hold_path=hold)
        watcher = deck.daemon.ForegroundWatcher(windows, sender)
        watcher.hold_file = str(hold)
        for action in ("tool cx", "tool cc", "tool ds", "cycle +1", "next_wait"):
            assert execute(controller, action).startswith("focus ")
            before = sender.calls[:]
            for elapsed in (0.6, 3.0):
                with patch.object(deck.daemon.time, "time", return_value=hold.stat().st_mtime + elapsed):
                    assert watcher.tick(now=elapsed) is None
                assert sender.calls == before
        assert execute(controller, "auto") == "focus -"
        assert not hold.exists()
        assert watcher.tick(now=4.0) == "cc-a"
        assert sender.calls[-2:] == ["list", "focus cc-a"]


def live_selftest_module():
    path = Path(__file__).resolve().parents[1] / "research" / "selftest_deck_live.py"
    spec = importlib.util.spec_from_file_location("selftest_deck_live", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_selftest_dump_parsing():
    live = live_selftest_module()

    def dump(top=b"Claude TOOL>", project=b"zz-st1", icons=b"\x7e\x04\x07."):
        rows = [b"\x00\x01 " + top.ljust(13), b"\x02\x03 " + project.ljust(8) + b" " + icons]
        return "dump\nok dump %s %s -\r\n" % tuple(row.hex() for row in rows)

    reply = dump()
    assert live.parse_screen(reply) == ("Claude", "zz-st1", "tool")
    assert live.parse_screen(dump(b"Codex >YOU<", b"zz-cx", b"    ")) == ("Codex", "zz-cx", "wait")
    assert live.parse_screen(dump(b"DSK THINK\x07", b"zz-ds")) == ("DSK", "zz-ds", "think")
    for bad in ("", "ok dump bad data", reply + reply, reply.replace("ok dump", "err dump"),
                dump(b"Agent READY")):
        raises(ValueError, lambda: live.parse_screen(bad))
    # A real title containing only the tool name must never trigger activation.
    with patch.object(live.WindowControl, "__init__", return_value=None), \
            patch.object(live.WindowControl, "windows", return_value=[
                (1, "Code.exe", "Claude"), (2, "Code.exe", "h1 - Codex"),
                (3, "Code.exe", "zz-st1 - Claude")]):
        assert live.TestWindows().windows() == [(3, "Code.exe", "zz-st1 - Claude")]


def test_live_selftest_offline_success_and_failure_cleanup():
    from test_ui import make_ui
    live = live_selftest_module()
    original = (deck.Session("cc-saved", "error", "original project"),
                deck.Session("ds-saved", "idle", "saved"))
    for failure in (None, "late drift", "setup", "restore", "missing ack", "bad initial list"):
        with tempfile.TemporaryDirectory() as folder:
            hold = Path(folder) / ".deck_hold"
            hold.write_text("existing hold", encoding="utf-8")
            ui, unused_lcd, unused_lights = make_ui()
            for session in original:
                ui.handle("set %s %s %s" % session, 0)
            clock, commands, dump_times = [0.0], [], []

            def sender(lines, **kwargs):
                assert kwargs["wait_reply"] >= 0.3
                replies = []
                for command in lines:
                    commands.append(command)
                    if failure == "bad initial list" and commands == ["list"]:
                        return "ok list n=2\ncc-incomplete wait original"
                    if failure == "setup" and command.startswith("set cc-test1 "):
                        raise OSError("fake setup failure")
                    if failure == "restore" and command.startswith("set cc-saved "):
                        return "err set: fake restoration failure"
                    if command == "dump":
                        dump_times.append(clock[0])
                        if failure == "late drift" and len(dump_times) == 2:
                            ui.handle("focus cx-test1", round(clock[0] * 1000))
                        ui.render(round(clock[0] * 1000))
                    reply = ui.handle(command, round(clock[0] * 1000))
                    if failure == "missing ack" and command == "focus cc-test1":
                        reply = ""
                    replies.append(reply)
                return "\n".join(replies)

            def sleep(seconds):
                assert seconds >= 0
                clock[0] += seconds

            windows = Windows((0, "", ""))
            windows.items = []
            with contextlib.redirect_stdout(io.StringIO()) as output, \
                    patch.object(deck.agent_lcd.serial, "Serial", side_effect=AssertionError("serial forbidden")):
                code = live.main(sender=sender, windows=windows, hold_path=hold,
                                 sleep=sleep, monotonic=lambda: clock[0])
            text = output.getvalue()
            if failure is None:
                assert code == 0 and "9 passed, 0 failed" in text and "FAIL" not in text
            else:
                assert code != 0 and "FAIL" in text
            if failure == "bad initial list":
                assert commands == ["list"] and hold.read_text(encoding="utf-8") == "existing hold"
            else:
                assert not hold.exists() and commands[-1] == "list"
                restored = deck.parse_sessions(ui.handle("list", round(clock[0] * 1000)))
                if failure == "restore":
                    assert restored == list(original[1:]) and "restore" in text
                else:
                    assert restored == list(original)
            if failure in (None, "late drift", "missing ack"):
                assert len(dump_times) == 16
                for index in range(8):
                    assert abs(dump_times[index * 2 + 1] - dump_times[index * 2] - 2.4) < 1e-6
                    if failure != "missing ack":
                        assert abs(dump_times[index * 2] - (index * 3 + 0.6)) < 1e-6


def test_actions_and_logging():
    with tempfile.TemporaryDirectory() as folder:
        windows, sender = Windows(), Sender()
        controller = make_controller(windows, sender, hold_path=Path(folder) / ".deck_hold")
        with patch.object(deck.log, "debug") as logged:
            assert execute(controller, "slot 2") == "focus cx-b; foreground ok"
            logged.assert_called_once()
            assert logged.call_args.args[0] == "%s -> %s"
        assert sender.calls == ["list", "focus cx-b"] and windows.activated == [2]
        assert execute(controller, "next_wait").startswith("focus cc-c;")
        assert execute(controller, "cycle +1").startswith("focus cx-d;")
        assert execute(controller, "cycle +1").startswith("focus cc-a;")
        assert execute(controller, "slot 8") == "no matching session"
        assert controller.selected == "cc-a"
        assert execute(controller, "auto") == "focus -" and controller.selected is None
        assert sender.calls[-1] == "focus -"
        windows.items = []
        assert execute(controller, "slot 1") == "focus cc-a; no matching window"
        windows.items = [(7, "Code.exe", "app - Claude")]
        windows.activate_ok = False
        assert execute(controller, "slot 1").endswith("denied by Windows")
        sender.reply = "ok list n=4"
        assert execute(controller, "approve").startswith("blocked:")
        assert windows.keys == []
        controller.sender = lambda *args, **kw: (_ for _ in ()).throw(OSError("fake serial busy"))
        assert "fake serial busy" in execute(controller, "approve")
        assert execute(controller, "bad action").startswith("blocked:")


def test_approval_guards():
    with tempfile.TemporaryDirectory() as folder:
        windows, sender = Windows(), Sender()
        controller = make_controller(windows, sender, hold_path=Path(folder) / ".deck_hold")
        assert execute(controller, "approve") == "sent Enter to cc-a"
        assert execute(controller, "deny") == "sent Esc to cc-a"
        assert windows.keys == [0x0D, 0x1B]
        windows.keys.clear()
        for window in ((1, "firefox.exe", "app Claude"), (1, "notepad.exe", "app"),
                       (1, "Code.exe", "unrelated"), (2, "Code.exe", "app-server Codex"),
                       (0, "Code.exe", "app Claude"), (1, "Code.exe", "Claude")):
            windows.window = window
            for action in ("approve", "deny"):
                assert execute(controller, action).startswith("blocked:")
        assert windows.keys == []
        sender.reply = "ok list n=1\ncc-a wait app"
        for title in ("happy - Visual Studio Code", "app - Codex", "app - Claude and Codex", "myapp"):
            windows.window = (1, "Code.exe", title)
            assert execute(controller, "approve").startswith("blocked:")
            assert execute(controller, "deny").startswith("blocked:")
        assert windows.keys == []
        windows.window = (1, "Code.exe", "app Claude")
        for state in ("idle", "think", "tool", "done", "error"):
            sender.reply = "ok list n=1\ncc-a %s app" % state
            assert execute(controller, "approve").startswith("blocked:")
            assert execute(controller, "deny").startswith("blocked:")
        sender.reply = "ok list n=2\ncc-a wait app\ncc-other wait app"
        assert execute(controller, "approve").startswith("blocked:")
        sender.reply = "ok list n=2\ncc-a wait app\ncx-b wait app"
        assert execute(controller, "approve").startswith("sent Enter")  # 标题工具消除跨工具歧义。
        windows.keys.clear()
        sender.reply = REPLY
        sender.on_list = lambda: setattr(windows, "window", (3, "Code.exe", "notes Claude"))
        assert "window context changed" in execute(controller, "approve")
        assert windows.keys == []
        sender.on_list = lambda: None
        windows.key_ok = False
        assert "guard failed" in execute(controller, "deny")


def test_window_matching_and_input():
    sessions = deck.parse_sessions(REPLY)
    assert deck.match_session((1, "Code.exe", "app-server"), sessions) is None
    assert deck.match_session((1, "Code.exe", "Codex"), sessions) is None
    assert deck.match_session((1, "Code.exe", "Codex"), sessions[:2]) is None
    assert deck.find_window(sessions[0], [(9, "firefox.exe", "app Claude"),
                                        (8, "Code.exe", "Claude"), (7, "Code.exe", "app Claude")], sessions)[0] == 7
    assert deck.find_window(sessions[0], [(8, "Code.exe", "Claude")], sessions) is None
    assert deck.find_window(sessions[0], [(8, "Code.exe", "notes - Claude")], sessions) is None
    assert deck.find_window(sessions[1], [(8, "ChatGPT.exe", "app-server Codex")], sessions)[0] == 8
    assert deck.match_session((8, "ChatGPT.exe", "app-server Codex"), sessions) is None
    same_project = [deck.Session("cc-a", "wait", "app"), deck.Session("cx-b", "wait", "app")]
    assert deck.match_title("app - Codex", same_project).key == "cx-b"
    assert deck.daemon.map_target("Code.exe", "app - Codex", [(s.key, s.name) for s in same_project]) == "cx-b"
    assert deck.daemon.map_target("Code.exe", "happy", [("cc-a", "app")]) == "-"
    expected = (1, "Code.exe", "app")
    window = deck_windows.WindowControl.__new__(deck_windows.WindowControl)
    sent = []
    window.user = SimpleNamespace(GetAsyncKeyState=lambda key: 0,
                                  SendInput=lambda count, events, size: sent.append((count, events, size)) or count)
    with patch.object(deck_windows.WindowControl, "__call__", return_value=expected):
        assert window.send_key(0x0D, expected)
        count, events, size = sent[-1]
        assert count == 2 and size == ctypes.sizeof(deck_windows.INPUT)
        assert [(e.type, e.ki.wVk, e.ki.dwFlags) for e in events] == [(1, 0x0D, 0), (1, 0x0D, 2)]
        window.user.GetAsyncKeyState = lambda key: 0x8000 if key == 0x11 else 0
        assert not window.send_key(0x0D, expected)
        assert len(sent) == 1
    window.user.GetAsyncKeyState = lambda key: 0
    with patch.object(deck_windows.WindowControl, "__call__", return_value=(2, "Code.exe", "other")):
        assert not window.send_key(0x1B, expected)
        assert len(sent) == 1
    # Win64 INPUT union 必须含 MOUSEINPUT，否则 SendInput cbSize 错误。
    assert ctypes.sizeof(deck_windows.INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


def test_foreground_fallback_cleanup():
    window = deck_windows.WindowControl.__new__(deck_windows.WindowControl)
    calls = []
    foreground = [10]
    attempts = [False, True]

    def activate(hwnd):
        ok = attempts.pop(0)
        if ok:
            foreground[0] = hwnd
        return ok

    window.user = SimpleNamespace(IsIconic=lambda hwnd: True,
                                  ShowWindow=lambda hwnd, flag: calls.append(("show", hwnd, flag)),
                                  SetForegroundWindow=activate, GetForegroundWindow=lambda: foreground[0],
                                  GetWindowThreadProcessId=lambda hwnd, unused: hwnd + 100,
                                  AttachThreadInput=lambda a, b, on: calls.append((a, b, on)) or True)
    window.kernel = SimpleNamespace(GetCurrentThreadId=lambda: 1000)
    assert window.activate(20)
    attached = [(a, b) for a, b, on in calls if a != "show" and on is True]
    detached = [(a, b) for a, b, on in calls if a != "show" and on is False]
    assert sorted(attached) == sorted(detached) and len(attached) == 2


def _foreground_retry_window(attempts, sent=1, minimized=False):
    window = deck_windows.WindowControl.__new__(deck_windows.WindowControl)
    calls = []
    foreground = [10]
    attempts = iter(attempts)

    def activate(hwnd):
        calls.append(("foreground", hwnd))
        ok = next(attempts)
        if ok:
            foreground[0] = hwnd
        return ok

    def send_input(count, events, size):
        event = ctypes.cast(events, ctypes.POINTER(deck_windows.INPUT))[0]
        calls.append(("send", count, event.type, event.mi.dx, event.mi.dy,
                      event.mi.mouseData, event.mi.dwFlags, event.mi.time,
                      event.mi.dwExtraInfo, size))
        return sent

    window.user = SimpleNamespace(
        IsIconic=lambda hwnd: minimized,
        ShowWindow=lambda hwnd, flag: calls.append(("show", hwnd, flag)),
        SetForegroundWindow=activate, GetForegroundWindow=lambda: foreground[0],
        GetWindowThreadProcessId=lambda hwnd, unused: hwnd + 100,
        AttachThreadInput=lambda a, b, on: calls.append(("attach", a, b, on)) or True,
        SendInput=send_input)
    window.kernel = SimpleNamespace(GetCurrentThreadId=lambda: 1000)
    return window, calls


def test_foreground_mouse_retry():
    window, calls = _foreground_retry_window([False, False, True])
    assert window.activate(20)
    assert [call for call in calls if call[0] == "send"] == [
        ("send", 1, 0, 0, 0, 0, 1, 0, 0, ctypes.sizeof(deck_windows.INPUT))]
    assert len([call for call in calls if call[0] == "foreground"]) == 3
    attached = [call[1:3] for call in calls if call[0] == "attach" and call[3]]
    detached = [call[1:3] for call in calls if call[0] == "attach" and not call[3]]
    assert sorted(attached) == sorted(detached) and len(attached) == 2
    assert calls.index(next(call for call in calls if call[0] == "send")) > max(
        index for index, call in enumerate(calls) if call[0] == "attach")


def test_foreground_mouse_retry_send_failure():
    window, calls = _foreground_retry_window([False, False], sent=0)
    assert not window.activate(20)
    assert len([call for call in calls if call[0] == "foreground"]) == 2
    assert calls[-1][0] == "send"
    attached = [call[1:3] for call in calls if call[0] == "attach" and call[3]]
    detached = [call[1:3] for call in calls if call[0] == "attach" and not call[3]]
    assert sorted(attached) == sorted(detached) and len(attached) == 2


def test_foreground_mouse_retry_failure_cleanup():
    window, calls = _foreground_retry_window([False, False, False, False])
    assert not window.activate(20)
    assert len([call for call in calls if call[0] == "foreground"]) == 4
    assert len([call for call in calls if call[0] == "send"]) == 1
    attached = [call[1:3] for call in calls if call[0] == "attach" and call[3]]
    detached = [call[1:3] for call in calls if call[0] == "attach" and not call[3]]
    assert sorted(attached) == sorted(detached) and len(attached) == 4


def test_foreground_first_attempt_skips_mouse_retry():
    window, calls = _foreground_retry_window([True])
    assert window.activate(20)
    assert calls == [("foreground", 20)]


def test_foreground_restores_before_activation():
    window, calls = _foreground_retry_window([True], minimized=True)
    assert window.activate(20)
    assert calls == [("show", 20, 9), ("foreground", 20)]


def test_single_instance_and_daemon_launch():
    calls = []
    occupied = [False]

    class Socket:
        def setsockopt(self, *args):
            calls.append("exclusive")

        def bind(self, address):
            assert address == ("127.0.0.1", 47614)
            if occupied[0]:
                raise OSError("fake occupied")
            occupied[0] = True
            self.owner = True

        def close(self):
            if getattr(self, "owner", False):
                occupied[0] = False
            calls.append("close")

    with patch.object(deck.socket, "socket", Socket):
        first, second = deck.SingleInstance(), deck.SingleInstance()
        assert first.acquire() and first.acquire()
        assert not second.acquire()
        with patch.object(deck.subprocess, "Popen") as launch:
            assert not deck.ensure_running()
            assert deck.run() == 0  # 不会创建 Win32 / RawInput 或打开串口。
            launch.assert_not_called()
        first.close()
        assert second.acquire()
        second.close()
        second.close()
        with patch.object(deck.subprocess, "Popen") as launch:
            assert deck.ensure_running()
            assert launch.call_args.args[0][-1] == "run"
            assert launch.call_args.kwargs["creationflags"] & 0x08000000
    assert occupied[0] is False
    # daemon 的可选启动路径；其余外部服务全部替换。
    fake_lock = SimpleNamespace(setsockopt=lambda *args: None, bind=lambda addr: None, close=lambda: None)
    with patch.object(deck.daemon.socket, "socket", return_value=fake_lock), \
            patch.object(deck.daemon.dsh_watch, "Watcher", return_value=SimpleNamespace(key_for_title=lambda _: None)), \
            patch.object(deck.daemon, "ForegroundWindow", return_value=None), \
            patch.object(deck.daemon, "ForegroundWatcher", side_effect=KeyboardInterrupt), \
            patch.object(deck, "ensure_running") as ensure, \
            patch.object(deck.daemon.logging, "basicConfig"), \
            patch.object(deck.daemon.sys, "argv", ["daemon.py", "--deck"]):
        deck.daemon.main(verbose=True)
        ensure.assert_called_once()


def test_cli_and_learn():
    with contextlib.redirect_stdout(io.StringIO()) as output:
        deck.learn_event({"keys": ("vk:0x7C", "scan:0x0064:0"), "kind": "keyboard",
                          "vkey": 124, "make_code": 100, "flags": 0})
    assert "vk:0x7C" in output.getvalue() and "make_code=100" in output.getvalue()
    with patch.object(deck, "run", return_value=0) as run, patch.object(deck.logging, "basicConfig"):
        assert deck.main(["run", "-v"]) == 0
        run.assert_called_once_with(deck.DEFAULT_MAP, exclusive=False, backend="auto")
        run.reset_mock()
        assert deck.main(["run", "--no-exclusive", "-v"]) == 0
        run.assert_called_once_with(deck.DEFAULT_MAP, exclusive=False, backend="auto")
        run.reset_mock()
        assert deck.main(["run", "--backend", "rawinput", "--exclusive", "-v"]) == 0
        run.assert_called_once_with(deck.DEFAULT_MAP, exclusive=True, backend="rawinput")


def test_run_event_dispatch_and_cleanup():
    with tempfile.TemporaryDirectory() as folder, \
            patch.object(deck.daemon, "DECK_HOLD", str(Path(folder) / ".deck_hold")):
        import deck_input
        windows, sender, calls = Windows(), Sender(), []

        class Lock:
            def acquire(self):
                calls.append("lock")
                return True

            def close(self):
                calls.append("close")

        class Input:
            def __init__(self, callback, exclusive):
                self.callback = callback
                calls.append(("exclusive", exclusive))

            def run(self):
                # Exiting cancels unexecuted work, so let each event finish first.
                for event in ({"keys": ("vk:0x45", "scan:0x0012:0")},
                              {"keys": ("vk:0x47",), "vkey": 0x47, "pressed": frozenset((0x47,)), "modifiers": ()},
                              {"keys": ("vk:0xDD",)}, {"keys": ("vk:0x01",)}):
                    self.callback(event)
                    self.callback.__self__.events.join()

        with patch.object(deck, "SingleInstance", Lock), \
                patch.object(deck_input, "RawInput", Input), \
                patch.object(deck_windows, "WindowControl", return_value=windows), \
                patch.object(deck.agent_lcd, "send", sender):
            assert deck.run(backend="rawinput", exclusive=True) == 0
        assert calls == ["lock", ("exclusive", True), "close"]
        assert sender.calls == ["list", "focus cc-a", "list", "list", "focus cx-b"], sender.calls
        assert windows.keys == [0x0D] and windows.activated == [1, 2]
        calls.clear()
        with patch.object(deck, "SingleInstance", Lock), \
                patch.object(deck_input, "RawInput", Input), \
                patch.object(deck_windows, "WindowControl", return_value=windows), \
                patch.object(deck.agent_lcd, "send", sender):
            assert deck.run(backend="rawinput", exclusive=False) == 0
        assert calls == ["lock", ("exclusive", False), "close"]
        calls.clear()
        with patch.object(deck, "SingleInstance", Lock), \
                patch.object(deck_input, "RawInput", Input), \
                patch.object(deck_windows, "WindowControl", return_value=windows), \
                patch.object(deck, "load_map", side_effect=ValueError("fake invalid map")):
            raises(ValueError, deck.run)
        assert calls == ["lock", "close"]


def test_action_queue_combo_priority_and_isolation():
    import deck_input
    actions, logged, threads = [], [], []
    bindings = {"ctrl+vk:0x5A": "slot 3", "vk:0x5A": "auto", "vk:0x45": "slot 1",
                "alt+scan:0x0026:0": "deny", "vk:0x4C": "auto", "vk:0x12": "next_wait"}
    controller = SimpleNamespace(execute=lambda action, **kwargs: (actions.append(action), threads.append(threading.get_ident())))
    state = deck_input.EventState()
    dispatcher = deck.ActionQueue(bindings, controller)

    def put(event):
        # One event at a time: this test is about bindings, not coalescing.
        dispatcher.events.put(event)
        dispatcher.events.join()

    with patch.object(deck.log, "debug", side_effect=lambda *args: logged.append(args)):
        dispatcher.thread.start()
        try:
            # Main-keyboard Ctrl (different handle) must not alter deck shortcuts.
            state.keyboard(2, 0x11, 29, 0)
            for args in ((1, 0x5A, 44, 0), (1, 0x5A, 44, 1),
                         (1, 0x11, 29, 0), (1, 0x5A, 44, 0), (1, 0x5A, 44, 0),
                         (1, 0x5A, 44, 1), (1, 0x11, 29, 1),
                         (1, 0x12, 56, 0), (1, 0x4C, 38, 0), (1, 0x4C, 38, 1),
                         (1, 0x12, 56, 1), (1, 0x45, 18, 0), (1, 0x45, 18, 0)):
                for event in state.keyboard(*args):
                    put(event)
            put({"keys": ("vk:0x01",)})
            put({"kind": "hook", "decision": "suppressed", "keys": ("vk:0x45",)})
            put({"kind": "hook", "decision": "other-device", "keys": ("vk:0x41",)})
            put({"kind": "hook", "decision": "timeout", "keys": ("vk:0x42",)})
        finally:
            dispatcher.close()
    assert actions == ["auto", "slot 3", "next_wait", "deny", "slot 1"]
    assert threads and all(thread != threading.get_ident() for thread in threads)
    assert not dispatcher.thread.is_alive()
    assert any(row[0] == "unbound %s" and row[1] == ("vk:0x01",) for row in logged)
    assert any(row[:2] == ("hook %s %s", "suppressed") for row in logged)
    assert not any(len(row) > 1 and row[1] in ("other-device", "timeout") for row in logged)


def test_run_action_thread_and_error_cleanup():
    import deck_input
    entered, release = threading.Event(), threading.Event()
    calls = []
    origin = threading.get_ident()

    class Input:
        def __init__(self, callback, exclusive):
            assert exclusive is True
            self.callback = callback

        def run(self):
            self.callback({"keys": ("vk:0x45",)})
            assert entered.wait(1), "action worker did not start"
            assert not release.is_set()
            self.callback({"keys": ("vk:0x42",)})
            raise RuntimeError("fake input failure")

    def execute(action):
        assert threading.get_ident() != origin
        calls.append(action)
        entered.set()
        assert release.wait(1)

    original_close = deck.ActionQueue.close

    def close(self):
        # Release the in-flight action only after exit has been requested.
        self._stop.set()
        release.set()
        original_close(self)

    lock = SimpleNamespace(acquire=lambda: True, close=lambda: calls.append("closed"))
    with patch.object(deck, "SingleInstance", return_value=lock), \
            patch.object(deck_input, "RawInput", Input), \
            patch.object(deck_windows, "WindowControl"), \
            patch.object(deck.Controller, "execute", side_effect=execute):
        with patch.object(deck.ActionQueue, "close", close):
            raises(RuntimeError, lambda: deck.run(backend="rawinput", exclusive=True))
    # The in-flight action finishes, but the queued slot 2 is cancelled at exit.
    assert calls == ["slot 1", "closed"]
    assert not any(thread.name in ("AgentDeck actions", "AgentDeck hold")
                   for thread in threading.enumerate())


def test_review_project_and_tool_must_both_match():
    with tempfile.TemporaryDirectory() as folder:
        sender = Sender("ok list n=1\ncx-a wait project-A")
        windows = Windows((1, "Code.exe", "project-B - Codex"))
        controller = make_controller(windows, sender, hold_path=Path(folder) / "hold")
        for action in ("approve", "deny"):
            assert execute(controller, action).startswith("blocked:"), action
        assert windows.keys == []
    sessions = [deck.Session("cc-a", "wait", "project-A")]
    assert deck.find_window(sessions[0], [(2, "ChatGPT.exe", "project-A")], sessions) is None
    assert deck.find_window(sessions[0], [(2, "Code.exe", "Claude")], sessions) is None


def test_review_approval_uses_press_context_and_expires_during_query():
    with tempfile.TemporaryDirectory() as folder:
        windows, sender, clock = Windows(), Sender(), [10.0]
        controller = make_controller(windows, sender, hold_path=Path(folder) / "hold",
                                     monotonic=lambda: clock[0])
        event = {"hwnd": 1, "window": (1, "Code.exe", "app Claude"), "t": 10.0, "usage": 0x0A,
                 "pressed": frozenset((0x0A,)), "modifiers": (), "new_modifiers": ()}
        assert "missing event context" in controller.execute("approve")
        windows.window = (3, "Code.exe", "notes Claude")
        assert "window context changed" in controller.execute("approve", event, "hid:0x0A")
        assert sender.calls == [] and windows.keys == []
        windows.window = (1, "Code.exe", "app Claude")
        clock[0] = 11.01
        assert "expired" in controller.execute("approve", event, "hid:0x0A")
        assert sender.calls == []
        clock[0] = 10.0
        sender.on_list = lambda: clock.__setitem__(0, 11.01)
        assert "expired" in controller.execute("approve", event, "hid:0x0A")
        assert windows.keys == []
        sender.on_list = lambda: None
        clock[0] = 11.0  # The specified one-second boundary is inclusive.
        assert controller.execute("approve", event, "hid:0x0A") == "sent Enter to cc-a"


def test_review_usb_queue_blocks_navigation_and_approval_in_same_report():
    from deck_usb import ReportState
    from test_deck_usb import report
    with tempfile.TemporaryDirectory() as folder:
        windows, sender = Windows(), Sender("ok list n=2\ncc-a wait app\ncx-b wait app-server")
        controller = make_controller(windows, sender, hold_path=Path(folder) / "hold")
        dispatcher = deck.ActionQueue(deck.load_map(), controller)
        # Navigation can change the foreground before the queued approve runs.
        def activate(hwnd):
            windows.activated.append(hwnd)
            windows.window = next(window for window in windows.items if window[0] == hwnd)
            return True
        windows.activate = activate
        for event in ReportState().feed(report(0x05, 0x0A)):
            dispatcher.enqueue(event)
        with patch.object(deck.log, "debug") as logged:
            dispatcher.thread.start()
            dispatcher.events.join()  # Closing cancels unexecuted events.
            dispatcher.close()
        assert windows.activated == [2] and windows.keys == []
        assert any(call.args[1] == "approve" and call.args[2].startswith("blocked:")
                   for call in logged.call_args_list if len(call.args) == 3)
        # Even if no navigation actually changes HWND, the shared report is unsafe.
        windows.window = (1, "Code.exe", "app Claude")
        event = {"hwnd": 1, "window": windows.window, "t": controller.monotonic(), "usage": 0x0A,
                 "pressed": frozenset((0x05, 0x0A)), "modifiers": (), "other_bound": True}
        assert "other bound" in controller.execute("approve", event, "hid:0x0A")


def test_review_usb_modifier_overlap_and_sensitive_exact_binding():
    from deck_usb import ReportState
    from test_deck_usb import report
    with tempfile.TemporaryDirectory() as folder:
        windows, sender = Windows(), Sender()
        controller = make_controller(windows, sender, hold_path=Path(folder) / "hold")
        dispatcher = deck.ActionQueue(deck.load_map(), controller)
        state = ReportState()
        for packet in (report(0x1D, modifiers=1), report(0x1D, 0x09, modifiers=1)):
            for event in state.feed(packet):
                dispatcher.enqueue(event)
        with patch.object(deck.log, "debug") as logged:
            dispatcher.thread.start()
            dispatcher.events.join()  # Closing cancels unexecuted events.
            dispatcher.close()
        results = [call.args[1:3] for call in logged.call_args_list if len(call.args) == 3]
        assert [action for action, result in results] == ["tool ds", "cycle -1"]
        assert windows.keys == []
        for packet in (report(0x0A, modifiers=2), report(0x0A, 0x70)):
            event = next(e for e in ReportState().feed(packet) if not e["modifier"])
            event.update(hwnd=1, window=windows.window, t=controller.monotonic())
            assert controller.execute("approve", event, "hid:0x0A").startswith("blocked:")
        # A fresh, sole Ctrl+F remains a valid intentional deny.
        event = next(e for e in ReportState().feed(report(0x09, modifiers=1)) if not e["modifier"])
        event.update(hwnd=1, window=windows.window, t=controller.monotonic())
        assert controller.execute("deny", event, "ctrl+hid:0x09") == "sent Esc to cc-a"
        assert windows.keys == [0x1B]


def ordered_guard(mutex, entered=None):
    """In-process stand-in for focus_lock: same contract, timeout raises."""
    @contextlib.contextmanager
    def guard(timeout):
        assert timeout == 1.0
        if entered is not None:
            entered.set()
        if not mutex.acquire(timeout=timeout):
            raise TimeoutError("focus lock timed out")
        try:
            yield
        finally:
            mutex.release()
    return guard


def test_review2_focus_lock_wraps_hold_touch_and_single_send():
    # Review 2/4: hold touch -> focus runs inside one critical section; no
    # fixed-delay resend remains.
    with tempfile.TemporaryDirectory() as folder:
        hold, state = Path(folder) / "hold", {"held": False, "hold_at_entry": None}
        calls = []

        @contextlib.contextmanager
        def guard(timeout):
            assert timeout == 1.0 and not state["held"]
            state["hold_at_entry"] = hold.exists()
            state["held"] = True
            try:
                yield
            finally:
                state["held"] = False

        def sender(lines, **kwargs):
            assert state["held"] == (lines != ["list"]), "list outside, focus inside the lock"
            calls.extend(lines)
            return REPLY if lines == ["list"] else "ok " + lines[0]

        with patch.object(deck.time, "sleep", side_effect=AssertionError("no fixed delay")):
            controller = make_controller(Windows(), sender, hold_path=hold, focus_guard=guard)
            assert controller.execute("slot 2").startswith("focus cx-b;")
            assert state["hold_at_entry"] is False and hold.exists()
            assert calls == ["list", "focus cx-b"]
            assert controller.execute("auto") == "focus -" and not hold.exists()
        assert calls[-1] == "focus -"


def test_review2_focus_lock_timeout_skips_without_touching_hold():
    with tempfile.TemporaryDirectory() as folder:
        hold, sender = Path(folder) / "hold", Sender()
        mutex = threading.Lock()
        mutex.acquire()  # Another process owns focus.
        controller = make_controller(Windows(), sender, hold_path=hold,
                                     focus_guard=ordered_guard(mutex))
        result = controller.execute("slot 2")
        assert result == "blocked: focus lock timed out"
        assert sender.calls == ["list"] and not hold.exists()
        assert controller.selected is None and controller.focus_target is None
        mutex.release()
        assert controller.execute("slot 2").startswith("focus cx-b;") and hold.exists()


def test_review2_deck_is_final_sender_after_delayed_daemon_send():
    # Review issue 2: daemon passed its hold check, then stalls before sending.
    with tempfile.TemporaryDirectory() as folder:
        hold = Path(folder) / "hold"
        mutex, sending, release, attempted = threading.Lock(), threading.Event(), threading.Event(), threading.Event()
        sent, done = [], threading.Event()

        def sender(lines, **kwargs):
            if lines == ["list"]:
                return REPLY
            sent.append(lines[0])
            if len(sent) == 1:
                sending.set()
                assert release.wait(2)
            return "ok " + lines[0]

        windows = Windows((1, "Code.exe", "notes - Claude"))
        watcher = deck.daemon.ForegroundWatcher(windows, sender, focus_guard=ordered_guard(mutex))
        watcher.hold_file = str(hold)
        controller = make_controller(windows, sender, hold_path=hold,
                                     focus_guard=ordered_guard(mutex, attempted))
        automatic = threading.Thread(target=lambda: watcher.tick(0))
        manual = threading.Thread(target=lambda: (controller.execute("slot 2"), done.set()))
        automatic.start()
        try:
            assert sending.wait(2)
            manual.start()
            assert attempted.wait(2)
            assert not done.wait(0.05) and not hold.exists(), "deck must wait for the lock"
        finally:
            release.set()
            automatic.join(3)
            manual.join(3)
        assert sent == ["focus cc-c", "focus cx-b"], sent  # Deck owns the final focus.
        assert controller.selected == "cx-b" and hold.exists()
        assert watcher.tick(1) is None and sent == ["focus cc-c", "focus cx-b"]


def test_review5_focus_send_failure_restores_hold_and_selection():
    with tempfile.TemporaryDirectory() as folder:
        hold, sender = Path(folder) / "hold", Sender()
        controller = make_controller(Windows(), sender, hold_path=hold)
        fail = [True]
        original = sender.__call__

        def flaky(lines, **kwargs):
            if lines[0].startswith("focus ") and fail[0]:
                raise OSError("COM busy")
            return original(lines, **kwargs)

        controller._sender = flaky
        # Newly created hold is removed so the daemon takes over immediately.
        assert controller.execute("slot 2") == "blocked: COM busy"
        assert not hold.exists() and controller.selected is None
        assert controller.focus_target is None and controller.focus_at is None
        watcher = deck.daemon.ForegroundWatcher(Windows((1, "Code.exe", "notes - Claude")), sender)
        watcher.hold_file = str(hold)
        assert watcher.tick(0) == "cc-c" and sender.calls[-1] == "focus cc-c"
        # Existing selection and hold timestamp survive a later failure.
        fail[0] = False
        assert controller.execute("slot 1").startswith("focus cc-a;")
        stat, selected, focus_at = hold.stat().st_mtime_ns, controller.selected, controller.focus_at
        os.utime(hold, ns=(stat - 5_000_000_000, stat - 5_000_000_000))
        stat -= 5_000_000_000
        fail[0] = True
        assert controller.execute("slot 2") == "blocked: COM busy"
        assert controller.selected == selected == "cc-a" and controller.focus_target == "cc-a"
        assert controller.focus_at == focus_at and hold.stat().st_mtime_ns == stat
        # A stale hold stays stale: nothing renewed it, so the daemon may follow.
        os.utime(hold, (1, 1))
        assert controller.execute("tool cx") == "blocked: COM busy"
        assert hold.stat().st_mtime == 1 and controller.selected == "cc-a"


def test_review1_approval_binds_hwnd_process_and_title():
    # Windows Terminal tabs share one HWND; only the title tells them apart.
    from test_deck_usb import report
    from deck_usb import ReportState
    reply = "ok list n=2\ncx-a wait proj-a\ncx-b wait proj-b"
    with tempfile.TemporaryDirectory() as folder:
        for change, expected in (((5, "WindowsTerminal.exe", "proj-b - Codex"), "window context changed"),
                                 ((5, "pwsh.exe", "proj-a - Codex"), "window context changed"),
                                 ((6, "WindowsTerminal.exe", "proj-a - Codex"), "window context changed"),
                                 (None, "sent Enter to cx-a")):
            windows, sender = Windows((5, "WindowsTerminal.exe", "proj-a - Codex")), Sender(reply)
            controller = make_controller(windows, sender, hold_path=Path(folder) / "hold")
            dispatcher = deck.ActionQueue(deck.load_map(), controller)
            for event in ReportState().feed(report(0x0A)):
                dispatcher.enqueue(event)  # Pressed in tab A.
                assert dispatcher.events.queue[-1]["window"] == (5, "WindowsTerminal.exe", "proj-a - Codex")
            if change:
                windows.window = change  # Tab/process/handle changes while queued.
            with patch.object(deck.log, "debug") as logged:
                dispatcher.thread.start()
                dispatcher.events.join()
                dispatcher.close()
            result = next(call.args[2] for call in logged.call_args_list
                          if len(call.args) == 3 and call.args[1] == "approve")
            assert result == ("blocked: " + expected if change else expected), (change, result)
            assert windows.keys == ([] if change else [0x0D])
    # The sampled handle and the later window query disagree: never matchable.
    windows = Windows((7, "WindowsTerminal.exe", "proj-a - Codex"))
    dispatcher = deck.ActionQueue({}, make_controller(windows, Sender()))
    dispatcher.enqueue({"keys": ("x",), "hwnd": 5, "t": 0.0})
    event = dispatcher.events.get_nowait()
    assert event["window"] == (5, None, None) and event["hwnd"] == 5
    controller = make_controller(windows, Sender("ok list n=1\ncx-a wait proj-a"))
    event.update(usage=0x0A, pressed=frozenset((0x0A,)), modifiers=(), new_modifiers=(), t=controller.monotonic())
    assert controller.execute("approve", event, "hid:0x0A") == "blocked: window context changed"
    assert windows.keys == []


def test_review3_tool_identity_ignores_project_name_words():
    for project, title, key in (("deepseek-project", "deepseek-project - Codex", "cx-a"),
                                ("chatgpt-demo", "chatgpt-demo - Claude", "cc-a"),
                                ("codex-tools", "codex-tools - Claude", "cc-a"),
                                ("claude-notes", "claude-notes - DeepSeek", "ds-a")):
        sessions = [deck.Session(key, "wait", project)]
        assert deck.match_title(title, sessions) == sessions[0], title
        assert deck.match_session((1, "WindowsTerminal.exe", title), sessions) == sessions[0]
        assert deck.find_window(sessions[0], [(4, "Code.exe", title)], sessions) == (4, "Code.exe", title)
    # The tool part still decides: a Claude tab never matches a Codex session.
    sessions = [deck.Session("cx-a", "wait", "deepseek-project")]
    assert deck.match_title("deepseek-project - Claude", sessions) is None
    assert deck.match_title("deepseek-project", sessions) is None
    assert deck.find_window(sessions[0], [(4, "Code.exe", "deepseek-project - Claude")], sessions) is None
    # Project-only prefix collisions: the longest project name is excluded as a whole.
    sessions = [deck.Session("cx-a", "wait", "app"), deck.Session("cc-b", "wait", "app-server")]
    assert deck.match_title("app-server - Claude", sessions) == sessions[1]
    assert deck.match_title("app - Codex", sessions) == sessions[0]
    # Native processes decide the tool; the title only needs the project.
    for tool, process in (("cx", "ChatGPT.exe"), ("cc", "claude.exe"), ("ds", "DeepSeek Harness.exe")):
        project = {"cx": "claude-demo", "cc": "chatgpt-demo", "ds": "codex-demo"}[tool]
        sessions = [deck.Session(tool + "-a", "wait", project)]
        assert deck.find_window(sessions[0], [(3, process, project)], sessions) == (3, process, project)
    sessions = [deck.Session("cc-a", "wait", "chatgpt-demo")]
    assert deck.find_window(sessions[0], [(3, "ChatGPT.exe", "chatgpt-demo")], sessions) is None
    # Approval path: the real project name no longer blocks a legitimate Enter.
    with tempfile.TemporaryDirectory() as folder:
        windows = Windows((1, "Code.exe", "deepseek-project - Codex"))
        controller = make_controller(windows, Sender("ok list n=1\ncx-a wait deepseek-project"),
                                     hold_path=Path(folder) / "hold")
        assert execute(controller, "approve") == "sent Enter to cx-a"


class Recorder:
    def __init__(self):
        self.calls = []

    def execute(self, action, **kwargs):
        self.calls.append((action, "event" in str(kwargs)))


def run_backlog(bindings, keys, controller=None):
    controller = Recorder() if controller is None else controller
    dispatcher = deck.ActionQueue(bindings, controller)
    for key in keys:
        dispatcher.events.put({"keys": (key,), "window": (1, "", ""), "t": 0.0})
    dispatcher.thread.start()  # The whole backlog exists before the worker looks.
    dispatcher.events.join()
    dispatcher.close()
    return controller.calls


def test_review4_backlog_merges_cycles_and_keeps_last_navigation():
    assert deck.parse_action("cycle +3") == ("cycle", 3) and deck.parse_action("cycle -12") == ("cycle", -12)
    for action in ("cycle +0", "cycle 3", "cycle ++1", "cycle +01", "cycle +1.5"):
        raises(ValueError, lambda: deck.parse_action(action))
    sessions = deck.parse_sessions(REPLY)
    assert deck.select_session(sessions, "cycle +3", "cc-a").key == "cx-d"
    assert deck.select_session(sessions, "cycle +5", "cc-a").key == "cx-b"
    assert deck.select_session(sessions, "cycle -2", "cc-a").key == "cc-c"
    assert deck.select_session(sessions, "cycle +2", None).key == "cx-b"
    assert deck.select_session(sessions, "cycle -2", None).key == "cc-c"
    b = {"up": "cycle +1", "down": "cycle -1", "s1": "slot 1", "s2": "slot 2", "tool": "tool cc",
         "wait": "next_wait", "ok": "approve", "no": "deny", "auto": "auto"}
    assert run_backlog(b, ["up", "up", "up", "down"]) == [("cycle +2", False)]
    assert run_backlog(b, ["down", "down", "down"]) == [("cycle -3", False)]
    assert run_backlog(b, ["up", "down"]) == []  # Net zero: nothing to navigate.
    assert run_backlog(b, ["up", "down", "up"]) == [("cycle +1", False)]
    assert run_backlog(b, ["tool", "wait", "s1", "s2"]) == [("slot 2", False)]
    assert run_backlog(b, ["s1", "up", "s2"]) == [("slot 1", False), ("cycle +1", False), ("slot 2", False)]
    # approve/deny are never merged or skipped, and they split cycle runs.
    assert run_backlog(b, ["up", "ok", "up", "up", "no", "tool", "auto", "s1"]) == [
        ("cycle +1", False), ("approve", True), ("cycle +2", False), ("deny", True),
        ("tool cc", False), ("auto", False), ("slot 1", False)]
    assert run_backlog(b, ["ok", "ok", "no"]) == [("approve", True), ("approve", True), ("deny", True)]
    assert run_backlog(b, ["tool", "ok", "wait"]) == [("tool cc", False), ("approve", True), ("next_wait", False)]


def test_review4_backlog_cannot_expire_approval_and_navigation_is_fast():
    # Review scenario: three knob steps then G while staying on the correct session.
    clock = [0.0]

    def sender(lines, **kwargs):
        clock[0] += kwargs.get("wait_reply", 0.0)  # Virtual serial latency.
        return "ok list n=1\ncx-a wait proj" if lines == ["list"] else "ok " + lines[0]

    with tempfile.TemporaryDirectory() as folder, \
            patch.object(deck.time, "sleep", side_effect=AssertionError("no blocking delay")):
        windows = Windows((1, "Code.exe", "proj - Codex"))
        controller = make_controller(windows, sender, hold_path=Path(folder) / "hold",
                                     monotonic=lambda: clock[0])
        started = clock[0]
        assert controller.execute("cycle +1").startswith("focus cx-a;")
        single = clock[0] - started
        assert single == deck.LIST_WAIT < 0.2, single  # Was 0.3 s list + 0.4 s resend.
        clock[0] = 0.0
        dispatcher = deck.ActionQueue({"up": "cycle +1", "hid:0x0A": "approve"}, controller)
        for _ in range(3):
            dispatcher.enqueue({"keys": ("up",)})
        dispatcher.enqueue({"keys": ("hid:0x0A",), "usage": 0x0A, "pressed": frozenset((0x0A,)),
                            "modifiers": (), "new_modifiers": ()})
        with patch.object(deck.log, "debug") as logged:
            dispatcher.thread.start()
            dispatcher.events.join()
            dispatcher.close()
        results = [call.args[1:3] for call in logged.call_args_list if len(call.args) == 3]
        assert [action for action, result in results] == ["cycle +3", "approve"]
        assert results[1][1] == "sent Enter to cx-a", results
        assert windows.keys == [0x0D] and clock[0] < 0.5


def test_review4_exit_cancels_unexecuted_events():
    entered, release, calls = threading.Event(), threading.Event(), []

    class Slow:
        def execute(self, action, **kwargs):
            calls.append(action)
            entered.set()
            assert release.wait(2)

    bindings = {"a": "slot 1", "b": "approve", "c": "slot 2", "d": "cycle +1"}
    dispatcher = deck.ActionQueue(bindings, Slow())
    dispatcher.thread.start()
    dispatcher.events.put({"keys": ("a",), "window": (1, "", ""), "t": 0.0})
    assert entered.wait(2)
    for key in "bcdc":
        dispatcher.events.put({"keys": (key,), "window": (1, "", ""), "t": 0.0, "pressed": frozenset()})
    closer = threading.Thread(target=dispatcher.close)
    closer.start()
    deadline = threading.Event()
    for unused in range(200):
        if dispatcher._stop.is_set():
            break
        deadline.wait(0.01)
    assert dispatcher._stop.is_set()
    release.set()  # Only the already running action may finish.
    closer.join(3)
    assert not closer.is_alive() and not dispatcher.thread.is_alive()
    assert calls == ["slot 1"]
    assert dispatcher.events.empty() and dispatcher.events.unfinished_tasks == 0
    dispatcher.enqueue({"keys": ("a",)})  # Input after exit is ignored too.
    assert dispatcher.events.empty()


def test_review_hold_clears_disappeared_selection_and_ignores_partial_list():
    with tempfile.TemporaryDirectory() as folder:
        windows, sender = Windows(), Sender()
        hold = Path(folder) / "hold"
        controller = make_controller(windows, sender, hold_path=hold)
        controller.execute("slot 1")
        sender.reply = "ok list n=2\ncc-a wait app"  # Incomplete is not evidence of deletion.
        raises(ValueError, controller.maintain)
        assert controller.selected == "cc-a" and hold.exists()
        sender.reply = "ok list n=1\ncc-c wait notes"
        controller.maintain()
        assert sender.calls[-2:] == ["list", "focus -"]
        assert controller.selected is None and controller.focus_target is None and not hold.exists()
        calls = sender.calls[:]
        controller.maintain()
        assert sender.calls == calls


def test_review_hold_heartbeat_preserves_firmware_ttl_until_handoff():
    from test_ui import make_ui
    ui, unused_lcd, unused_lights = make_ui()
    ui.handle("set cc-a idle app", 0)
    ui.handle("set cx-b wait other", 0)
    clock, focus_times = [0.0], []
    with tempfile.TemporaryDirectory() as folder:
        hold = Path(folder) / "hold"
        def sender(lines, **kwargs):
            if lines[0].startswith("focus "):
                focus_times.append(clock[0])
            return ui.handle(lines[0], round(clock[0] * 1000))
        controller = make_controller(Windows(), sender, hold_path=hold,
                                     monotonic=lambda: clock[0])
        controller.execute("slot 1")
        wall = hold.stat().st_mtime
        for elapsed in (2.4, 18.4, 20.4, 22.4, 40.4, 58.4, 59.99):
            clock[0] = elapsed
            with patch.object(deck.time, "time", return_value=wall + elapsed):
                controller.maintain()
            assert ui.choose(round(elapsed * 1000)) == "cc-a"
        assert focus_times == [0.0, 20.4, 40.4]
        clock[0] = 60.05
        with patch.object(deck.time, "time", return_value=wall + clock[0]):
            controller.maintain()
            assert focus_times == [0.0, 20.4, 40.4]
            watcher = deck.daemon.ForegroundWatcher(lambda: (4, "Code.exe", "other Codex"), sender)
            watcher.hold_file = str(hold)
            assert watcher.tick(now=clock[0]) == "cx-b"
        assert ui.choose(round(clock[0] * 1000)) == "cx-b"


def test_review_window_matching_rejects_ambiguous_candidates():
    with tempfile.TemporaryDirectory() as folder:
        windows, sender = Windows(), Sender("ok list n=2\ncc-a wait project-A\ncc-b wait project-B")
        controller = make_controller(windows, sender, hold_path=Path(folder) / "hold")
        for items in ([(3, "ChatGPT.exe", "project-A")], [(3, "Code.exe", "Claude")],
                      [(3, "Code.exe", "project-A - Codex")]):
            windows.items = items
            assert controller.execute("slot 1") == "focus cc-a; no matching window"
            assert windows.activated == []
        windows.items = [(3, "Code.exe", "project-A Claude"), (4, "claude.exe", "project-A")]
        assert controller.execute("slot 1") == "focus cc-a; window ambiguous"
        assert windows.activated == []
        windows.items = [(4, "claude.exe", "project-A")]
        assert controller.execute("slot 1") == "focus cc-a; foreground ok"
        sender.reply = "ok list n=2\ncc-a wait project-A\ncc-b wait project-A"
        windows.activated.clear()
        assert controller.execute("slot 1") == "focus cc-a; window ambiguous"
        assert windows.activated == []
    for tool, process, title in (("cx", "ChatGPT.exe", "proj"), ("cc", "claude.exe", "proj"),
                                  ("ds", "DeepSeek Harness.exe", "proj"),
                                  ("ds", "Code.exe", "proj - DeepSeek"),
                                  ("cx", "Code.exe", "proj - ChatGPT")):
        sessions = [deck.Session(tool + "-a", "wait", "proj")]
        assert deck.find_window(sessions[0], [(1, process, title)], sessions) == (1, process, title)


def test_review_hold_thread_serializes_io_and_joins():
    with tempfile.TemporaryDirectory() as folder:
        sender = Sender()
        controller = make_controller(Windows(), sender, hold_path=Path(folder) / "hold")
        controller.execute("slot 1")
        entered, release, action_done = threading.Event(), threading.Event(), threading.Event()
        def on_list():
            entered.set()
            assert release.wait(1)
        sender.on_list = on_list
        with patch.object(deck, "HOLD_POLL", 0.01):
            controller.start()
            try:
                assert entered.wait(1)
                def auto():
                    controller.execute("auto")
                    action_done.set()
                action = threading.Thread(target=auto)
                action.start()
                assert not action_done.wait(0.02), "action must wait for maintenance's serial transaction"
                release.set()
                action.join(1)
                assert action_done.is_set()
            finally:
                release.set()
                controller.close()
        assert not controller.thread.is_alive()
        assert sender.calls[-1] == "focus -"


def test_review_rawinput_approval_sees_all_device_main_keys():
    from deck_input import EventState
    state = EventState()
    state.keyboard(2, 0x45, 0x12, 0)  # Another keyboard cannot contaminate this report.
    first = state.keyboard(1, 0x47, 0x22, 0)[0]
    assert first["pressed"] == frozenset((0x47,)) and first["modifiers"] == ()
    second = state.keyboard(1, 0x42, 0x30, 0)[0]
    assert second["pressed"] == frozenset((0x47, 0x42))
    state.keyboard(1, 0x42, 0x30, 1)
    state.keyboard(1, 0x47, 0x22, 1)
    state.keyboard(1, 0xA2, 0x1D, 0)
    deny = state.keyboard(1, 0x46, 0x21, 0)[0]
    assert deny["pressed"] == frozenset((0x46,)) and deny["modifiers"] == ("ctrl",)


def main():
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    import test_deck_input
    import test_deck_probe
    import test_deck_exclusive
    for module in (test_deck_input, test_deck_probe, test_deck_exclusive):
        tests.extend(value for name, value in vars(module).items() if name.startswith("test_") and callable(value))
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("AgentDeck offline tests: %d groups passed" % len(tests))


if __name__ == "__main__":
    main()
