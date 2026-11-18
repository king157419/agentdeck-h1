"""Windows tray entry point. Importing it never starts Hub or native interfaces."""
import argparse
import errno
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import shutil
import socket
import subprocess
import sys
import threading

import hub
from hub_overlay import Overlay


log = logging.getLogger("agentdeck.app")
APP_PORT = 47801
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
COLORS = {"idle": "#858b93", "running": "#31b66b", "waiting": "#e5a52e", "error": "#e35757"}
STATES = {"idle": "空闲", "think": "思考", "tool": "运行", "wait": "待批",
          "locked": "终端确认", "error": "出错", "done": "完成"}
TOOLS = {"cc": "Claude", "cx": "Codex"}
# Measured physical positions, including unbound keys and keys without a report.
KEY_ROWS = (
    (("E", "hid:0x08"), ("B", "hid:0x05"), ("Ctrl+Z", "ctrl+hid:0x1D"), ("Space", "hid:0x2C")),
    (("G", "hid:0x0A"), ("Ctrl+F", "ctrl+hid:0x09"), ("H", "hid:0x0B"), ("无信号", None)),
    (("L", "hid:0x0F"), ("M", "hid:0x10"), ("Ctrl+T", "ctrl+hid:0x17"), ("Ctrl+D", "ctrl+hid:0x07")),
    (("U", "hid:0x18"), ("X", "hid:0x1B"), ("无信号", None), ("无信号", None)),
    (("Tab", "hid:0x2B"), ("Ctrl+C", "ctrl+hid:0x06"), ("Ctrl+V", "ctrl+hid:0x19"), ("P", "hid:0x13")),
)
KNOBS = (("hid:0x16", "hid:0x09", "hid:0x0F"), ("hid:0x15", "hid:0x13", "hid:0x14"),
         ("hid:0x2D", "hid:0x2E", "hid:0x19"), ("hid:0x30", "hid:0x2F", "ctrl+hid:0x27"))


def data_dir(home=None):
    return (Path.home() if home is None else Path(home)) / ".agentdeck"


def resource_dir():
    return Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def prepare_configs(home=None):
    folder = data_dir(home)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in ("hub_keys.json", "hub_prompts.json"):
        target = folder / name
        if not target.exists():
            # Exclusive creation also protects a user file during simultaneous launches.
            with (resource_dir() / name).open("rb") as source:
                try:
                    with target.open("xb") as output:
                        shutil.copyfileobj(source, output)
                except FileExistsError:
                    pass
        paths.append(target)
    return tuple(paths)


