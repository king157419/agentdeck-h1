"""Read-only Hub diagnostics; every external check can be substituted offline."""
import http.client
import io
import json
import logging
import math
from pathlib import Path
import subprocess
import shutil
import sys
import time

import hub_install


RECENT_SECONDS = 600
log = logging.getLogger("agentdeck.hub.doctor")
MAC_PERMISSION_ADVICE = "系统设置 → 隐私与安全性 → 辅助功能 / 自动化 / 屏幕录制 / 输入监控"


def _get_json(path, port, token, connection_factory):
    connection = connection_factory("127.0.0.1", port, timeout=2)
    try:
        headers = {"X-AgentDeck-Token": token} if token else {}
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("HTTP %s" % response.status)
        result = json.loads(response.read(1024 * 1024))
        if not isinstance(result, dict):
            raise ValueError("response is not an object")
        return result
    finally:
        connection.close()


def _has_relay(path, agent):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    if not isinstance(hooks, dict):
        return False
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            entries = group.get("hooks", []) if isinstance(group, dict) else []
            if not isinstance(entries, list):
                continue
            for entry in entries:
                info = hub_install.relay_info(entry)
                if info is not None and info["agent"] == agent:
                    return True
    return False


def _logged_in(result):
    if result.returncode != 0:
        return False
    try:
        data = json.loads(result.stdout)
    except (TypeError, ValueError):
        # Older CLI versions may print a human-readable status instead of JSON.
        text = (result.stdout or "").strip().casefold()
        return text.startswith("logged in as ") or text.startswith("logged in using ")
    return isinstance(data, dict) and data.get("loggedIn") is True


def _global_label(status):
    return ("未启用" if not status["enabled"] else
            "路径失效" if status["missing_paths"] or status["needs_repair"] else "已启用")


def doctor(*, port=47800, home=None, stdout=None, connection_factory=None,
           runner=None, wall_time=None, checks=None):
    """Print read-only checks (two extra on macOS); return 0 only if healthy."""
    home = Path.home() if home is None else Path(home)
    if stdout is None:
        stdout = sys.stdout
        if hasattr(stdout, "reconfigure"):
            stdout.reconfigure(encoding="utf-8")
    connection_factory = http.client.HTTPConnection if connection_factory is None else connection_factory
    runner = subprocess.run if runner is None else runner
    now = time.time() if wall_time is None else wall_time()
    failures = 0

    def check(label, success, detail=""):
        nonlocal failures
        failures += not success
        if checks is not None:
            checks.append({"label": label, "success": bool(success), "detail": detail})
        stdout.write("%s %s%s\n" % ("✓" if success else "✗", label,
                                   ": " + detail if detail else ""))

    try:
        health = _get_json("/health", port, None, connection_factory)
        running = health.get("ok") is True
    except (OSError, ValueError, http.client.HTTPException):
        running = False
    check("Hub /health", running,
          "http://127.0.0.1:%s" % port if running else
          "start python pc/hub.py --backend none --port %s" % port)

    path = home / ".agentdeck" / "token"
    try:
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        token = ""
    check("Token file", bool(token), str(path) if token else
          "start Hub to create a nonempty token at %s" % path)

    stdout.write("全局钩子：" + _global_label(hub_install.global_status(home=home)) + "\n")
    for agent, folders in hub_install.TARGETS.items():
        path = home.joinpath(*folders)
        try:
            present = _has_relay(path, agent)
        except (OSError, ValueError, UnicodeError):
            present = False
        check("%s hub_relay hook" % agent, present, str(path) if present else
              "check %s; run python pc/hub_install.py install %s" % (path, agent))

    seen = {}
    if running and token:
        try:
            seen = _get_json("/state", port, token, connection_factory).get("agents_seen", {})
            if not isinstance(seen, dict):
                seen = {}
        except (OSError, ValueError, http.client.HTTPException):
            pass
    for agent in ("cc", "cx"):
        stamp = seen.get(agent)
        recent = (isinstance(stamp, (int, float)) and not isinstance(stamp, bool)
                  and math.isfinite(stamp) and 0 <= now - stamp <= RECENT_SECONDS)
        advice = ("trigger a Claude Code event and check the relay/Hub token" if agent == "cc" else
                  "在 Codex 里输入 /hooks 信任 AgentDeck 钩子")
        check("%s event in last 10 minutes" % agent, recent,
              "last event %.0fs ago" % (now - stamp) if recent else
              advice + "; ensure Hub is running and /state accepts the token")

    try:
        result = runner(["claude", "auth", "status"], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=5, check=False)
        authenticated = _logged_in(result)
    except (OSError, subprocess.SubprocessError, ValueError):
        authenticated = False
    check("Claude login", authenticated, "logged in" if authenticated else "运行 claude 登录")
    if sys.platform == "darwin":
        stdout.write("macOS permissions: %s\n" % MAC_PERMISSION_ADVICE)
        stdout.write('macOS dictation requires dictation_shortcut in the Hub config: '
                     '{"key_codes": [49], "modifiers": ["control", "option"]}; '
                     'enable Dictation in System Settings → Keyboard and set the same '
                     'Control+Option+Space shortcut. Without this config, voice is unavailable.\n')
        probes = (("macOS osascript", "return 1", "1"),
                  ("macOS accessibility", 'tell application "System Events" to get UI elements enabled', "true"))
        permission_hint_logged = False
        for label, script, expected in probes:
            detail = ""
            try:
                result = runner(["osascript", "-e", script], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=3, check=False)
                success = result.returncode == 0 and result.stdout.strip().casefold() == expected
                if not success:
                    detail = (getattr(result, "stderr", "") or "probe returned %r" % result.stdout).strip()
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                success, detail = False, str(error)
            if not success:
                log.warning("%s probe failed: %s", label, detail)
                if not permission_hint_logged:
                    log.warning("macOS permissions: %s", MAC_PERMISSION_ADVICE)
                    permission_hint_logged = True
            check(label, success, "available" if success else
                  "%s; check osascript and grant permissions in %s" % (detail, MAC_PERMISSION_ADVICE))
    return 1 if failures else 0


