"""AgentDeck 打包版验收脚本（对着正在运行的 AgentDeck.exe 跑）。

检查项：
  window-health   AgentDeck 每个窗口 20 秒内反复 1 秒内响应 WM_NULL，IsHungAppWindow 为假，并截图
  window-cursor   鼠标移到浮窗上不是忙碌/转圈光标
  hook ...        按 ~/.claude/settings.json、~/.codex/hooks.json 里的原样命令，用 agent 真实的方式
                  （Claude Code = Git Bash，Codex = cmd 与 PowerShell）喂中文 UTF-8 载荷，走完
                  SessionStart → UserPromptSubmit → PreToolUse → PermissionRequest → PostToolUse → Stop → SessionEnd，
                  并在 /state、/audit 里核对效果；批准、拒绝、高危两次批准都走 POST /action
  window-switch   开两个标题含项目名的控制台窗口，POST slot 后前台窗口必须变成对应窗口
  overlay-content 两个会话同时在时 /state 列出它们，浮窗截图
  window-load     上面所有操作期间窗口一直在响应
  relay-log       ~/.agentdeck/relay.log 在标记之后没有新错误
  app-log         本次运行期间 app.log 没有 ERROR / 卡顿
  cleanup         /state 里不留 accept- 会话

运行（项目根目录）：
  D:\\conda\\miniconda3\\python.exe -X utf8 research\\acceptance\\accept.py            # 全部检查
  ... accept.py --dry-run      只读：列出将要执行的 hook 命令、窗口、日志位置，不发请求不跑 hook
  ... accept.py --self-test    离线自检脚本自身的逻辑
  ... accept.py --port 47891 --home D:\\tmp\\iso   对隔离实例（hub.py --port/--home）跑
退出码：0 = 全部 PASS；1 = 有 FAIL；2 = 前置条件不满足（hub 不在、token 缺失等）。
证据：research/acceptance/out/<时间>/（report.txt、report.json、hooks.jsonl、截图）。
"""
import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = Path(__file__).resolve().parent / "out"
DEFAULT_PORT = 47800
# Copied from pc/daemon.py (TITLE_PROCESSES / PROCESS_TARGETS) so the harness stays standalone.
TITLE_PROCESSES = {"windowsterminal.exe", "conhost.exe", "openconsole.exe", "pwsh.exe", "powershell.exe",
                   "cmd.exe", "code.exe", "cursor.exe", "wezterm-gui.exe", "alacritty.exe"}
NATIVE_PROCESSES = {"claude.exe", "codex.exe", "chatgpt.exe", "deepseek harness.exe"}
RELAY_HINTS = ("agentdeck-relay", "hub_relay")
SEQUENCE = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest",
            "PostToolUse", "Stop", "SessionEnd")
EXPECTED_STATE = {"SessionStart": "idle", "UserPromptSubmit": "think", "PreToolUse": "tool",
                  "PostToolUse": "think", "Stop": "done"}
SCENARIOS = {
    "approve": {"actions": ("approve",), "statuses": ("allowed",), "behavior": "allow", "risk": "low"},
    "deny": {"actions": ("deny",), "statuses": ("denied",), "behavior": "deny", "risk": "low"},
    "high": {"actions": ("approve", "approve"), "statuses": ("confirm", "allowed"), "behavior": "allow",
             "risk": "high"},
}
SHORT = {"auto": "doc", "bash": "sh", "cmd": "cmd", "powershell": "ps", "exec": "ex"}
CHECK_GROUPS = ("window", "cursor", "hooks", "overlay", "switch", "logs")
PROMPT = "后面再说，先把 D:\\工作\\后面的项目 里的测试跑一遍，然后总结进度 ✅🚀"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010


# --------------------------------------------------------------------------- small helpers

def now_ms():
    return time.monotonic() * 1000


