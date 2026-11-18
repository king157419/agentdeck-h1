"""macOS desktop actions using system tools only; all subprocesses are injectable."""
import logging
import os
import subprocess
import uuid

from hub_desktop import DesktopEffects


log = logging.getLogger("agentdeck.hub.desktop.mac")
TIMEOUT = 3
PERMISSION_HINT = ("macOS: 系统设置 → 隐私与安全性 → 辅助功能 / 自动化，"
                   "允许启动 Hub 的终端或 Python 控制 System Events 和目标应用。"
                   "截图需要屏幕录制（Screen Recording），热键需要输入监控（Input Monitoring）。")
APPLICATIONS = ("Terminal", "iTerm2", "iTerm", "Visual Studio Code", "Code",
                "Cursor", "Warp", "Ghostty", "ghostty")
BUNDLE_IDENTIFIERS = ("com.apple.Terminal", "com.googlecode.iterm2", "com.microsoft.VSCode",
                      "com.microsoft.VSCodeInsiders", "com.vscodium",
                      "com.todesktop.230313mzl4w4u92", "dev.warp.Warp-Stable",
                      "dev.warp.Warp-Preview", "com.mitchellh.ghostty")
DICTATION_HINT = ('macOS dictation is unavailable: enable Dictation in System Settings > Keyboard, '
                  'set its shortcut to Control+Option+Space, and add '
                  '"dictation_shortcut": {"key_codes": [49], "modifiers": ["control", "option"]} '
                  'to ~/.agentdeck/config.json.')

# AXWindowNumber is not exposed by every app. The exact title is a conservative
# fallback: if it changes, stop owning that window rather than guessing by index.
WINDOW_HELPERS = '''on windowNumber(w)
    tell application "System Events"
        try
            set n to value of attribute "AXWindowNumber" of w
            if n is missing value then return ""
            return n as text
        on error
            return ""
        end try
    end tell
end windowNumber

on windowTitleText(w)
    tell application "System Events"
        set rawTitle to name of w
        if rawTitle is missing value then return ""
        return rawTitle as text
    end tell
end windowTitleText

on windowRow(p, w)
    tell application "System Events"
        set windowTitle to my windowTitleText(w)
        if windowTitle contains (character id 30) or windowTitle contains (character id 31) then error "unsupported control character in window title"
        return (unix id of p as text) & (character id 31) & (name of p as text) & (character id 31) & my windowNumber(w) & (character id 31) & windowTitle
    end tell
end windowRow
'''


def literal(value):
    """Quote AppleScript text without invoking a shell or accepting script input."""
    if not isinstance(value, str) or any(char in value for char in ("\0", "\x1e", "\x1f")):
        raise ValueError("unsupported control character in window text")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace(
        "\r", "\\r").replace("\n", "\\n").replace("\t", "\\t") + '"'


