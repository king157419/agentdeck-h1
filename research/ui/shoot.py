"""Render every AgentDeck window with fake data and save screenshots.
Usage: python research/ui/shoot.py before|after   (no Hub, no COM4, temp home)."""
import ctypes, sys, tempfile, types
from pathlib import Path
from queue import SimpleQueue
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pc"))
mode = sys.argv[1]
out = Path(__file__).resolve().parent / mode
out.mkdir(parents=True, exist_ok=True)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import tkinter as tk
from PIL import Image, ImageGrab
import agentdeck_app as app
import hub_overlay
from hub_overlay import Overlay
import hub

user = ctypes.windll.user32
root = tk.Tk()
root.geometry("+40+40")
root.withdraw()
home = Path(tempfile.mkdtemp(prefix="agentdeck-shoot-"))


def pump(ms=250):
    root.after(ms, root.quit)
    root.mainloop()


def grab_widget(w, name, pad=0):
    w.update_idletasks()
    w.update()
    pump(200)
    x, y, wd, ht = w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height()
    ImageGrab.grab(bbox=(x - pad, y - pad, x + wd + pad, y + ht + pad), all_screens=True).save(out / (name + ".png"))
    print("saved", name, wd, ht)


class FakeHub:
    def __init__(self, state): self._s = state; self.home = home; self.lock = None
    def state(self): return self._s
    def monotonic(self): return 0.0
    def record_rendered(self, *a, **k): pass
    def action(self, *a, **k): return {"status": "ok"}
    def hide_display(self, *a): pass


SESS = [
    {"slot": 1, "name": "h1-firmware", "project": "h1", "state": "tool", "agent": "cc", "session_id": "a"},
    {"slot": 2, "name": "paper-draft", "project": "paper", "state": "wait", "agent": "cx", "session_id": "b"},
    {"slot": 3, "name": "web-dashboard-with-a-very-long-name", "state": "done", "agent": "cc", "session_id": "c"},
    {"slot": 4, "name": "infra", "state": "error", "agent": "cc", "session_id": "d"},
    {"slot": 5, "name": "notes", "state": "idle", "agent": "cx", "session_id": "e"},
]
STATES = {
    "overlay-idle": {"sessions": SESS[:3] and [dict(s, state="idle") for s in SESS[:2]], "selected_slot": 1},
    "overlay-pending": {"sessions": SESS, "selected_slot": 2, "displayed_request_id": "r1",
                        "pending": [{"id": "r1", "summary": "git push --force origin main && rm -rf build/ dist/ node_modules", "risk": "high", "armed": True, "nonce": 0x1a2b}]},
    "overlay-locked": {"sessions": SESS, "selected_slot": 2, "displayed_request_id": "r2",
                       "locked": [{"id": "r2", "summary": "sudo rm -rf /var/lib", "risk": "critical", "status": "locked"}]},
}


def shoot_overlay(name, state):
    top = tk.Toplevel(root)
    ov = Overlay(FakeHub(state), window=None, state_path=None)
    ov.root = top
    ov._build()
    ov.model = hub_overlay.display_model(state)
    ov._render()
    top.geometry("+120+80")
    top.update_idletasks()
    top.geometry("%dx%d+120+80" % (hub_overlay.WIDTH, top.winfo_reqheight()))
    top.attributes("-topmost", True)
    grab_widget(top, name, pad=16)
    top.destroy()


class FakeAuto:
    def enabled(self): return False
    def set_enabled(self, v): pass


import hub_install
keys = app.prepare_configs(home)[0]
overlay = Mock(); overlay.root = root; overlay.hidden = False
engine = types.SimpleNamespace(home=home, lock=None, state=lambda: {"sessions": SESS})
tray = app.TrayApplication(engine, commands=SimpleQueue(), prefs=app.Preferences(home), keys_path=keys,
                           autostart=FakeAuto(), overlay=overlay)


def new_toplevels(before):
    return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and w not in before]


def shoot_new(name, action):
    before = set(w for w in root.winfo_children())
    action()
    wins = new_toplevels(before)
    assert wins, name
    w = wins[-1]
    w.geometry("+160+120")
    w.attributes("-topmost", True)
    grab_widget(w, name, pad=16)
    w.destroy()


def shoot_modal(name, action, title):
    """Run a blocking dialog; grab it from a timer, then close it."""
    def grab_and_close():
        hwnd = user.FindWindowW(None, title)
        rect = ctypes.wintypes.RECT()
        if hwnd:
            user.GetWindowRect(hwnd, ctypes.byref(rect))
            ImageGrab.grab(bbox=(rect.left - 16, rect.top - 16, rect.right + 16, rect.bottom + 16),
                           all_screens=True).save(out / (name + ".png"))
            print("saved", name)
            user.PostMessageW(hwnd, 0x10, 0, 0)
        for w in ([] if hwnd else root.winfo_children()):
            if isinstance(w, tk.Toplevel) and w.winfo_viewable():
                try:
                    w.update()
                except Exception:
                    continue
                x, y, wd, ht = w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height()
                if not hwnd:
                    ImageGrab.grab(bbox=(x - 16, y - 16, x + wd + 16, y + ht + 16), all_screens=True).save(out / (name + ".png"))
                    print("saved", name)
                try:
                    w.destroy()
                except Exception:
                    pass
    root.after(900, grab_and_close)
    root.deiconify() if False else None
    action()


import ctypes.wintypes
for name, state in STATES.items():
    shoot_overlay(name, state)

shoot_new("keys", lambda: tray.show_keys())
report = {"text": "\n".join([
    "中枢服务：正常运行", "本机认证 token：已生成（不会显示密钥）",
    "Claude 最近十分钟的事件：已收到", "Codex 最近十分钟的事件：未收到；请在项目中输入 /hooks 信任钩子",
    "Claude 登录：已登录", "键盘 USB：已连接", "接口 0 驱动：WinUSB（正确）", "COM4 占用：未发现占用",
    "全局钩子：未启用", "发现 2 处旧版 1602 钩子"]), "legacy_count": 2}
shoot_new("diagnostics", lambda: tray.show_report(report))
tray.prefs.values["onboarding_dismissed"] = False
shoot_new("onboarding", lambda: tray.onboarding())
shoot_modal("dialog-confirm", lambda: tray.global_action(True), "所有项目启用")
shoot_modal("dialog-notice", lambda: tray.message("项目钩子", "已安装项目钩子：\nD:\desk\hardware\h1\n\n请重启该项目的 agent 会话；在 Codex 里输入 /hooks，审核并信任 AgentDeck 钩子。\n\n"), "项目钩子")
shoot_modal("dialog-error", lambda: tray.message("AgentDeck 操作失败", "backup failed: Permission denied", error=True), "AgentDeck 操作失败")

# tray icons
from agentdeck_icon import create_icon
sheet = Image.new("RGBA", (4 * 140 + 20, 2 * 150), (240, 240, 240, 255) if mode == "x" else (255, 255, 255, 255))
dark = Image.new("RGBA", sheet.size, (32, 32, 32, 255))
for bg, tag in ((Image.new("RGBA", sheet.size, (255, 255, 255, 255)), "light"), (dark, "dark")):
    s = bg.copy()
    for i, st in enumerate(("idle", "running", "waiting", "error")):
        big = create_icon(size=128, color=app.COLORS[st])
        small = create_icon(size=32, color=app.COLORS[st])
        s.alpha_composite(big, (10 + i * 140, 10))
        s.alpha_composite(small, (10 + i * 140 + 48, 150 + 40))
    s.save(out / ("tray-icons-%s.png" % tag))
    print("saved tray-icons", tag)
root.destroy()