def wait_for(predicate, timeout, interval=0.1):
    """Return the first truthy predicate() result within timeout seconds, else None."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            value = predicate()
        except Exception:
            value = None
        if value:
            return value
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def expected_name(cwd):
    """Same rule as pc/agent_lcd.ascii_name: last folder, printable ASCII only, 24 chars."""
    name = os.path.basename(os.path.normpath(cwd or "")) or "agent"
    name = "".join(c if 33 <= ord(c) < 127 else "" for c in name)
    return name[:24] or "agent"


def short(value, limit=160):
    text = value if isinstance(value, str) else repr(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "…"


def big_text(kib):
    """Realistic large tool_input: Chinese prose, Windows paths, emoji. No risky shell words."""
    line = "第{0:05d}行：后面的步骤先别动，路径 D:\\工作\\后面的项目\\src\\模块{0}.py ✅🚀 中文混排 ABC 123\n"
    parts, size, index = [], 0, 0
    while size < kib * 1024:
        text = line.format(index)
        parts.append(text)
        size += len(text.encode("utf-8"))
        index += 1
    return "".join(parts)


BIG_PRE = big_text(400)
BIG_PERM = big_text(200)


def permission_input(scenario, cwd):
    if scenario == "approve":
        return "Bash", {"command": "python -m pytest -q tests\\测试_后面.py", "description": "运行后面的测试"}
    if scenario == "deny":
        return "Write", {"file_path": cwd + "\\docs\\后面的笔记.md", "content": BIG_PERM}
    return "Bash", {"command": "git push --force origin main", "description": "强制推送到 main（后面再改）"}


def build_payload(agent, event, sid, cwd, scenario, turn_id):
    payload = {"session_id": sid, "transcript_path": cwd + "\\" + sid + ".jsonl", "cwd": cwd,
               "hook_event_name": event}
    if agent == "cc":
        payload["permission_mode"] = "default"
    else:
        payload.update(model="gpt-5.6-sol", turn_id=turn_id)
    tool_name, tool_input = permission_input(scenario or "approve", cwd)
    if event == "SessionStart":
        payload["source"] = "startup"
        if agent == "cc":
            payload["model"] = "claude-opus-5-5"
    elif event == "UserPromptSubmit":
        payload["prompt"] = PROMPT
    elif event == "PreToolUse":
        payload.update(tool_name="Write", tool_use_id="toolu_accept_pre",
                       tool_input={"file_path": cwd + "\\docs\\后面的计划.md", "content": BIG_PRE})
    elif event == "PermissionRequest":
        payload.update(tool_name=tool_name, tool_input=tool_input)
        if agent == "cc":
            payload["permission_suggestions"] = [{"type": "addRules", "behavior": "allow",
                                                  "destination": "localSettings",
                                                  "rules": [{"toolName": tool_name}]}]
    elif event == "PostToolUse":
        payload.update(tool_name=tool_name, tool_input=tool_input, tool_use_id="toolu_accept_post",
                       tool_response={"stdout": "3 passed（后面还有 2 个）\nD:\\工作\\后面的项目\\ok",
                                      "stderr": "", "interrupted": False})
    elif event == "Stop":
        payload.update(stop_hook_active=False, last_assistant_message="后面的步骤已经完成。")
    elif event == "SessionEnd":
        payload["reason"] = "other"
    return payload


def encode_payload(payload):
    # Agents send raw UTF-8 JSON (node JSON.stringify / serde), not \\u escapes.
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def parse_decision(stdout):
    """Return (behavior, problem) from a PermissionRequest hook stdout."""
    try:
        data = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, "stdout 不是 JSON：%s" % short(stdout.decode("utf-8", "replace"), 120)
    if not isinstance(data, dict) or set(data) != {"hookSpecificOutput"}:
        return None, "stdout 结构不对：%s" % short(json.dumps(data, ensure_ascii=False), 120)
    output = data["hookSpecificOutput"]
    if not isinstance(output, dict) or output.get("hookEventName") != "PermissionRequest":
        return None, "hookEventName 不是 PermissionRequest"
    decision = output.get("decision")
    if not isinstance(decision, dict) or decision.get("behavior") not in ("allow", "deny"):
        return None, "缺 decision.behavior"
    extra = set(decision) - {"behavior", "message"}
    if extra:
        return None, "decision 含 Codex 会拒绝的字段：%s" % sorted(extra)
    return decision["behavior"], None


def matcher_applies(matcher, event, payload):
    if matcher in (None, "", "*"):
        return True
    target = {"PreToolUse": payload.get("tool_name"), "PostToolUse": payload.get("tool_name"),
              "PermissionRequest": payload.get("tool_name"), "PostToolUseFailure": payload.get("tool_name"),
              "SessionStart": payload.get("source"), "SessionEnd": payload.get("reason"),
              "Notification": payload.get("notification_type")}.get(event)
    if target is None:
        return True
    try:
        return re.fullmatch(matcher, target) is not None
    except re.error:
        return matcher == target


def parse_netstat(text, port):
    for line in text.splitlines():
        parts = line.split()
        if (len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].endswith(":%d" % port)
                and parts[2] in ("0.0.0.0:0", "[::]:0") and parts[-1].isdigit()):
            return int(parts[-1])
    return None


def listening_pid(port):
    try:
        text = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                              errors="replace", timeout=15, creationflags=CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_netstat(text, port)


def new_log_lines(path, offset, skip_prefix=None):
    try:
        data = Path(path).read_bytes()
    except OSError:
        return []
    if offset > len(data):  # rotated
        offset = 0
    lines = data[offset:].decode("utf-8", "replace").splitlines()
    return [line for line in lines if line.strip() and not (skip_prefix and line.startswith(skip_prefix))]


def file_size(path):
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


# --------------------------------------------------------------------------- hook configuration

def load_hook_config(hooks_home):
    """Read (never write) the AgentDeck relay entries from the real agent configs."""
    entries, notes = {"cc": {}, "cx": {}}, []
    files = {"cc": Path(hooks_home) / ".claude" / "settings.json",
             "cx": Path(hooks_home) / ".codex" / "hooks.json"}
    for agent, path in files.items():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            notes.append("%s 不存在" % path)
            continue
        except (OSError, ValueError) as error:
            notes.append("%s 读不了：%s" % (path, error))
            continue
        hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
        for event, groups in (hooks.items() if isinstance(hooks, dict) else ()):
            for group in groups if isinstance(groups, list) else ():
                if not isinstance(group, dict):
                    continue
                for hook in group.get("hooks", []) or []:
                    if not isinstance(hook, dict) or hook.get("type", "command") != "command":
                        continue
                    command = hook.get("command") or ""
                    windows = (hook.get("commandWindows") or hook.get("command_windows")) if agent == "cx" else None
                    effective = windows or command
                    if not isinstance(effective, str) or not any(h in effective.lower() for h in RELAY_HINTS):
                        continue
                    entries[agent].setdefault(event, []).append({
                        "agent": agent, "event": event, "command": effective,
                        "args": hook.get("args") if isinstance(hook.get("args"), list) else None,
                        "shell": hook.get("shell"), "timeout": hook.get("timeout"),
                        "matcher": group.get("matcher"), "source": str(path),
                        "gate": "--gate" in effective})
    toml = Path(hooks_home) / ".codex" / "config.toml"
    try:
        if any(h in toml.read_text(encoding="utf-8", errors="replace").lower() for h in RELAY_HINTS):
            notes.append("%s 里也有 AgentDeck 命令（本脚本只跑 hooks.json 的）" % toml)
    except OSError:
        pass
    return entries, notes


def find_git_bash():
    candidates = []
    if os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"):
        candidates.append(Path(os.environ["CLAUDE_CODE_GIT_BASH_PATH"]))
    git = shutil.which("git")
    if git:
        resolved = Path(git).resolve()
        for root in (resolved.parent.parent, resolved.parent.parent.parent):
            candidates += [root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            candidates.append(Path(base) / "Git" / "bin" / "bash.exe")
    for candidate in candidates:
        lowered = str(candidate).lower()
        if candidate.is_file() and "system32" not in lowered and "windowsapps" not in lowered:
            return candidate  # never WSL's bash.exe
    return None


def find_powershell():
    found = shutil.which("powershell.exe")
    if found:
        return Path(found)
    fallback = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return fallback if fallback.is_file() else None


def adapt_command(command, entry_args, options):
    """Route the exact command to an isolated hub / override relay; report what changed."""
    changed, extras = [], []
    if options.relay_override:
        match = re.search(r"\s--agent\b", command)
        if match:
            command = options.relay_override.strip() + command[match.start():]
            changed.append("relay 换成 --relay-override")
    if options.port != DEFAULT_PORT and not re.search(r"--port\b", command):
        extras += ["--port", str(options.port)]
    if options.home and not re.search(r"--home\b", command):
        extras += ["--home", Path(options.home).resolve().as_posix()]
    if extras:
        changed.append("追加 " + " ".join(extras))
        if entry_args is not None:
            entry_args = list(entry_args) + extras
        else:
            command += " " + " ".join('"%s"' % item if " " in item or "/" in item else item for item in extras)
    return command, entry_args, changed


def resolve_executor(agent, mode, entry, bash):
    if entry.get("args") is not None:
        return "exec"  # Claude Code exec form: no shell at all
    if agent == "cc" and mode == "auto":
        if entry.get("shell") in ("bash", "powershell"):
            return entry["shell"] if entry["shell"] == "powershell" or bash else "powershell"
        return "bash" if bash else "powershell"  # documented Claude Code behaviour on Windows
    return mode


def process_spec(executor, command, entry_args, bash, powershell):
    if executor == "exec":
        return [command] + list(entry_args or [])
    if executor == "bash":
        return [str(bash), "-c", command]
    if executor == "powershell":
        return [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command]
    if executor == "cmd":
        comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
        return '"%s" /d /s /c "%s"' % (comspec, command)  # same form as node's shell:true
    raise ValueError("unknown executor " + executor)


def spec_text(spec):
    return spec if isinstance(spec, str) else subprocess.list2cmdline(spec)


def parse_modes(text, bash):
    modes = []
    for item in [part.strip() for part in text.split(",") if part.strip()]:
        agent, _, mode = item.partition(":")
        if agent not in ("cc", "cx") or mode not in ("auto", "bash", "cmd", "powershell"):
            raise ValueError("bad --shells item %r (use cc:auto,cx:cmd,...)" % item)
        if agent == "cx" and mode == "auto":
            raise ValueError("cx:auto is undefined; Codex does not document its Windows shell")
        if mode == "bash" and bash is None:
            raise ValueError("Git Bash not found for %r" % item)
        modes.append((agent, mode))
    return modes


# --------------------------------------------------------------------------- Win32

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    class CURSORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("hCursor", ctypes.c_void_p), ("ptScreenPos", wintypes.POINT)]

    for _name, _args, _res in (
            ("EnumWindows", [EnumWindowsProc, wintypes.LPARAM], wintypes.BOOL),
            ("GetWindowThreadProcessId", [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            ("GetWindowTextLengthW", [wintypes.HWND], ctypes.c_int),
            ("GetWindowTextW", [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            ("GetClassNameW", [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            ("IsWindowVisible", [wintypes.HWND], wintypes.BOOL),
            ("IsWindow", [wintypes.HWND], wintypes.BOOL),
            ("IsHungAppWindow", [wintypes.HWND], wintypes.BOOL),
            ("GetWindowRect", [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            ("SendMessageTimeoutW", [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                     wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)],
             ctypes.c_ssize_t),
            ("PostMessageW", [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
            ("FindWindowExW", [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR], wintypes.HWND),
            ("GetForegroundWindow", [], wintypes.HWND),
            ("GetCursorInfo", [ctypes.POINTER(CURSORINFO)], wintypes.BOOL),
            ("GetCursorPos", [ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
            ("SetCursorPos", [ctypes.c_int, ctypes.c_int], wintypes.BOOL),
            ("LoadCursorW", [wintypes.HINSTANCE, ctypes.c_void_p], ctypes.c_void_p),
            ("WindowFromPoint", [wintypes.POINT], wintypes.HWND),
            ("GetAncestor", [wintypes.HWND, wintypes.UINT], wintypes.HWND)):
        _fn = getattr(user32, _name)
        _fn.argtypes, _fn.restype = _args, _res
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    for _name, _args, _res in (
            ("GetDC", [wintypes.HWND], ctypes.c_void_p),
            ("ReleaseDC", [wintypes.HWND, ctypes.c_void_p], ctypes.c_int),
            ("PrintWindow", [wintypes.HWND, ctypes.c_void_p, wintypes.UINT], wintypes.BOOL),
            ("GetWindowLongPtrW", [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t),
            ("OpenInputDesktop", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            ("CloseDesktop", [wintypes.HANDLE], wintypes.BOOL),
            ("GetUserObjectInformationW", [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)):
        _fn = getattr(user32, _name)
        _fn.argtypes, _fn.restype = _args, _res
    for _name, _args, _res in (
            ("CreateCompatibleDC", [ctypes.c_void_p], ctypes.c_void_p),
            ("CreateCompatibleBitmap", [ctypes.c_void_p, ctypes.c_int, ctypes.c_int], ctypes.c_void_p),
            ("SelectObject", [ctypes.c_void_p, ctypes.c_void_p], ctypes.c_void_p),
            ("DeleteObject", [ctypes.c_void_p], wintypes.BOOL),
            ("DeleteDC", [ctypes.c_void_p], wintypes.BOOL),
            ("GetDIBits", [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                           ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT], ctypes.c_int)):
        _fn = getattr(gdi32, _name)
        _fn.argtypes, _fn.restype = _args, _res
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]


def set_dpi_aware():
    try:
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return "per-monitor-v2"
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return "per-monitor"
    except (AttributeError, OSError):
        return "unaware"


def window_pid(hwnd):
    pid = wintypes.DWORD()
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value, tid


def window_text(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(max(length, 0) + 2)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def window_class(hwnd):
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def window_rect(hwnd):
    rect = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:  # extended frame
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
    return rect.left, rect.top, rect.right, rect.bottom


def window_cloaked(hwnd):
    value = wintypes.DWORD()
    if dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(value), ctypes.sizeof(value)) != 0:
        return False
    return bool(value.value)


def process_name(pid):
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def describe_window(hwnd):
    pid, tid = window_pid(hwnd)
    rect = window_rect(hwnd)
    visible = bool(user32.IsWindowVisible(hwnd)) and not window_cloaked(hwnd)
    if rect and (rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0):
        visible = False
    return {"hwnd": int(hwnd), "pid": pid, "tid": tid, "title": window_text(hwnd), "cls": window_class(hwnd),
            "visible": visible, "rect": rect}


def enum_windows(pid=None):
    found = []

    @EnumWindowsProc
    def collect(hwnd, _):
        try:
            if pid is None or window_pid(hwnd)[0] == pid:
                found.append(int(hwnd))
        except Exception:
            pass
        return True

    user32.EnumWindows(collect, 0)
    if pid is not None:  # message-only windows (Raw Input, tray helpers) are not top-level
        child = None
        message = wintypes.HWND(-3)
        while True:
            child = user32.FindWindowExW(message, child, None, None)
            if not child:
                break
            if window_pid(child)[0] == pid:
                found.append(int(child))
    result = []
    for hwnd in found:
        try:
            result.append(describe_window(hwnd))
        except Exception:
            pass
    return result


def label_window(item):
    title = item["title"] or "-"
    return "%s「%s」0x%X%s" % (item["cls"], short(title, 40), item["hwnd"], "" if item["visible"] else " 隐藏")


def probe_window(hwnd, timeout_ms=1000):
    """(ok, elapsed_ms, hung, gone)"""
    if not user32.IsWindow(hwnd):
        return True, 0.0, False, True
    result = ctypes.c_size_t()
    start = now_ms()
    answered = user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 0x0002 | 0x0020, timeout_ms, ctypes.byref(result))
    elapsed = now_ms() - start
    error = ctypes.get_last_error()
    if not answered and not user32.IsWindow(hwnd):
        return True, elapsed, False, True
    hung = bool(user32.IsHungAppWindow(hwnd))
    return bool(answered), elapsed, hung, False if answered or error != 1400 else True


def foreground():
    return int(user32.GetForegroundWindow() or 0)


def cursor_handles():
    return {int(user32.LoadCursorW(None, ctypes.c_void_p(32514)) or 0): "IDC_WAIT（忙碌）",
            int(user32.LoadCursorW(None, ctypes.c_void_p(32650)) or 0): "IDC_APPSTARTING（后台转圈）"}


def current_cursor():
    info = CURSORINFO()
    info.cbSize = ctypes.sizeof(CURSORINFO)
    if not user32.GetCursorInfo(ctypes.byref(info)):
        return None
    return int(info.hCursor or 0)


def cursor_pos():
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def root_at(x, y):
    hwnd = user32.WindowFromPoint(wintypes.POINT(x, y))
    if not hwnd:
        return 0
    return int(user32.GetAncestor(hwnd, 2) or hwnd)  # GA_ROOT


def grab(rect, path):
    """What the user actually sees at that rectangle (may include windows covering it)."""
    from PIL import ImageGrab
    image = ImageGrab.grab(bbox=tuple(int(v) for v in rect), include_layered_windows=True, all_screens=True)
    image.save(path)
    return image


def _print_window(hwnd, width, height):
    from PIL import Image
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    old = gdi32.SelectObject(memory, bitmap)
    try:
        if not user32.PrintWindow(hwnd, memory, 2):  # PW_RENDERFULLCONTENT: DWM copy, works when covered
            return None
        gdi32.SelectObject(memory, old)
        old = None
        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(width * height * 4)
        if gdi32.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(header), 0) != height:
            return None
        return Image.frombuffer("RGB", (width, height), buffer.raw, "raw", "BGRX", 0, 1)
    finally:
        if old:
            gdi32.SelectObject(memory, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(None, screen)


def capture_window(hwnd, timeout=3.0):
    """The window's own rendering via PrintWindow, in a worker so a hung window cannot block us."""
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    result = {}

    def work():
        try:
            result["image"] = _print_window(hwnd, width, height)
        except Exception as error:
            result["error"] = error

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(timeout)
    return result.get("image")