def _entries(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    if not isinstance(hooks, dict):
        return []
    return [entry for groups in hooks.values() if isinstance(groups, list)
            for group in groups if isinstance(group, dict)
            for entry in (group.get("hooks") if isinstance(group.get("hooks"), list) else [])]


def installed_projects(projects):
    """Inspect only registered project paths, with no recursive home scan or writes."""
    records = []
    for project in dict.fromkeys(str(Path(project).resolve()) for project in projects):
        root = Path(project)
        record = {"path": project, "agents": [], "missing_paths": [], "errors": []}
        for agent, folders in hub_install.PROJECT_TARGETS.items():
            path = root.joinpath(*folders)
            try:
                entries = _entries(path)
            except FileNotFoundError:
                continue
            except (OSError, ValueError, UnicodeError) as error:
                record["errors"].append("%s：%s" % (path, error))
                continue
            for entry in entries:
                info = hub_install.relay_info(entry)
                if info is None or info["agent"] != agent:
                    continue
                if agent not in record["agents"]:
                    record["agents"].append(agent)
                for target in info["paths"]:
                    candidate = Path(target)
                    exists = candidate.is_file() if candidate.is_absolute() else bool(shutil.which(target))
                    if not exists and target not in record["missing_paths"]:
                        record["missing_paths"].append(target)
        records.append(record)
    return records


def serial_log_status(home):
    """Recent error evidence only; never probe a serial port by opening it."""
    path = Path(home) / ".agentdeck" / "logs" / "app.log"
    try:
        # Keep work bounded even when a user replaces our rotating log with a large file.
        with path.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 65536))
            lines = stream.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return "未确认（诊断不打开串口）；没有最近的串口错误记录"
    evidence = next((line for line in reversed(lines)
                     if ("LCD unavailable" in line or "COM4" in line.upper())
                     and any(word in line.casefold() for word in
                             ("denied", "busy", "permission", "占用", "拒绝访问"))), None)
    if evidence:
        return "最近日志显示被占用或权限不足（不代表此刻仍占用）：" + evidence[-300:]
    return "未确认（诊断不打开串口）；最近日志未发现占用或权限不足记录"


