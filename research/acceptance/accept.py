"""AgentDeck 打包版验收脚本（对着正在运行的 AgentDeck.exe 跑）。

检查项：
  window-health   AgentDeck 每个窗口 20 秒内反复 1 秒内响应 WM_NULL，IsHungAppWindow 为假，并截图
  window-cursor   鼠标移到浮窗上不是忙碌/转圈光标
  hook ...        按 ~/.claude/settings.json、~/.codex/hooks.json 里的原样命令，用 agent 真实的方式
                  （Claude Code = Git Bash，Codex = cmd 与 PowerShell）喂中文 UTF-8 载荷，走完
                  SessionStart → UserPromptSubmit → PreToolUse → PermissionRequest → PostToolUse → Stop → SessionEnd，
                  并在 /state、/audit 里核对效果；批准、拒绝、高危两次批准都走 POST /action
  hold-mode       临时切到 always，结束时恢复原模式（期间真实会话的权限请求也会挂起）
  hold-auto       未接宏键盘时 auto 不挂起，relay 及时返回 {}，会话显示 native_wait
  ghost           同会话 PostToolUse 释放仍挂起的 PermissionRequest
  window-switch   开两个标题含项目名的控制台窗口，POST slot 后前台窗口必须变成对应窗口
  overlay-content 两个会话同时在时 /state 列出它们，浮窗截图
  window-load     上面所有操作期间窗口一直在响应
  relay-log       ~/.agentdeck/relay.log 在标记之后没有新错误
  relay-log-format 日志含时间、agent、事件、短 sid，错误探针不泄露原始 stdin
  app-log         本次运行期间 app.log 没有 ERROR / 卡顿
  restart-check   可选：重启打包进程后保留未过期会话，hold 默认恢复 auto
  codex-exec      可选：真跑一次 codex exec（花 Codex 额度），会话进 /state，SessionEnd 后
                  recent_ended 里是 done/Stop 和回复；额度用完或模型不可用记 SKIP
  autostart       只读核对当前用户登录计划任务与旧 HKCU Run 迁移
  cleanup         /state 里不留 accept- 会话

运行（项目根目录）：
  D:\\conda\\miniconda3\\python.exe -X utf8 research\\acceptance\\accept.py            # 全部检查
  ... accept.py --dry-run      只读：列出将要执行的 hook 命令、窗口、日志位置，不发请求不跑 hook
  ... accept.py --self-test    离线自检脚本自身的逻辑
  ... accept.py --restart-check  额外终止并重启默认端口的打包进程，核对会话持久化
  ... accept.py --codex-exec   额外真跑一次 codex exec（从项目根目录，去掉 SSL_CERT_FILE）
  ... accept.py --port 47891 --home D:\\tmp\\iso   对隔离实例（hub.py --port/--home）跑
退出码：0 = 全部 PASS；1 = 有 FAIL；2 = 前置条件不满足（hub 不在、token 缺失等）。
证据：research/acceptance/out/<时间>/（report.txt、report.json、hooks.jsonl、截图）。
"""
import argparse
import atexit
import csv
import ctypes
import json
import math
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
import xml.etree.ElementTree as ET
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
CHECK_GROUPS = ("window", "cursor", "hooks", "overlay", "switch", "logs", "hold", "ghost", "autostart")
PROMPT = "后面再说，先把 D:\\工作\\后面的项目 里的测试跑一遍，然后总结进度 ✅🚀"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
PASSTHROUGH_LIMIT = 2.0
STOP_TEXT = "后面的步骤已经完成。"
CODEX_PROMPT = "Reply only: ok"
CODEX_TIMEOUT = 240
# Codex output that means the account/model is unavailable: environment, not AgentDeck.
CODEX_ENV_MARKERS = ("usage limit", "not supported when using Codex with a ChatGPT account")
GHOST_LIMIT = 2.0
RELAY_LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d (\S+) (\S+) (\S{1,8})(?: (.*))?$")


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
        payload.update(stop_hook_active=False, last_assistant_message=STOP_TEXT)
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


