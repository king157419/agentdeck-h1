"""Open the management panel in its own Edge app window (or the default browser).

Registry, process start, window lookup and the browser fallback are all injected so
tests never touch the real ones.
"""
import ntpath
import subprocess

TITLE = "AgentDeck"
WINDOW_SIZE = "--window-size=1180,760"
APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"


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


def find_window(windows):
    """The already open panel window: an Edge window titled AgentDeck."""
    for window in windows.windows():
        hwnd, exe, title = window[0], window[1], window[2]
        if ntpath.basename(exe or "").casefold() == "msedge.exe" and (title or "").strip() == TITLE:
            return hwnd
    return None


def open_panel(panel, port, *, windows=None, registry=None, exists=None, popen=None, browser_open=None):
    """Raise the open panel window, else start Edge in app mode. Returns what happened."""
    if windows is not None and panel.auth.has_session():
        try:
            hwnd = find_window(windows)
            if hwnd is not None and windows.activate(hwnd):
                return "activated"
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