def occlusion(item, pid):
    """Fraction of a 5x5 grid inside the window that belongs to another process's window."""
    left, top, right, bottom = item["rect"]
    others = {}
    total = 0
    for i in range(5):
        for j in range(5):
            x = left + 2 + (right - left - 4) * i // 4
            y = top + 2 + (bottom - top - 4) * j // 4
            root = root_at(x, y)
            total += 1
            if not root or window_pid(root)[0] != pid:
                key = "%s「%s」" % (window_class(root), short(window_text(root), 20)) if root else "无窗口"
                others[key] = others.get(key, 0) + 1
    covered = sum(others.values())
    top_other = max(others, key=others.get) if others else ""
    return covered / float(total), top_other


BLOCKING_CLASSES = {"Shell_SystemDialog", "LockScreenBackstopFrame", "Credential Dialog Xaml Host"}
BLOCKING_PROCESSES = {"lockapp.exe", "logonui.exe", "consent.exe", "credentialuibroker.exe"}


def session_locked():
    """True/False from WTSQuerySessionInformation(WTSSessionInfoEx); None if unknown.

    On Windows 10/11 the lock curtain can sit on the *Default* input desktop with a NULL foreground
    window, so the desktop-name check alone reported "usable" while the session was locked."""
    class WTSINFOEX_LEVEL1_W(ctypes.Structure):
        _fields_ = [("SessionId", wintypes.ULONG), ("SessionState", ctypes.c_int),
                    ("SessionFlags", wintypes.LONG), ("WinStationName", wintypes.WCHAR * 33),
                    ("UserName", wintypes.WCHAR * 21), ("DomainName", wintypes.WCHAR * 18),
                    ("LogonTime", ctypes.c_longlong), ("ConnectTime", ctypes.c_longlong),
                    ("DisconnectTime", ctypes.c_longlong), ("LastInputTime", ctypes.c_longlong),
                    ("CurrentTime", ctypes.c_longlong)] + [(n, wintypes.DWORD) for n in (
                        "IncomingBytes", "OutgoingBytes", "IncomingFrames", "OutgoingFrames",
                        "IncomingCompressedBytes", "OutgoingCompressedBytes")]

    class WTSINFOEXW(ctypes.Structure):
        _fields_ = [("Level", wintypes.DWORD), ("Data", WTSINFOEX_LEVEL1_W)]

    try:
        wts = ctypes.WinDLL("wtsapi32")
        wts.WTSQuerySessionInformationW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
                                                    ctypes.POINTER(ctypes.c_void_p),
                                                    ctypes.POINTER(wintypes.DWORD)]
        wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        session = wintypes.DWORD()
        if not kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(session)):
            return None
        buffer, size = ctypes.c_void_p(), wintypes.DWORD()
        if not wts.WTSQuerySessionInformationW(None, session.value, 25, ctypes.byref(buffer), ctypes.byref(size)):
            return None  # 25 = WTSSessionInfoEx
        try:
            flags = ctypes.cast(buffer, ctypes.POINTER(WTSINFOEXW)).contents.Data.SessionFlags
        finally:
            wts.WTSFreeMemory(buffer)
    except (AttributeError, OSError, ValueError):
        return None
    # WTS_SESSIONSTATE_LOCK = 0, UNLOCK = 1, UNKNOWN = -1 (Windows 7 had them reversed; not supported here).
    return True if flags == 0 else False if flags == 1 else None


def lock_curtain_visible():
    """A visible LockScreenBackstopFrame (LockApp) window means the lock screen covers everything."""
    found = []

    @EnumWindowsProc
    def collect(hwnd, _):
        if user32.IsWindowVisible(hwnd) and window_class(hwnd) == "LockScreenBackstopFrame":
            found.append(hwnd)
        return True

    user32.EnumWindows(collect, 0)
    return bool(found)


def desktop_status():
    """(usable, description). Locked screen, UAC or a Windows Security prompt make window checks meaningless."""
    locked = session_locked()
    curtain = lock_curtain_visible()
    if locked or curtain:
        return False, "会话已锁屏（WTS 锁定=%s，锁屏窗口可见=%s）：截图、悬停、切窗口都测不了" % (locked, curtain)
    name = None
    handle = user32.OpenInputDesktop(0, False, 0x0001)  # DESKTOP_READOBJECTS
    if handle:
        buffer = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD()
        if user32.GetUserObjectInformationW(handle, 2, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)):
            name = buffer.value
        user32.CloseDesktop(handle)
    hwnd = foreground()
    cls = window_class(hwnd) if hwnd else ""
    title = window_text(hwnd) if hwnd else ""
    process = os.path.basename(process_name(window_pid(hwnd)[0])).lower() if hwnd else ""
    usable = name == "Default" and cls not in BLOCKING_CLASSES and process not in BLOCKING_PROCESSES
    return usable, "输入桌面 %s；前台窗口 %s「%s」（%s）" % (name or "打不开（锁屏？）", cls or "-", short(title, 30),
                                                    process or "-")


def window_styles(hwnd):
    return user32.GetWindowLongPtrW(hwnd, -16) & 0xFFFFFFFF, user32.GetWindowLongPtrW(hwnd, -20) & 0xFFFFFFFF


def image_blank(image):
    low, high = image.convert("L").getextrema()
    return high - low < 8


def image_diff_ratio(first, second):
    from PIL import ImageChops
    if first is None or second is None or first.size != second.size:
        return None
    diff = ImageChops.difference(first.convert("RGB"), second.convert("RGB")).convert("L")
    histogram = diff.histogram()
    changed = sum(histogram[16:])
    return changed / float(first.size[0] * first.size[1] or 1)


class Prober(threading.Thread):
    """Probe every AgentDeck window (visible, hidden and message-only) with WM_NULL."""

    def __init__(self, pid, interval=0.5, timeout_ms=1000):
        super().__init__(name="accept-prober", daemon=True)
        self.pid, self.interval, self.timeout_ms = pid, interval, timeout_ms
        self.stop_event = threading.Event()
        self.stats = {}
        self.lock = threading.Lock()

    def run(self):
        windows, enumerated = [], 0.0
        while True:
            if time.monotonic() - enumerated > 3:
                try:
                    windows = enum_windows(self.pid)
                except Exception:
                    windows = []
                enumerated = time.monotonic()
            for item in windows:
                ok, elapsed, hung, gone = probe_window(item["hwnd"], self.timeout_ms)
                with self.lock:
                    stat = self.stats.setdefault(item["hwnd"], {"item": item, "n": 0, "fail": 0, "hung": 0,
                                                                "max_ms": 0.0, "gone": False})
                    stat["item"] = item if not gone else stat["item"]
                    if gone:
                        stat["gone"] = True
                        continue
                    stat["n"] += 1
                    stat["fail"] += 0 if ok else 1
                    stat["hung"] += 1 if hung else 0
                    stat["max_ms"] = max(stat["max_ms"], elapsed)
            if self.stop_event.wait(self.interval):
                return

    def finish(self):
        self.stop_event.set()
        self.join(timeout=10)
        with self.lock:
            return {hwnd: dict(stat) for hwnd, stat in self.stats.items()}


def summarize_probe(stats):
    problems, lines, visible = [], [], 0
    for stat in stats.values():
        item = stat["item"]
        visible += 1 if item["visible"] else 0
        line = "%s：%d 次，最慢 %.0f ms" % (label_window(item), stat["n"], stat["max_ms"])
        if stat["gone"]:
            line += "（中途关闭）"
        lines.append(line)
        if stat["fail"] or stat["hung"]:
            problems.append("%s：%d/%d 次 1 秒内无响应，IsHungAppWindow=%d 次" % (
                label_window(item), stat["fail"], stat["n"], stat["hung"]))
    return problems, lines, visible


# --------------------------------------------------------------------------- hub HTTP

class HubClient:
    def __init__(self, port, token):
        self.base = "http://127.0.0.1:%d" % port
        self.token = token
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy

    def call(self, method, path, body=None, timeout=5.0):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"X-AgentDeck-Token": self.token or "",
                                                  "Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read() or b"{}")
            except ValueError:
                return error.code, {}
        except (OSError, ValueError) as error:
            return None, {"error": repr(error)}

    def state(self):
        code, body = self.call("GET", "/state")
        return body if code == 200 and isinstance(body, dict) else None

    def post(self, path, body):
        return self.call("POST", path, body)


# --------------------------------------------------------------------------- hook processes