def empty_json_object(stdout):
    try:
        data = json.loads(stdout.strip().decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False
    return isinstance(data, dict) and not data


def passthrough_problems(code, stdout_bytes, seconds, seen, session_dict, audit_records, sid):
    problems = []
    if code != 0:
        problems.append("relay 退出码 %s，应为 0" % code)
    if not empty_json_object(stdout_bytes):
        problems.append("relay stdout 不是 {}")
    if seconds >= PASSTHROUGH_LIMIT:
        problems.append("放行耗时 %.3fs，应小于 %.1fs" % (seconds, PASSTHROUGH_LIMIT))
    if seen:
        problems.append("请求曾出现在 pending/locked")
    session = session_dict or {}
    if session.get("native_wait") is not True:
        problems.append("会话 native_wait 不是 true")
    if session.get("state") != "wait":
        problems.append("会话状态不是 wait：%s" % session.get("state"))
    if not any(r.get("session_id") == sid and r.get("decision") == "passthrough" for r in audit_records):
        problems.append("审计没有该会话的 passthrough 记录")
    return problems


def find_ended(state, agent, sid):
    """Newest /state recent_ended entry for agent/sid, else None."""
    entries = (state or {}).get("recent_ended")
    for entry in reversed(entries if isinstance(entries, list) else []):
        if isinstance(entry, dict) and entry.get("agent") == agent and entry.get("session_id") == sid:
            return entry
    return None


def ended_problems(state, agent, sid, last_sent=None, stop_text=None):
    """A session SessionEnd just removed must be in recent_ended with its final state."""
    if not isinstance((state or {}).get("recent_ended"), list):
        return ["/state 没有 recent_ended（hub 太旧？）"]
    entry = find_ended(state, agent, sid)
    if entry is None:
        return ["SessionEnd 后 recent_ended 里没有这个会话"]
    problems = []
    if entry.get("ended_by") != "SessionEnd":
        problems.append("recent_ended 的 ended_by 是 %r，应为 SessionEnd" % entry.get("ended_by"))
    if last_sent == "Stop":
        if (entry.get("state"), entry.get("last_event")) != ("done", "Stop"):
            problems.append("结束前是 %s/%s，应为 done/Stop" % (entry.get("state"), entry.get("last_event")))
        if stop_text is not None and entry.get("last_text") != stop_text:
            problems.append("结束前 last_text 是 %r，应为 Stop 的回复" % short(entry.get("last_text"), 40))
    return problems


def codex_exec_problems(code, output, seen, ended, alive=None):
    """Judge one real `codex exec "Reply only: ok"` run.

    seen: /state snapshots of the new cx session(s) while it ran; ended: its recent_ended
    entry; alive: the session still in /state afterwards (a Codex without SessionEnd).
    Returns (skip_reason or None, problems).
    """
    text = output or ""
    marker = next((m for m in CODEX_ENV_MARKERS if m.lower() in text.lower()), None)
    if marker:
        return "环境：Codex 输出含“%s”（额度或模型不可用，不是 AgentDeck 的问题）" % marker, []
    problems = []
    if code != 0:
        problems.append("codex exec 退出码 %s" % code)
    final = ended or alive
    if not seen and final is None:
        problems.append("codex exec 的会话没进 /state")
        return None, problems
    if final is None:
        problems.append("会话不在 /state，recent_ended 里也没有（SessionEnd 没记录，hub 太旧？）")
        return None, problems
    if ended is not None and ended.get("ended_by") != "SessionEnd":
        problems.append("recent_ended 的 ended_by 是 %r" % ended.get("ended_by"))
    if (final.get("state"), final.get("last_event")) != ("done", "Stop"):
        problems.append("Stop 没到 hub：最后是 %s/%s" % (final.get("state"), final.get("last_event")))
    if "ok" not in str(final.get("last_text") or "").lower():
        problems.append("last_text 不含回复 ok：%r" % short(final.get("last_text"), 60))
    return None, problems


def relay_line_problems(line, markers=()):
    problems = []
    if len(line) > 400:
        problems.append("整行超过 400 字符")
    match = RELAY_LINE.fullmatch(line)
    if not match:
        problems.append("缺时间/agent/事件/短 sid，日志格式不对")
    elif len(match.group(4) or "") > 300:
        problems.append("消息超过 300 字符")
    if any(marker and marker in line for marker in ("第00000行", PROMPT) + tuple(markers)):
        problems.append("日志泄露原始 stdin")
    return problems


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


def read_log_since(path, offset):
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError:
        data = b""
    if len(data) < offset:
        try:
            previous = path.with_name(path.name + ".1").read_bytes()
        except OSError:
            previous = b""
        data = (previous[offset:] if len(previous) >= offset else b"") + data
    else:
        data = data[offset:]
    return [line for line in data.decode("utf-8", "replace").splitlines()
            if line.strip() and not line.startswith("=== accept")]


def file_size(path):
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def decode_console(data):
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    for encoding in ("utf-8", "oem"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("mbcs", "replace")


def parse_whoami(text):
    ids = set()
    for row in csv.reader(text.splitlines()):
        if len(row) >= 2 and re.fullmatch(r"S-\d+(?:-\d+)+", row[1].strip(), re.I):
            ids.update(value.strip().lower() for value in row[:2] if value.strip())
    return ids


def parse_task_xml(text):
    # schtasks declares UTF-16 even when stdout actually contains ANSI/OEM bytes.
    text = re.sub(r"^\s*<\?xml\b[^?]*\?>", "", text.lstrip("\ufeff"), count=1)
    root = ET.fromstring(text)
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

    def value(node, path, default=""):
        return node.findtext(path, default=default, namespaces=ns).strip()

    principal = root.find("t:Principals/t:Principal", ns)
    return {"uri": value(root, "t:RegistrationInfo/t:URI"),
            "enabled": value(root, "t:Settings/t:Enabled", "true"),
            "logon_triggers": [{"user_id": value(node, "t:UserId"),
                                "enabled": value(node, "t:Enabled", "true")}
                               for node in root.findall("t:Triggers/t:LogonTrigger", ns)],
            "principal": {"user_id": value(principal, "t:UserId") if principal is not None else "",
                          "logon_type": value(principal, "t:LogonType") if principal is not None else "",
                          "run_level": value(principal, "t:RunLevel") if principal is not None else ""},
            "execs": [{"command": value(node, "t:Command"), "arguments": value(node, "t:Arguments"),
                       "working_dir": value(node, "t:WorkingDirectory")}
                      for node in root.findall("t:Actions/t:Exec", ns)]}


def normalized_path(value):
    return os.path.normcase(os.path.normpath(str(value).strip().strip('"')))


def autostart_verdict(task, query_error, run_value, user_ids, exe_path, fallback_note):
    notes = ["计划任务查询：%s" % query_error] if query_error else []
    if task is None:
        if run_value is not None and fallback_note:
            return "WARN", ["计划任务不存在，已选择注册表回退：%s" % fallback_note,
                            "HKCU Run AgentDeck=%s" % run_value] + notes
        if run_value is not None:
            return "FAIL", ["计划任务 AgentDeck 不存在，HKCU Run 仍是 %s——没迁移" % run_value] + notes
        return "FAIL", ["计划任务和 HKCU Run 都没有 AgentDeck——开机自启没开"] + notes
    problems = []
    ids = {item.lower() for item in user_ids}
    if not any(t.get("user_id", "").lower() in ids and str(t.get("enabled", "true")).lower() != "false"
               for t in task.get("logon_triggers", [])):
        problems.append("没有当前用户且已启用的 LogonTrigger")
    principal = task.get("principal", {})
    if principal.get("logon_type") != "InteractiveToken":
        problems.append("Principal LogonType=%s，应为 InteractiveToken" % principal.get("logon_type"))
    level = principal.get("run_level")
    if level and level != "LeastPrivilege":
        problems.append("RunLevel=%s，应为 LeastPrivilege" % level)
    elif not level:
        notes.append("RunLevel 缺省，按 schema 默认 LeastPrivilege 接受")
    execs = task.get("execs", [])
    first = execs[0] if execs else {}
    if normalized_path(first.get("command", "")) != normalized_path(exe_path):
        problems.append("Exec Command=%r，应为 %s" % (first.get("command"), exe_path))
    if first.get("arguments", "").strip() != "--background":
        problems.append("Exec Arguments=%r，应为 --background" % first.get("arguments"))
    if str(task.get("enabled", "true")).lower() == "false":
        problems.append("Settings Enabled=false，计划任务被禁用")
    if task.get("uri") and task["uri"].lower() != r"\agentdeck":
        problems.append("任务 URI=%r，应为根目录 \\AgentDeck" % task.get("uri"))
    if run_value is not None:
        problems.append("HKCU Run 仍有 AgentDeck=%s，登录时会启动两次" % run_value)
    return ("FAIL" if problems else "PASS"), (problems or ["当前用户的 AgentDeck 登录任务正确，HKCU Run 已迁移"]) + notes


def autostart_fallback_note(state, app_log_text):
    value = (state or {}).get("autostart", "")
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value if isinstance(value, str) else ""
    values = value.values() if isinstance(value, dict) else (value,)
    fallback = re.compile(r"registry|\brun\b|fallback|注册表|回退", re.I)
    if any(isinstance(item, str) and fallback.search(item) for item in values):
        return text
    for line in reversed(app_log_text.splitlines()):
        if re.search(r"autostart|自启", line, re.I) and re.search(r"registry|注册表|fallback|回退|Run\s*键", line, re.I):
            return line
    return ""


def parse_idle_seconds(text):
    match = re.search(r"^SESSION_IDLE_SECONDS\s*=\s*([^\r\n#]+)", text, re.M)
    expression = match.group(1).strip() if match else ""
    if not expression or not re.fullmatch(r"[0-9 *+]+", expression):
        return 21600
    try:
        # Only positive integer sums/products; no eval, names or calls.
        value = sum(math.prod(int(n.strip()) for n in term.split("*"))
                    for term in expression.split("+"))
        return value if value > 0 else 21600
    except ValueError:
        return 21600


def compare_restart(before, after, idle_limit, now):
    def key(session):
        return session.get("agent"), session.get("session_id"), session.get("slot")

    old, new = {key(s): s for s in before}, {key(s): s for s in after}
    problems, notes = [], []
    for identity in old.keys() - new.keys():
        session = old[identity]
        try:
            expired = now - float(session.get("last_updated", now)) > idle_limit - 60
        except (TypeError, ValueError):
            expired = False
        label = "%s/%s/slot %s" % identity
        if expired:
            notes.append("%s 闲置过期，被丢弃是对的" % label)
        else:
            problems.append("重启后丢失会话 %s" % label)
    for identity in new.keys() - old.keys():
        notes.append("重启后新增 %s/%s/slot %s（可能有真实事件）" % identity)
    return problems, notes


# These three I/O helpers are read-only and are blocked throughout self_test().
def query_task_xml(name="AgentDeck"):
    try:
        result = subprocess.run(["schtasks", "/Query", "/TN", name, "/XML", "ONE"], capture_output=True,
                                timeout=20, creationflags=CREATE_NO_WINDOW)
        if result.returncode == 0:
            return decode_console(result.stdout), ""
        return None, decode_console(result.stderr or result.stdout).strip()
    except (OSError, subprocess.SubprocessError) as error:
        return None, str(error)


def read_run_value(name="AgentDeck"):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_READ) as key:
            return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError:
        return None


def current_user_ids():
    ids = set()
    try:
        result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True,
                                timeout=20, creationflags=CREATE_NO_WINDOW)
        if result.returncode == 0:
            ids = parse_whoami(decode_console(result.stdout))
    except (OSError, subprocess.SubprocessError):
        pass
    domain, user = os.environ.get("USERDOMAIN"), os.environ.get("USERNAME")
    if domain and user:
        ids.add((domain + "\\" + user).lower())
    return ids


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

    def state(self, timeout=5.0):
        code, body = self.call("GET", "/state", timeout=timeout)
        return body if code == 200 and isinstance(body, dict) else None

    def post(self, path, body):
        return self.call("POST", path, body)


