"""电脑入口和固件循环的隔离测试；所有外部访问均替换为本地替身。"""
import contextlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import agent_lcd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lcd1602"))
import ui
from test_ui import FakeLCD


def test_names_hooks():
    assert len(agent_lcd.ascii_name("a" * 30)) == 24
    with patch.dict(agent_lcd.os.environ, {"CLAUDE_PROJECT_DIR": "abcdefghijklmnopqrstuvwx"}):
        line = agent_lcd.hook_line({"hook_event_name": "UserPromptSubmit", "session_id": "abcdef123"}, "cc")
    assert line == "set cc-abcdef think abcdefghijklmnopqrstuvwx"
    assert agent_lcd.hook_line({"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion"}, "cx").startswith("set cx-0 wait ")
    assert agent_lcd.hook_line({"hook_event_name": "SessionEnd"}, "cx") == "end cx-0"


def test_ensure_daemon():
    calls = []

    class Socket:
        def bind(self, address):
            assert address == ("127.0.0.1", 47613)

        def close(self):
            calls.append("close")

    # 禁止查询用户目录；Popen 只记录参数，完全不创建子进程。
    with patch("socket.socket", Socket), patch("subprocess.Popen") as launch, \
            patch.object(agent_lcd.os.path, "isdir", side_effect=AssertionError("home access")):
        agent_lcd.ensure_watcher()
        args = launch.call_args
        assert Path(args.args[0][1]) == ROOT / "pc" / "daemon.py"
        assert args.kwargs["creationflags"] & 0x08000000
    assert calls == ["close"]

    class Occupied(Socket):
        def bind(self, address):
            raise OSError("fake occupied")

    with patch("socket.socket", Occupied), patch("subprocess.Popen") as launch:
        agent_lcd.ensure_watcher()
        launch.assert_not_called()


def test_demo():
    lines = []
    with patch.object(sys, "argv", ["agent_lcd.py", "demo"]), \
            patch.object(agent_lcd, "send", side_effect=lambda cmds, **kw: lines.extend(cmds) or "ok"), \
            patch.object(agent_lcd.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
        agent_lcd.main()
    for tool in ("cc", "cx", "ds"):
        for state in ui.STATES:
            assert any(line.startswith("set %s-demo %s " % (tool, state)) for line in lines)
    assert "focus cx" in lines and "focus ds" in lines and "focus -" in lines


def test_firmware_loop():
    # 用有限的假时钟跨过 ticks 回绕，验证长行后仍能处理下一条命令及定期重初始化。
    period = 1 << 30
    clocks = iter((period - 100, period - 60, 20, 320001, 320041))
    sleeps = []
    input_data = iter("x" * 170 + "\nset cc-a think project\nbogus\nfocus cx\n")
    pending = [True]

    def read(count):
        try:
            return next(input_data)
        except StopIteration:
            pending[0] = False
            return ""

    def sleep_ms(value):
        sleeps.append(value)
        if len(sleeps) == 4:
            raise KeyboardInterrupt

    class LCD(FakeLCD):
        def __init__(self):
            super().__init__()
            self.inits = 0

        def init(self):
            self.inits += 1
            self.glyphs = [None] * 8

    class Pin:
        OUT = 1

        def __init__(self, *args, **kwargs):
            self.values = []

        def value(self, value):
            self.values.append(value)

    poll = SimpleNamespace(register=lambda *args: None, poll=lambda timeout: [1] if pending[0] else [])
    fake_time = SimpleNamespace(ticks_ms=lambda: next(clocks),
                               ticks_diff=lambda a, b: (a - b + period // 2) % period - period // 2,
                               sleep_ms=sleep_ms)
    namespace = {"__name__": "__firmware_test__"}
    output = io.StringIO()
    modules = {"machine": SimpleNamespace(Pin=Pin), "lcd1602": SimpleNamespace(LCD=LCD),
               "select": SimpleNamespace(poll=lambda: poll, POLLIN=1), "time": fake_time}
    with patch.dict(sys.modules, modules), patch.object(sys, "stdin", SimpleNamespace(read=read)), \
            contextlib.redirect_stdout(output):
        try:
            exec(compile((ROOT / "lcd1602/main.py").read_text(encoding="utf-8"), "main.py", "exec"), namespace)
        except KeyboardInterrupt:
            pass
    assert "err line too long" in output.getvalue()
    assert "ok set cc-a think" in output.getvalue()
    assert "err unknown command" in output.getvalue()
    assert "ok focus cx" in output.getvalue()
    assert namespace["now"] == 320141
    assert namespace["lcd"].inits == 1
    assert all(glyph is not None for glyph in namespace["lcd"].glyphs)
    assert sleeps == [40] * 4


def main():
    tests = (test_names_hooks, test_ensure_daemon, test_demo, test_firmware_loop)
    for test in tests:
        test()
        print(test.__name__ + ": PASS")
    print("PC and firmware loop: %d groups passed" % len(tests))


if __name__ == "__main__":
    main()
