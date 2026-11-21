"""Lazy JSON-lines bridge to Claude's Windows UI Automation sidebar.

Importing this module never starts PowerShell or accesses a window. Each command
owns a bounded wait, and a failed command is never replayed (especially Invoke).
"""
import json
import logging
import math
from pathlib import Path
import queue
import subprocess
import threading


COMMAND_TIMEOUT = 5.0
# Invoke also needs process startup, expansion polling and sidebar restoration.
INVOKE_TIMEOUT = 10.0
log = logging.getLogger("agentdeck.hub.uia")


class ClaudeUIA:
    def __init__(self, *, popen=None, timeout=None):
        invoke_timeout = INVOKE_TIMEOUT if timeout is None else timeout
        timeout = COMMAND_TIMEOUT if timeout is None else timeout
        if not isinstance(timeout, (int, float)) or not 0 < timeout < float("inf"):
            raise ValueError("UIA timeout must be positive and finite")
        self._popen = subprocess.Popen if popen is None else popen
        self.timeout = timeout
        self.invoke_timeout = invoke_timeout
        self._lock = threading.Lock()
        self._process = None
        self._worker = None
        self._requests = None
        self._responses = None
        self._sequence = 0
        self._closed = False

    def list(self, hwnd=None):
        """Return current_title and ordered title/status entries, or None."""
        result = self._command("list", hwnd=hwnd)
        if result is None:
            return None
        sessions = result.get("sessions")
        if (not isinstance(result.get("current_title"), str)
                or not isinstance(sessions, list)
                or any(not isinstance(item, dict)
                       or not isinstance(item.get("title"), str)
                       or not isinstance(item.get("status"), str) for item in sessions)):
            return None
        return result

    def invoke(self, title, index=0, hwnd=None, group=None):
        """Invoke an exact sidebar title, preferring its optional project group."""
        if not isinstance(title, str) or not title.strip() or len(title) > 4096:
            raise ValueError("UIA title must be a nonempty string of at most 4096 characters")
        if type(index) is not int or index < 0:
            raise ValueError("UIA index must be a nonnegative integer")
        fields = dict(title=title, index=index)
        if group is not None:
            if not isinstance(group, str) or not group.strip() or len(group) > 4096:
                raise ValueError("UIA group must be a nonempty string of at most 4096 characters")
            fields["group"] = group
        return self._command("invoke", hwnd=hwnd, timeout=self.invoke_timeout, **fields)

    def panes(self, hwnd):
        """Validate pixel rectangles and preserve pane metadata, including chat."""
        result = self._command("panes", hwnd=hwnd)
        if result is None or not isinstance(result.get("panes"), list):
            return None
        panes = []
        for item in result["panes"]:
            rect = item.get("rect") if isinstance(item, dict) else None
            if (not isinstance(rect, list) or len(rect) != 4
                    or any(type(value) not in (int, float) or not math.isfinite(value) for value in rect)
                    or rect[2] <= rect[0] or rect[3] <= rect[1]):
                return None
            panes.append(dict(item, rect=[int(value) for value in rect]))
        return dict(result, panes=sorted(panes[:4], key=lambda item: item["rect"][0]))

    def prompt_text(self, hwnd):
        result = self._command("prompt_text", hwnd=hwnd)
        return result.get("text") if isinstance(result, dict) and isinstance(result.get("text"), str) else None

    def focus_prompt(self, hwnd):
        return self._command("focus_prompt", hwnd=hwnd)

    def click(self, name, hwnd):
        if not isinstance(name, str) or not name or len(name) > 256:
            raise ValueError("UIA button name must be a nonempty string of at most 256 characters")
        return self._command("click", hwnd=hwnd, name=name)

    def focused_editable(self, hwnd):
        result = self._command("focused_editable", hwnd=hwnd)
        return isinstance(result, dict) and result.get("editable") is True

    def _command(self, command, *, hwnd=None, timeout=None, **fields):
        if hwnd is not None and (type(hwnd) is not int or not 0 < hwnd < 2**64):
            raise ValueError("UIA hwnd must be a positive window handle")
        with self._lock:
            if self._closed:
                return None
            try:
                if self._process is None or self._process.poll() is not None:
                    self._stop()
                    self._start()
                self._sequence += 1
                request = dict(command=command, id=self._sequence, **fields)
                if hwnd is not None:
                    request["hwnd"] = hwnd
                self._requests.put(request)
                result = self._responses.get(timeout=self.timeout if timeout is None else timeout)
                if not isinstance(result, dict) or result.get("id") != request["id"]:
                    raise ValueError("invalid UIA response")
                if result.get("ok") is not True:
                    log.debug("Claude UIA %s failed: %s", command, result.get("error", "unavailable"))
                    return None
                result.pop("id", None)
                return result
            except (OSError, ValueError, queue.Empty) as error:
                log.debug("Claude UIA %s unavailable: %s", command, error)
                self._stop()
                return None

    def _start(self):
        # The script contains ASCII only: Windows PowerShell 5.1 reads a .ps1
        # without a BOM using the system ANSI encoding. All pipe data is UTF-8.
        script = str(Path(__file__).with_suffix(".ps1"))
        self._process = self._popen(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._requests, self._responses = queue.Queue(), queue.Queue()
        self._worker = threading.Thread(target=self._exchange,
                                        args=(self._process, self._requests, self._responses),
                                        name="AgentDeck Claude UIA", daemon=True)
        self._worker.start()

    @staticmethod
    def _exchange(process, requests, responses):
        # The worker owns *both* writes and reads: a blocked stdin flush must
        # time out just like a blocked UI Automation call or stdout read.
        try:
            while True:
                request = requests.get()
                if request is None:
                    return
                process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                process.stdin.flush()
                line = process.stdout.readline()
                if not line:
                    responses.put(None)
                    return
                responses.put(json.loads(line))
        except (OSError, ValueError):
            responses.put(None)
        finally:
            # A timed-out writer can finish after _stop's bounded join. Its
            # pipes still need closing once that worker eventually unblocks.
            for stream in (process.stdin, process.stdout):
                try:
                    stream.close()
                except OSError:
                    pass

    def _stop(self):
        process, worker = self._process, self._worker
        self._process = self._worker = None
        if self._requests is not None:
            self._requests.put(None)
        self._requests = self._responses = None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=0.2)
        except (OSError, subprocess.TimeoutExpired):
            pass
        if worker is not None:
            worker.join(timeout=0.2)
        # Avoid acquiring a TextIOWrapper lock held by an uninterruptible IO
        # worker. Normally killing the process has already unblocked the pipe.
        if worker is None or not worker.is_alive():
            for stream in (process.stdin, process.stdout):
                try:
                    stream.close()
                except OSError:
                    pass

    def close(self):
        with self._lock:
            self._closed = True
            self._stop()
