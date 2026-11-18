"""离线断言：不读取真实用户目录、不调用 Win32、不打开串口、不启动后台进程。"""
import ctypes
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import zstandard

import daemon
import dsh_watch


class Sender:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.reply = "ok list n=3\n  cc-a think app\n  cx-b tool app-server\n  ds-c wait notes"

    def __call__(self, lines, **kwargs):
        self.calls.append(lines[0])
        if self.fail:
            raise OSError("fake unplugged")
        return self.reply if lines == ["list"] else ""


def test_mapping():
    for process, target in daemon.PROCESS_TARGETS.items():
        assert daemon.map_target(process.upper(), "codex claude") == target
    for process in daemon.TITLE_PROCESSES:
        assert daemon.map_target(process.upper(), "codex") == "cx"
        assert daemon.map_target(process, "CLAUDE") == "cc"
        assert daemon.map_target(process, "unrelated") == "-"
    assert daemon.map_target("firefox.exe", "claude app", [("cc-a", "app")]) == "-"
    assert daemon.map_target("Code.exe", "APP-SERVER", [("cc-a", "app"), ("cx-b", "app-server")]) == "cx-b"
    titles = {"notes": "ds-abcdef"}
    for separator in (" ? ", " — ", " - "):
        assert daemon.map_target("DeepSeek Harness.exe", "notes" + separator + "DeepSeek Harness",
                                 title_resolver=titles.get) == "ds-abcdef"
    assert daemon.session_title("Plan? ? DeepSeek Harness") == "Plan?"
    assert daemon.session_title("dash- - DeepSeek Harness") == "dash-"
    assert daemon.map_target("DeepSeek Harness.exe", "Plan? ? DeepSeek Harness",
                             title_resolver={"Plan?": "ds-punct"}.get) == "ds-punct"
    assert daemon.map_target("DeepSeek Harness.exe", "missing ? DeepSeek Harness",
                             title_resolver=titles.get) == "ds"
    assert daemon.parse_sessions("noise\nok list n=1\n  cc-a wait project with spaces\nerr failed") == [
        ("cc-a", "project with spaces")]


def test_focus():
    sender = Sender()
    window = [1, "Code.exe", "app-server - editor"]
    watcher = daemon.ForegroundWatcher(lambda: tuple(window), sender)
    assert watcher.tick(0) == "cx-b"
    assert sender.calls == ["list", "focus cx-b"]
    watcher.tick(0.3)
    watcher.tick(19.99)
    assert sender.calls == ["list", "focus cx-b"]
    watcher.tick(20)
    assert sender.calls == ["list", "focus cx-b", "focus cx-b"]
    window[0] = 2
    watcher.tick(21)
    assert sender.calls[-1] == "list"
    assert sender.calls.count("focus cx-b") == 2
    window[:] = [3, "claude.exe", "other"]
    assert watcher.tick(22) == "cc"
    window[:] = [4, "notepad.exe", "other"]
    assert watcher.tick(23) == "-"
    sender.fail = True
    window[:] = [5, "powershell.exe", "codex"]
    assert watcher.tick(24) is None
    assert watcher.tick(24.3) is None
    assert sender.calls.count("list") == 3
    sender.fail = False
    assert watcher.tick(25) == "cx"
    assert sender.calls[-1] == "focus cx"
    assert sender.calls.count("list") == 3
    watcher.window_reader = lambda: (_ for _ in ()).throw(OSError("fake inaccessible"))
    assert watcher.tick(26) is None

    # 同一前台窗口的标题变化可以改变目标，但不能触发第二次 list。
    sender = Sender()
    window[:] = [8, "Code.exe", "app-server"]
    watcher = daemon.ForegroundWatcher(lambda: tuple(window), sender)
    assert watcher.tick(0) == "cx-b"
    window[2] = "notes - editor"
    assert watcher.tick(0.3) == "ds-c"
    window[2] = "Claude - editor"
    assert watcher.tick(0.6) == "cc"
    assert sender.calls.count("list") == 1