# --------------------------------------------------------------------------- hook processes

class HookRun:
    """One hook command execution, exactly like an agent: stdin = UTF-8 JSON, then wait."""

    def __init__(self, ctx, entry, executor, payload, cwd, timeout, raw=None):
        self.ctx, self.entry, self.executor = ctx, entry, executor
        self.event = payload["hook_event_name"]
        command, entry_args, self.adapted = adapt_command(entry["command"], entry.get("args"), ctx.args)
        self.spec = process_spec(executor, command, entry_args, ctx.bash, ctx.powershell)
        self.payload = encode_payload(payload) if raw is None else raw
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
        self.sent = []
        ctx.created[self.sid] = agent

    def payload(self, event):
        return build_payload(self.agent, event, self.sid, self.cwd, self.scenario, self.turn_id)

    def entries(self, event, payload):
        return [entry for entry in self.ctx.entries[self.agent].get(event, [])
                if matcher_applies(entry.get("matcher"), event, payload)]

    def start(self, entry, payload, timeout, raw=None):
        executor = resolve_executor(self.agent, self.mode, entry, self.ctx.bash)
        return HookRun(self.ctx, entry, executor, payload, self.cwd, timeout, raw=raw)

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
        self.hold_supported = False
        self.hold_original = None
        self.hold_restored = False
        self.restarted = False
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

def hold_set(ctx, mode):
    code, body = ctx.hub.post("/action", {"action": "hold " + mode})
    return code == 200 and isinstance(body, dict) and body.get("hold_mode") == mode, code, body


def hold_begin(ctx, register_exit=True):
    original = (ctx.hub.state() or {}).get("hold_mode")
    ctx.hold_original = original if original in ("auto", "always", "never") else None
    ok, code, body = hold_set(ctx, "always")
    ctx.hold_supported = ok
    if register_exit:
        atexit.register(hold_restore, ctx, False)
    if ok:
        ctx.report.add("hold-mode", True, "原来 %s，测试期间改成 always（宏键盘没接时也走挂起/批准路径），"
                       "结束时恢复；期间真实会话的权限请求也会被挂起" % (ctx.hold_original or "未知（按 auto 恢复）"), info=True)
    elif code == 400:
        ctx.report.add("hold-mode", True, "hub 不支持 hold 模式（旧版，HTTP 400），按旧行为继续", info=True)
    else:
        ctx.report.add("hold-mode", False, "设置 hold always 失败：HTTP %s %s" % (code, short(body)))


def hold_restore(ctx, report=True):
    if ctx.hold_restored or not ctx.hold_supported:
        return
    target = ctx.hold_original or "auto"
    try:
        ok, code, body = hold_set(ctx, target)
        actual = (ctx.hub.state() or {}).get("hold_mode")
        ok = ok and actual == target
        if ok:
            ctx.hold_restored = True
        if report:
            ctx.report.add("hold-restore", ok, "恢复 %s：HTTP %s %s；/state hold_mode=%s" % (
                target, code, short(body), actual))
    except Exception as error:
        if report:
            ctx.report.add("hold-restore", False, "恢复 hold 模式出错：%r" % error)


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
    last_sent = session.sent[-1] if session.sent else None
    session.sent.append(event)
    if event == "SessionEnd":
        if not wait_for(lambda: session.find() is None, 3):
            problems.append("SessionEnd 后会话仍在 /state")
            return False
        if last_sent is not None:  # it was registered, so the hub must remember how it ended
            found = ended_problems(session.ctx.hub.state(), session.agent, session.sid, last_sent, STOP_TEXT)
            problems.extend("SessionEnd：" + item for item in found)
            return not found
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


def session_requests(state, sid):
    return [p for p in state.get("pending", []) + state.get("locked", []) if p.get("session_id") == sid]


def audit_records(ctx):
    code, body = ctx.hub.call("GET", "/audit?limit=200")
    records = [r for r in body if isinstance(r, dict)] if code == 200 and isinstance(body, list) else []
    try:
        lines = (ctx.agentdeck / "audit.jsonl").read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
    except OSError:
        lines = []
    for line in lines:
        try:
            record = json.loads(line)
            if isinstance(record, dict):
                records.append(record)
        except ValueError:
            pass
    return records


def start_permission(session, problems, notes, timeout):
    payload = session.payload("PermissionRequest")
    entries = session.entries("PermissionRequest", payload)
    if not entries:
        problems.append("PermissionRequest：没装 AgentDeck hook（或 matcher 不匹配）")
        return None
    if len(entries) > 1:
        notes.append("PermissionRequest 有 %d 条 relay，只跑第一条" % len(entries))
    return session.start(entries[0], payload, timeout=timeout)


def hold_auto(ctx, cc_mode):
    if not ctx.hold_supported:
        ctx.report.add("hold-auto", True, "hub 不支持 hold 模式，无法检查 auto 放行", skip=True)
        return
    problems, notes = [], []
    session, run, skip = None, None, False
    try:
        ok, code, body = hold_set(ctx, "auto")
        if not ok:
            problems.append("设置 hold auto 失败：HTTP %s %s" % (code, short(body)))
        else:
            state = ctx.hub.state() or {}
            connected = state.get("deck_connected")
            if "deck_connected" not in state:
                problems.append("/state 缺 deck_connected，契约字段缺失")
            elif not isinstance(connected, bool):
                problems.append("/state deck_connected 不是 bool")
            if state.get("hold_mode") != "auto":
                problems.append("/state hold_mode 不是 auto：%s" % state.get("hold_mode"))
            if connected is True:
                if state.get("hold_active") is not True:
                    problems.append("键盘连接且 auto 时 hold_active 不是 true")
                notes.append("宏键盘已连接（input_reader=%s），auto 模式会挂起；这项只在键盘拔掉时测" % state.get("input_reader"))
                skip = not problems
            elif state.get("hold_active") is not False:
                problems.append("键盘未连接且 auto 时 hold_active 不是 false：%s" % state.get("hold_active"))
            if not problems and not skip:
                session = Session(ctx, "cc", cc_mode, "approve", name="accept-auto-%s" % ctx.tag)
                event_step(ctx, session, "SessionStart", problems, notes)
                event_step(ctx, session, "UserPromptSubmit", problems, notes)
                run = start_permission(session, problems, notes, timeout=20)
                if run is not None:
                    seen, unreadable = False, False
                    deadline = run.started + 15
                    while time.monotonic() < deadline:
                        state = ctx.hub.state(timeout=min(0.5, max(0.01, deadline - time.monotonic())))
                        if state is None:
                            unreadable = True
                        seen = seen or bool(session_requests(state or {}, session.sid))
                        if not run.running():
                            break
                        time.sleep(min(0.075, max(0, deadline - time.monotonic())))
                    if unreadable:
                        problems.append("放行期间读不到 /state")
                    if run.running():
                        problems.append("15 秒没放行")
                        run.kill()
                        run.wait(5)
                    current = session.find() or {}
                    problems += passthrough_problems(run.code, run.stdout, run.seconds, seen,
                                                    current, audit_records(ctx), session.sid)
                    if run.error:
                        problems.append(run.error)
                    notes += ["放行耗时 %.3fs；state=%s，native_wait=%s；last_text=%r，label=%r，text=%r" % (
                        run.seconds, current.get("state"), current.get("native_wait"), current.get("last_text"),
                        current.get("label"), current.get("text")), "stdout=%r" % short(run.text("stdout"), 200)]
    finally:
        if run is not None and run.running():
            run.kill()
            run.wait(5)
        try:
            if session is not None:
                event_step(ctx, session, "SessionEnd", problems, notes)
        finally:
            ok, code, body = hold_set(ctx, "always")
            if not ok:
                problems.append("恢复 hold always 失败：HTTP %s %s" % (code, short(body)))
                skip = False
    extra = [n for n in notes if n != "adapted"]
    if "adapted" in notes:
        extra.append("命令按 --port/--home/--relay-override 改过（隔离实例）")
    ctx.report.add("hold-auto", not problems, (problems or ([] if skip else ["auto 未挂起，原生权限等待与审计符合契约"])) + extra,
                   skip=skip)


