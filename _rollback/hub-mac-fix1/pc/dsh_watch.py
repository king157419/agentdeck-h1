"""DeepSeek harness (dsh) 监视程序：读它的会话日志，把会话状态发给状态屏。

dsh 没有对外的上报接口，但它会把事件实时追加到
  ~/.dsh/sessions/<工作区>/session-<id>/session.v4.jsonl.zstd
（一批事件压成一个独立的 zstd 帧，约 200 毫秒落盘一次）。统一 daemon 每 0.3 秒看一眼文件
有没有变长，把新增的帧解出来，按事件推出状态：

  turn/start ... turn/end       一轮对话的开始和结束
  tool/call / tool/result       工具调用（没配对的 = 正在跑工具）
  approval/asked / decided      等你批准（没配对的 = 在等你）

用法： pythonw dsh_watch.py        后台常驻（同一时间只会有一个在跑）
       python  dsh_watch.py -v     前台运行并打印日志
"""
import glob
import ctypes
from ctypes import wintypes
import json
import logging
import os
import sys
import time

import zstandard

import agent_lcd

ROOT = os.path.join(os.path.expanduser("~"), ".dsh")
SESS_GLOB = os.path.join(ROOT, "sessions", "*", "session-*", "session.v4.jsonl.zstd")
CACHE_DIR = os.path.join(ROOT, "storages", "session_projcache", "sessions")
EXE_NAME = "DeepSeek Harness.exe"
LOCK_PORT = 47613                 # 只用来保证单实例，不收发任何数据
POLL = 0.4
RECENT = 15 * 60                  # 启动时只上报最近 15 分钟内有动静的会话
REPLAY_WINDOW = 6 * 3600          # 更早的文件不回放，只从文件末尾开始跟
RESEND = 60                       # 进行中的会话每分钟重发一次（板子重新上电后能恢复）

log = logging.getLogger("dsh_watch")


class Session:
    def __init__(self, path, cache_dir=None):
        self.path = path
        self.sid = os.path.basename(os.path.dirname(path))[len("session-"):]
        self.key = "ds-" + self.sid.replace("-", "")[:6]
        self.cache_dir = CACHE_DIR if cache_dir is None else cache_dir
        self.name = self._name()
        self.title = ""
        self.offset = 0            # 已经解完的压缩数据长度（总是落在帧边界上）
        self.tail = ""             # 上一帧末尾没写完的半行
        self.open = False
        self.calls = set()
        self.asks = set()
        self.terminal = None
        self.started = False       # 见过至少一轮对话才上报
        self.last_event = 0.0
        self.sent = None           # 板子上目前的状态
        self.sent_at = 0.0

    def _name(self):
        try:
            with open(os.path.join(self.cache_dir, "session-%s.json" % self.sid), encoding="utf-8") as f:
                return agent_lcd.ascii_name(json.load(f)["record"]["identity"]["cwd"])
        except Exception:
            ws = os.path.basename(os.path.dirname(os.path.dirname(self.path))).strip("-")
            return agent_lcd.ascii_name(ws.split("-")[-1])

    def reset(self):
        self.offset, self.tail = 0, ""
        self.open, self.terminal, self.started = False, None, False
        self.calls.clear()
        self.asks.clear()
        self.title = ""

    def read_new(self):
        """解出文件里新增的完整帧。返回是否有新事件。"""
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return False
        if size < self.offset:                 # 文件被截断或替换：从头再来
            self.reset()
        if size == self.offset:
            return False
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            data = f.read()
        got = False
        while data:
            d = zstandard.ZstdDecompressor().decompressobj()
            try:
                out = d.decompress(data)
            except zstandard.ZstdError:
                break                          # 尾巴还没写完，下次再试
            if not d.eof:
                break
            self.offset += len(data) - len(d.unused_data)
            data = d.unused_data
            lines = (self.tail + out.decode("utf-8", "replace")).split("\n")
            self.tail = lines.pop()
            for line in lines:
                if line.strip():
                    try:
                        self.apply(json.loads(line))
                        got = True
                    except Exception:
                        pass
        return got

    def apply(self, ev):
        t, d = ev.get("type", ""), ev.get("data") or {}
        if ev.get("time"):
            self.last_event = ev["time"] / 1000.0
        if t == "session/title":
            title = d if isinstance(d, str) else d.get("title", "")
            if isinstance(title, str):
                self.title = title
        elif t == "turn/start":
            self.open, self.terminal, self.started = True, None, True
            self.calls.clear()
            self.asks.clear()
        elif t == "turn/end":
            self.open = False
            self.terminal = (d.get("reason") or {}).get("kind") or "completed"
            self.calls.clear()
            self.asks.clear()
        elif t == "tool/call":
            self.calls.add(d.get("callId"))
        elif t == "tool/result":
            m = d.get("message") or {}
            self.calls.discard((m.get("source") or {}).get("callId") or m.get("toolCallId"))
        elif t.endswith("/asked"):             # approval/asked，以及其它向用户提问的事件
            self.asks.add(d.get("id"))
        elif t.endswith(("/decided", "/answered", "/resolved")):
            self.asks.discard(d.get("id"))

    def state(self):
        if not self.started:
            return None
        if self.open:
            return "wait" if self.asks else ("tool" if self.calls else "think")
        if self.terminal == "completed":
            return "done"
        if self.terminal == "aborted":
            return "idle"
        return "error"                         # error / max-tokens


