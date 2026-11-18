"""统一监视 DeepSeek 日志与 Windows 前台窗口；直接运行时常驻，-v 打印日志。"""
import ctypes
from ctypes import wintypes
import logging
import logging.handlers
import ntpath
import os
import re
import socket
import sys
import time

import agent_lcd
import dsh_watch

# 按进程名判断工具；终端和编辑器再按窗口标题匹配项目名。
PROCESS_TARGETS = {
    "claude.exe": "cc",
    "deepseek harness.exe": "ds",
    "chatgpt.exe": "cx",
    "codex.exe": "cx",
}
TITLE_PROCESSES = {
    "windowsterminal.exe", "conhost.exe", "openconsole.exe", "pwsh.exe",
    "powershell.exe", "cmd.exe", "code.exe", "cursor.exe", "wezterm-gui.exe",
    "alacritty.exe",
}
TITLE_TARGETS = (("claude", "cc"), ("codex", "cx"))
LOCK_PORT = 47613
POLL = 0.3
HEARTBEAT = 20.0
# 宏键盘（deck.py）切换焦点后写这个文件；在此期间前台窗口跟随让路，不抢屏。
DECK_HOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".deck_hold")
DECK_HOLD_SECONDS = 60.0

log = logging.getLogger("agent_daemon")


class ForegroundWindow:
    """只用 Win32 ctypes 查询当前窗口；不读取键盘、鼠标或其它窗口。"""

    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user.GetForegroundWindow.argtypes = []
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user.GetWindowTextLengthW.restype = ctypes.c_int
        self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user.GetWindowTextW.restype = ctypes.c_int
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL

    def __call__(self):
        return self.read(self.user.GetForegroundWindow())

    def read(self, hwnd):
        """查询指定窗口，供 AgentDeck 的 EnumWindows 复用。"""
        if not hwnd:
            return (0, "", "")
        title = ctypes.create_unicode_buffer(self.user.GetWindowTextLengthW(hwnd) + 1)
        self.user.GetWindowTextW(hwnd, title, len(title))
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = self.kernel.OpenProcess(0x1000, False, pid.value)
        if not process:
            return (hwnd, "", title.value)
        try:
            name = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(name))
            if not self.kernel.QueryFullProcessImageNameW(process, 0, name, ctypes.byref(size)):
                return (hwnd, "", title.value)
            return (hwnd, ntpath.basename(name.value), title.value)
        finally:
            self.kernel.CloseHandle(process)


def parse_sessions(reply, include_state=False):
    """解析 list 回显，忽略回显命令、启动提示和不完整行。"""
    sessions = []
    found = False
    for line in reply.splitlines():
        if line.startswith("ok list n="):
            found = True
            continue
        parts = line.strip().split(None, 2)
        if found and len(parts) == 3 and parts[1] in (
                "idle", "think", "tool", "wait", "done", "error"):
            sessions.append(tuple(parts) if include_state else (parts[0], parts[2]))
    return sessions


def session_title(title):
    # 标题的分隔符可能是问号、横杠或 Windows 使用的长横线。
    suffix = "deepseek harness"
    if title.casefold().endswith(suffix):
        prefix = title[:-len(suffix)]
        for separator in (" ? ", " — ", " – ", " - ", " | ", " · "):
            if prefix.endswith(separator):
                return prefix[:-len(separator)].strip()
        return prefix.strip()
    return title.strip()


def title_contains(title, name):
    return bool(name and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", title, re.IGNORECASE))


def map_target(process, title, sessions=(), title_resolver=None):
    process = ntpath.basename(process).casefold()
    if process in PROCESS_TARGETS:
        target = PROCESS_TARGETS[process]
        if target == "ds" and title_resolver is not None:
            return title_resolver(session_title(title)) or target
        return target
    if process not in TITLE_PROCESSES:
        return "-"
    text = title.casefold()
    matches = [(key, name) for key, name in sessions if title_contains(title, name)]
    if matches:
        # 优先完整长名字；同名跨工具时按标题消歧，与 AgentDeck 保持一致。
        longest = max(len(name) for key, name in matches)
        matches = [(key, name) for key, name in matches if len(name) == longest]
        tools = {target for word, target in TITLE_TARGETS if title_contains(text, word)}
        preferred = [item for item in matches if item[0].split("-", 1)[0] in tools]
        return (preferred if len(tools) == 1 and preferred else matches)[0][0]
    return next((target for word, target in TITLE_TARGETS if title_contains(text, word)), "-")


class ForegroundWatcher:
    """窗口输入、串口输出均可替换，让测试完全不碰硬件。"""

    def __init__(self, window_reader, sender=None, title_resolver=None):
        self.window_reader = window_reader
        self.sender = agent_lcd.send if sender is None else sender
        self.title_resolver = title_resolver
        self.context = None
        self.sessions = []
        self.sent_target = None
        self.sent_at = None

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        try:
            hold = getattr(self, "hold_file", None)
            if hold and os.path.exists(hold) and time.time() - os.path.getmtime(hold) < DECK_HOLD_SECONDS:
                self.sent_target = None
                return None
            hwnd, process, title = self.window_reader()
            # 同一窗口更新标题时复用列表，避免终端的动态标题反复查询串口。
            context = (hwnd, process.casefold())
            if context != self.context:
                self.context = context
                self.sessions = []
                if ntpath.basename(process).casefold() in TITLE_PROCESSES:
                    try:
                        self.sessions = parse_sessions(self.sender(
                            ["list"], wait_reply=0.2, retry_for=0.0))
                    except Exception as e:
                        log.debug("list failed: %s", e)
            target = map_target(process, title, self.sessions, self.title_resolver)
            if target != self.sent_target or self.sent_at is None or now - self.sent_at >= HEARTBEAT:
                self.sender(["focus " + target], retry_for=0.0)
                self.sent_target, self.sent_at = target, now
                log.debug("focus %s (%s: %s)", target, process, title)
            return target
        except Exception as e:
            log.debug("foreground tick: %s", e)
            return None


def main(verbose=None):
    verbose = "-v" in sys.argv if verbose is None else verbose
    handler = logging.StreamHandler() if verbose else logging.handlers.RotatingFileHandler(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "daemon.log"),
        maxBytes=200_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=[handler])
    lock = socket.socket()
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            lock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            lock.bind(("127.0.0.1", LOCK_PORT))
        except OSError:
            return
        if "--deck" in sys.argv:
            import deck
            try:
                deck.ensure_running()
            except OSError:
                log.exception("AgentDeck launch failed")
        logs = dsh_watch.Watcher()
        foreground = ForegroundWatcher(ForegroundWindow(), title_resolver=logs.key_for_title)
        foreground.hold_file = DECK_HOLD
        log.info("started; foreground and DeepSeek logs")
        while True:
            started = time.monotonic()
            try:
                logs.tick()
            except Exception:
                log.exception("log tick failed")
            foreground.tick()
            time.sleep(max(0.0, POLL - (time.monotonic() - started)))
    except KeyboardInterrupt:
        pass
    finally:
        lock.close()


if __name__ == "__main__":
    main()