class MacWindowControl:
    """Window tuples contain ((pid, AXWindowNumber, fallback_title), app, title)."""

    def __init__(self, run=None):
        self.run = subprocess.run if run is None else run
        self.permission_hint_shown = False

    def failure(self, operation, error):
        log.warning("%s failed: %s", operation, error)
        if not self.permission_hint_shown:
            self.permission_hint_shown = True
            log.warning(PERMISSION_HINT)

    def command(self, args, *, input=None, env=None, timeout=TIMEOUT):
        try:
            result = self.run(args, input=input, capture_output=True, text=True,
                              encoding="utf-8", timeout=timeout, check=False,
                              **({"env": env} if env is not None else {}))
            if result.returncode:
                self.failure(args[0], (result.stderr or "command failed").strip())
                return None
            return result.stdout or ""
        except (OSError, subprocess.SubprocessError) as error:
            self.failure(args[0], error)
            return None

    def script(self, script, *, timeout=TIMEOUT):
        return self.command(["osascript", "-e", WINDOW_HELPERS + script], timeout=timeout)

    @staticmethod
    def _row(row):
        pid, app, number, title = row.split("\x1f", 3)
        # Reject record delimiters instead of allowing a title to forge a row.
        if ("\x1e" in title or "\x1f" in title or not pid.isdecimal()
                or int(pid) <= 0 or (number and not number.isdecimal())):
            raise ValueError("unsupported control character in window title")
        return ((int(pid), number, "" if number else title), app, title)

    def windows(self):
        names = "{" + ", ".join(literal(app) for app in APPLICATIONS) + "}"
        identifiers = "{" + ", ".join(literal(app) for app in BUNDLE_IDENTIFIERS) + "}"
        output = self.script('''tell application "System Events"
    set rows to {}
    repeat with p in (application processes whose background only is false)
        try
            set appID to bundle identifier of p
            if appID is missing value then
                set supported to (name of p as text) is in ''' + names + '''
            else
                set supported to (appID as text) is in ''' + identifiers + '''
            end if
            if supported then
                repeat with w in windows of p
                    try
                        set end of rows to my windowRow(p, w)
                    end try
                end repeat
            end if
        end try
    end repeat
    set AppleScript's text item delimiters to character id 30
    return rows as text
end tell''')
        if output is None:
            return []
        windows = []
        for row in output.removesuffix("\n").split("\x1e"):
            if row:
                try:
                    windows.append(self._row(row))
                except (ValueError, TypeError) as error:
                    self.failure("window enumeration", error)
        return windows

    def __call__(self, *, timeout=TIMEOUT):
        output = self.script('''tell application "System Events"
    set p to first application process whose frontmost is true
    if (count of windows of p) is 0 then return ""
    return my windowRow(p, front window of p)
end tell''', timeout=timeout)
        line = (output or "").removesuffix("\n")
        if line:
            try:
                return self._row(line)
            except (ValueError, TypeError) as error:
                self.failure("foreground window", error)
        return (None, "", "")

    @staticmethod
    def _matches(window, handle):
        _, number, title = handle
        if number:
            return "my windowNumber(" + window + ") is " + literal(number)
        return "my windowTitleText(" + window + ") is " + literal(title)

    def activate(self, handle):
        pid = int(handle[0])
        output = self.script('''tell application "System Events"
    set p to first application process whose unix id is ''' + str(pid) + '''
    set targets to {}
    repeat with w in windows of p
        if ''' + self._matches("w", handle) + ''' then set end of targets to contents of w
    end repeat
    if (count of targets) is not 1 then error "target window lost or ambiguous"
    set targetWindow to item 1 of targets
    set appName to name of p as text
    set appID to bundle identifier of p
    set frontmost of p to true
end tell
if appID is missing value or appID is "" then
    tell application appName to activate
else
    tell application id appID to activate
end if
tell application "System Events"
    perform action "AXRaise" of targetWindow
    return "ok"
end tell''')
        return output is not None and output.strip() == "ok"

    def exists(self, handle):
        # Query the pinned process directly, including hidden/titleless windows.
        output = self.script('''tell application "System Events"
    if not (exists (application process whose unix id is ''' + str(int(handle[0])) + ''')) then return "false"
    set p to first application process whose unix id is ''' + str(int(handle[0])) + '''
    set matches to 0
    repeat with w in windows of p
        if ''' + self._matches("w", handle) + ''' then set matches to matches + 1
    end repeat
    return (matches is 1) as text
end tell''')
        return output is not None and output.strip() == "true"

    def guarded(self, commands, expected):
        if not expected or not expected[0]:
            return False
        handle = expected[0]
        output = self.script('''tell application "System Events"
    set p to first application process whose frontmost is true
    if (unix id of p) is not ''' + str(int(handle[0])) + ''' then return "false"
    if (count of windows of p) is 0 then return "false"
    set matches to 0
    repeat with w in windows of p
        if ''' + self._matches("w", handle) + ''' then set matches to matches + 1
    end repeat
    if matches is not 1 then return "false"
    set w to front window of p
    if not (''' + self._matches("w", handle) + ''') then return "false"
    -- guarded input
    ''' + commands + '''
    return "true"
end tell''')
        return output is not None and output.strip() == "true"

    def send_key(self, key, expected):
        return self.guarded("key code " + str({0x1B: 53, 0x0D: 36}[key]), expected)