def ghost_check(ctx, cc_mode):
    problems, notes = [], []
    if ctx.hold_supported:
        ok, code, body = hold_set(ctx, "always")
        if not ok:
            ctx.report.add("ghost", False, "设置 hold always 失败：HTTP %s %s" % (code, short(body)))
            return
    else:
        notes.append("旧版 hub 总是挂起")
    session = Session(ctx, "cc", cc_mode, "approve", name="accept-ghost-%s" % ctx.tag)
    run = None
    try:
        event_step(ctx, session, "SessionStart", problems, notes)
        event_step(ctx, session, "UserPromptSubmit", problems, notes)
        run = start_permission(session, problems, notes, timeout=50)
        if run is not None:
            pending_deadline = run.started + 15

            def locate():
                remaining = pending_deadline - time.monotonic()
                if remaining <= 0:
                    return "timeout"
                state = ctx.hub.state(timeout=min(0.5, remaining)) or {}
                if time.monotonic() > pending_deadline:
                    return "timeout"
                request = next((p for p in state.get("pending", []) if p.get("session_id") == session.sid), None)
                return request or ("exited" if not run.running() else None)

            request = wait_for(locate, max(0, pending_deadline - time.monotonic()), 0.075)
            if not isinstance(request, dict):
                problems.append("PermissionRequest 15 秒内没进入 pending：%s" % run.brief())
            else:
                time.sleep(0.3)
                payload = session.payload("PostToolUse")
                entries = session.entries("PostToolUse", payload)
                if not entries:
                    problems.append("PostToolUse：没装 AgentDeck hook（或 matcher 不匹配）")
                else:
                    # Start all matching installed entries before waiting for the held relay.
                    t0 = time.monotonic()
                    posts = [session.start(entry, payload, timeout=20) for entry in entries]
                    released = run.wait(max(0, t0 + GHOST_LIMIT - time.monotonic()))
                    if not released:
                        problems.append("PostToolUse 后 2 秒 relay 还在等")
                    clear_deadline = (run.ended if released and run.ended is not None else t0 + GHOST_LIMIT) + 1

                    def cleared():
                        remaining = clear_deadline - time.monotonic()
                        if remaining <= 0:
                            return False
                        state = ctx.hub.state(timeout=min(0.2, remaining))
                        return (time.monotonic() <= clear_deadline and state is not None
                                and not session_requests(state, session.sid))

                    if not wait_for(cleared, max(0, clear_deadline - time.monotonic()), 0.075):
                        problems.append("relay 退出后 1 秒内仍有 pending/locked（或读不到 /state）")
                    if not released:
                        if not run.wait(15):
                            run.kill()
                            run.wait(5)
                    release = run.ended - t0 if run.ended is not None else time.monotonic() - t0
                    notes.append("释放耗时 %.3fs；stdout=%r" % (release, short(run.text("stdout"), 200)))
                    if release >= GHOST_LIMIT and "PostToolUse 后 2 秒 relay 还在等" not in problems:
                        problems.append("释放耗时 %.3fs，超过 2 秒" % release)
                    if release < 0:
                        problems.append("PostToolUse 启动前 relay 已退出")
                    problems += run.problems()
                    if not empty_json_object(run.stdout):
                        problems.append("PermissionRequest stdout 不是 {}")

                    for post in posts:
                        post.wait(25)
                        problems += ["PostToolUse：" + p for p in post.problems(expect_stdout="{}")]
                    decisions = [r.get("decision") for r in audit_records(ctx) if r.get("request_id") == request.get("id")]
                    notes.append("审计 decision（仅参考）：%s" % (decisions or "无记录"))
    finally:
        if run is not None and run.running():
            run.kill()
            run.wait(5)
        event_step(ctx, session, "SessionEnd", problems, notes)
    extra = [n for n in notes if n != "adapted"]
    if "adapted" in notes:
        extra.append("命令按 --port/--home/--relay-override 改过（隔离实例）")
    ctx.report.add("ghost", not problems, (problems or ["PostToolUse 已释放仍挂起的权限请求"]) + extra)


def open_console(ctx, title, console_mode):
    if console_mode == "conhost":
        return subprocess.Popen(["conhost.exe", "cmd.exe", "/k", "title " + title])
    return subprocess.Popen("cmd.exe /k title " + title, creationflags=CREATE_NEW_CONSOLE)


