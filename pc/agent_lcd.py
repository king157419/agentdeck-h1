"""电脑端：把 Agent 状态通过 USB 串口发给 1602 状态屏。

用法：
  python agent_lcd.py hook cc|cx      作为 Claude Code / Codex 的 hook 运行（从标准输入读事件 JSON）
  python agent_lcd.py doctor          自检：串口、板子、三个工具的上报是否就位
  python agent_lcd.py send "list"     手动发一条命令并打印回显
  python agent_lcd.py demo            演示一遍各种状态

串口默认自动找 CH340（找不到用 COM4），可用环境变量 AGENT_LCD_PORT 指定。
作为 hook 运行时永远安静退出：不往标准输出写任何东西，出错也不影响 Claude Code。
"""
import json
import os
import sys
import time

import serial
from serial.tools import list_ports

# Claude Code 事件 -> 屏上的状态
EVENT_STATE = {
    "SessionStart": "idle",
    "UserPromptSubmit": "think",
    "PreToolUse": "tool",
    "PostToolUse": "think",
    "PostToolUseFailure": "think",
    "PermissionRequest": "wait",
    "Stop": "done",
    "Interrupt": "idle",
}
WAIT_NOTIFICATIONS = ("permission_prompt", "elicitation_dialog")


def find_port():
    if os.environ.get("AGENT_LCD_PORT"):
        return os.environ["AGENT_LCD_PORT"]
    for p in list_ports.comports():
        if p.vid == 0x1A86:          # CH340 / CH9102
            return p.device
    return "COM4"


def send(lines, wait_reply=0.0, retry_for=1.5, expected_replies=None):
    """发若干行命令。串口被别的 hook 占着时重试一小会儿。返回板子的回显。"""
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = find_port(), 115200, 0.05
    s.dtr = False   # CH340 板子：打开串口时别拉 DTR/RTS，否则会把 ESP32 复位
    s.rts = False
    t0 = time.time()
    while True:
        try:
            s.open()
            break
        except serial.SerialException:
            if time.time() - t0 > retry_for:
                raise
            time.sleep(0.05)
    try:
        for line in lines:
            s.write((line + "\r\n").encode("ascii", "replace"))
        s.flush()
        reply = b""
        t1 = time.time()
        while time.time() - t1 < wait_reply:
            reply += s.read(256)
            if expected_replies and all(line in reply.decode(errors='replace').splitlines()
                                        for line in expected_replies):
                break
        return reply.decode(errors="replace").strip()
    finally:
        s.close()


def ascii_name(path):
    name = os.path.basename(os.path.normpath(path or "")) or "agent"
    name = "".join(c if 33 <= ord(c) < 127 else "" for c in name)
    return name[:24] or "agent"


def hook_line(ev, agent="cc"):
    """把一条 hook 事件翻译成一行串口命令；不关心的事件返回 None。
    会话 key = 工具代号 + 会话 id 前 6 位，屏幕靠前缀知道是哪个工具。"""
    sid = str(ev.get("session_id") or ev.get("thread_id") or ev.get("conversation_id") or "0")
    key = agent + "-" + sid.replace("-", "")[:6]
    name = ascii_name((os.environ.get("CLAUDE_PROJECT_DIR") if agent == "cc" else None) or ev.get("cwd"))
    event = ev.get("hook_event_name", "")
    if event == "SessionEnd":
        return "end %s" % key
    if event == "Notification":
        kind = ev.get("notification_type", "")
        msg = (ev.get("message") or "").lower()
        if kind in WAIT_NOTIFICATIONS or (not kind and "permission" in msg):
            return "set %s wait %s" % (key, name)
        return None
    if event == "PreToolUse" and ev.get("tool_name") == "AskUserQuestion":
        return "set %s wait %s" % (key, name)      # 在等你回答问题
    if event in EVENT_STATE:
        return "set %s %s %s" % (key, EVENT_STATE[event], name)
    return None


def ensure_watcher():
    """保证统一监视程序在跑；没有 DeepSeek 日志也需要跟随前台焦点。"""
    import socket
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", 47613))      # 端口空着 = 监视程序没在跑
    except OSError:
        return
    finally:
        probe.close()
    import subprocess
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    subprocess.Popen([pyw if os.path.exists(pyw) else sys.executable,
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), "daemon.py")],
                     creationflags=0x00000008 | 0x00000200 | 0x08000000,   # 脱离父进程、不弹窗口
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True)


def doctor():
    """自检：串口、板子、三个工具的上报是否就位。"""
    import socket
    port = find_port()
    print("serial port :", port)
    try:
        print("board       :", send(["ping"], wait_reply=0.6) or "NO REPLY (wrong port, or board not running agent-lcd)")
        print(send(["list"], wait_reply=0.6))
    except Exception as e:
        print("board       : CANNOT OPEN %s (%s) - unplugged, or a serial monitor is holding the port" % (port, e))
    import install
    for name, t in install.TARGETS.items():
        data = install.load(t["path"])
        n = sum(1 for gs in data.get("hooks", {}).values() for g in gs if install.is_ours(g))
        print("%-12s: %s" % (name + " hooks", "%d events installed" % n if n else "NOT INSTALLED (run: python install.py install)"))
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", 47613))
        print("daemon      : not running (starts with the next hook event, or run: pythonw daemon.py)")
    except OSError:
        print("daemon      : running (DeepSeek logs + foreground focus)")
    finally:
        probe.close()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "hook"
    if mode != "hook":
        try:
            sys.stdout.reconfigure(errors="replace")   # 控制台编码不支持中文时别崩
        except Exception:
            pass
    if mode == "hook":
        try:
            raw = sys.stdin.buffer.read().decode("utf-8", "replace")
            agent = sys.argv[2] if len(sys.argv) > 2 else "cc"
            line = hook_line(json.loads(raw or "{}"), agent)
            if line:
                send([line])
        except Exception:
            pass                      # 屏没插、串口被占：都不该影响正在工作的 Agent
        try:
            ensure_watcher()
        except Exception:
            pass
        return
    if mode == "send":
        print(send([" ".join(sys.argv[2:])], wait_reply=0.5))
        return
    if mode == "demo":
        steps = [("focus -", 0.1), ("clear", 0.3)]
        for tool, name in (("cc", "demo-app"), ("cx", "website"), ("ds", "scraper")):
            for state in ("idle", "think", "tool", "wait", "done", "error"):
                steps.append(("set %s-demo %s %s" % (tool, state, name), 4 if state == "done" else 2))
            steps.append(("end %s-demo" % tool, 0.2))
        steps.extend([("set cc-demo wait demo-app", 1), ("set cx-demo think website", 1),
                      ("focus cx", 3), ("focus ds", 3), ("focus -", 2), ("clear", 0.2)])
        for line, pause in steps:
            print(line, "->", send([line], wait_reply=0.3))
            time.sleep(pause)
        return
    if mode == "doctor":
        doctor()
        return
    print(__doc__)


if __name__ == "__main__":
    main()