class PROCESSENTRY32W(ctypes.Structure):
    # 默认堆标识和快照句柄在 64 位 Python 下也必须保持指针宽度。
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _process_kernel():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        function.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def dsh_running(kernel=None):
    snapshot = None
    invalid = wintypes.HANDLE(-1).value
    try:
        kernel = _process_kernel() if kernel is None else kernel
        snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)
        if snapshot in (None, 0, invalid):
            return True
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.szExeFile.casefold() == EXE_NAME.casefold():
                return True
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        # 正常走完快照会报“没有更多文件”；其它查询失败不应清空屏上的会话。
        return ctypes.get_last_error() != 18
    except Exception:
        return True                            # 查不了就当它在跑
    finally:
        if snapshot not in (None, 0, invalid):
            try:
                kernel.CloseHandle(snapshot)
            except Exception:
                pass


def send(line):
    try:
        agent_lcd.send([line], retry_for=0.0)
        return True
    except Exception as e:
        log.debug("send failed (%s): %s", line, e)
        return False


class Watcher:
    """单步监视日志；主循环由 daemon 统一调度，测试可注入本地目录和发送函数。"""

    def __init__(self, sender=None, session_glob=None, cache_dir=None, process_check=None):
        self.sender = send if sender is None else sender
        self.session_glob = SESS_GLOB if session_glob is None else session_glob
        self.cache_dir = CACHE_DIR if cache_dir is None else cache_dir
        self.process_check = dsh_running if process_check is None else process_check
        self.sessions = {}
        self.t_scan = self.t_proc = None
        self.running = True

    def key_for_title(self, title):
        matches = [s for s in self.sessions.values()
                   if s.title and s.title.casefold() == title.strip().casefold()]
        return max(matches, key=lambda s: s.last_event).key if matches else None

    def _send(self, line):
        try:
            return self.sender(line)
        except Exception as e:
            log.debug("send failed (%s): %s", line, e)
            return False

    def tick(self, now=None):
        now = time.time() if now is None else now
        if self.t_scan is None or now - self.t_scan >= 3:
            self.t_scan = now
            for path in glob.glob(self.session_glob):
                if path in self.sessions:
                    continue
                try:
                    s = self.sessions[path] = Session(path, self.cache_dir)
                    age = now - os.path.getmtime(path)
                    if age > REPLAY_WINDOW:
                        s.offset = os.path.getsize(path)      # 太旧：只跟以后的新内容
                    else:
                        s.read_new()
                        if now - s.last_event > RECENT:
                            s.started = False                 # 旧会话：等它有新一轮再上报
                    log.info("tracking %s (%s)", s.key, s.name)
                except Exception as e:
                    log.warning("scan %s: %s", path, e)
        if self.t_proc is None or now - self.t_proc >= 10:
            self.t_proc = now
            try:
                was, self.running = self.running, self.process_check()
            except Exception as e:
                log.debug("process check: %s", e)
                was = self.running
            if was and not self.running:
                log.info("dsh exited")
                for s in self.sessions.values():              # 程序关了：等待和进行中的状态都不算数了
                    s.open, s.started = False, False
                    s.calls.clear()
                    s.asks.clear()
        for s in self.sessions.values():
            try:
                s.read_new()
            except Exception as e:
                log.warning("read %s: %s", s.key, e)
                s.reset()
            st = s.state()
            if st is None:
                if s.sent is not None and self._send("end %s" % s.key):
                    s.sent = None
            elif st != s.sent or (st in ("think", "tool", "wait") and now - s.sent_at > RESEND):
                if self._send("set %s %s %s" % (s.key, st, s.name)):
                    if st != s.sent:
                        log.info("%s %s -> %s", s.key, s.sent, st)
                    s.sent, s.sent_at = st, now


def main():
    # 旧入口也运行统一 daemon，避免两个循环争抢原来的单实例端口。
    import daemon
    daemon.main(verbose="-v" in sys.argv)


if __name__ == "__main__":
    main()