def codex_exec_check(ctx):
    """Opt-in: one real `codex exec` through the user's global hooks (uses Codex quota).

    codex exec fires SessionEnd milliseconds after Stop, so the session is polled while it
    runs and its final state is read from /state recent_ended afterwards.
    """
    exe = shutil.which("codex.cmd") or shutil.which("codex")
    if not exe:
        ctx.report.add("codex-exec", False, "PATH 上没有 codex", skip=True)
        return
    state = ctx.hub.state() or {}
    before = {s.get("session_id") for s in state.get("sessions", []) if s.get("agent") == "cx"}
    before |= {e.get("session_id") for e in state.get("recent_ended", []) or [] if isinstance(e, dict)}
    root = os.path.normcase(os.path.normpath(str(ROOT)))

    def mine(item):
        return (isinstance(item, dict) and item.get("agent") == "cx" and item.get("session_id") not in before
                and os.path.normcase(os.path.normpath(str(item.get("cwd") or ""))) == root)

    env = dict(os.environ)
    env.pop("SSL_CERT_FILE", None)  # codex needs it unset on this machine (conda's bundle breaks TLS)
    ctx.out.mkdir(parents=True, exist_ok=True)
    out_path = ctx.out / "codex_exec.txt"
    seen, timeline = {}, []
    started = time.monotonic()
    with open(out_path, "wb") as out:
        proc = subprocess.Popen([exe, "exec", "--skip-git-repo-check", "-s", "read-only", CODEX_PROMPT],
                                cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL, stdout=out,
                                stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
        last = None
        while True:
            current = [s for s in (ctx.hub.state(timeout=2) or {}).get("sessions", []) if mine(s)]
            for item in current:
                seen[item["session_id"]] = item
            snap = [(s["session_id"][:8], s.get("state"), s.get("last_event"), short(s.get("last_text") or "", 30))
                    for s in current]
            if snap != last:
                timeline.append("%.2fs %s" % (time.monotonic() - started, snap))
                last = snap
            if proc.poll() is not None:
                break
            if time.monotonic() - started > CODEX_TIMEOUT:
                proc.kill()
                proc.wait(10)
                timeline.append("超过 %d 秒，已终止 codex" % CODEX_TIMEOUT)
                break
            time.sleep(0.15)
    code = proc.returncode
    output = out_path.read_bytes().decode("utf-8", "replace")

    def final():
        st = ctx.hub.state() or {}
        ended = [e for e in st.get("recent_ended", []) or [] if mine(e)]
        alive = [s for s in st.get("sessions", []) if mine(s)]
        return (ended[-1] if ended else None, alive[-1] if alive else None)

    ended, alive = wait_for(lambda: (lambda pair: pair if pair[0] else None)(final()), 3) or final()
    skip, problems = codex_exec_problems(code, output, seen, ended, alive)
    detail = ["退出码 %s，%.1fs，新 cx 会话 %s" % (code, time.monotonic() - started,
                                              ", ".join(sid[:8] for sid in seen) or "无")]
    if ended:
        detail.append("recent_ended：%s/%s last_text=%r ended_by=%s" % (
            ended.get("state"), ended.get("last_event"), short(ended.get("last_text") or "", 40), ended.get("ended_by")))
    elif alive:
        detail.append("仍在 /state（codex 没发 SessionEnd）：%s/%s" % (alive.get("state"), alive.get("last_event")))
    if skip:
        ctx.report.add("codex-exec", False, [skip] + detail + timeline, [out_path], skip=True)
    else:
        ctx.report.add("codex-exec", not problems, problems + detail + timeline, [out_path])


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


def relay_log_check(ctx, lines):
    path = ctx.agentdeck / "relay.log"
    ctx.report.add("relay-log", not lines, ["标记之后 %d 行新错误" % len(lines)] + [short(l, 200) for l in lines[:10]],
                   [path])


def relay_log_format_check(ctx, offset, lines_run, cc_mode):
    path = ctx.agentdeck / "relay.log"
    marker = "RAWPROBE-" + uuid.uuid4().hex[:12]
    raw = ('{"session_id": "accept-logfmt-%s", "hook_event_name": "Stop", "note": "%s ' % (
        ctx.tag, marker)).encode("utf-8") + b"\xff"
    payload = {"hook_event_name": "Stop"}
    entries = [entry for entry in ctx.entries["cc"].get("Stop", [])
               if matcher_applies(entry.get("matcher"), "Stop", payload)]
    notes = []
    if entries:
        entry = entries[0]
        executor = resolve_executor("cc", cc_mode, entry, ctx.bash)
        probe = HookRun(ctx, entry, executor, payload, str(ROOT), timeout=20, raw=raw)
        if not probe.wait(25):
            probe.kill()
            probe.wait(5)
        if probe.code != 0 or probe.error:
            notes.append("探针应退出 0：%s" % probe.brief())
    else:
        notes.append("cc Stop 没装 AgentDeck hook，无法运行错误探针")
    lines_all = read_log_since(path, offset)
    probe_lines = lines_all[len(lines_run):]
    bad = [(line, relay_line_problems(line, markers=(marker,))) for line in lines_all]
    bad = [(line, problems) for line, problems in bad if problems]
    detail = ["运行日志 %d 行，探针日志 %d 行；共检查 %d 行" % (len(lines_run), len(probe_lines), len(lines_all))]
    detail += ["%s：%s" % ("；".join(problems), short(line, 220)) for line, problems in bad[:8]] + notes
    if not probe_lines:
        detail.insert(0, "探针没写日志")
    ctx.report.add("relay-log-format", not bad and bool(probe_lines), detail, [path], info=not bad and not probe_lines)


def app_log_check(ctx, offset):
    path = ctx.agentdeck / "logs" / "app.log"
    if not path.exists():
        ctx.report.add("app-log", True, "没有 %s（隔离的 hub.py 不写这个文件）" % path, skip=True)
        return
    lines = read_log_since(path, offset)
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


def restart_skip_reason(port, home, image, exe_path):
    if port != DEFAULT_PORT or home:
        return "只重启默认端口且未指定 --home 的打包实例"
    if not image or normalized_path(image) != normalized_path(exe_path):
        return "监听进程不是 %s：%s" % (exe_path, image or "没找到")
    return ""


def restart_check(ctx):
    exe = ROOT / "dist" / "AgentDeck" / "AgentDeck.exe"
    pid = listening_pid(ctx.args.port)
    reason = restart_skip_reason(ctx.args.port, ctx.args.home, process_name(pid) if pid else "", exe)
    if reason:
        ctx.report.add("restart-check", True, reason, skip=True)
        return
    problems, notes = [], []
    state = ctx.hub.state()
    if state is None:
        ctx.report.add("restart-check", False, "重启前读不到 /state，未重启")
        return
    for session in state.get("sessions", []):
        if str(session.get("session_id", "")).startswith("accept-"):
            ctx.hub.post("/event?agent=%s" % session["agent"],
                         {"hook_event_name": "SessionEnd", "session_id": session["session_id"]})
    state = ctx.hub.state()
    if state is None:
        ctx.report.add("restart-check", False, "结束残留会话后读不到 /state，未重启")
        return
    before = [s for s in state.get("sessions", []) if not str(s.get("session_id", "")).startswith("accept-")]
    time.sleep(3)  # sessions.json saves are throttled to two seconds.
    saved = ctx.agentdeck / "sessions.json"
    if saved.exists():
        notes.append("sessions.json mtime=%s" % datetime.fromtimestamp(saved.stat().st_mtime).isoformat(timespec="seconds"))
    else:
        notes.append("重启前没有 sessions.json")
    result = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                            timeout=20, creationflags=CREATE_NO_WINDOW)
    if result.returncode != 0:
        ctx.report.add("restart-check", False, ["终止进程失败：" + decode_console(result.stderr or result.stdout)] + notes)
        return
    if not wait_for(lambda: listening_pid(ctx.args.port) is None, 10, 0.2):
        ctx.report.add("restart-check", False, ["终止后 10 秒端口仍被占用，未启动第二个进程"] + notes)
        return
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        try:
            subprocess.Popen([str(exe), "--background"], cwd=exe.parent, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                             creationflags=flags | CREATE_BREAKAWAY_FROM_JOB)
        except OSError:
            subprocess.Popen([str(exe), "--background"], cwd=exe.parent, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags)
    except OSError as error:
        ctx.report.add("restart-check", False, ["AgentDeck 没重新起来——请手动运行 dist\\AgentDeck\\AgentDeck.exe",
                                               str(error)] + notes)
        return

    def healthy():
        code, body = ctx.hub.call("GET", "/health", timeout=1)
        return code == 200 and isinstance(body, dict) and body.get("ok") is True

    if not wait_for(healthy, 45, 0.2):
        ctx.report.add("restart-check", False, ["AgentDeck 没重新起来——请手动运行 dist\\AgentDeck\\AgentDeck.exe"] + notes)
        return
    try:
        token = (ctx.agentdeck / "token").read_text(encoding="utf-8").strip()
    except OSError as error:
        ctx.report.add("restart-check", False, ["重启后读不到 token：%s" % error] + notes)
        return
    ctx.hub = HubClient(ctx.args.port, token)
    ctx.hub_pid = listening_pid(ctx.args.port)
    ctx.restarted = True
    deadline = time.monotonic() + 10

    def read_state():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        state = ctx.hub.state(timeout=min(0.5, remaining))
        return state if time.monotonic() <= deadline else None

    state = wait_for(read_state, 10, 0.2)
    if state is None:
        ctx.report.add("restart-check", False, ["重启后 10 秒仍读不到 /state"] + notes)
        return
    if ctx.hold_supported and state.get("hold_mode") != "auto":
        problems.append("重启后 hold_mode=%s，应默认 auto" % state.get("hold_mode"))
    try:
        idle_limit = parse_idle_seconds((ROOT / "pc" / "hub.py").read_text(encoding="utf-8"))
    except OSError:
        idle_limit = 21600
    # Reloading can finish shortly after /health becomes available.
    while True:
        missing, extra = compare_restart(before, state.get("sessions", []), idle_limit, time.time())
        if not missing or time.monotonic() >= deadline:
            break
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))
        state = read_state() or state
    problems += missing
    notes += extra + ["重启前 %d 个真实会话，重启后 %d 个；闲置上限 %ds" % (
        len(before), len(state.get("sessions", [])), idle_limit)]
    ctx.report.add("restart-check", not problems, (problems or ["打包进程已重启，未过期会话与槽位保留"]) + notes, [saved])