class Preferences:
    def __init__(self, home=None):
        self.path = data_dir(home) / "app.json"
        self.values = hub.load_json(self.path) if self.path.exists() else {}
        if not isinstance(self.values, dict):
            raise ValueError("app.json 必须是 JSON 对象")

    @property
    def projects(self):
        return self.values.get("projects", [])

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(self.values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def project_changed(self, project, installed):
        project = str(Path(project).resolve())
        projects = [p for p in self.projects if os.path.normcase(p) != os.path.normcase(project)]
        if installed:
            projects.append(project)
        self.values["projects"] = projects
        self.save()


def tray_status(state):
    sessions = state.get("sessions", [])
    waiting = sum(bool(s.get("pending_requests") or s.get("locked_requests")) or
                  s.get("state") in ("wait", "locked") for s in sessions)
    if any(s.get("state") == "error" for s in sessions):
        status = "error"
    elif waiting or state.get("pending") or state.get("locked"):
        status = "waiting"
    elif any(s.get("state") in ("think", "tool") for s in sessions):
        status = "running"
    else:
        status = "idle"
    return status, "AgentDeck · %s 个会话 · %s 个待批" % (len(sessions), waiting)


def session_label(session):
    return "%s %s %s" % (STATES.get(session.get("state"), session.get("state", "")),
                          TOOLS.get(session.get("agent"), session.get("agent", "Agent")),
                          session.get("project") or session.get("name") or session.get("cwd", ""))


def keymap_model(config, profile="default"):
    selected = config if profile == "default" else config.get(profile)
    if not isinstance(selected, dict) or not isinstance(selected.get("bindings"), dict):
        raise ValueError("找不到键位 profile：%s" % profile)
    mapping = selected["bindings"]

    def action(code):
        value = mapping.get(code, "未绑定") if code else "无信号"
        if isinstance(value, dict):
            return " / ".join(("按下 " if edge == "down" else "松开 ") + text
                              for edge, text in value.items())
        return str(value)

    return {"rows": [[(name, action(code)) for name, code in row] for row in KEY_ROWS],
            "knobs": [[action(code) for code in knob] for knob in KNOBS]}


def launch_command():
    if getattr(sys, "frozen", False):
        return subprocess.list2cmdline([str(Path(sys.executable).resolve())])
    python = Path(sys.executable).with_name("pythonw.exe")
    return subprocess.list2cmdline([str(python), str(Path(__file__).resolve())])


class AutoStart:
    def __init__(self, registry=None, command=None):
        if registry is None:
            import winreg
            registry = winreg
        self.registry = registry
        self.command = launch_command() if command is None else command

    def enabled(self):
        r = self.registry
        try:
            with r.OpenKey(r.HKEY_CURRENT_USER, RUN_KEY) as key:
                return r.QueryValueEx(key, "AgentDeck")[0] == self.command
        except FileNotFoundError:
            return False

    def set_enabled(self, enabled):
        r = self.registry
        with r.CreateKeyEx(r.HKEY_CURRENT_USER, RUN_KEY, 0, r.KEY_SET_VALUE) as key:
            if enabled:
                r.SetValueEx(key, "AgentDeck", 0, r.REG_SZ, self.command)
            else:
                try:
                    r.DeleteValue(key, "AgentDeck")
                except FileNotFoundError:
                    pass


class SingleInstance:
    """Loopback ownership plus an acknowledged SHOW message; no second Hub."""
    def __init__(self, commands, *, socket_factory=socket.socket, connector=socket.create_connection):
        self.commands = commands
        self.socket_factory = socket_factory
        self.connector = connector
        self.listener = None
        self.thread = None
        self.stopped = threading.Event()

    def acquire(self):
        listener = self.socket_factory(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind((hub.HOST, APP_PORT))
            listener.listen(4)
            listener.settimeout(.2)
        except OSError as error:
            listener.close()
            if error.errno not in (errno.EADDRINUSE, 10048) and getattr(error, "winerror", None) != 10048:
                raise
            for _ in range(20):
                try:
                    with self.connector((hub.HOST, APP_PORT), timeout=.3) as connection:
                        connection.sendall(b"AgentDeck SHOW\n")
                        if connection.recv(64) == b"AgentDeck OK\n":
                            return False
                except OSError:
                    pass
                self.stopped.wait(.1)
            raise RuntimeError("AgentDeck 单实例端口已被占用，无法联系已有实例。") from error
        self.listener = listener
        self.thread = threading.Thread(target=self._listen, name="AgentDeck instance", daemon=True)
        self.thread.start()
        return True

    def _listen(self):
        while not self.stopped.is_set():
            try:
                connection, _ = self.listener.accept()
                with connection:
                    connection.settimeout(.5)
                    message = b""
                    while b"\n" not in message and len(message) < 64:
                        part = connection.recv(64 - len(message))
                        if not part:
                            break
                        message += part
                    if message == b"AgentDeck SHOW\n":
                        self.commands.put(("show", None))
                        connection.sendall(b"AgentDeck OK\n")
            except socket.timeout:
                continue
            except OSError:
                if not self.stopped.is_set():
                    log.exception("单实例消息接收失败")

    def close(self):
        self.stopped.set()
        if self.listener is not None:
            self.listener.close()
        if self.thread is not None:
            self.thread.join(timeout=1)


def tray_icon_type(base):
    """Refresh dynamic menus on pystray's Windows message thread before opening.

    pystray 0.19.5 destroys the previous HMENU in update_menu(). Refreshing
    from Tk's timer could destroy a menu while the user is selecting an item.
    """
    class LiveMenuIcon(base):
        def _on_notify(self, wparam, lparam):
            if lparam == 0x0205:  # WM_RBUTTONUP, before TrackPopupMenuEx.
                self.update_menu()
            return super()._on_notify(wparam, lparam)

    return LiveMenuIcon


class TrayApplication:
    """Tk stays on the main thread. Tray callbacks only enqueue operations."""
    def __init__(self, engine, *, commands, prefs, keys_path, profile="default",
                 autostart=None, overlay=None):
        self.hub = engine
        self.commands = commands
        self.prefs = prefs
        self.keys_path = keys_path
        self.profile = profile
        self.autostart = AutoStart() if autostart is None else autostart
        self.overlay = Overlay(engine) if overlay is None else overlay
        self.icon = None
        self.tray_thread = None
        self.state = {}
        self.last_status = None
        self.autostart_enabled = self.autostart.enabled()

    def enqueue(self, action, payload=None):
        def callback(icon=None, item=None):
            self.commands.put((action, payload))
        return callback

    def menu(self, pystray):
        item, menu = pystray.MenuItem, pystray.Menu

        def sessions():
            rows = [item(session_label(s), self.enqueue("select", (s["agent"], s["session_id"])))
                    for s in self.state.get("sessions", [])]
            return rows or [item("暂无会话", None, enabled=False)]

        return menu(
            item(lambda _: "显示浮窗" if self.overlay.hidden else "隐藏浮窗", self.enqueue("toggle"), default=True),
            item("会话", menu(sessions)), item("跳到等我的会话", self.enqueue("next_wait")),
            item("键位", self.enqueue("keys")), item("诊断", self.enqueue("diagnostics")),
            menu.SEPARATOR, item("安装到项目…", self.enqueue("install")),
            item("从项目卸载…", self.enqueue("uninstall")),
            item("开机自启", self.enqueue("autostart"), checked=lambda _: self.autostart_enabled),
            item("打开日志文件夹", self.enqueue("logs")), menu.SEPARATOR,
            item("退出", self.enqueue("quit")))

    def run(self):
        try:
            self.overlay.run(on_ready=self.ready)
        finally:
            if self.icon is not None:
                self.icon.stop()
            if self.tray_thread is not None:
                self.tray_thread.join(timeout=2)

    def ready(self):
        import pystray
        self.icon = tray_icon_type(pystray.Icon)("AgentDeck", self.draw_icon("idle"), "AgentDeck", self.menu(pystray))
        self.tray_thread = threading.Thread(target=self._run_tray, name="AgentDeck tray", daemon=True)
        self.tray_thread.start()
        self.overlay.root.after(100, self.pump)
        self.overlay.root.after(400, self.onboarding)

    def _run_tray(self):
        try:
            self.icon.run()
        except Exception as error:
            log.exception("托盘启动失败")
            self.commands.put(("fatal", str(error)))

    @staticmethod
    def draw_icon(status):
        from agentdeck_icon import create_icon
        return create_icon(size=64, color=COLORS[status])

    def stop(self):
        self.overlay.stop()

    def pump(self):
        try:
            for _ in range(50):
                try:
                    action, payload = self.commands.get_nowait()
                except Empty:
                    break
                try:
                    self.dispatch(action, payload)
                except Exception as error:
                    log.exception("菜单动作失败：%s", action)
                    self.message("AgentDeck 操作失败", str(error), error=True)
            self.state = self.hub.state()
            status = tray_status(self.state)
            if status != self.last_status:
                self.icon.icon = self.draw_icon(status[0])
                self.icon.title = status[1]
                self.last_status = status
        except Exception:
            log.exception("托盘状态更新失败")
        if not self.overlay.stopped.is_set():
            self.overlay.root.after(300, self.pump)

    def message(self, title, text, *, error=False):
        from tkinter import messagebox
        method = messagebox.showerror if error else messagebox.showinfo
        method(title, text, parent=self.overlay.root)

    def dispatch(self, action, payload=None):
        if action == "show":
            self.overlay.show()
        elif action == "toggle":
            (self.overlay.show if self.overlay.hidden else self.overlay.hide)()
        elif action == "select":
            # Verify the full identity at click time; a recycled slot must never retarget.
            with self.hub.lock:
                session = next((s for s in self.hub.state()["sessions"]
                                if (s["agent"], s["session_id"]) == payload), None)
                if session is None:
                    raise ValueError("该会话已结束")
                self.hub.action({"action": "slot %s" % session["slot"]})
        elif action == "next_wait":
            self.hub.action({"action": "next_wait"})
        elif action == "keys":
            self.show_keys()
        elif action == "diagnostics":
            self.diagnostics()
        elif action in ("install", "uninstall"):
            self.project_action(action)
        elif action == "autostart":
            self.autostart.set_enabled(not self.autostart_enabled)
            self.autostart_enabled = self.autostart.enabled()
        elif action == "logs":
            os.startfile(str(data_dir(self.hub.home) / "logs"))
        elif action == "quit":
            self.stop()
        elif action == "fatal":
            self.message("AgentDeck 无法启动", payload, error=True)
            self.stop()
        elif action == "report":
            self.show_report(payload)

    def project_action(self, action):
        from tkinter import filedialog
        import io
        import hub_install
        folder = filedialog.askdirectory(title="选择要%s钩子的项目" % ("安装" if action == "install" else "卸载"),
                                         parent=self.overlay.root, mustexist=True)
        if not folder:
            return
        output = io.StringIO()
        hub_install.apply(action, project=folder, output=output)
        self.prefs.project_changed(folder, action == "install")
        text = "已%s项目钩子：\n%s" % ("安装" if action == "install" else "卸载", folder)
        if action == "install":
            text += "\n\n请重启该项目的 agent 会话；在 Codex 里输入 /hooks，审核并信任 AgentDeck 钩子。"
        self.message("项目钩子", text + "\n\n" + output.getvalue())

    def show_keys(self):
        import tkinter as tk
        model = keymap_model(hub.load_json(self.keys_path), self.profile)
        window = tk.Toplevel(self.overlay.root)
        window.title("CXT 键位 · %s（只读）" % self.profile)
        for y, row in enumerate(model["rows"]):
            for x, (key, action) in enumerate(row):
                tk.Label(window, text=key + "\n" + action, width=24, height=4,
                         relief="groove", wraplength=175).grid(row=y, column=x, padx=3, pady=3, sticky="nsew")
        for y, actions in enumerate(model["knobs"], 5):
            tk.Label(window, text="旋钮 %s：顺时针 %s · 逆时针 %s · 按下 %s" % (y - 4, *actions),
                     wraplength=740, justify="left").grid(row=y, column=0, columnspan=4, sticky="w", padx=8, pady=4)

    def diagnostics(self):
        import hub_doctor

        def worker():
            try:
                result = hub_doctor.app_report(home=self.hub.home, projects=self.prefs.projects)
                self.commands.put(("report", result))
            except Exception as error:
                log.exception("诊断失败")
                self.commands.put(("report", {"text": "诊断失败：%s" % error, "legacy_count": 0}))

        threading.Thread(target=worker, name="AgentDeck diagnostics", daemon=True).start()

    def show_report(self, report):
        import tkinter as tk
        from tkinter.scrolledtext import ScrolledText
        window = tk.Toplevel(self.overlay.root)
        window.title("AgentDeck 诊断")
        text = ScrolledText(window, width=88, height=26, wrap="word")
        text.insert("1.0", report["text"])
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=12, pady=12)
        if report.get("legacy_count"):
            tk.Button(window, text="移除旧版钩子", command=lambda: self.remove_legacy(window)).pack(pady=8)

    def remove_legacy(self, window):
        from tkinter import messagebox
        import hub_install
        if not messagebox.askyesno("移除旧版钩子", "将先备份全局配置，再只删除 agent_lcd.py 钩子。\n其他配置保持不变。是否继续？",
                                   parent=window):
            return
        changed = hub_install.remove_legacy_hooks(home=self.hub.home, confirmed=True)
        self.message("旧版钩子", "已处理 %s 个文件，备份保存在原文件旁（*.bak-agentdeck-时间）。" % len(changed))
        window.destroy()
        self.diagnostics()

    def onboarding(self):
        import hub_doctor
        if self.prefs.values.get("onboarding_dismissed") or any(
                project["agents"] for project in hub_doctor.installed_projects(self.prefs.projects)):
            return
        import tkinter as tk
        window = tk.Toplevel(self.overlay.root)
        window.title("欢迎使用 AgentDeck")
        tk.Label(window, text="1. 安装到项目\n\n2. 在项目的 Codex 中输入 /hooks，审核并信任钩子\n\n3. 开始干活，用宏键盘管理会话",
                 justify="left", padx=24, pady=20).pack()
        dismissed = tk.BooleanVar(window, value=False)
        tk.Checkbutton(window, text="不再提示", variable=dismissed).pack(anchor="w", padx=24)

        def close():
            self.prefs.values["onboarding_dismissed"] = dismissed.get()
            self.prefs.save()
            window.destroy()

        tk.Button(window, text="安装到项目…", command=lambda: self.project_action("install")).pack(pady=10)
        tk.Button(window, text="开始使用", command=close).pack(pady=10)
        window.protocol("WM_DELETE_WINDOW", close)


def configure_logging(home=None):
    folder = data_dir(home) / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    return handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--profile")
    args = parser.parse_args(argv)
    home = Path.home() if args.home is None else args.home.resolve()
    commands = SimpleQueue()
    instance = SingleInstance(commands)
    handler = None
    try:
        if not instance.acquire():
            return 0
        handler = configure_logging(home)
        keys, prompts = prepare_configs(home)
        prefs = Preferences(home)
        profile = args.profile or prefs.values.get("profile", "default")
        keymap_model(hub.load_json(keys), profile)  # Validate before listeners/native inputs.
        return hub.main(["--backend", "usb,hotkey", "--overlay", "--require-nonce",
                         "--home", str(home), "--keys", str(keys), "--prompts", str(prompts),
                         "--profile", profile],
                        ui_factory=lambda engine: TrayApplication(engine, commands=commands, prefs=prefs,
                                                                  keys_path=keys, profile=profile))
    except Exception as error:
        log.exception("AgentDeck 启动失败")
        from tkinter import messagebox
        messagebox.showerror("AgentDeck 无法启动", "%s\n\n请查看 %s。若命令行 Hub 已在运行，请先将其退出。" %
                             (error, data_dir(home) / "logs" / "app.log"))
        return 1
    finally:
        instance.close()
        if handler is not None:
            logging.getLogger().removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    raise SystemExit(main())
