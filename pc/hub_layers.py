"""Foreground layers with a quiet period; no native I/O at import time."""
import ntpath


LAYER_NAMES = {"agent": "Agent", "chat": "聊天", "browser": "浏览器",
               "video": "视频", "default": "默认"}
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe"}
TERMINALS = {"windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
             "conhost.exe", "wezterm-gui.exe"}


def classify_layer(window, fullscreen=False):
    if not isinstance(window, (tuple, list)) or len(window) < 3:
        return "default"
    process = ntpath.basename(window[1] or "").casefold()
    title = (window[2] or "").casefold()
    if process == "claude.exe" or ("codex" in process and process not in TERMINALS):
        return "agent"
    if process in {"weixin.exe", "wechat.exe", "feishu.exe", "lark.exe"}:
        return "chat"
    if process in BROWSERS:
        if fullscreen or any(name in title for name in ("哔哩哔哩", "抖音", "youtube")):
            return "video"
        return "browser"
    return "default"


class Layers:
    def __init__(self, delay=.3):
        self.current = "default"
        self.delay = delay
        self.candidate = None
        self.since = 0.0

    def update(self, window, now, *, frozen=False, fullscreen=False):
        identity = tuple(window or ()) + (bool(fullscreen),)
        if identity != self.candidate:
            self.candidate, self.since = identity, now
        target = classify_layer(window, fullscreen)
        if not frozen and now - self.since + 1e-9 >= self.delay and target != self.current:
            self.current = target
            return True
        return False
