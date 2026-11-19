"""Windows tray entry point. Importing it never starts Hub or native interfaces."""
import argparse
import errno
import io
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
import tempfile
import threading

import agentdeck_theme as theme
import hub
import hub_install
from hub_overlay import Overlay
from voice_shortcut_capture import ShortcutCapture


log = logging.getLogger("agentdeck.app")
APP_PORT = 47801
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
COLORS = {"idle": theme.STATUS["IDLE"], "running": theme.STATUS["RUN"],
          "waiting": theme.STATUS["ASK"], "error": theme.STATUS["ERR"]}
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


class ShortcutRecorder:
    """Record one chord; repeated keydowns never add another key."""
    MODIFIERS = {
        "Control_L": (0xA2, "control", "Ctrl"), "Control_R": (0xA3, "control", "Right Ctrl"),
        "Alt_L": (0xA4, "option", "Alt"), "Alt_R": (0xA5, "option", "Right Alt"),
        "Shift_L": (0xA0, "shift", "Shift"), "Shift_R": (0xA1, "shift", "Right Shift"),
        "Win_L": (0x5B, "command", "Win"), "Win_R": (0x5C, "command", "Right Win"),
        "Super_L": (0x5B, "command", "Win"), "Super_R": (0x5C, "command", "Right Win"),
    }

    def __init__(self):
        self.held = {}
        self.chord = {}
        self.shortcut = None
        self.label = ""

    def key(self, event):
        if event.keysym in self.MODIFIERS:
            return self.MODIFIERS[event.keysym]
        code = event.keycode
        if type(code) is not int or not 1 <= code <= 254:
            return None
        name = {"space": "Space", "Return": "Enter", "Escape": "Esc"}.get(event.keysym, event.keysym)
        return code, None, name.upper() if len(name) == 1 else name

    def press(self, event):
        key = self.key(event)
        if self.shortcut is not None or key is None or key[0] in self.held:
            return
        self.held[key[0]] = key
        self.chord[key[0]] = key

    def release(self, event):
        key = self.key(event)
        if self.shortcut is not None or key is None or key[0] not in self.held:
            return None
        self.held.pop(key[0])
        if self.held:
            return None
        keys = list(self.chord.values())
        main = [key[0] for key in keys if key[1] is None]
        right = {0xA1, 0xA3, 0xA5, 0x5C}
        modifiers = list(dict.fromkeys(key[1] for key in keys if key[1] is not None and key[0] not in right))
        # Preserve right modifiers even in chords; modifier-only shortcuts keep both sides.
        codes = [key[0] for key in keys if key[0] in right] + main if main else [key[0] for key in keys]
        self.shortcut = {"key_codes": codes, "modifiers": modifiers if main else []}
        self.label = " + ".join(key[2] for key in keys)
        return self.shortcut


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


def set_global_hooks(home, enabled):
    if enabled:
        hub_install.remove_legacy_hooks(home=home, confirmed=True)
    return hub_install.apply("install" if enabled else "uninstall", home=home, output=io.StringIO())