def app_report(*, home=None, projects=(), port=47800, usb_probe=None, serial_probe=None,
               connection_factory=None, runner=None, wall_time=None):
    """Chinese tray diagnostics, using the existing doctor and injectable external probes."""
    home = Path.home() if home is None else Path(home)
    projects = installed_projects(projects)
    checks = []
    if runner is None:
        def runner(command, **options):
            if sys.platform == "win32":
                options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            return subprocess.run(command, **options)
    doctor(home=home, port=port, stdout=io.StringIO(), connection_factory=connection_factory,
           runner=runner, wall_time=wall_time, checks=checks)
    labels = {
        "Hub /health": ("中枢服务", "正常运行", "未连接，请退出后重新打开 AgentDeck"),
        "Token file": ("本机认证 token", "已生成（不会显示密钥）", "缺失或为空，请重新打开 AgentDeck"),
        "cc event in last 10 minutes": ("Claude 最近十分钟的事件", "已收到", "未收到；请在已安装钩子的项目中开始会话"),
        "cx event in last 10 minutes": ("Codex 最近十分钟的事件", "已收到", "未收到；请在项目中输入 /hooks 信任钩子"),
        "Claude login": ("Claude 登录", "已登录", "未登录或 CLI 不可用，请在 Claude 中检查登录"),
    }
    lines = []
    for check in checks:
        label = labels.get(check["label"])
        if label:
            lines.append("%s：%s" % (label[0], label[1] if check["success"] else label[2]))
    try:
        if usb_probe is None:
            from deck_usb import interface0_driver
            driver = interface0_driver()
            usb = {"connected": True if driver else None, "driver": driver}
        else:
            usb = usb_probe()
        driver = usb.get("driver")
        connected = usb.get("connected")
        lines.extend(("键盘 USB：" + ("已连接" if connected is True else "未连接" if connected is False else "未检测到或无法确认"),
                      "接口 0 驱动：" + ("WinUSB（正确）" if str(driver).casefold() == "winusb" else
                      "HidUsb（请由用户手动通过 Zadig 更换接口 0）" if str(driver).casefold() == "hidusb" else "无法确认")))
    except Exception as error:
        usb = {"connected": None, "driver": None}
        lines.append("键盘 USB / 接口 0 驱动：无法确认（%s）" % error)
    lines.append("COM4 占用：" + ((serial_probe or serial_log_status)(home)))
    global_hooks = hub_install.global_status(home=home)
    lines.append("全局钩子：" + _global_label(global_hooks))
    lines.extend(global_hooks["errors"])
    legacy_count = 0
    global_missing = global_hooks["missing_paths"]
    for folders in hub_install.TARGETS.values():
        path = home.joinpath(*folders)
        try:
            entries = _entries(path)
        except FileNotFoundError:
            continue
        except (OSError, ValueError, UnicodeError):
            continue
        legacy_count += sum(hub_install.is_legacy(entry) for entry in entries)
    lines.append("全局旧版 agent_lcd.py 钩子：%s 条（仅在点击移除并确认后备份、删除）" % legacy_count)
    lines.append("项目钩子：")
    installed = [project for project in projects if project["agents"]]
    if not installed:
        lines.append("尚无已登记且安装钩子的项目")
    for project in projects:
        names = ["Claude" if agent == "cc" else "Codex" for agent in project["agents"]]
        lines.append("%s：%s" % (project["path"], "、".join(names) if names else "未发现 AgentDeck 钩子"))
        for target in project["missing_paths"]:
            lines.append("路径已失效：%s；文件夹移动后，请从托盘重新安装到该项目" % target)
        lines.extend(project["errors"])
    for target in dict.fromkeys(global_missing):
        lines.append("全局钩子路径已失效：%s；请检查原安装位置" % target)
    lines.append("Codex 需要在项目里输入 /hooks 信任；安装或修改钩子后请重开会话并再次信任。")
    return {"text": "\n".join(lines), "legacy_count": legacy_count, "projects": projects,
            "usb": usb, "checks": checks, "global_missing_paths": global_missing,
            "global_hooks": global_hooks}