class MacDesktopEffects(DesktopEffects):
    """Share the v1.2 voice lifecycle; native failures log and return False."""

    def __init__(self, windows=None, *, run=None, dictation_shortcut=None, **kwargs):
        super().__init__(windows=MacWindowControl(run) if windows is None else windows,
                         **kwargs)
        self.dictation_shortcut = self._shortcut(dictation_shortcut)

    @staticmethod
    def _shortcut(shortcut):
        # Config is data, never arbitrary AppleScript or a synthetic Fn default.
        if shortcut is None:
            return None
        if not isinstance(shortcut, dict) or set(shortcut) - {"key_codes", "modifiers"}:
            raise ValueError("dictation_shortcut needs key_codes and optional modifiers")
        codes, modifiers = shortcut.get("key_codes"), shortcut.get("modifiers", [])
        if (not isinstance(codes, list) or not 1 <= len(codes) <= 4
                or any(type(code) is not int or not 0 <= code <= 127 for code in codes)
                or not isinstance(modifiers, list) or len(modifiers) != len(set(modifiers))
                or any(modifier not in ("command", "control", "option", "shift")
                       for modifier in modifiers)):
            raise ValueError("invalid dictation key_codes or modifiers")
        using = " using {" + ", ".join(modifier + " down" for modifier in modifiers) + "}" if modifiers else ""
        return "\n    delay 0.1\n    ".join("key code " + str(code) + using for code in codes)

    def _attempt(self, operation, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:
            self.windows.failure(operation, error)
            return False

    def focus(self, session, sessions):
        return self._attempt("window focus", self._focus, session, sessions)

    def _focus(self, session, sessions):
        from deck import Session, window_for_session
        target = Session(session["key"], session["state"], session["name"])
        candidates = [Session(item["key"], item["state"], item["name"]) for item in sessions]
        native = self.windows.windows()
        # Map the allowed macOS terminals/editors onto the existing title matcher.
        # No global Windows process rules or matching semantics are changed.
        windows = [(handle, "WindowsTerminal.exe", title) for handle, app, title in native]
        matched, reason = window_for_session(target, windows, candidates)
        if matched is None:
            raise RuntimeError(reason)
        window = next(window for window in native if window[0] == matched[0])
        if not self.windows.activate(window[0]):
            raise RuntimeError("could not activate the selected session window")
        deadline = self.monotonic() + 0.3
        for attempt in range(11):
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                break
            if self.windows(timeout=min(0.3, remaining))[0] == window[0]:
                return window
            remaining = deadline - self.monotonic()
            if remaining <= 0 or attempt == 10:
                break
            self.sleep(min(0.03, remaining))
        raise RuntimeError("could not activate the selected session window")

    def _voice_shortcut(self, expected):
        if self.dictation_shortcut is None:
            raise RuntimeError(DICTATION_HINT)
        if not self.windows.guarded(self.dictation_shortcut, expected):
            raise RuntimeError("foreground changed or dictation shortcut failed")

    def _close_voice(self, voice):
        foreground = self.windows()
        if foreground[0] == voice.hwnd:
            self._voice_shortcut(foreground)

    def _key(self, key, expected):
        if not self.windows.send_key(key, expected):
            raise RuntimeError("foreground changed or key input failed")

    def _paste(self, text, expected, *, submit=False):
        if self.windows.command(["pbcopy"], input=text,
                                env={**os.environ, "LC_CTYPE": "UTF-8"}) is None:
            raise RuntimeError("clipboard copy failed")
        commands = "key code 9 using command down"
        if submit:
            commands += ('''
    delay 0.08
    if not (frontmost of p) then return "false"
    if (count of windows of p) is 0 then return "false"
    set w to front window of p
    if not (''' + self.windows._matches("w", expected[0]) + ''') then return "false"
    key code 36''')
        if not self.windows.guarded(commands, expected):
            raise RuntimeError("foreground changed or paste failed")

    def interrupt(self, session, sessions):
        return self._attempt("interrupt", super().interrupt, session, sessions)

    def prompt(self, session, sessions, text):
        return self._attempt("prompt", self._prompt, session, sessions, text)

    def _prompt(self, session, sessions, text):
        if not isinstance(text, str) or not text:
            raise ValueError("prompt text must be a nonempty string")
        self._paste(text, self._focus(session, sessions), submit=True)
        return True

    def screenshot(self, session, sessions):
        return self._attempt("screenshot", self._screenshot, session, sessions)

    def _screenshot(self, session, sessions):
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        stamp = self.now().strftime("%Y%m%d-%H%M%S-%f")
        path = (self.shots_dir / (stamp + "-" + uuid.uuid4().hex[:8] + ".png")).resolve()
        if self.windows.command(["screencapture", "-x", str(path)]) is None:
            raise RuntimeError("screen capture failed")
        self._paste(str(path), self._focus(session, sessions))
        return str(path)

    def voice_down(self, session, sessions, *, on_stop=None):
        return self._attempt("voice start", super().voice_down, session, sessions, on_stop=on_stop)

    def voice_up(self):
        return self._attempt("voice stop", super().voice_up)

    def voice(self, session, sessions):
        with self._voice_commands:
            if not self.voice_down(session, sessions):
                return False
            return self.voice_up() is not False

    def close(self):
        return self._attempt("voice shutdown", super().close)