class HookRun:
    """One hook command execution, exactly like an agent: stdin = UTF-8 JSON, then wait."""

    def __init__(self, ctx, entry, executor, payload, cwd, timeout):
        self.ctx, self.entry, self.executor = ctx, entry, executor
        self.event = payload["hook_event_name"]
        command, entry_args, self.adapted = adapt_command(entry["command"], entry.get("args"), ctx.args)
        self.spec = process_spec(executor, command, entry_args, ctx.bash, ctx.powershell)
        self.payload = encode_payload(payload)
        self.timeout = timeout
        self.stdout = self.stderr = b""
        self.code = None
        self.error = None
        self.timed_out = False
        self.started = time.monotonic()
        self.ended = None
        try:
            self.proc = subprocess.Popen(self.spec, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, cwd=cwd, creationflags=CREATE_NO_WINDOW)
        except OSError as error:
            self.proc, self.error, self.ended = None, "启动失败：%r" % error, time.monotonic()
            self.thread = None
            ctx.log_hook(self)
            return
        ctx.live_runs.append(self)
        self.thread = threading.Thread(target=self._communicate, daemon=True)
        self.thread.start()

    def _communicate(self):
        try:
            self.stdout, self.stderr = self.proc.communicate(self.payload, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self.timed_out = True
            self.proc.kill()
            try:
                self.stdout, self.stderr = self.proc.communicate(timeout=5)
            except Exception:
                pass
        except Exception as error:
            self.error = repr(error)
        self.code = self.proc.returncode
        self.ended = time.monotonic()
        self.ctx.log_hook(self)

    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def wait(self, timeout):
        if self.thread is not None:
            self.thread.join(timeout)
        return not self.running()

    def kill(self):
        if self.proc is not None and self.running():
            try:
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True,
                               timeout=10, creationflags=CREATE_NO_WINDOW)
            except Exception:
                self.proc.kill()

    @property
    def seconds(self):
        return ((self.ended or time.monotonic()) - self.started)

    def text(self, which):
        return getattr(self, which).decode("utf-8", "replace").strip()

    def brief(self):
        if self.error:
            return self.error
        return "退出码 %s，%.1fs，stdout=%r，stderr=%r" % (self.code, self.seconds, short(self.text("stdout"), 100),
                                                    short(self.text("stderr"), 160))

    def problems(self, expect_stdout=None, expect_behavior=None):
        found = []
        if self.error:
            return [self.error]
        if self.running():
            return ["hook 进程还没结束"]
        if self.timed_out:
            found.append("超时（%ss）被杀" % self.timeout)
        if self.code != 0:
            found.append("退出码 %s" % self.code)
        limit = self.entry.get("timeout")
        if isinstance(limit, (int, float)) and self.seconds > limit:
            found.append("耗时 %.1fs 超过 agent 的 hook 超时 %ss" % (self.seconds, limit))
        out = self.text("stdout")
        if expect_stdout is not None and out != expect_stdout:
            found.append("stdout=%r（应为 %r；空 = hub 没收到或 relay 出错）" % (short(out, 100), expect_stdout))
        if expect_behavior is not None:
            behavior, problem = parse_decision(self.stdout)
            if problem:
                found.append(problem)
            elif behavior != expect_behavior:
                found.append("决定是 %s，应为 %s" % (behavior, expect_behavior))
        if found and self.text("stderr"):
            found.append("stderr=%r" % short(self.text("stderr"), 200))
        return found


# --------------------------------------------------------------------------- report

class Report:
    def __init__(self):
        self.rows = []

    def add(self, name, ok, detail, evidence=(), info=False, skip=False):
        status = "SKIP" if skip else "INFO" if info else "PASS" if ok else "FAIL"
        if info and not ok and not skip:
            status = "WARN"
        lines = [detail] if isinstance(detail, str) else [line for line in detail if line]
        self.rows.append({"name": name, "status": status, "detail": lines, "evidence": [str(p) for p in evidence]})
        print("  [%s] %s — %s" % (status, name, lines[0] if lines else ""), flush=True)
        return ok

    def failed(self):
        return [row for row in self.rows if row["status"] == "FAIL"]

    def render(self, header, run_dir):
        width = max([len(row["name"]) for row in self.rows] + [10])
        out = [header, "-" * 78, "结果  %-*s  说明" % (width, "检查项"), "-" * 78]
        for row in self.rows:
            detail = row["detail"] or [""]
            out.append("%-4s  %-*s  %s" % (row["status"], width, row["name"], detail[0]))
            out += ["      %-*s  %s" % (width, "", line) for line in detail[1:12]]
            if len(detail) > 12:
                out.append("      %-*s  …另有 %d 行，见 report.json" % (width, "", len(detail) - 12))
            out += ["      %-*s  证据 %s" % (width, "", path) for path in row["evidence"][:8]]
        counts = {}
        for row in self.rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        verdict = "FAIL" if self.failed() else "PASS"
        out += ["-" * 78, "合计：" + "，".join("%s %d" % (k, v) for k, v in sorted(counts.items())) +
                "  →  " + verdict, "证据目录：%s" % run_dir]
        return "\n".join(out)


# --------------------------------------------------------------------------- test context

class Session:
    def __init__(self, ctx, agent, mode, scenario, name=None):
        self.ctx, self.agent, self.mode, self.scenario = ctx, agent, mode, scenario
        tag = ("sh" if ctx.bash else "ps") if mode == "auto" else SHORT[mode]
        self.sid = "accept-%s-%s-%s-%s-%s" % (agent, tag, scenario or "win", ctx.tag, uuid.uuid4().hex[:6])
        # Distinctive last folder (<= 24 ASCII chars) so the overlay name is unambiguous.
        name = name or "accept-%s-%s-%s-%s" % (agent, tag, (scenario or "w")[0], ctx.tag)
        folder = ctx.work / "后面的项目" / name
        folder.mkdir(parents=True, exist_ok=True)
        self.cwd = str(folder)
        self.name = expected_name(self.cwd)
        self.turn_id = str(uuid.uuid4())
        self.slot = None
        ctx.created[self.sid] = agent

    def payload(self, event):
        return build_payload(self.agent, event, self.sid, self.cwd, self.scenario, self.turn_id)

    def entries(self, event, payload):
        return [entry for entry in self.ctx.entries[self.agent].get(event, [])
                if matcher_applies(entry.get("matcher"), event, payload)]

    def start(self, entry, payload, timeout):
        executor = resolve_executor(self.agent, self.mode, entry, self.ctx.bash)
        return HookRun(self.ctx, entry, executor, payload, self.cwd, timeout)

    def find(self, state=None):
        state = state if state is not None else self.ctx.hub.state()
        for session in (state or {}).get("sessions", []):
            if session.get("session_id") == self.sid and session.get("agent") == self.agent:
                return session
        return None


