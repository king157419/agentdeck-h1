"""AgentDeck 离线断言：串口、Win32、HID、进程和单实例锁全部使用替身。"""
import contextlib
import ctypes
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
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


def raises(error, call):
    try:
        call()
    except error:
        return
    raise AssertionError("expected " + error.__name__)


def test_mapping():
    mapping = deck.load_map()
    assert [mapping["vk:0x%02X" % key] for key in range(0x7C, 0x82)] == [
        "slot 1", "slot 2", "slot 3", "slot 4", "approve", "deny"]
    for key in ("wheel:+1", "consumer:0x00E9"):
        assert mapping[key] == "cycle +1"
    for key in ("wheel:-1", "consumer:0x00EA"):
        assert mapping[key] == "cycle -1"
    assert deck.normalize_key("VK:0x7c") == "vk:0x7C"
    assert deck.normalize_key("scan:0x64:2") == "scan:0x0064:2"
    assert deck.parse_action(" cycle -1 ") == ("cycle", -1)
    for action in ("slot 0", "slot 9", "cycle 2", "cycle 1", "approve now", "exec cmd", [], None):
        raises(ValueError, lambda: deck.parse_action(action))
    for key in ("vk:0x100", "vk:0x0", "scan:0x64:1", "wheel:0", "F13", None):
        raises(ValueError, lambda: deck.normalize_key(key))
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "map.json"
        for text in ('{"version":1,"bindings":{"vk:0x7c":"auto","vk:0x7C":"deny"}}',
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


def test_actions_and_logging():
    windows, sender = Windows(), Sender()
    controller = deck.Controller(windows, sender)
    with patch.object(deck.log, "debug") as logged:
        assert controller.execute("slot 2") == "focus cx-b; foreground ok"
        logged.assert_called_once()
        assert logged.call_args.args[0] == "%s -> %s"
    assert sender.calls == ["list", "focus cx-b"] and windows.activated == [2]
    assert controller.execute("next_wait").startswith("focus cc-c;")
    assert controller.execute("cycle +1").startswith("focus cx-d;")
    assert controller.execute("cycle +1").startswith("focus cc-a;")
    assert controller.execute("slot 8") == "no matching session"
    assert controller.selected == "cc-a"
    assert controller.execute("auto") == "focus -" and controller.selected is None
    assert sender.calls[-1] == "focus -"
    windows.items = []
    assert controller.execute("slot 1") == "focus cc-a; no matching window"
    windows.items = [(7, "Code.exe", "app - Claude")]
    windows.activate_ok = False
    assert controller.execute("slot 1").endswith("denied by Windows")
    sender.reply = "ok list n=4"
    assert controller.execute("approve").startswith("blocked:")
    assert windows.keys == []
    controller.sender = lambda *args, **kw: (_ for _ in ()).throw(OSError("fake serial busy"))
    assert "fake serial busy" in controller.execute("approve")
    assert controller.execute("bad action").startswith("blocked:")


def test_approval_guards():
    windows, sender = Windows(), Sender()
    controller = deck.Controller(windows, sender)
    assert controller.execute("approve") == "sent Enter to cc-a"
    assert controller.execute("deny") == "sent Esc to cc-a"
    assert windows.keys == [0x0D, 0x1B]
    windows.keys.clear()
    for window in ((1, "firefox.exe", "app Claude"), (1, "notepad.exe", "app"),
                   (1, "Code.exe", "unrelated"), (2, "Code.exe", "app-server Codex"),
                   (0, "Code.exe", "app Claude"), (1, "Code.exe", "Claude")):
        windows.window = window
        for action in ("approve", "deny"):
            assert controller.execute(action).startswith("blocked:")
    assert windows.keys == []
    sender.reply = "ok list n=1\ncc-a wait app"
    for title in ("happy - Visual Studio Code", "app - Codex", "app - Claude and Codex", "myapp"):
        windows.window = (1, "Code.exe", title)
        assert controller.execute("approve").startswith("blocked:")
        assert controller.execute("deny").startswith("blocked:")
    assert windows.keys == []
    windows.window = (1, "Code.exe", "app Claude")
    for state in ("idle", "think", "tool", "done", "error"):
        sender.reply = "ok list n=1\ncc-a %s app" % state
        assert controller.execute("approve").startswith("blocked:")
        assert controller.execute("deny").startswith("blocked:")
    sender.reply = "ok list n=2\ncc-a wait app\ncc-other wait app"
    assert controller.execute("approve").startswith("blocked:")
    sender.reply = "ok list n=2\ncc-a wait app\ncx-b wait app"
    assert controller.execute("approve").startswith("sent Enter")  # 标题工具消除跨工具歧义。
    windows.keys.clear()
    sender.reply = REPLY
    sender.on_list = lambda: setattr(windows, "window", (3, "Code.exe", "notes Claude"))
    assert "foreground changed" in controller.execute("approve")
    assert windows.keys == []
    sender.on_list = lambda: None
    windows.key_ok = False
    assert "guard failed" in controller.execute("deny")


def test_window_matching_and_input():
    sessions = deck.parse_sessions(REPLY)
    assert deck.match_session((1, "Code.exe", "app-server"), sessions).key == "cx-b"
    assert deck.match_session((1, "Code.exe", "Codex"), sessions) is None
    assert deck.match_session((1, "Code.exe", "Codex"), sessions[:2]).key == "cx-b"
    assert deck.find_window(sessions[0], [(9, "firefox.exe", "app Claude"),
                                        (8, "Code.exe", "Claude"), (7, "Code.exe", "app")], sessions)[0] == 7
    assert deck.find_window(sessions[0], [(8, "Code.exe", "Claude")], sessions)[0] == 8
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
        run.assert_called_once_with(deck.DEFAULT_MAP)


def test_run_event_dispatch_and_cleanup():
    import deck_input
    windows, sender, calls = Windows(), Sender(), []

    class Lock:
        def acquire(self):
            calls.append("lock")
            return True

        def close(self):
            calls.append("close")

    class Input:
        def __init__(self, callback):
            self.callback = callback

        def run(self):
            self.callback({"keys": ("vk:0x7C", "scan:0x0064:0")})
            self.callback({"keys": ("vk:0x80",)})
            self.callback({"keys": ("consumer:0x00E9",)})
            self.callback({"keys": ("vk:0x01",)})

    with patch.object(deck, "SingleInstance", Lock), \
            patch.object(deck_input, "RawInput", Input), \
            patch.object(deck_windows, "WindowControl", return_value=windows), \
            patch.object(deck.agent_lcd, "send", sender):
        assert deck.run() == 0
    assert calls == ["lock", "close"]
    assert sender.calls == ["list", "focus cc-a", "list", "list", "focus cx-b"]
    assert windows.keys == [0x0D] and windows.activated == [1, 2]
    calls.clear()
    with patch.object(deck, "SingleInstance", Lock), \
            patch.object(deck_input, "RawInput", Input), \
            patch.object(deck_windows, "WindowControl", return_value=windows), \
            patch.object(deck, "load_map", side_effect=ValueError("fake invalid map")):
        raises(ValueError, deck.run)
    assert calls == ["lock", "close"]


def main():
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    import test_deck_input
    import test_deck_probe
    for module in (test_deck_input, test_deck_probe):
        tests.extend(value for name, value in vars(module).items() if name.startswith("test_") and callable(value))
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("AgentDeck offline tests: %d groups passed" % len(tests))


if __name__ == "__main__":
    main()