def test_hold_rechecked_before_focus_send():
    # Hold can appear after tick's first check, including while list is in flight.
    for phase in ("window", "list", "mapping"):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent,
                                         prefix="test-hold-") as folder:
            hold = Path(folder) / ".deck_hold"
            sender = Sender()

            def take_hold():
                hold.touch()
                os.utime(hold, (100, 100))

            def window_reader():
                if phase == "window":
                    take_hold()
                return (1, "Code.exe", "app-server - editor")

            def send(lines, **kwargs):
                reply = sender(lines, **kwargs)
                if phase == "list" and lines == ["list"]:
                    take_hold()
                return reply

            original_mapping = daemon.map_target

            def map_target(*args, **kwargs):
                target = original_mapping(*args, **kwargs)
                if phase == "mapping":
                    take_hold()
                return target

            watcher = daemon.ForegroundWatcher(window_reader, send)
            watcher.hold_file = str(hold)
            watcher.sent_target, watcher.sent_at = "cc-a", 0
            with patch.object(daemon.time, "time", return_value=100), \
                    patch.object(daemon, "map_target", map_target):
                assert watcher.tick(1) is None, phase
            assert sender.calls == ["list"], (phase, sender.calls)
            assert watcher.sent_target is None and watcher.sent_at == 0

            # Expired hold returns ownership and immediately sends the current target.
            with patch.object(daemon.time, "time", return_value=160):
                assert watcher.tick(2) == "cx-b"
            assert sender.calls == ["list", "focus cx-b"]


def test_state_machine():
    session = object.__new__(dsh_watch.Session)
    session.open = session.started = False
    session.terminal = None
    session.title = ""
    session.calls, session.asks = set(), set()
    session.last_event = 0
    assert session.state() is None
    session.apply({"type": "session/title", "data": {"title": "demo"}})
    assert session.title == "demo"
    session.apply({"type": "session/title", "data": "renamed"})
    assert session.title == "renamed"
    session.apply({"type": "turn/start", "time": 2000})
    assert session.state() == "think" and session.last_event == 2
    session.apply({"type": "tool/call", "data": {"callId": "a"}})
    assert session.state() == "tool"
    session.apply({"type": "approval/asked", "data": {"id": "b"}})
    assert session.state() == "wait"
    session.apply({"type": "approval/decided", "data": {"id": "b"}})
    assert session.state() == "tool"
    session.apply({"type": "tool/result", "data": {"message": {"toolCallId": "a"}}})
    assert session.state() == "think"
    for reason, expected in (("completed", "done"), ("aborted", "idle"), ("error", "error")):
        session.apply({"type": "turn/end", "data": {"reason": {"kind": reason}}})
        assert session.state() == expected


def test_log_tick():
    # 临时目录明确位于工程内；所有缓存和压缩日志都是测试自己写的。
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent, prefix="test-dsh-") as folder:
        base = Path(folder)
        cache = base / "cache"
        cache.mkdir()
        session_dir = base / "workspace-myproject" / "session-abcdef1234"
        session_dir.mkdir(parents=True)
        path = session_dir / "session.v4.jsonl.zstd"
        cache.joinpath("session-abcdef1234.json").write_text(
            json.dumps({"record": {"identity": {"cwd": "myproject"}}}), encoding="utf-8")

        def frame(*events):
            return zstandard.ZstdCompressor().compress(
                "".join(json.dumps(ev) + "\n" for ev in events).encode())

        now = 1_800_000_000
        first = frame({"type": "session/title", "data": {"title": "Main session"}, "time": now * 1000},
                      {"type": "turn/start", "time": now * 1000})
        path.write_bytes(first)
        os.utime(path, (now, now))
        sent = []
        running = [True]

        def send(line):
            sent.append(line)
            return True

        logs = dsh_watch.Watcher(send, str(base / "*" / "session-*" / "*.zstd"), str(cache),
                                 process_check=lambda: running[0])
        logs.tick(now)
        assert sent == ["set ds-abcdef think myproject"]
        assert logs.key_for_title("MAIN SESSION") == "ds-abcdef"
        logs.tick(now + 1)
        assert len(sent) == 1
        logs.tick(now + 61)
        assert len(sent) == 2
        next_frame = frame({"type": "approval/asked", "data": {"id": "ask"}, "time": (now + 62) * 1000})
        path.write_bytes(first + next_frame[:-2])
        logs.tick(now + 62)
        assert len(sent) == 2
        path.write_bytes(first + next_frame)
        logs.tick(now + 63)
        assert sent[-1] == "set ds-abcdef wait myproject"
        running[0] = False
        logs.tick(now + 73)
        assert sent[-1] == "end ds-abcdef"
        path.write_bytes(frame({"type": "session/title", "data": {"title": "replaced"}}))
        logs.tick(now + 74)
        assert logs.key_for_title("Main session") is None
        assert logs.key_for_title("replaced") == "ds-abcdef"
        logs.sender = lambda line: (_ for _ in ()).throw(OSError("fake serial"))
        assert logs._send("set ds-abcdef think project") is False