def init_all(home, *, autostart=None):
    """Enable hooks and startup; persist success only after every step completes."""
    home = Path(home)
    prefs = Preferences(home)
    startup = AutoStart() if autostart is None else autostart
    set_global_hooks(home, True)
    if not startup.enabled():
        startup.set_enabled(True)
    if not prefs.values.get("initialized"):
        prefs.values["initialized"] = True
        prefs.save()
    return {"hooks": "enabled", "autostart": True, "initialized": True}


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
            item(lambda _: "显示" if self.overlay.hidden else "隐藏", self.enqueue("toggle"), default=True),
            item("会话", menu(sessions)), item("下一个待批", self.enqueue("next_wait")),
            item("键位", self.enqueue("keys")), item("诊断", self.enqueue("diagnostics")),
            menu.SEPARATOR, item("所有项目启用", self.enqueue("global"),
                                 checked=lambda _: hub_install.global_status(home=self.hub.home)["enabled"]),
            item("单个项目", menu(item("安装…", self.enqueue("install")),
                                 item("卸载…", self.enqueue("uninstall")))),
            item("开机自启", self.enqueue("autostart"), checked=lambda _: self.autostart_enabled),
            item("日志", self.enqueue("logs")), menu.SEPARATOR,
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
        theme.notice(self.overlay.root, title, text, error=error)

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
        elif action == "global":
            self.global_action()
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

    def global_action(self, enabled=None):
        if enabled is None:
            enabled = not hub_install.global_status(home=self.hub.home)["enabled"]
        if enabled:
            if not theme.confirm(self.overlay.root, "所有项目启用",
                                 "备份两份全局配置，替换旧版 1602 钩子。\nAgentDeck 未运行时，agent 在终端确认。",
                                 ok="启用"):
                return False
        set_global_hooks(self.hub.home, enabled)
        log.info("全局钩子：%s", "已启用" if enabled else "已停用")
        return True

    def project_action(self, action):
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="选择项目",
                                         parent=self.overlay.root, mustexist=True)
        if not folder:
            return
        output = io.StringIO()
        hub_install.apply(action, project=folder, output=output)
        self.prefs.project_changed(folder, action == "install")
        text = "已%s\n%s" % ("安装" if action == "install" else "卸载", folder)
        if action == "install":
            text += "\n\n重启该项目的会话，在 Codex 输入 /hooks 并信任。"
        detail = output.getvalue().strip()
        self.message("项目钩子", text + ("\n\n" + detail if detail else ""))

    def show_keys(self):
        import tkinter as tk
        model = keymap_model(hub.load_json(self.keys_path), self.profile)
        window = theme.style_window(tk.Toplevel(self.overlay.root), "键位")
        grid = tk.Frame(window, bg=theme.BG, padx=theme.S5, pady=theme.S5)
        grid.pack()
        for y, row in enumerate(model["rows"]):
            for x, (key, action) in enumerate(row):
                dead = action == "无信号"
                card = tk.Frame(grid, bg=theme.SURFACE, padx=theme.S3, pady=theme.S3, width=170, height=72)
                card.grid(row=y, column=x, padx=theme.S1, pady=theme.S1, sticky="nsew")
                card.grid_propagate(False)
                theme.label(card, key, color=theme.FAINT if dead else theme.TEXT, size=10, bold=True,
                            latin=True, bg=theme.SURFACE).pack(anchor="w")
                if not dead:
                    theme.label(card, action, color=theme.FAINT if action == "未绑定" else theme.MUTED,
                                size=9, bg=theme.SURFACE, wraplength=150, justify="left").pack(anchor="w")
        knobs = tk.Frame(grid, bg=theme.BG)
        knobs.grid(row=len(model["rows"]), column=0, columnspan=4, sticky="ew", pady=(theme.S3, 0))
        for number, (cw, ccw, press) in enumerate(model["knobs"]):
            knobs.columnconfigure(number, weight=1, uniform="knob")
            card = tk.Frame(knobs, bg=theme.SURFACE, padx=theme.S3, pady=theme.S3)
            card.grid(row=0, column=number, padx=theme.S1, sticky="nsew")
            theme.label(card, "旋钮 %d" % (number + 1), color=theme.TEXT, size=10, bold=True,
                        bg=theme.SURFACE).pack(anchor="w")
            for mark, value in (("顺", cw), ("逆", ccw), ("按", press)):
                theme.label(card, "%s  %s" % (mark, value), color=theme.MUTED, size=9, bg=theme.SURFACE,
                            wraplength=140, justify="left").pack(anchor="w")
        theme.button(grid, "语音快捷键", self.show_voice_shortcut, "quiet").grid(
            row=len(model["rows"]) + 1, column=0, columnspan=4, sticky="e", pady=(theme.S4, 0))
        theme.center(window)

    def save_voice_shortcut(self, shortcut):
        from hub_desktop import DesktopEffects
        shortcut = DesktopEffects._shortcut(shortcut)
        with self.hub.lock:
            desktop = self.hub._desktop()
            if desktop.voice_active:
                raise RuntimeError("请先松开语音键")
            path = data_dir(self.hub.home) / "config.json"
            config = hub.load_json(path) if path.exists() else {}
            if not isinstance(config, dict):
                raise ValueError("config.json 必须是 JSON 对象")
            config["dictation_shortcut"] = shortcut
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                                 prefix="config-", suffix=".tmp", delete=False) as output:
                    temporary = Path(output.name)
                    output.write(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
                previous = desktop.dictation_shortcut
                desktop.set_dictation_shortcut(shortcut)
                try:
                    os.replace(temporary, path)
                except Exception:
                    desktop.set_dictation_shortcut(previous)
                    raise
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    def show_voice_shortcut(self):
        import tkinter as tk
        window = theme.style_window(tk.Toplevel(self.overlay.root), "语音快捷键")
        body = tk.Frame(window, bg=theme.BG, padx=theme.S5, pady=theme.S5)
        body.pack(fill="both", expand=True)
        caption = theme.label(body, "按一次语音软件的快捷键", color=theme.MUTED)
        caption.pack(anchor="w")
        chord = theme.label(body, "等待按键…", size=14, bold=True, latin=True)
        chord.pack(anchor="w", pady=(theme.S3, theme.S4))
        mode = tk.StringVar(window, value="hold")
        choices = []
        for value, text in (("hold", "按住说话"), ("toggle", "按一下开始、再按结束")):
            choice = tk.Radiobutton(body, text=text, value=value, variable=mode, bg=theme.BG,
                                    fg=theme.TEXT, selectcolor=theme.RAISED, activebackground=theme.BG,
                                    activeforeground=theme.TEXT, font=theme.font(10), anchor="w",
                                    highlightthickness=0, state="disabled")
            choice.pack(anchor="w", pady=theme.S1)
            choices.append(choice)
        bar = tk.Frame(body, bg=theme.BG)
        bar.pack(fill="x", pady=(theme.S5, 0))
        state = {"recorder": ShortcutRecorder(), "capture": None}

        def stop_capture():
            capture = state["capture"]
            if capture is not None:
                capture.close()
                state["capture"] = None

        def failed(text):
            state["recorder"] = ShortcutRecorder()
            caption.configure(text=text, fg=theme.STATUS["ERR"])
            save.configure(fg=theme.FAINT)

        def record(focus=True):
            stop_capture()
            state["recorder"] = ShortcutRecorder()
            caption.configure(text="按一次语音软件的快捷键", fg=theme.MUTED)
            chord.configure(text="等待按键…")
            for choice in choices:
                choice.configure(state="disabled")
            save.configure(fg=theme.FAINT)
            if focus:
                window.focus_force()
            capture = ShortcutCapture(window, lambda down, event: pressed(event) if down else released(event), failed)
            state["capture"] = capture
            try:
                capture.start()
            except Exception:
                stop_capture()
                failed("无法录制，请重录")

        def pressed(event):
            recorder = state["recorder"]
            if recorder.shortcut is None:
                recorder.press(event)
                if recorder.chord:
                    chord.configure(text=" + ".join(key[2] for key in recorder.chord.values()))
                return "break"

        def released(event):
            from hub_desktop import DesktopEffects
            recorder = state["recorder"]
            if recorder.shortcut is not None:
                return
            if recorder.release(event) is not None:
                stop_capture()
                try:
                    DesktopEffects._shortcut(recorder.shortcut)
                except ValueError:
                    record()
                    caption.configure(text="组合键太长，请重录", fg=theme.STATUS["ERR"])
                else:
                    caption.configure(text="选择语音方式", fg=theme.MUTED)
                    chord.configure(text=recorder.label)
                    for choice in choices:
                        choice.configure(state="normal")
                    save.configure(fg=theme.BG)
            return "break"

        def persist():
            shortcut = state["recorder"].shortcut
            if shortcut is None:
                return
            try:
                self.save_voice_shortcut(dict(shortcut, mode=mode.get()))
            except Exception as error:
                caption.configure(text=str(error), fg=theme.STATUS["ERR"])
            else:
                finish()

        def finish():
            try:
                stop_capture()
            finally:
                window.destroy()

        def lost_focus(event):
            if event.widget is window and state["capture"] is not None:
                stop_capture()
                failed("窗口已失焦，请重录")

        def destroyed(event):
            if event.widget is window:
                stop_capture()

        theme.button(bar, "重录", record, "plain").pack(side="left")
        theme.button(bar, "取消", finish, "quiet").pack(side="right", padx=(theme.S2, 0))
        save = theme.button(bar, "保存", persist)
        save.pack(side="right")
        save.configure(fg=theme.FAINT)
        window.bind("<FocusOut>", lost_focus)
        window.bind("<Destroy>", destroyed)
        window.protocol("WM_DELETE_WINDOW", finish)
        theme.center(window)
        window.attributes("-topmost", True)
        window.grab_set()
        record()

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
        window = theme.style_window(tk.Toplevel(self.overlay.root), "诊断", resizable=True)
        lines = report["text"].splitlines()
        text = tk.Text(window, width=64, height=min(max(len(lines), 6), 22), wrap="word", bd=0,
                       highlightthickness=0, bg=theme.BG, fg=theme.TEXT, font=theme.font(10),
                       padx=theme.S5, pady=theme.S5, spacing1=theme.S1, spacing3=theme.S1,
                       cursor="arrow", tabs=("230",))
        text.tag_configure("name", foreground=theme.MUTED, lmargin2=230)
        text.tag_configure("warn", foreground=theme.STATUS["ASK"])
        text.tag_configure("plain", lmargin2=230)
        trouble = ("请", "失败", "缺失", "无法", "未连接", "未收到", "未登录")
        for line in lines:
            name, sep, value = line.partition("：")
            if sep:
                text.insert("end", name, "name")
                text.insert("end", "\t" + value + "\n", "warn" if any(w in value for w in trouble) else "plain")
            else:
                text.insert("end", line + "\n", "warn")
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)
        if report.get("legacy_count"):
            bar = tk.Frame(window, bg=theme.BG, padx=theme.S5, pady=theme.S4)
            bar.pack(fill="x")
            theme.button(bar, "移除旧版钩子", lambda: self.remove_legacy(window), "quiet").pack(side="right")
        theme.center(window)

    def remove_legacy(self, window):
        if not theme.confirm(window, "移除旧版钩子",
                             "备份全局配置，只删除 agent_lcd.py 钩子，其余不动。", ok="移除"):
            return
        changed = hub_install.remove_legacy_hooks(home=self.hub.home, confirmed=True)
        self.message("旧版钩子", "已处理 %s 个文件，备份在原文件旁。" % len(changed))
        window.destroy()
        self.diagnostics()

    def onboarding(self):
        if self.prefs.values.get("initialized"):
            return
        import tkinter as tk
        # Installing global hooks also creates .codex on machines without Codex.
        codex_installed = (self.hub.home / ".codex").exists()
        window = theme.style_window(tk.Toplevel(self.overlay.root), "AgentDeck")
        body = tk.Frame(window, bg=theme.BG, padx=theme.S5, pady=theme.S5)
        body.pack()
        caption = theme.label(body, "点击开始，自动启用钩子和开机自启。")
        caption.pack(anchor="w")

        def enable():
            if self.prefs.values.get("initialized"):
                return
            try:
                init_all(self.hub.home, autostart=self.autostart)
                self.prefs.values["initialized"] = True
                self.autostart_enabled = self.autostart.enabled()
                if codex_installed:
                    caption.configure(text="在 Codex 里输入 /hooks，信任一次", fg=theme.TEXT)
                    start.destroy()
                    theme.center(window)
                else:
                    window.destroy()
            except Exception as error:
                log.exception("初始化失败")
                caption.configure(text="初始化失败：%s" % error, fg=theme.STATUS["ERR"])

        start = theme.button(body, "开始使用", enable)
        start.pack(anchor="e", pady=(theme.S5, 0))
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        theme.center(window)


