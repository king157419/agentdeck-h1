"""Open the management panel in its own Edge app window (or the default browser).

Registry, process start, window lookup and the browser fallback are all injected so
tests never touch the real ones.
"""
from ctypes import wintypes
import ntpath
import subprocess

TITLE = "AgentDeck"
WINDOW_SIZE = "--window-size=1180,760"
APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
WM_CLOSE = 0x0010


def find_edge(registry=None, exists=None):
    """Path of msedge.exe from App Paths (HKLM first, then HKCU), or None."""
    if registry is None:
        import winreg as registry
    if exists is None:
        import os
        exists = os.path.isfile
    for root in (registry.HKEY_LOCAL_MACHINE, registry.HKEY_CURRENT_USER):
        try:
            with registry.OpenKey(root, APP_PATHS) as key:
                value, _ = registry.QueryValueEx(key, "")
        except OSError:
            continue
        if isinstance(value, str) and value.strip() and exists(value.strip('" ')):
            return value.strip('" ')
    return None


def _is_panel(window):
    return (ntpath.basename(window[1] or "").casefold() == "msedge.exe"
            and window[2] == TITLE)


def find_window(windows):
    """The already open panel window: an Edge window titled AgentDeck."""
    for window in windows.windows():
        if _is_panel(window):
            return window[0]
    return None


def close_window(windows, hwnd):
    """Request closure only if the handle still identifies the Edge panel."""
    current = windows.read(hwnd)
    if current[0] != hwnd or not _is_panel(current):
        return False
    post = windows.user.PostMessageW
    post.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    post.restype = wintypes.BOOL
    return bool(post(hwnd, WM_CLOSE, 0, 0))


def open_panel(panel, port, *, windows=None, registry=None, exists=None, popen=None, browser_open=None):
    """Raise the open panel window, else start Edge in app mode. Returns what happened."""
    if windows is not None:
        try:
            hwnd = find_window(windows)
            if hwnd is not None:
                if panel.auth.has_session():
                    if windows.activate(hwnd):
                        return "activated"
                else:
                    close_window(windows, hwnd)
        except Exception:
            pass  # fall through and open a fresh window with a fresh code
    url = panel.login_url(panel.new_login_code(), port)
    try:
        edge = find_edge(registry, exists)
    except Exception:
        edge = None
    if edge is not None:
        (popen or subprocess.Popen)([edge, "--app=" + url, WINDOW_SIZE])
        return "edge"
    if browser_open is None:
        import webbrowser
        browser_open = webbrowser.open
    browser_open(url)
    return "browser"