def autostart_check(ctx, state=None):
    text, query_error = query_task_xml()
    if ctx.restarted:
        deadline = time.monotonic() + 10
        while text is None and time.monotonic() < deadline:
            time.sleep(0.2)
            text, query_error = query_task_xml()
    task = None
    if text is not None:
        try:
            task = parse_task_xml(text)
        except (ET.ParseError, ValueError) as error:
            ctx.report.add("autostart", False, "计划任务 XML 无法解析：%s" % error)
            return
    try:
        run_value = read_run_value()
    except OSError as error:
        ctx.report.add("autostart", False, "无法只读查询 HKCU Run：%s" % error)
        return
    user_ids = current_user_ids()
    try:
        app_text = (ctx.agentdeck / "logs" / "app.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        app_text = ""
    if state is None and not ctx.args.dry_run:
        state = ctx.hub.state()
    status, lines = autostart_verdict(task, query_error, run_value, user_ids,
                                    ROOT / "dist" / "AgentDeck" / "AgentDeck.exe",
                                    autostart_fallback_note(state, app_text))
    ctx.report.add("autostart", status == "PASS", lines, info=status == "WARN")


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
    exe = ROOT / "dist" / "AgentDeck" / "AgentDeck.exe"
    reason = restart_skip_reason(ctx.args.port, ctx.args.home, process_name(pid) if pid else "", exe)
    print("--restart-check：%s%s" % ("正式运行会 SKIP：" + reason if reason else "正式运行会终止并重启这个打包进程",
          "（本次 dry-run 不执行）" if ctx.args.restart_check else "（当前未启用，不重启）"))
    codex = shutil.which("codex.cmd") or shutil.which("codex")
    print("--codex-exec：%s（%s）" % ("正式运行会在 %s 跑 %s exec --skip-git-repo-check -s read-only %r" % (
        ROOT, codex, CODEX_PROMPT) if codex else "PATH 上没有 codex，正式运行会 SKIP",
        "已启用" if ctx.args.codex_exec else "当前未启用"))
    if not ctx.skipped("autostart"):
        autostart_check(ctx, state={})  # No HTTP in dry-run; fallback evidence comes from app.log only.
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
    sessions = 3 * len(agents_first) + (len(required) - len(agents_first)) + len(info) + 4
    print("\n正式运行会：写 relay.log 标记、跑上面的命令（%d 个假会话）、截图、移动鼠标悬停浮窗、"
          "开两个控制台测切窗口，约 2~3 分钟；期间 hold 模式临时改成 always（真实会话的权限请求也会挂起），结束恢复。" % sessions)
    return 0


def self_test():
    from unittest.mock import patch
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("离线自检禁止查询计划任务、注册表或当前用户")

    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # Importing pc/hub_risk must not create/update pc/__pycache__.
    try:
        with patch.dict(globals(), {name: forbidden for name in ("query_task_xml", "read_run_value", "current_user_ids")}):
            return _self_test(attempts)
    finally:
        sys.dont_write_bytecode = previous


def _self_test(io_attempts):
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
    for label, data, want in (("空对象", b"{}", True), ("空白", b" \n { }\r\n", True),
                              ("空 stdout", b"", False), ("数组", b"[]", False), ("null", b"null", False),
                              ("布尔", b"false", False), ("非空对象", b'{"x":1}', False),
                              ("重复 JSON", b"{}{}", False), ("坏 UTF-8", b"{\xff}", False)):
        check("empty_json_object " + label, empty_json_object(data) is want)
    good = {"code": 0, "stdout_bytes": b"{}", "seconds": 0.5, "seen": False,
            "session_dict": {"native_wait": True, "state": "wait"},
            "audit_records": [{"session_id": "accept-s", "decision": "passthrough"}], "sid": "accept-s"}
    check("passthrough 正常", passthrough_problems(**good) == [])
    for label, changes in (("退出码", {"code": 1}), ("stdout", {"stdout_bytes": b"[]"}),
                            ("耗时边界", {"seconds": PASSTHROUGH_LIMIT}), ("曾挂起", {"seen": True}),
                            ("native_wait", {"session_dict": {"native_wait": False, "state": "wait"}}),
                            ("状态", {"session_dict": {"native_wait": True, "state": "think"}}),
                            ("会话缺失", {"session_dict": None}), ("审计缺失", {"audit_records": []}),
                            ("审计其他会话", {"audit_records": [{"session_id": "other", "decision": "passthrough"}]}),
                            ("审计其他决定", {"audit_records": [{"session_id": "accept-s", "decision": "allow"}]})):
        check("passthrough 拒绝" + label, bool(passthrough_problems(**dict(good, **changes))))
    done = {"agent": "cc", "session_id": "accept-s", "state": "done", "last_event": "Stop",
            "last_text": STOP_TEXT, "ended_by": "SessionEnd"}
    ended_state = {"recent_ended": [{"agent": "cx", "session_id": "accept-s"}, done]}
    check("recent_ended 正常", ended_problems(ended_state, "cc", "accept-s", "Stop", STOP_TEXT) == [])
    check("recent_ended 取最新一条", find_ended({"recent_ended": [dict(done, state="think"), done]},
                                             "cc", "accept-s") is done)
    check("recent_ended 只核对 ended_by（上一步不是 Stop）",
          ended_problems({"recent_ended": [dict(done, state="wait", last_event="PermissionRequest")]},
                         "cc", "accept-s", "UserPromptSubmit", STOP_TEXT) == [])
    for label, state in (("字段缺失", {}), ("非列表", {"recent_ended": {}}), ("空", {"recent_ended": []}),
                         ("别的 agent", {"recent_ended": [dict(done, agent="cx")]}),
                         ("ended_by", {"recent_ended": [dict(done, ended_by="idle")]}),
                         ("状态", {"recent_ended": [dict(done, state="think")]}),
                         ("事件", {"recent_ended": [dict(done, last_event="UserPromptSubmit")]}),
                         ("回复", {"recent_ended": [dict(done, last_text="别的")]})):
        check("recent_ended 拒绝" + label, bool(ended_problems(state, "cc", "accept-s", "Stop", STOP_TEXT)))
    cx_done = {"agent": "cx", "session_id": "01a1f746", "state": "done", "last_event": "Stop",
               "last_text": "ok", "ended_by": "SessionEnd"}
    seen = {"01a1f746": {"state": "think"}}
    check("codex-exec 正常", codex_exec_problems(0, "ok\r\n", seen, cx_done) == (None, []))
    check("codex-exec 没 SessionEnd 也认",
          codex_exec_problems(0, "ok", seen, None, dict(cx_done, ended_by=None)) == (None, []))
    check("codex-exec 只在 recent_ended 里也认", codex_exec_problems(0, "ok", {}, cx_done) == (None, []))
    limit = "ERROR: You've hit your usage limit. Upgrade to Pro ... try again at Nov 20th, 2026 1:09 AM."
    model = "The 'gpt-5.5' model is not supported when using Codex with a ChatGPT account."
    for label, text in (("额度", limit), ("模型", model)):
        skip, found = codex_exec_problems(1, text, seen, dict(cx_done, state="think", last_event="UserPromptSubmit"))
        check("codex-exec %s记 SKIP" % label, skip and found == [], skip)
    for label, args in (("退出码", (1, "ok", seen, cx_done)),
                        ("没进 hub", (0, "ok", {}, None)),
                        ("会话消失没记录", (0, "ok", seen, None)),
                        ("没 Stop", (0, "ok", seen, dict(cx_done, state="think", last_event="UserPromptSubmit"))),
                        ("回复不对", (0, "ok", seen, dict(cx_done, last_text="Reply only: ok"[:5]))),
                        ("ended_by", (0, "ok", seen, dict(cx_done, ended_by="idle")))):
        skip, found = codex_exec_problems(*args)
        check("codex-exec 拒绝" + label, skip is None and bool(found), found)
    good_line = "2026-11-19 22:18:03 cc PermissionRequest 3f2a9c1d hub not reachable: ConnectionRefusedError(10061)"
    prefix = "2026-11-19 22:18:03 cc Stop - "
    check("relay 格式正常", relay_line_problems(good_line) == [])
    check("relay sid 为 -", relay_line_problems(prefix + "error") == [])
    check("relay 无消息", relay_line_problems(prefix.rstrip()) == [])
    check("relay 拒绝旧格式", bool(relay_line_problems("cc PreToolUse UnicodeDecodeError('后面')")))
    check("relay 拒绝 401 字符", bool(relay_line_problems("x" * 401)))
    check("relay 拒绝 301 字符消息", bool(relay_line_problems(prefix + "x" * 301)))
    check("relay 接受 300 字符消息", relay_line_problems(prefix + "x" * 300) == [])
    for marker in ("第00000行", PROMPT, "RAWPROBE-fake"):
        check("relay 拒绝原始 stdin " + short(marker, 18),
              bool(relay_line_problems(prefix + marker, markers=("RAWPROBE-fake",))))

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
        check("read_log_since 不轮转", read_log_since(log, offset) == ["cc PreToolUse UnicodeDecodeError('后面')"])
        check("read_log_since 无新行", read_log_since(log, file_size(log)) == [])
        log.write_bytes(b"old line\n" * 100)
        offset = file_size(log)
        with open(log, "ab") as handle:
            handle.write((good_line + "\n=== accept end\n").encode("utf-8"))
        log.rename(log.with_name("relay.log.1"))
        log.write_text(prefix + "新错误\n", encoding="utf-8")
        check("read_log_since 合并轮转前后", read_log_since(log, offset) == [good_line, prefix + "新错误"])
        log.with_name("relay.log.1").write_bytes(b"short\n")
        check("read_log_since 旧备份不足偏移", read_log_since(log, offset) == [prefix + "新错误"])
        log.with_name("relay.log.1").unlink()
        check("read_log_since 没有轮转备份", read_log_since(log, offset) == [prefix + "新错误"])
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
    check("decode_console UTF-16 LE BOM", decode_console("任务 后面".encode("utf-16")) == "任务 后面")
    check("decode_console UTF-16 BE BOM", decode_console(b"\xfe\xff" + "任务 后面".encode("utf-16-be")) == "任务 后面")
    check("decode_console UTF-8", decode_console("后面".encode("utf-8")) == "后面")
    ansi = b"\xb2\xe2\xca\xd4"
    try:
        ansi_text = ansi.decode("oem")
    except UnicodeDecodeError:
        ansi_text = ansi.decode("mbcs", "replace")
    check("decode_console ANSI/OEM 字节", decode_console(ansi) == ansi_text)
    xml = r'''<?xml version="1.0" encoding="UTF-16"?>
<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><URI>\AgentDeck</URI></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>DESKTOP\King</UserId></LogonTrigger></Triggers>
  <Principals><Principal><UserId>S-1-5-21-123</UserId><LogonType>InteractiveToken</LogonType>
    <RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><Enabled>true</Enabled></Settings>
  <Actions><Exec><Command>"D:\apps\AgentDeck\AgentDeck.exe"</Command>
    <Arguments>--background</Arguments><WorkingDirectory>D:\apps\AgentDeck</WorkingDirectory></Exec></Actions>
</Task>'''
    task = parse_task_xml(decode_console(xml.encode("ascii")))
    exe = r"D:\apps\AgentDeck\AgentDeck.exe"
    ids = {r"desktop\king", "s-1-5-21-123"}

    def verdict(task_data, run_value=None, fallback="", user_ids=ids):
        return autostart_verdict(task_data, "fake query error" if task_data is None else "",
                                 run_value, user_ids, exe, fallback)

    check("parse_task_xml UTF-16 声明与命名空间", task["uri"] == r"\AgentDeck" and task["enabled"] == "true"
          and task["principal"]["user_id"] == "S-1-5-21-123"
          and task["execs"][0]["working_dir"] == r"D:\apps\AgentDeck")
    check("autostart 正常 PASS", verdict(task)[0] == "PASS")
    check("autostart Run 仍存在 FAIL", verdict(task, exe)[0] == "FAIL")
    for label, old, new in (("提权", "LeastPrivilege", "HighestAvailable"),
                             ("密码登录", "InteractiveToken", "Password"),
                             ("错误命令", "AgentDeck.exe", "wrong.exe"),
                             ("错误参数", "--background", "--other"),
                             ("其他用户", r"DESKTOP\King", r"DESKTOP\Other"),
                             ("任务禁用", "<Settings><Enabled>true", "<Settings><Enabled>false"),
                             ("触发器禁用", "<LogonTrigger><Enabled>true", "<LogonTrigger><Enabled>false"),
                             ("非根任务", r"<URI>\AgentDeck", r"<URI>\Other\AgentDeck")):
        check("autostart " + label + " FAIL", verdict(parse_task_xml(xml.replace(old, new)))[0] == "FAIL")
    no_level = parse_task_xml(xml.replace("<RunLevel>LeastPrivilege</RunLevel>", ""))
    status, lines = verdict(no_level)
    check("autostart 缺 RunLevel PASS 并注明默认值", status == "PASS" and any("缺省" in line for line in lines))
    check("autostart SID 匹配不区分大小写", verdict(parse_task_xml(xml.replace(r"DESKTOP\King", "S-1-5-21-123")))[0] == "PASS")
    check("autostart Enabled 缺省 true", verdict(parse_task_xml(xml.replace("<Enabled>true</Enabled>", "")))[0] == "PASS")
    check("autostart 缺任务仍有 Run FAIL", verdict(None, exe)[0] == "FAIL")
    check("autostart 缺任务 Run 回退 WARN", verdict(None, exe, "registry fallback")[0] == "WARN")
    status, lines = verdict(None)
    check("autostart 两者都没有 FAIL 并保留查询错误", status == "FAIL" and any("fake query error" in line for line in lines))
    check("parse_whoami CSV", parse_whoami('"DESKTOP\\King","S-1-5-21-123"\r\n') == ids)
    check("parse_whoami 忽略坏行", parse_whoami('ERROR: whoami failed\n"User Name","SID"') == set())
    check("autostart fallback state 字符串", autostart_fallback_note({"autostart": "Registry fallback"}, "") == "Registry fallback")
    check("autostart fallback state 字典", "registry" in autostart_fallback_note({"autostart": {"backend": "registry"}}, ""))
    check("autostart fallback 不把键名当证据", autostart_fallback_note({"autostart": {"registry": False, "fallback": False}}, "") == "")
    check("autostart fallback 不把 running 当 Run", autostart_fallback_note({"autostart": {"mode": "task", "status": "running"}}, "") == "")
    check("autostart fallback app 最后一条", autostart_fallback_note({}, "autostart registry old\n自启 回退到 Run 键\n无关") == "自启 回退到 Run 键")
    check("autostart fallback 没有证据", autostart_fallback_note({"autostart": "task"}, "registry 无关\nautostart enabled") == "")
    before = [{"agent": "cc", "session_id": "real-s", "slot": 1, "last_updated": 10000}]
    check("compare_restart 保留会话", compare_restart(before, before, 21600, 10001) == ([], []))
    check("compare_restart 丢失新会话 FAIL", bool(compare_restart(before, [], 21600, 10001)[0]))
    problems, notes = compare_restart(before, [], 21600, 31600)
    check("compare_restart 过期允许丢弃", not problems and any("闲置过期，被丢弃是对的" in note for note in notes))
    problems, notes = compare_restart(before, before + [{"agent": "cx", "session_id": "new", "slot": 2}], 21600, 10001)
    check("compare_restart 额外会话仅备注", not problems and len(notes) == 1)
    check("compare_restart 槽位改变 FAIL", bool(compare_restart(before, [dict(before[0], slot=2)], 21600, 10001)[0]))
    check("parse_idle_seconds 乘法", parse_idle_seconds("SESSION_IDLE_SECONDS = 6 * 60 * 60\n") == 21600)
    check("parse_idle_seconds 加法与注释", parse_idle_seconds("SESSION_IDLE_SECONDS = 2 * 60 + 3 # seconds") == 123)
    for expression in ("", "SESSION_IDLE_SECONDS = bad()", "SESSION_IDLE_SECONDS = 2 ** 3",
                       "SESSION_IDLE_SECONDS = 0", "SESSION_IDLE_SECONDS = 12 / 2", "SESSION_IDLE_SECONDS = 1 - 2"):
        check("parse_idle_seconds 安全缺省 " + short(expression, 36), parse_idle_seconds(expression) == 21600)

    from types import SimpleNamespace

    class FakeHub:
        def __init__(self, mode="auto", code=200):
            self.mode, self.code, self.posts = mode, code, []

        def state(self):
            return {"hold_mode": self.mode}

        def post(self, path, body):
            self.posts.append((path, body))
            if self.code == 400:
                return 400, {"error": "unknown action"}
            if self.code != 200:
                return self.code, {"error": "fake failure"}
            self.mode = body["action"].split()[1]
            return 200, {"status": "ok", "hold_mode": self.mode}

    class FakeReport:
        def __init__(self):
            self.rows = []

        def add(self, *args, **kwargs):
            self.rows.append((args, kwargs))

    def hold_context(mode="auto", code=200):
        return SimpleNamespace(hub=FakeHub(mode, code), report=FakeReport(), hold_supported=False,
                               hold_original=None, hold_restored=False)

    fake = hold_context()
    hold_begin(fake, register_exit=False)
    check("hold_begin 支持 always", fake.hold_supported and fake.hold_original == "auto" and fake.hub.mode == "always")
    hold_restore(fake)
    hold_restore(fake)
    check("hold_restore 恢复且幂等", fake.hold_restored and fake.hub.mode == "auto" and fake.hub.posts == [
        ("/action", {"action": "hold always"}), ("/action", {"action": "hold auto"})])
    fake = hold_context(code=400)
    hold_begin(fake, register_exit=False)
    hold_restore(fake)
    check("hold 旧版 400 不恢复 POST", not fake.hold_supported and len(fake.hub.posts) == 1)
    fake = hold_context("never")
    hold_begin(fake, register_exit=False)
    hold_restore(fake, report=False)
    check("hold_restore 保留原 never 且静默", fake.hold_restored and fake.hub.mode == "never" and len(fake.report.rows) == 1)
    fake = hold_context("invalid")
    hold_begin(fake, register_exit=False)
    hold_restore(fake)
    check("hold_restore 未知原模式按 auto", fake.hold_restored and fake.hold_original is None and fake.hub.mode == "auto")
    fake = hold_context(code=503)
    hold_begin(fake, register_exit=False)
    check("hold_begin 非 400 错误 FAIL", not fake.hold_supported and fake.report.rows[0][0][1] is False)
    fake = hold_context()
    hold_begin(fake, register_exit=False)
    fake.hub.state = lambda: {"hold_mode": "always"}
    hold_restore(fake)
    check("hold_restore 核对 state，不只信 POST", not fake.hold_restored and fake.report.rows[-1][0][1] is False)
    fake = hold_context()
    hold_begin(fake, register_exit=False)
    fake.hub.code = 503
    hold_restore(fake)
    check("hold_restore POST 失败保留重试", not fake.hold_restored and fake.report.rows[-1][0][1] is False)
    fake = hold_context()
    hold_begin(fake, register_exit=False)

    def failed_post(*args, **kwargs):
        raise OSError("fake unavailable hub")

    fake.hub.post = failed_post
    hold_restore(fake, report=False)
    check("hold_restore 退出回调失败仍静默", not fake.hold_restored and len(fake.report.rows) == 1)
    fake = hold_context("never")
    hold_begin(fake, register_exit=False)
    working_post = fake.hub.post
    fake.hub.post = failed_post
    hold_restore(fake)
    check("hold_restore 异常报告且保留重试", not fake.hold_restored and fake.report.rows[-1][0][1] is False)
    fake.hub.post = working_post
    hold_restore(fake, report=False)
    check("hold_restore 失败后退出回调重试成功", fake.hold_restored and fake.hub.mode == "never"
          and fake.hub.posts[-1] == ("/action", {"action": "hold never"}) and len(fake.report.rows) == 2)
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
    check("自检未调用计划任务/注册表/用户查询", not io_attempts)
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
    hold_begin(ctx)
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
    cc_mode = next((m for a, m in required if a == "cc"), "auto")
    if not ctx.skipped("hold"):
        hold_auto(ctx, cc_mode)
    if not ctx.skipped("ghost"):
        ghost_check(ctx, cc_mode)
    if not (ctx.skipped("overlay") and ctx.skipped("switch")):
        cx_mode = next((m for a, m in required if a == "cx"), "cmd")
        overlay_and_switch(ctx, cc_mode, cx_mode)
    if ctx.args.codex_exec:
        codex_exec_check(ctx)
    if prober:
        problems, lines, _ = summarize_probe(prober.finish())
        ctx.report.add("window-load", not problems, (problems or ["hook、批准、切窗口期间所有窗口始终 1 秒内响应"]) + lines)
    if not ctx.skipped("logs"):
        try:
            with open(relay_path, "a", encoding="utf-8") as handle:
                handle.write("=== accept %s end\n" % ctx.run_id)
        except OSError:
            pass
        lines_run = read_log_since(relay_path, relay_offset)
        relay_log_check(ctx, lines_run)
        relay_log_format_check(ctx, relay_offset, lines_run, cc_mode)
        app_log_check(ctx, app_offset)
        keyboard_info(ctx)
    if ctx.args.restart_check:
        restart_check(ctx)
    if not ctx.skipped("autostart"):
        autostart_check(ctx)
    return None


def finish(ctx):
    try:
        hold_restore(ctx)
    except Exception as error:
        ctx.report.add("hold-restore", False, "恢复 hold 模式出错：%r" % error)
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
    parser.add_argument("--restart-check", action="store_true", help="额外终止并重启默认打包进程，核对会话持久化（默认不开）")
    parser.add_argument("--codex-exec", action="store_true",
                        help="额外真跑一次 codex exec（花 Codex 额度），核对 Stop 的回复进了 /state（默认不开）")
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