def repair_global_hooks(home):
    if not getattr(sys, "frozen", False):
        return False
    try:
        if not hub_install.global_status(home=home)["needs_repair"]:
            return False
        hub_install.apply("install", home=home, output=io.StringIO())
        log.info("全局钩子 relay 路径已修复：%s", Path(sys.executable).resolve().with_name("AgentDeck-relay.exe"))
        return True
    except Exception:
        log.exception("全局钩子 relay 路径修复失败")
        return False


def configure_logging(home=None):
    folder = data_dir(home) / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    return handler


def restore_cli_output():
    """Windowed builds reuse a pipe or the parent console, without opening a window."""
    if sys.platform != "win32" or sys.stdout is not None:
        return
    import ctypes
    import msvcrt
    kernel = ctypes.windll.kernel32
    kernel.GetStdHandle.restype = ctypes.c_void_p
    invalid = (None, 0, ctypes.c_void_p(-1).value)
    if kernel.GetStdHandle(-11) in invalid:
        kernel.AttachConsole(ctypes.c_uint(-1))  # ATTACH_PARENT_PROCESS
    for name, number in (("stdout", -11), ("stderr", -12)):
        handle = kernel.GetStdHandle(number)
        if getattr(sys, name) is None and handle not in invalid:
            descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY)
            setattr(sys, name, os.fdopen(descriptor, "w", encoding="utf-8", buffering=1))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--profile")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--init", action="store_true", help="enable global hooks and startup, then exit")
    action.add_argument("--uninstall", action="store_true", help="remove global hooks and startup, then exit")
    args = parser.parse_args(argv)
    home = Path.home() if args.home is None else args.home.resolve()
    if args.init or args.uninstall:
        restore_cli_output()
        try:
            if args.init:
                result = init_all(home)
            else:
                prefs = Preferences(home)
                set_global_hooks(home, False)
                AutoStart().set_enabled(False)
                if "initialized" in prefs.values:
                    del prefs.values["initialized"]
                    prefs.save()
                result = {"hooks": "disabled", "autostart": False, "initialized": False}
            print(json.dumps(result, ensure_ascii=False))
            return 0
        except Exception as error:
            print("AgentDeck: %s" % error, file=sys.stderr)
            return 1
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
        repair_global_hooks(home)
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