def test_main_schedule_and_lock():
    calls = []

    class Lock:
        def setsockopt(self, *args):
            pass

        def bind(self, address):
            assert address == ("127.0.0.1", 47613)
            calls.append("bind")

        def close(self):
            calls.append("close")

    class Logs:
        def key_for_title(self, title):
            return None

        def tick(self):
            calls.append("logs")

    class Foreground:
        def __init__(self, reader, title_resolver):
            pass

        def tick(self):
            calls.append("foreground")

    def sleep(seconds):
        assert 0 <= seconds <= 0.3
        calls.append("sleep")
        raise KeyboardInterrupt

    with patch.object(daemon.socket, "socket", Lock), \
            patch.object(daemon.dsh_watch, "Watcher", Logs), \
            patch.object(daemon, "ForegroundWindow", lambda: None), \
            patch.object(daemon, "ForegroundWatcher", Foreground), \
            patch.object(daemon.time, "sleep", sleep), \
            patch.object(daemon.logging, "basicConfig"):
        daemon.main(verbose=True)
    assert calls == ["bind", "logs", "foreground", "sleep", "close"]

    class AlreadyRunning(Lock):
        def bind(self, address):
            calls.append("occupied")
            raise OSError("fake already running")

    calls.clear()
    with patch.object(daemon.socket, "socket", AlreadyRunning), \
            patch.object(daemon.logging, "basicConfig"):
        daemon.main(verbose=True)
    assert calls == ["occupied", "close"]


def test_process_snapshot():
    class Kernel:
        def __init__(self, names=(), failure=None):
            self.names = iter(names)
            self.failure = failure
            self.last_error = 0
            self.closed = []
            self.handle = 0x123456789

        def CreateToolhelp32Snapshot(self, flags, pid):
            assert (flags, pid) == (2, 0)
            return dsh_watch.wintypes.HANDLE(-1).value if self.failure == "snapshot" else self.handle

        def _next(self, handle, pointer):
            assert handle == self.handle
            if self.failure == "raise":
                raise OSError("fake snapshot failure")
            if self.failure == "query":
                self.last_error = 5
                return False
            name = next(self.names, None)
            if name is None:
                self.last_error = 18
                return False
            entry = ctypes.cast(pointer, ctypes.POINTER(dsh_watch.PROCESSENTRY32W)).contents
            assert entry.dwSize == ctypes.sizeof(dsh_watch.PROCESSENTRY32W)
            entry.szExeFile = name
            return True

        Process32FirstW = Process32NextW = _next

        def CloseHandle(self, handle):
            self.closed.append(handle)
            return True

    cases = ((["other.exe", "DEEPSEEK HARNESS.EXE"], None, True),
             (["other.exe"], None, False), ([], None, False),
             ([], "snapshot", True), ([], "query", True), ([], "raise", True))
    for names, failure, expected in cases:
        kernel = Kernel(names, failure)
        with patch.object(dsh_watch.ctypes, "get_last_error", lambda: kernel.last_error):
            assert dsh_watch.dsh_running(kernel) is expected
        assert kernel.closed == ([] if failure == "snapshot" else [kernel.handle])
    fields = dict(dsh_watch.PROCESSENTRY32W._fields_)
    assert fields["th32DefaultHeapID"] is ctypes.c_size_t
    with patch.object(dsh_watch.agent_lcd, "send") as sender:
        assert dsh_watch.send("set ds-test think project") is True
        sender.assert_called_once_with(["set ds-test think project"], retry_for=0.0)
    with patch.object(daemon, "main") as main, patch.object(dsh_watch.sys, "argv", ["dsh_watch.py", "-v"]):
        dsh_watch.main()
        main.assert_called_once_with(verbose=True)


def main():
    tests = (test_mapping, test_focus, test_hold_rechecked_before_focus_send,
             test_state_machine, test_log_tick, test_main_schedule_and_lock,
             test_process_snapshot)
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("daemon offline tests: %d groups passed" % len(tests))


if __name__ == "__main__":
    main()