class Context:
    def __init__(self, args):
        self.args = args
        self.home = Path(args.home).resolve() if args.home else Path.home()
        self.hooks_home = Path(args.hooks_home).resolve() if args.hooks_home else Path.home()
        self.agentdeck = self.home / ".agentdeck"
        self.run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.tag = "%06d" % (int(time.time()) % 1000000)
        self.out = Path(args.out).resolve() / self.run_id if args.out else OUT_ROOT / self.run_id
        self.work = self.out / "work"
        self.report = Report()
        self.created = {}
        self.live_runs = []
        self.consoles = []
        self.hub = None
        self.hub_pid = None
        self.bash = find_git_bash()
        self.powershell = find_powershell()
        self.entries, self.entry_notes = load_hook_config(self.hooks_home)
        self.hook_log_lock = threading.Lock()
        self.baseline_images = {}
        self.saved_cursor = None
        self.desktop_usable, self.desktop_where = True, ""

    def skipped(self, group):
        return group in self.args.skip

    def log_hook(self, run):
        record = {"time": datetime.now().isoformat(timespec="milliseconds"), "agent": run.entry["agent"],
                  "event": run.event, "executor": run.executor, "configured_command": run.entry["command"],
                  "adapted": run.adapted, "spawn": spec_text(run.spec), "exit": run.code,
                  "seconds": round(run.seconds, 3), "timed_out": run.timed_out, "error": run.error,
                  "stdout": run.text("stdout")[:2000], "stderr": run.text("stderr")[:2000],
                  "payload_bytes": len(run.payload)}
        with self.hook_log_lock:
            self.out.mkdir(parents=True, exist_ok=True)
            with open(self.out / "hooks.jsonl", "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def snap(self, label):
        """DPI-aware screenshots of every visible AgentDeck window.

        <label>-N-screen.png is what the user sees there (other windows may cover it);
        <label>-N-window.png is the window's own rendering (PrintWindow), used for content checks.
        Returns (paths, {hwnd: window image}, notes)."""
        paths, images, notes = [], {}, []
        if not self.hub_pid:
            return paths, images, notes
        for index, item in enumerate(w for w in enum_windows(self.hub_pid) if w["visible"] and w["rect"]):
            base = "%s-%d-%s" % (label, index, re.sub(r"[^A-Za-z0-9]+", "", item["cls"])[:20])
            try:
                grab(item["rect"], self.out / (base + "-screen.png"))
                paths.append(self.out / (base + "-screen.png"))
            except Exception as error:
                notes.append("屏幕截图失败 %s：%s" % (label_window(item), error))
            image = capture_window(item["hwnd"])
            if image is not None:
                image.save(self.out / (base + "-window.png"))
                paths.append(self.out / (base + "-window.png"))
                images[item["hwnd"]] = image
            else:
                notes.append("PrintWindow 截不到 %s（失败或 3 秒没返回）" % label_window(item))
            covered, other = occlusion(item, self.hub_pid)
            if covered > 0.05:
                notes.append("%s 在屏幕上被遮挡 %.0f%%，挡住它的是 %s" % (label_window(item), covered * 100, other))
        return paths, images, notes

    def decide(self, request_id, nonce, action, pre_sleep):
        time.sleep(pre_sleep)  # honour the 300 ms switch guard
        result = (None, {})
        for _ in range(12):
            result = self.hub.post("/action", {"action": action, "request_id": request_id, "nonce": nonce})
            code, body = result
            if code == 409 and body.get("error") == "switch_guard":
                time.sleep(0.35)
                continue
            break
        return result

    def modes(self):
        required = parse_modes(self.args.shells, self.bash)
        info = []
        if self.args.all_shells:
            doc_cc = "bash" if self.bash else "powershell"
            for agent, mode in (("cc", "cmd"), ("cc", "powershell"), ("cc", "bash"), ("cx", "bash"),
                                ("cx", "cmd"), ("cx", "powershell")):
                if mode == "bash" and self.bash is None:
                    continue
                if (agent, mode) in required or (agent == "cc" and mode == doc_cc and ("cc", "auto") in required):
                    continue
                info.append((agent, mode))
        return required, info


# --------------------------------------------------------------------------- checks

def preflight(ctx):
    problems, lines = [], []
    lines.append("hub 127.0.0.1:%d，AgentDeck 目录 %s，hook 配置目录 %s" % (ctx.args.port, ctx.agentdeck, ctx.hooks_home))
    token_path = ctx.agentdeck / "token"
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        token = ""
        problems.append("读不到 token %s：%s" % (token_path, error))
    ctx.hub = HubClient(ctx.args.port, token)
    code, body = ctx.hub.call("GET", "/health", timeout=3)
    if code != 200 or body.get("ok") is not True:
        problems.append("GET /health 失败（%s %s）——AgentDeck 没在这个端口运行" % (code, short(body, 80)))
    state = ctx.hub.state() if token else None
    if token and state is None:
        problems.append("GET /state 被拒或失败（token 不对？）")
    ctx.hub_pid = listening_pid(ctx.args.port)
    if ctx.hub_pid:
        lines.append("监听进程 PID %d：%s" % (ctx.hub_pid, process_name(ctx.hub_pid) or "?"))
    else:
        problems.append("netstat 找不到监听 %d 端口的进程" % ctx.args.port)
    for agent, needed in (("cc", SEQUENCE), ("cx", SEQUENCE)):
        missing = [event for event in needed if event not in ctx.entries[agent]]
        found = sum(len(v) for v in ctx.entries[agent].values())
        lines.append("%s：找到 %d 条 AgentDeck hook%s" % (agent, found, "，缺 " + ",".join(missing) if missing else ""))
        if missing and not ctx.skipped("hooks"):
            problems.append("%s 的 hook 缺事件：%s" % (agent, ", ".join(missing)))
    lines += ctx.entry_notes
    lines.append("Git Bash：%s；PowerShell：%s" % (ctx.bash or "没找到", ctx.powershell or "没找到"))
    if state is not None:
        sessions = state.get("sessions", [])
        free = 6 - len(sessions)
        lines.append("当前 %d 个会话，空槽 %d；nonce_required=%s；input_mode=%s" % (
            len(sessions), free, state.get("nonce_required"), state.get("input_mode")))
        if free < 2:
            lines.append("注意：空槽不足 2 个，测试会挤掉最久没动的真实会话（它下次有事件会回来）")
        stale = [s for s in sessions if str(s.get("session_id", "")).startswith("accept-")]
        for session in stale:
            ctx.hub.post("/event?agent=%s" % session["agent"],
                         {"hook_event_name": "SessionEnd", "session_id": session["session_id"]})
        if stale:
            lines.append("清掉上次残留的 %d 个 accept- 会话" % len(stale))
    ctx.report.add("preflight", not problems, problems + lines)
    return not problems


def build_freshness(ctx):
    if ctx.args.relay_override:
        return
    pairs = []
    for exe, sources in ((ROOT / "dist" / "AgentDeck" / "AgentDeck-relay.exe", [ROOT / "pc" / "hub_relay.py",
                                                                             ROOT / "pc" / "hub_risk.py"]),
                         (ROOT / "dist" / "AgentDeck" / "AgentDeck.exe", sorted((ROOT / "pc").glob("*.py")))):
        if not exe.exists():
            continue
        newest = max(sources, key=lambda p: p.stat().st_mtime if p.exists() else 0)
        exe_time, src_time = exe.stat().st_mtime, newest.stat().st_mtime if newest.exists() else 0
        stamp = lambda t: datetime.fromtimestamp(t).strftime("%m-%d %H:%M")
        if src_time > exe_time:
            pairs.append("%s 打包于 %s，比源码 %s（%s）旧——没重新打包？" % (exe.name, stamp(exe_time), newest.name,
                                                                   stamp(src_time)))
        else:
            pairs.append("%s 打包于 %s，不旧于源码" % (exe.name, stamp(exe_time)))
    if pairs:
        ctx.report.add("build-freshness", not any("旧——" in p for p in pairs), pairs, info=True)


def window_baseline(ctx):
    if not ctx.hub_pid:
        ctx.report.add("window-health", False, "没有 hub 进程 PID，无法检查窗口")
        return
    print("  窗口体检 %ds …" % ctx.args.duration, flush=True)
    windows = enum_windows(ctx.hub_pid)
    visible = [w for w in windows if w["visible"]]
    paths, images, notes = ctx.snap("baseline")
    ctx.baseline_images = images
    prober = Prober(ctx.hub_pid)
    prober.start()
    time.sleep(ctx.args.duration)
    problems, lines, _ = summarize_probe(prober.finish())
    if not visible:
        problems.insert(0, "没有可见的 AgentDeck 窗口（浮窗被隐藏？托盘里点“显示”）")
    blank = [label_window(w) for w in visible if w["hwnd"] in images and image_blank(images[w["hwnd"]])]
    if blank:
        problems.append("窗口自身画面是纯色（没画出内容）：%s" % ", ".join(blank))
    ctx.report.add("window-health", not problems,
                   problems + ["%d 个窗口（可见 %d），每 0.5 秒发一次 WM_NULL，持续 %d 秒" % (
                       len(windows), len(visible), ctx.args.duration)] + notes + lines, paths)
    # The overlay must not steal focus from the agent terminal when clicked (README: WS_EX_NOACTIVATE).
    overlay_problems, overlay_lines = [], []
    for item in visible:
        style, exstyle = window_styles(item["hwnd"])
        if exstyle & 0x8 and (style & 0x00C00000) != 0x00C00000:  # topmost, no caption = the floating overlay
            overlay_lines.append("%s exstyle=0x%X" % (label_window(item), exstyle))
            if not exstyle & 0x08000000:
                overlay_problems.append("%s 没有 WS_EX_NOACTIVATE（exstyle=0x%X），点它会抢走终端焦点" % (
                    label_window(item), exstyle))
    if overlay_lines:
        ctx.report.add("overlay-noactivate", not overlay_problems, overlay_problems or overlay_lines)


def cursor_check(ctx):
    if not ctx.hub_pid:
        ctx.report.add("window-cursor", False, "没有 hub 进程 PID")
        return
    if not ctx.desktop_usable:
        ctx.report.add("window-cursor", True, "没测：" + ctx.desktop_where, skip=True)
        return
    busy = cursor_handles()
    visible = [w for w in enum_windows(ctx.hub_pid) if w["visible"] and w["rect"]]
    if not visible:
        ctx.report.add("window-cursor", False, "没有可见窗口可悬停")
        return
    ctx.saved_cursor = cursor_pos()
    problems, lines = [], []
    try:
        for item in visible:
            left, top, right, bottom = item["rect"]
            points = [((left + right) // 2, (top + bottom) // 2), (left + 12, top + 12),
                      (right - 12, bottom - 12), ((left + right) // 2, top + 8)]
            point = next((p for p in points if window_pid(root_at(*p))[0] == ctx.hub_pid), None)
            if point is None:
                lines.append("%s 被别的窗口挡住，跳过" % label_window(item))
                continue
            user32.SetCursorPos(*point)
            time.sleep(0.4)
            samples = []
            for _ in range(8):
                user32.SetCursorPos(point[0] + (len(samples) % 2), point[1])  # tiny wiggle -> WM_SETCURSOR
                time.sleep(0.25)
                samples.append(current_cursor())
            bad = sorted({busy[h] for h in samples if h in busy})
            if bad:
                problems.append("%s 上光标是 %s" % (label_window(item), "、".join(bad)))
            else:
                lines.append("%s 上光标正常（8 次采样）" % label_window(item))
    finally:
        if ctx.saved_cursor:
            user32.SetCursorPos(*ctx.saved_cursor)
            ctx.saved_cursor = None
    if not problems and not any("正常" in line for line in lines):
        problems.append("没有一个窗口能悬停检查")
    ctx.report.add("window-cursor", not problems, problems + lines)


def event_step(ctx, session, event, problems, notes):
    payload = session.payload(event)
    entries = session.entries(event, payload)
    if not entries:
        problems.append("%s：%s 没装 AgentDeck hook（或 matcher 不匹配）" % (event, session.agent))
        return False
    before = session.find()
    before_updated = (before or {}).get("last_updated", 0)
    ok = True
    for entry in entries:
        limit = entry.get("timeout") if isinstance(entry.get("timeout"), (int, float)) else 10
        run = session.start(entry, payload, timeout=limit + 15)
        run.wait(limit + 25)
        found = run.problems(expect_stdout="{}")
        if run.adapted and "adapted" not in notes:
            notes.append("adapted")
        if found:
            problems.append("%s[%s]：%s" % (event, run.executor, "；".join(found)))
            ok = False
        elif run.text("stderr"):
            notes.append("%s stderr：%s" % (event, short(run.text("stderr"), 120)))
    if not ok:
        return False
    if event == "SessionEnd":
        if not wait_for(lambda: session.find() is None, 3):
            problems.append("SessionEnd 后会话仍在 /state")
            return False
        return True
    state_session = wait_for(lambda: (lambda s: s if s and (event == "SessionStart" or
                                                             s.get("last_updated", 0) > before_updated) else None)(
        session.find()), 3)
    if not state_session:
        problems.append("%s：hook 返回了 {} 但 /state 没变化" % event)
        return False
    if event == "SessionStart":
        session.slot = state_session.get("slot")
        if not isinstance(session.slot, int) or not 1 <= session.slot <= 6:
            problems.append("槽位不对：%r" % session.slot)
        if state_session.get("name") != session.name:
            problems.append("名字是 %r，应为 %r" % (state_session.get("name"), session.name))
        if state_session.get("cwd") != session.cwd:
            problems.append("cwd 是 %r，应为 %r（中文路径被改坏？）" % (state_session.get("cwd"), session.cwd))
    want = EXPECTED_STATE.get(event)
    if want and state_session.get("state") != want:
        problems.append("%s 后状态是 %s，应为 %s" % (event, state_session.get("state"), want))
    return not problems


def permission_step(ctx, session, problems, notes, evidence):
    spec = SCENARIOS[session.scenario]
    payload = session.payload("PermissionRequest")
    entries = session.entries("PermissionRequest", payload)
    if not entries:
        problems.append("PermissionRequest：没装 AgentDeck hook")
        return False
    if len(entries) > 1:
        notes.append("PermissionRequest 有 %d 条 relay，只跑第一条" % len(entries))
    entry = entries[0]
    limit = entry.get("timeout") if isinstance(entry.get("timeout"), (int, float)) else 120
    run = session.start(entry, payload, timeout=limit + 5)

    def locate():
        state = ctx.hub.state() or {}
        for item in state.get("pending", []) + state.get("locked", []):
            if item.get("session_id") == session.sid and item.get("agent") == session.agent:
                return item
        return None if run.running() else "exited"

    request = wait_for(locate, 15)
    if request in (None, "exited"):
        run.wait(5)
        if run.running():
            run.kill()
        problems.append("PermissionRequest[%s] 没出现在 /state：%s" % (run.executor, run.brief()))
        return False
    request_id, nonce = request["id"], request["nonce"]
    if request.get("status") == "locked":
        problems.append("请求被判成 critical 锁定（应为 %s）" % spec["risk"])
        run.wait(10)
        return False
    if request.get("risk") != spec["risk"]:
        problems.append("风险等级 %s，应为 %s" % (request.get("risk"), spec["risk"]))
    current = session.find()
    if current and current.get("state") != "wait":
        problems.append("等批准时会话状态是 %s，应为 wait" % current.get("state"))
    shown = wait_for(lambda: (ctx.hub.state() or {}).get("displayed_request_id") == request_id, 3)
    if not shown and session.slot:
        code, body = ctx.hub.post("/action", {"action": "slot %d" % session.slot})
        notes.append("另有请求在显示，按 slot %d 切过来（HTTP %s）" % (session.slot, code))
        shown = wait_for(lambda: (ctx.hub.state() or {}).get("displayed_request_id") == request_id, 3)
    if not shown:
        problems.append("请求一直没成为当前显示的请求（displayed_request_id）")
        run.kill()
        return False
    shown_at = time.monotonic()
    rendered = wait_for(lambda: ((ctx.hub.state() or {}).get("input_request") or {}).get("request_id") == request_id,
                        6, 0.2)
    state = ctx.hub.state() or {}
    if not rendered:
        problems.append("显示 6 秒后 input_request 仍不是这条请求（input_mode=%s，input_request=%s）"
                        "——浮窗/LCD 没确认画出，实体键批准会被拒" % (state.get("input_mode"), state.get("input_request")))
    else:
        notes.append("input_mode=%s，画面确认用时 %.1fs" % (state.get("input_mode"), time.monotonic() - shown_at))
    time.sleep(0.5)
    paths, images, snap_notes = ctx.snap("pending-%s" % session.name)
    evidence += paths
    notes += snap_notes
    for hwnd, image in images.items():
        before = ctx.baseline_images.get(hwnd)
        if before is not None and image.size != before.size:
            notes.append("浮窗 %dx%d → 待批时 %dx%d" % (before.size + image.size))
    for index, (action, want) in enumerate(zip(spec["actions"], spec["statuses"])):
        code, body = ctx.decide(request_id, nonce, action, 0.35 if index == 0 else 0.15)
        if code != 200 or body.get("status") != want:
            problems.append("第 %d 次 %s：HTTP %s %s（应为 status=%s）" % (index + 1, action, code, short(body, 120), want))
            break
        if want == "confirm":
            time.sleep(0.2)
            if not run.running():
                problems.append("高危第一次批准后 hook 就返回了（应等第二次）：%s" % run.brief())
                break
            pending = [p for p in (ctx.hub.state() or {}).get("pending", []) if p.get("id") == request_id]
            if not pending or not pending[0].get("armed"):
                problems.append("第一次批准后请求没有进入待二次确认（armed）")
    if not run.wait(20):
        problems.append("决定后 20 秒 hook 仍没退出")
        run.kill()
        return False
    found = run.problems(expect_behavior=spec["behavior"])
    if found:
        problems.append("PermissionRequest[%s]：%s" % (run.executor, "；".join(found)))
    if wait_for(lambda: not any(p.get("id") == request_id for p in (ctx.hub.state() or {}).get("pending", [])), 3) is None:
        problems.append("决定后请求仍在 pending")
    code, records = ctx.hub.call("GET", "/audit?limit=100")
    if code != 200 or not isinstance(records, list):
        problems.append("GET /audit 失败：%s" % code)
    elif not any(r.get("request_id") == request_id and r.get("decision") == spec["behavior"] for r in records):
        problems.append("审计日志里没有 %s 的 %s 记录" % (request_id[:8], spec["behavior"]))
    return not problems


def run_session(ctx, agent, mode, scenario, required):
    session = Session(ctx, agent, mode, scenario)
    label = "hook %s/%s %s" % (agent, "bash(文档默认)" if mode == "auto" and ctx.bash else mode, scenario)
    problems, notes, evidence = [], [], []
    started = time.monotonic()
    for event in SEQUENCE:
        before = len(problems)
        if event == "PermissionRequest":
            permission_step(ctx, session, problems, notes, evidence)
        else:
            event_step(ctx, session, event, problems, notes)
        if event == "SessionStart" and len(problems) > before and session.find() is None:
            problems.append("SessionStart 没进 hub，后面只发 SessionEnd")
            event_step(ctx, session, "SessionEnd", [], [])
            break
    executors = sorted({resolve_executor(agent, mode, e, ctx.bash) for v in ctx.entries[agent].values() for e in v})
    summary = "7 个事件全部通过：槽位 %s，名字 %s，决定 %s，%.1fs" % (
        session.slot, session.name, SCENARIOS[scenario]["behavior"], time.monotonic() - started)
    extra = [n for n in notes if n != "adapted"]
    if "adapted" in notes:
        extra.append("命令按 --port/--home/--relay-override 改过（隔离实例）")
    extra.append("执行方式：%s；cwd：%s" % ("/".join(executors) if mode == "auto" else mode, session.cwd))
    ctx.report.add(label, not problems, (problems or [summary]) + extra, evidence, info=not required)
    return not problems


def open_console(ctx, title, console_mode):
    if console_mode == "conhost":
        return subprocess.Popen(["conhost.exe", "cmd.exe", "/k", "title " + title])
    return subprocess.Popen("cmd.exe /k title " + title, creationflags=CREATE_NEW_CONSOLE)


def find_console(marker, before):
    windows = [w for w in enum_windows() if w["visible"] and marker in w["title"]]
    fresh = [w for w in windows if w["hwnd"] not in before]
    return (fresh or windows or [None])[0]


def close_console(ctx, entry):
    proc, item, fresh = entry["proc"], entry.get("window"), entry.get("fresh")
    try:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10,
                       creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass
    if item and not wait_for(lambda: not user32.IsWindow(item["hwnd"]) or entry["marker"] not in window_text(item["hwnd"]), 5):
        if fresh:  # our own new window only; never close a pre-existing terminal window
            user32.PostMessageW(item["hwnd"], 0x0010, 0, 0)
            wait_for(lambda: not user32.IsWindow(item["hwnd"]), 3)
    return not (item and user32.IsWindow(item["hwnd"]) and entry["marker"] in window_text(item["hwnd"]))


def overlay_and_switch(ctx, cc_mode, cx_mode):
    """Two concurrent sessions: overlay content check, then real window switching."""
    alpha = Session(ctx, "cc", cc_mode, None, name="accept-alpha-%s" % ctx.tag)
    beta = Session(ctx, "cx", cx_mode, None, name="accept-beta-%s" % ctx.tag)
    problems, notes = [], []
    for session in (alpha, beta):
        for event in ("SessionStart", "UserPromptSubmit"):
            event_step(ctx, session, event, problems, notes)
    state = ctx.hub.state() or {}
    listed = {s.get("session_id"): s for s in state.get("sessions", [])}
    lines = []
    for session in (alpha, beta):
        item = listed.get(session.sid)
        if not item:
            problems.append("/state 没列出 %s" % session.name)
        else:
            lines.append("槽位 %s：%s（%s，%s）" % (item.get("slot"), item.get("name"), item.get("agent"), item.get("state")))
    if alpha.slot and alpha.slot == beta.slot:
        problems.append("两个会话占了同一个槽位")
    evidence = []
    if not ctx.skipped("overlay") and not ctx.desktop_usable:
        # Locked: DWM stops refreshing the redirection surface PrintWindow copies, so "no pixel changed" is noise.
        if problems:
            ctx.report.add("overlay-content", False, problems + lines + ["画面对比没做：" + ctx.desktop_where])
        else:
            ctx.report.add("overlay-content", True, ["画面对比没做：" + ctx.desktop_where] + lines, skip=True)
    elif not ctx.skipped("overlay"):
        time.sleep(0.8)  # overlay refreshes every 300 ms
        paths, images, snap_notes = ctx.snap("overlay-sessions")
        evidence += paths
        lines += snap_notes
        if not images:
            problems.append("没有可见的 AgentDeck 窗口可截图")
        for hwnd, image in images.items():
            if image_blank(image):
                problems.append("浮窗自身画面是纯色")
            before = ctx.baseline_images.get(hwnd)
            ratio = image_diff_ratio(before, image)
            if before is None:
                lines.append("开始时没有这个窗口的截图，无法对比")
            elif ratio is None:
                lines.append("浮窗尺寸 %dx%d → %dx%d" % (before.size + image.size))
            elif ratio == 0:
                problems.append("多了 2 个会话，浮窗画面一个像素都没变（看不到会话）")
            else:
                lines.append("与开始时相比变化 %.1f%% 像素" % (ratio * 100))
        ctx.report.add("overlay-content", not problems, problems + lines, evidence)
    switch_problems = list(problems) if ctx.skipped("overlay") else []
    if not ctx.skipped("switch"):
        window_switch(ctx, alpha, beta, switch_problems)
    for session in (alpha, beta):
        event_step(ctx, session, "SessionEnd", [], [])


def window_switch(ctx, alpha, beta, problems):
    if not (alpha.slot and beta.slot):
        ctx.report.add("window-switch", False, problems + ["会话没建起来，无法测切窗口"])
        return
    usable, where = desktop_status()
    if not usable:
        ctx.report.add("window-switch", not problems, problems + ["没测：" + where], skip=not problems)
        return
    console_mode = ctx.args.console
    lines, evidence = [], []
    targets = []
    for attempt in range(2):
        before = {w["hwnd"] for w in enum_windows()}
        targets = []
        for session, tool in ((alpha, "Claude Code"), (beta, "Codex")):
            title = "%s - %s" % (session.name, tool)
            entry = {"proc": open_console(ctx, title, console_mode), "marker": session.name, "session": session}
            ctx.consoles.append(entry)
            targets.append(entry)
        for entry in targets:
            entry["window"] = wait_for(lambda: find_console(entry["marker"], before), 15, 0.25)
            entry["fresh"] = bool(entry["window"]) and entry["window"]["hwnd"] not in before
        hwnds = [e["window"]["hwnd"] for e in targets if e["window"]]
        if len(hwnds) == 2 and hwnds[0] == hwnds[1] and console_mode != "conhost":
            lines.append("两个控制台进了同一个 Windows Terminal 窗口，改用 conhost 重开")
            for entry in targets:
                close_console(ctx, entry)
                ctx.consoles.remove(entry)
            console_mode = "conhost"
            continue
        break
    for entry in targets:
        item = entry["window"]
        if not item:
            problems.append("15 秒内没找到标题含 %s 的控制台窗口" % entry["marker"])
            continue
        name = os.path.basename(process_name(item["pid"])).lower()
        lines.append("窗口「%s」进程 %s（%s）" % (item["title"], name or "?", item["cls"]))
        if name and name not in TITLE_PROCESSES and name not in NATIVE_PROCESSES:
            problems.append("%s 不在 hub 认可的终端进程列表里" % name)
    if any(not e["window"] for e in targets):
        ctx.report.add("window-switch", False, problems + lines)
        return
    verified = {alpha.sid: 0, beta.sid: 0}
    for step, entry in enumerate([targets[0], targets[1], targets[0], targets[1]], 1):
        session, hwnd = entry["session"], entry["window"]["hwnd"]
        before_fg = foreground()
        if before_fg == hwnd:
            lines.append("第 %d 步：%s 已在前台，不计入" % (step, session.name))
            continue
        code, body = ctx.hub.post("/action", {"action": "slot %d" % session.slot})
        got = wait_for(lambda: foreground() == hwnd, 3)
        fg_title = window_text(foreground()) if foreground() else "-"
        if got:
            verified[session.sid] += 1
            lines.append("第 %d 步：slot %d → 前台变成「%s」（window=%s）" % (
                step, session.slot, short(fg_title, 40), body.get("window")))
            try:
                rect = window_rect(hwnd)
                if rect:
                    path = ctx.out / ("switch-%d-%s.png" % (step, session.name))
                    grab(rect, path)
                    evidence.append(path)
            except Exception:
                pass
        else:
            problems.append("第 %d 步：slot %d 后前台是「%s」不是 %s（HTTP %s，window=%s）" % (
                step, session.slot, short(fg_title, 40), session.name, code, body.get("window") or body.get("error")))
        time.sleep(0.4)
    if not verified[alpha.sid] or not verified[beta.sid]:
        problems.append("没有分别验证到切到两个窗口（alpha %d 次，beta %d 次）" % (verified[alpha.sid], verified[beta.sid]))
    closed = all(close_console(ctx, entry) for entry in targets)
    for entry in targets:
        if entry in ctx.consoles:
            ctx.consoles.remove(entry)
    if not closed:
        lines.append("有测试控制台没关掉，请手动关闭标题含 accept- 的窗口")
    ctx.report.add("window-switch", not problems, problems + lines, evidence)


def relay_log_check(ctx, offset):
    path = ctx.agentdeck / "relay.log"
    lines = new_log_lines(path, offset, skip_prefix="=== accept")
    ctx.report.add("relay-log", not lines, ["标记之后 %d 行新错误" % len(lines)] + [short(l, 200) for l in lines[:10]],
                   [path])


def app_log_check(ctx, offset):
    path = ctx.agentdeck / "logs" / "app.log"
    if not path.exists():
        ctx.report.add("app-log", True, "没有 %s（隔离的 hub.py 不写这个文件）" % path, skip=True)
        return
    lines = new_log_lines(path, offset)
    pattern = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ (\S+) (\w+) (.*)$")
    bad, counts = [], {}
    for line in lines:
        match = pattern.match(line)
        if not match:
            continue
        logger, level, message = match.groups()
        counts[level] = counts.get(level, 0) + 1
        if level in ("ERROR", "CRITICAL") or "卡顿" in message:
            bad.append(short(line, 200))
    summary = "本次运行期间新增 %d 行：%s" % (len(lines), "，".join("%s %d" % kv for kv in sorted(counts.items())) or "无")
    if bad:
        bad.append("（不是误报：卡顿期间 Tk 线程仍回应 Win32 消息，所以 WM_NULL 体检测不出；但 Tk 定时器不触发，"
                   "_poll 不跑 → 浮窗不刷新、画面确认发不出，实体键批准会被拒）")
    ctx.report.add("app-log", not bad, [summary] + bad[:12], [path])


def keyboard_info(ctx):
    path = ctx.agentdeck / "logs" / "app.log"
    try:
        text = path.read_bytes()[-2_000_000:].decode("utf-8", "replace")
    except OSError:
        return
    readers = re.findall(r"读键方式：([^\r\n]+)", text)
    if not readers:
        return
    reader = readers[-1]
    raw = "Raw Input" in reader
    ctx.report.add("keyboard-reader", not raw, ["最近一次：" + short(reader, 120)] + (
        ["Raw Input 只能旁听：宏键盘的按键同时会打字进前台窗口。要独占需用 Zadig 把接口 0 换成 WinUSB（用户操作）"]
        if raw else []), info=True)


def cleanup(ctx):
    for run in list(ctx.live_runs):
        if run.running():
            run.kill()
    for entry in list(ctx.consoles):
        close_console(ctx, entry)
        ctx.consoles.remove(entry)
    if ctx.saved_cursor:
        user32.SetCursorPos(*ctx.saved_cursor)
    if ctx.hub is None:
        return
    state = ctx.hub.state() or {}
    stragglers = [s for s in state.get("sessions", []) if str(s.get("session_id", "")).startswith("accept-")]
    for session in stragglers:
        ctx.hub.post("/event?agent=%s" % session["agent"],
                     {"hook_event_name": "SessionEnd", "session_id": session["session_id"]})
    state = ctx.hub.state()
    left = [s.get("session_id") for s in (state or {}).get("sessions", [])
            if str(s.get("session_id", "")).startswith("accept-")]
    detail = ["本次建了 %d 个 accept- 会话" % len(ctx.created)]
    if stragglers:
        detail.append("有 %d 个没被 hook 的 SessionEnd 清掉，已直接 POST /event 清理" % len(stragglers))
    if state is None:
        ctx.report.add("cleanup", False, ["清理后读不到 /state"] + detail)
    else:
        ctx.report.add("cleanup", not left, (["仍残留：%s" % ", ".join(left)] if left else ["/state 里没有 accept- 会话"]) + detail)


# --------------------------------------------------------------------------- modes

def dry_run(ctx):
    print("== 只读演练（不发 HTTP 请求、不跑 hook、不发窗口消息、不写文件）")
    set_dpi_aware()  # so the window rects below are physical pixels, as in a real run
    print("hub 端口 %d；AgentDeck 目录 %s；hook 配置 %s" % (ctx.args.port, ctx.agentdeck, ctx.hooks_home))
    print("token：%s" % ("存在" if (ctx.agentdeck / "token").exists() else "不存在"))
    usable, where = desktop_status()
    print("桌面：%s%s" % (where, "" if usable else "  ← 现在跑窗口检查会失败"))
    print("Git Bash：%s；PowerShell：%s" % (ctx.bash, ctx.powershell))
    try:
        required, info = ctx.modes()
    except ValueError as error:
        print("--shells 错误：%s" % error)
        return 2
    print("必过的执行方式：%s；仅参考：%s" % (required, info or "无"))
    for note in ctx.entry_notes:
        print("注意：" + note)
    sample_cwd = str(ctx.work / "后面的项目" / ("accept-sample-%s" % ctx.tag))
    for agent, mode in required + info:
        print("\n[%s / %s]" % (agent, mode))
        for event in SEQUENCE:
            entries = ctx.entries[agent].get(event, [])
            if not entries:
                print("  %-18s 没装 AgentDeck hook" % event)
            payload = build_payload(agent, event, "accept-sample", sample_cwd, "approve", "t")
            for entry in entries:
                applies = matcher_applies(entry.get("matcher"), event, payload)
                executor = resolve_executor(agent, mode, entry, ctx.bash)
                command, entry_args, changed = adapt_command(entry["command"], entry.get("args"), ctx.args)
                print("  %-18s 配置：%s%s" % (event, entry["command"], "" if applies else "  (matcher 不匹配，agent 不会跑)"))
                print("  %-18s 执行：%s%s" % ("", spec_text(process_spec(executor, command, entry_args, ctx.bash, ctx.powershell)),
                                          ("  [%s]" % "；".join(changed)) if changed else ""))
    pid = listening_pid(ctx.args.port)
    print("\n监听 %d 的进程：%s %s" % (ctx.args.port, pid, process_name(pid) if pid else ""))
    if pid:
        for item in enum_windows(pid):
            print("  窗口 %s rect=%s tid=%d" % (label_window(item), item["rect"], item["tid"]))
    for name in ("relay.log", "logs/app.log"):
        path = ctx.agentdeck / name
        print("%s：%s（%d 字节）" % (name, path, file_size(path)))
    build = []
    for exe in ("AgentDeck.exe", "AgentDeck-relay.exe"):
        path = ROOT / "dist" / "AgentDeck" / exe
        if path.exists():
            build.append("%s %s" % (exe, datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d %H:%M")))
    print("打包时间：%s；pc/hub_relay.py 修改于 %s" % ("，".join(build) or "无",
          datetime.fromtimestamp((ROOT / "pc" / "hub_relay.py").stat().st_mtime).strftime("%m-%d %H:%M")))
    agents_first = {agent for agent, _ in required}
    sessions = 3 * len(agents_first) + (len(required) - len(agents_first)) + len(info) + 2
    print("\n正式运行会：写 relay.log 标记、跑上面的命令（%d 个假会话）、截图、移动鼠标悬停浮窗、"
          "开两个控制台测切窗口，约 2~3 分钟。" % sessions)
    return 0


def self_test():
    """Offline checks of the harness's own logic (no hub, no hooks, no windows)."""
    results = []

    def check(name, condition, detail=""):
        results.append((name, bool(condition), detail))

    cwd = "D:\\工作\\后面的项目\\accept-x-123456"
    pre = encode_payload(build_payload("cc", "PreToolUse", "accept-s", cwd, "approve", "t"))
    check("载荷是原始 UTF-8 且含“后面”", "后面".encode("utf-8") in pre and b"\\u540e" not in pre)
    check("载荷含 Windows 反斜杠路径", b"D:\\\\\\xe5" in pre or "D:\\\\工作".encode("utf-8") in pre)
    check("PreToolUse 载荷 300KB~1MiB", 300 * 1024 < len(pre) < 1024 * 1024, "%d 字节" % len(pre))
    for agent in ("cc", "cx"):
        for event in SEQUENCE:
            data = json.loads(encode_payload(build_payload(agent, event, "accept-s", cwd, "deny", "t")).decode("utf-8"))
            check("%s %s 载荷字段" % (agent, event), data["hook_event_name"] == event and data["cwd"] == cwd)
    check("名字规则", expected_name(cwd) == "accept-x-123456" and expected_name("D:\\a\\后面") == "agent"
          and expected_name("C:\\" + "x" * 30) == "x" * 24)
    check("matcher", matcher_applies(None, "PreToolUse", {"tool_name": "Write"})
          and matcher_applies("Bash|Write", "PreToolUse", {"tool_name": "Write"})
          and not matcher_applies("Bash", "PreToolUse", {"tool_name": "Write"})
          and matcher_applies("startup|resume", "SessionStart", {"source": "startup"})
          and matcher_applies("Bash", "Stop", {}))
    allow = b'{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}'
    deny = ('{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":'
            '{"behavior":"deny","message":"Denied from AgentDeck"}}}').encode()
    check("解析 allow/deny", parse_decision(allow) == ("allow", None) and parse_decision(deny) == ("deny", None))
    check("拒绝坏输出", parse_decision(b"")[0] is None and parse_decision(b"{}")[0] is None and parse_decision(
        b'{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow","interrupt":true}}}')[0] is None)

    class Opt:
        relay_override, port, home = None, DEFAULT_PORT, None

    real = r"D:\desk\hardware\h1\dist\AgentDeck\AgentDeck-relay.exe --agent cc"
    check("默认不改命令", adapt_command(real, None, Opt)[0] == real and not adapt_command(real, None, Opt)[2])
    Opt.port, Opt.home = 47891, "D:/tmp/iso"
    adapted = adapt_command(real, None, Opt)[0]
    check("隔离实例追加端口与 home", adapted.startswith(real) and "--port 47891" in adapted and '--home "' in adapted, adapted)
    Opt.relay_override = "py relay.py"
    check("relay 覆盖", adapt_command(real, None, Opt)[0].startswith("py relay.py --agent cc"))
    check("cmd 形式", process_spec("cmd", real, None, None, None).endswith('/d /s /c "%s"' % real))
    check("bash 形式", process_spec("bash", real, None, Path("bash.exe"), None) == ["bash.exe", "-c", real])
    check("cc 默认 bash", resolve_executor("cc", "auto", {"command": real}, Path("b")) == "bash"
          and resolve_executor("cc", "auto", {"command": real}, None) == "powershell"
          and resolve_executor("cc", "auto", {"command": real, "args": []}, Path("b")) == "exec"
          and resolve_executor("cx", "cmd", {"command": real}, Path("b")) == "cmd")
    sample = ("  TCP    0.0.0.0:135   0.0.0.0:0   LISTENING   1100\n"
              "  TCP    127.0.0.1:47800   0.0.0.0:0   LISTENING   4242\n"
              "  TCP    127.0.0.1:47800   127.0.0.1:5000   ESTABLISHED   4242\n")
    check("netstat 解析", parse_netstat(sample, 47800) == 4242 and parse_netstat(sample, 1) is None)
    with tempfile.TemporaryDirectory() as folder:
        log = Path(folder) / "relay.log"
        log.write_text("old error\n", encoding="utf-8")
        with open(log, "a", encoding="utf-8") as handle:
            handle.write("=== accept 1 start\n")
        offset = file_size(log)
        check("relay.log 无新行", new_log_lines(log, offset, "=== accept") == [])
        with open(log, "a", encoding="utf-8") as handle:
            handle.write("cc PreToolUse UnicodeDecodeError('后面')\n=== accept 1 end\n")
        check("relay.log 抓到新错误", new_log_lines(log, offset, "=== accept") == ["cc PreToolUse UnicodeDecodeError('后面')"])
        home = Path(folder) / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".codex").mkdir()
        (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "powershell other"}]},
                             {"hooks": [{"type": "command", "command": real, "timeout": 10}]}],
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": real + " --gate"}]}]}}),
            encoding="utf-8")
        (home / ".codex" / "hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "x", "commandWindows": real.replace("cc", "cx")}]}]}}), encoding="utf-8")
        entries, _ = load_hook_config(home)
        check("读 hook 配置", len(entries["cc"]["SessionStart"]) == 1 and entries["cc"]["PreToolUse"][0]["gate"]
              and entries["cc"]["PreToolUse"][0]["matcher"] == "Bash"
              and entries["cx"]["Stop"][0]["command"].endswith("--agent cx"))
    sys.path.insert(0, str(ROOT / "pc"))
    try:
        from hub_risk import PROTECTED_BRANCHES, classify
        for scenario, want in (("approve", "low"), ("deny", "low"), ("high", "high")):
            tool, tool_input = permission_input(scenario, cwd)
            got = classify(tool, tool_input, protected_branches=PROTECTED_BRANCHES)
            check("风险分级 %s=%s" % (scenario, want), got == want, got)
        check("大载荷不触发风险规则", classify("Write", {"file_path": cwd + "\\a.md", "content": BIG_PRE},
                                     protected_branches=PROTECTED_BRANCHES) == "low")
    except ImportError as error:
        check("导入 pc/hub_risk", False, repr(error))
    finally:
        sys.path.pop(0)
    check("找到 Git Bash（非 WSL）", find_git_bash() is not None, str(find_git_bash()))
    for name, ok, detail in results:
        print("%s  %s%s" % ("PASS" if ok else "FAIL", name, "  (%s)" % detail if detail and not ok else ""))
    failed = [r for r in results if not r[1]]
    print("自检 %d 项，失败 %d 项" % (len(results), len(failed)))
    return 1 if failed else 0


def run(ctx):
    print("AgentDeck 验收 run=%s 端口=%d 证据=%s" % (ctx.run_id, ctx.args.port, ctx.out), flush=True)
    ctx.out.mkdir(parents=True, exist_ok=True)
    print("DPI 感知：%s" % set_dpi_aware())
    try:
        required, info = ctx.modes()
    except ValueError as error:
        print("参数错误：%s" % error)
        return 2
    if not preflight(ctx):
        finish(ctx)
        return 2
    build_freshness(ctx)
    usable, where = desktop_status()
    ctx.desktop_usable, ctx.desktop_where = usable, where
    ctx.report.add("desktop", usable, [where] + ([] if usable else [
        "锁屏、UAC 或 Windows 安全中心对话框挡在最前，截图/悬停/切窗口的结果不可信；先关掉它再跑",
        "window-cursor、overlay-content、window-switch 这次记为 SKIP；hook、批准、窗口响应、日志照常检查"]))
    relay_path = ctx.agentdeck / "relay.log"
    try:
        with open(relay_path, "a", encoding="utf-8") as handle:
            handle.write("=== accept %s start\n" % ctx.run_id)
    except OSError as error:
        ctx.report.add("relay-log", False, "写不了标记：%s" % error)
    relay_offset = file_size(relay_path)
    app_offset = file_size(ctx.agentdeck / "logs" / "app.log")
    if not ctx.skipped("window"):
        window_baseline(ctx)
    if not ctx.skipped("cursor"):
        cursor_check(ctx)
    prober = Prober(ctx.hub_pid) if ctx.hub_pid and not ctx.skipped("window") else None
    if prober:
        prober.start()
    if not ctx.skipped("hooks"):
        seen = set()
        for agent, mode in required:
            scenarios = ("approve", "deny", "high") if agent not in seen else ("approve",)
            seen.add(agent)
            for scenario in scenarios:
                run_session(ctx, agent, mode, scenario, required=True)
        for agent, mode in info:
            run_session(ctx, agent, mode, "approve", required=False)
    if not (ctx.skipped("overlay") and ctx.skipped("switch")):
        cc_mode = next((m for a, m in required if a == "cc"), "auto")
        cx_mode = next((m for a, m in required if a == "cx"), "cmd")
        overlay_and_switch(ctx, cc_mode, cx_mode)
    if prober:
        problems, lines, _ = summarize_probe(prober.finish())
        ctx.report.add("window-load", not problems, (problems or ["hook、批准、切窗口期间所有窗口始终 1 秒内响应"]) + lines)
    if not ctx.skipped("logs"):
        try:
            with open(relay_path, "a", encoding="utf-8") as handle:
                handle.write("=== accept %s end\n" % ctx.run_id)
        except OSError:
            pass
        relay_log_check(ctx, relay_offset)
        app_log_check(ctx, app_offset)
        keyboard_info(ctx)
    return None


def finish(ctx):
    try:
        cleanup(ctx)
    except Exception as error:
        ctx.report.add("cleanup", False, "清理出错：%r" % error)
    header = "AgentDeck 验收  run=%s  端口=%d  home=%s" % (ctx.run_id, ctx.args.port, ctx.home)
    text = ctx.report.render(header, ctx.out)
    ctx.out.mkdir(parents=True, exist_ok=True)
    (ctx.out / "report.txt").write_text(text + "\n", encoding="utf-8")
    (ctx.out / "report.json").write_text(json.dumps({"run_id": ctx.run_id, "port": ctx.args.port,
                                                     "home": str(ctx.home), "rows": ctx.report.rows},
                                                    ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n" + text)


def main(argv=None):
    parser = argparse.ArgumentParser(description="AgentDeck 打包版验收（对着正在运行的 AgentDeck.exe）",
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="hub 端口（默认 47800）")
    parser.add_argument("--home", help="AgentDeck home（含 .agentdeck/ 的目录），隔离实例用；"
                                       "设置后 hook 命令会追加 --home/--port 指向它")
    parser.add_argument("--hooks-home", help="从哪里读 .claude/settings.json 和 .codex/hooks.json（默认真实用户目录，只读）")
    parser.add_argument("--shells", default="cc:auto,cx:cmd,cx:powershell",
                        help="必过的执行方式。cc:auto = Claude Code 文档行为（有 Git Bash 用 bash，否则 PowerShell，"
                             "条目带 args/shell 时照它）。默认 %(default)s")
    parser.add_argument("--all-shells", action="store_true", help="另外用其余 shell 各跑一遍（结果只作参考）")
    parser.add_argument("--relay-override", help="把命令里 --agent 之前的部分换成这个（例如源码 relay），只用于对比")
    parser.add_argument("--duration", type=int, default=20, help="窗口体检秒数（默认 20）")
    parser.add_argument("--console", choices=("default", "conhost"), default="default",
                        help="切窗口测试用的控制台：default=系统默认终端（Windows Terminal），conhost=经典控制台")
    parser.add_argument("--skip", default="", help="跳过的检查组，逗号分隔：" + ",".join(CHECK_GROUPS))
    parser.add_argument("--out", help="证据根目录（默认 research/acceptance/out）")
    parser.add_argument("--dry-run", action="store_true", help="只读演练：列出命令与窗口，不发请求不跑 hook")
    parser.add_argument("--self-test", action="store_true", help="离线自检脚本逻辑")
    args = parser.parse_args(argv)
    args.skip = {item.strip() for item in args.skip.split(",") if item.strip()}
    unknown = args.skip - set(CHECK_GROUPS)
    if unknown:
        parser.error("未知检查组：%s" % ", ".join(sorted(unknown)))
    if sys.platform != "win32":
        parser.error("只支持 Windows")
    if args.self_test:
        return self_test()
    ctx = Context(args)
    if args.dry_run:
        return dry_run(ctx)
    code = None
    try:
        code = run(ctx)
    except KeyboardInterrupt:
        ctx.report.add("interrupted", False, "Ctrl+C 中断")
    except Exception as error:
        import traceback
        traceback.print_exc()
        ctx.report.add("harness-error", False, "脚本自身出错：%r" % error)
    if code != 2:
        finish(ctx)
    if code is not None:
        return code
    return 1 if ctx.report.failed() else 0


if __name__ == "__main__":
    raise SystemExit(main())
