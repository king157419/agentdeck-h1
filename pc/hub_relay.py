"""Forward hooks to the local hub; on gate failure only risky operations are denied."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

# Ordinary telemetry only needs these fields plus the capped preview text in
# _body(); dropping tool_response and cutting replies/prompts to TEXT_LIMIT keeps
# huge payloads (60 KB answers, 1 MiB tool output) far below the hub's body limit.
ORDINARY_KEYS = ("hook_event_name", "session_id", "thread_id", "conversation_id", "cwd",
                 "tool_name", "notification_type", "agentdeck_window", "agent_id",
                 "transcript_path", "session_title")  # hub reads the Claude sidebar title from these
MESSAGE_LIMIT = 300
TEXT_LIMIT = 4000            # last reply / prompt kept for the overlay preview
CONNECT_TIMEOUT = 0.1        # unknown hub state: a listening loopback port accepts in ms
LIVE_CONNECT_TIMEOUT = 0.5   # hub.json names a live process: allow a busy accept loop
ORDINARY_TIMEOUT = 2.0
LOG_LIMIT = 512 * 1024


_SURROGATE = None


def scrub_surrogates(value):
    """Replace lone UTF-16 surrogates (agents cut strings by UTF-16 units) with U+FFFD."""
    global _SURROGATE
    if isinstance(value, str):
        if _SURROGATE is None:
            import re
            _SURROGATE = re.compile("[\ud800-\udfff]")
        if _SURROGATE.search(value) is None:
            return value
        return value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    if isinstance(value, dict):
        return {scrub_surrogates(key): scrub_surrogates(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_surrogates(item) for item in value]
    return value


def tool_input_hash(tool_input):
    """Canonical SHA-256 shared with the hub (ASCII-safe, so lone surrogates hash too)."""
    return hashlib.sha256(json.dumps(tool_input, ensure_ascii=True, sort_keys=True,
                                     separators=(",", ":")).encode("ascii")).hexdigest()


def gate_denial(reason="hub unavailable or invalid response"):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "Blocked by AgentDeck gate: " + reason}}).encode("utf-8")


def _home(home):
    return Path.home() if home is None else Path(home)


def escape_log_text(value, limit):
    """Keep printable Unicode, escape controls, and cap the escaped text's length."""
    parts, length = [], 0
    for char in str(value):
        part = char if char.isprintable() else char.encode("unicode_escape").decode("ascii")
        if length + len(part) > limit:
            break
        parts.append(part)
        length += len(part)
    return "".join(parts)


def _log(home, agent, event, error):
    try:  # Best-effort diagnostics only; never change the hook's output.
        event = event if isinstance(event, dict) else {}
        def field(value, limit):
            return escape_log_text(value if value not in (None, "") else "-", limit)

        name = field(event.get("hook_event_name"), 64)
        session = event.get("session_id") or event.get("thread_id") or event.get("conversation_id")
        message = (type(error).__name__ + ": " + str(error)) if isinstance(error, BaseException) else str(error)
        message = escape_log_text(message, MESSAGE_LIMIT)
        path = _home(home) / ".agentdeck" / "relay.log"
        if path.exists() and path.stat().st_size >= LOG_LIMIT:
            os.replace(path, path.with_name("relay.log.1"))
        with open(path, "a", encoding="utf-8",
                  errors="backslashreplace") as log:
            line = "%s %s %s %s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                        field(agent, 64), name, field(session, 8), message)
            log.write(line[:400] + "\n")
    except Exception:
        pass


def _pid_alive(pid):
    if sys.platform == "win32":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: the process exists
        try:
            code = ctypes.c_uint32()
            kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def hub_status(home, port):
    """'down' when hub.json names a dead process, 'up' when alive, else 'unknown'."""
    try:
        data = json.loads((_home(home) / ".agentdeck" / "hub.json").read_text(encoding="utf-8"))
        pid = data["pid"]
        if data.get("port") != port or type(pid) is not int or pid <= 0:
            return "unknown"
    except Exception:
        return "unknown"
    try:
        return "up" if _pid_alive(pid) else "down"
    except Exception:
        return "unknown"


# Ancestors past these never own the agent's window (shell and system hosts).
NOT_AGENT_WINDOWS = {"explorer.exe", "svchost.exe", "services.exe", "wininit.exe", "winlogon.exe",
                     "sihost.exe", "userinit.exe", "runtimebroker.exe", "taskhostw.exe", "csrss.exe"}


def find_agent_window(pid=None, *, processes=None, windows=None, started=None, max_depth=12):
    """Find the nearest window-owning ancestor, stopping at unverified parent links."""
    try:
        if sys.platform != "win32" or max_depth <= 0:
            return None
        pid = os.getpid() if pid is None else pid
        if processes is None or windows is None or started is None:
            import ctypes
            from ctypes import wintypes
        if processes is None or started is None:
            kernel = ctypes.WinDLL("kernel32")
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
        if processes is None:
            class PROCESSENTRY32W(ctypes.Structure):
                _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                            ("th32ProcessID", wintypes.DWORD),
                            ("th32DefaultHeapID", ctypes.c_size_t),  # ULONG_PTR, native alignment
                            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                            ("th32ParentProcessID", wintypes.DWORD),
                            ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                            ("szExeFile", wintypes.WCHAR * 260)]

            kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
            kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
            kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
            kernel.Process32FirstW.restype = wintypes.BOOL
            kernel.Process32NextW.argtypes = kernel.Process32FirstW.argtypes
            kernel.Process32NextW.restype = wintypes.BOOL
            snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
            if snapshot is None or snapshot == ctypes.c_void_p(-1).value:
                return None
            try:
                entry = PROCESSENTRY32W()
                entry.dwSize = ctypes.sizeof(entry)
                entry_pointer = ctypes.byref(entry)
                next_process = kernel.Process32NextW
                processes = {}
                if not kernel.Process32FirstW(snapshot, entry_pointer):
                    return None
                while True:
                    processes[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
                    if not next_process(snapshot, entry_pointer):
                        break
            finally:
                kernel.CloseHandle(snapshot)
        if started is None:
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            kernel.GetProcessTimes.restype = wintypes.BOOL

            def started(process_id):
                handle = kernel.OpenProcess(0x1000, False, process_id)  # QUERY_LIMITED_INFORMATION
                if not handle:
                    return None
                try:
                    creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
                    if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time),
                                                  ctypes.byref(kernel_time), ctypes.byref(user_time)):
                        return None
                    return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
                finally:
                    kernel.CloseHandle(handle)

        if windows is None:
            user = ctypes.WinDLL("user32")
            enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            user.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
            user.EnumWindows.restype = wintypes.BOOL
            user.IsWindowVisible.argtypes = [wintypes.HWND]
            user.IsWindowVisible.restype = wintypes.BOOL
            user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
            user.GetWindow.restype = wintypes.HWND
            user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user.GetWindowTextLengthW.restype = ctypes.c_int
            user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user.GetWindowThreadProcessId.restype = wintypes.DWORD
            windows = {}

            @enum_proc
            def collect(hwnd, _):
                try:
                    if (user.IsWindowVisible(hwnd) and not user.GetWindow(hwnd, 4)  # GW_OWNER
                            and user.GetWindowTextLengthW(hwnd) > 0):
                        owner_pid = wintypes.DWORD()
                        if user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid)):
                            windows.setdefault(owner_pid.value, []).append(hwnd)
                    return True
                except Exception:
                    return False  # propagate callback failure via EnumWindows, not through ctypes

            if not user.EnumWindows(collect, 0):
                return None
            # Console agents: the console window, or the terminal that owns its
            # hidden ConPTY window (Windows Terminal sets that owner), is the
            # agent's window even when the process tree skips the terminal
            # (default-terminal handoff makes explorer.exe the shell's parent).
            console_window = ctypes.WinDLL("kernel32").GetConsoleWindow
            console_window.argtypes, console_window.restype = [], wintypes.HWND
            user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user.GetAncestor.restype = wintypes.HWND
            console = console_window()
            if console:
                root = user.GetAncestor(console, 3) or console  # GA_ROOTOWNER
                owner_pid = wintypes.DWORD()
                if (user.IsWindowVisible(root) and user.GetWindowTextLengthW(root) > 0
                        and user.GetWindowThreadProcessId(root, ctypes.byref(owner_pid))):
                    exe = processes.get(owner_pid.value, (0, ""))[1]
                    if exe.casefold() not in NOT_AGENT_WINDOWS:
                        return {"hwnd": int(root), "pid": int(owner_pid.value), "exe": exe}

        visited = {pid}
        child_started = started(pid)
        for _ in range(max_depth):
            if pid not in processes or child_started is None:
                return None
            parent = processes[pid][0]
            if not parent or parent not in processes or parent in visited:
                return None
            parent_started = started(parent)
            if parent_started is None or parent_started > child_started:
                return None  # a newer parent PID has been reused; do not follow it
            if str(processes[parent][1]).casefold() in NOT_AGENT_WINDOWS:
                return None  # the desktop shell: its File Explorer windows are not the agent
            handles = windows.get(parent)
            if handles:
                return {"hwnd": int(handles[0]), "pid": int(parent), "exe": processes[parent][1]}
            visited.add(parent)
            pid, child_started = parent, parent_started
        return None
    except Exception:
        return None


def _body(event, raw, full):
    if full:
        if raw is not None:
            window = event.get("agentdeck_window")
            if isinstance(window, dict):
                stripped = raw.lstrip()
                if stripped.startswith(b"{"):
                    entry = b'"agentdeck_window":' + json.dumps(window, ensure_ascii=True).encode("ascii")
                    comma = b"" if stripped[1:].lstrip().startswith(b"}") else b","
                    return b"{" + entry + comma + stripped[1:]
            return raw  # exact hook bytes: no re-encoding of Chinese or lone surrogates
        return json.dumps(event, ensure_ascii=True).encode("ascii")
    slim = {key: event[key] for key in ORDINARY_KEYS if key in event}
    if isinstance(event.get("message"), str):
        slim["message"] = event["message"][:MESSAGE_LIMIT]
    if isinstance(event.get("title"), str):
        slim["title"] = event["title"][:MESSAGE_LIMIT]
    name = event.get("hook_event_name")
    # The overlay shows each session's latest line: the tail is what was said last.
    if name in ("Stop", "StopFailure") and isinstance(event.get("last_assistant_message"), str):
        slim["last_assistant_message"] = event["last_assistant_message"][-TEXT_LIMIT:]
    if name == "StopFailure":
        for key, limit in (("error", 64), ("error_details", MESSAGE_LIMIT)):
            if isinstance(event.get(key), str):
                slim[key] = event[key][:limit]
    if name == "SessionEnd" and isinstance(event.get("reason"), str):
        slim["reason"] = event["reason"][:64]  # shown in /state recent_ended
    if name == "UserPromptSubmit" and isinstance(event.get("prompt"), str):
        slim["prompt"] = event["prompt"][-TEXT_LIMIT:]
    if name == "PreToolUse" and isinstance(event.get("tool_input"), dict):
        slim["tool_input"] = _tool_preview(event.get("tool_name"), event["tool_input"])
    if name in ("PostToolUse", "PostToolUseFailure") and "tool_input" in event:
        slim["tool_input_hash"] = tool_input_hash(scrub_surrogates(event["tool_input"]))
    return json.dumps(slim, ensure_ascii=True).encode("ascii")


def _tool_preview(tool_name, tool_input):
    """Only what the overlay shows: a question and its options, or a one-line summary."""
    if tool_name == "AskUserQuestion":
        questions = []
        for question in tool_input.get("questions", ())[:4] if isinstance(tool_input.get("questions"), list) else ():
            if not isinstance(question, dict):
                continue
            options = question.get("options") if isinstance(question.get("options"), list) else []
            questions.append({
                "question": str(question.get("question", ""))[:500],
                "options": [{"label": str(option.get("label", ""))[:100]}
                            for option in options[:8] if isinstance(option, dict)]})
        return {"questions": questions}
    return {key: tool_input[key][:MESSAGE_LIMIT] for key in ("command", "description", "file_path", "path")
            if isinstance(tool_input.get(key), str)}


def gate_failure(event, agent, home, reason):
    """Hub unusable: classify locally; deny only high/critical, else None (agent continues)."""
    try:
        if not isinstance(event, dict) or event.get("hook_event_name") != "PreToolUse":
            raise ValueError("not a PreToolUse event")
        tool_name = event.get("tool_name")
        if not isinstance(tool_name, str):
            raise ValueError("missing tool_name")
        from hub_risk import PROTECTED_BRANCHES, classify  # lazy: only on the failure path
        options = {}
        try:
            config = json.loads(_home(home).joinpath(
                ".agentdeck", "config.json").read_text(encoding="utf-8-sig"))
            if isinstance(config, dict):
                options = {name: config[name] for name in
                           ("production_hosts", "protected_branches", "mcp_write_tools") if name in config}
        except Exception:
            pass  # missing or unreadable config: built-in defaults
        options.setdefault("protected_branches", PROTECTED_BRANCHES)
        risk = classify(tool_name, event.get("tool_input", {}), **options)
    except Exception as error:
        _log(home, agent, event, "gate fallback classification failed: %s: %s (%s)" %
             (type(error).__name__, error, reason))
        return None
    if risk in ("high", "critical"):
        return gate_denial("hub unavailable (%s); %s-risk operation blocked" % (reason, risk))
    return None


def relay(event, agent, *, port=47800, approve_timeout=110, home=None,
          connection_factory=None, gate=False, raw=None, started=None, window_finder=None):
    """Return the original response bytes, or None without exposing errors.

    ``raw`` is the original stdin JSON (forwarded verbatim for decisions);
    ``started`` is the monotonic time the hook process began (read budget).
    """
    connection = None
    try:
        if agent not in ("cc", "cx") or not isinstance(event, dict):
            return gate_failure(event, agent, home, "invalid gate event") if gate else None
        if gate and event.get("hook_event_name") != "PreToolUse":
            return gate_failure(event, agent, home, "gate requires PreToolUse")
        approve_timeout = float(approve_timeout)
        if not math.isfinite(approve_timeout) or approve_timeout <= 0:
            return gate_failure(event, agent, home, "invalid approval timeout") if gate else None
        token = (_home(home) / ".agentdeck" / "token").read_text(encoding="utf-8").strip()
        if not token:
            return gate_failure(event, agent, home, "missing authentication token") if gate else None
        status = hub_status(home, port) if connection_factory is None else "unknown"
        if status == "down":
            return gate_failure(event, agent, home, "hub not running") if gate else None
        decision = gate or event.get("hook_event_name") == "PermissionRequest"
        window = None
        found_window = None
        window_thread = None
        if os.environ.get("AGENTDECK_NO_WINDOW") != "1":  # timing-test opt-out
            if window_finder is None and connection_factory is None:
                window_finder = find_agent_window
            if window_finder is not None:
                def lookup_window():
                    nonlocal found_window
                    try:
                        found_window = window_finder()
                    except Exception:
                        pass  # best-effort telemetry must never prevent hook forwarding

                try:
                    # Overlap every event's window lookup with cold HTTP imports/connect.
                    from threading import Thread
                    window_thread = Thread(target=lookup_window, daemon=True)
                    window_thread.start()
                except Exception:
                    window_thread = None
        if connection_factory is None:
            import http.client  # lazy: keeps the hub-down failure path fast
            connection_factory = http.client.HTTPConnection
        deadline = None if decision else time.monotonic() + ORDINARY_TIMEOUT

        def remaining():
            budget = deadline - time.monotonic()
            if budget <= 0:
                raise TimeoutError("ordinary event exceeded 2 s budget")
            return budget

        connect_timeout = LIVE_CONNECT_TIMEOUT if status == "up" else CONNECT_TIMEOUT
        if deadline is not None:
            connect_timeout = min(connect_timeout, remaining())
        connection = connection_factory("127.0.0.1", port, timeout=connect_timeout)
        connection.connect()
        if window_thread is not None:
            window_thread.join(0.25 if decision else min(0.05, remaining()))
            if not window_thread.is_alive():
                window = found_window
        if isinstance(window, dict):
            event = dict(event, agentdeck_window=window)
        body = _body(event, raw, decision)
        read_timeout = approve_timeout + 5 if decision else None
        if decision and started is not None:
            # One budget from hook start: the agent's own timeout is 120 s.
            read_timeout = max(0.5, read_timeout - max(0.0, time.monotonic() - started))
        connection_socket = connection.sock
        connection_socket.settimeout(read_timeout if decision else remaining())
        connection.request("POST", "/event?agent=" + agent + ("&gate=1" if gate else ""), body=body,
                           headers={"Content-Type": "application/json",
                                    "X-AgentDeck-Token": token})
        connection_socket.settimeout(read_timeout if decision else remaining())
        response = connection.getresponse()
        connection_socket.settimeout(read_timeout if decision else remaining())
        raw_response = response.read()
        if response.status != 200:
            try:
                decoded = json.loads(raw_response)
                error = decoded.get("error", "") if isinstance(decoded, dict) else ""
            except (ValueError, TypeError):
                error = ""
            _log(home, agent, event, "hub status %s: %s" % (response.status,
                 str(error).replace("\r", " ").replace("\n", " ")[:100]))
            return gate_failure(event, agent, home, "bad hub response") if gate else None
        decoded = json.loads(raw_response)
        if not isinstance(decoded, dict):
            return gate_failure(event, agent, home, "bad hub response") if gate else None
        if gate and decoded != {}:
            output = decoded.get("hookSpecificOutput")
            if (set(decoded) != {"hookSpecificOutput"} or not isinstance(output, dict)
                    or set(output) != {"hookEventName", "permissionDecision", "permissionDecisionReason"}
                    or output.get("hookEventName") != "PreToolUse"
                    or output.get("permissionDecision") != "deny"
                    or not isinstance(output.get("permissionDecisionReason"), str)):
                return gate_failure(event, agent, home, "bad hub response")
        return raw_response
    except Exception as error:
        _log(home, agent, event, error)
        return gate_failure(event, agent, home, "hub not reachable") if gate else None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def main(argv=None, *, stdin=None, stdout=None):
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("cc", "cx"), required=True)
    parser.add_argument("--port", type=int, default=47800)
    parser.add_argument("--approve-timeout", type=float, default=110)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--gate", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # argparse exits 2, which Claude Code treats as a blocking hook error.
        # A broken hook command must never block the agent.
        return 0
    try:
        source = sys.stdin if stdin is None else stdin
        # Hooks send UTF-8; the console code page (cp1252/GBK) would corrupt Chinese text.
        data = source.buffer.read() if hasattr(source, "buffer") else source.read()
        if isinstance(data, str):
            data = data.encode("utf-8", "surrogatepass")
        if data.startswith(b"\xef\xbb\xbf"):
            data = data[3:]
        if not data.strip():
            return 0  # empty stdin: a launch probe (doctor), nothing to relay
        event = json.loads(data.decode("utf-8", "surrogatepass"))
        result = relay(event, args.agent, port=args.port,
                       approve_timeout=args.approve_timeout, home=args.home, gate=args.gate,
                       raw=data, started=started)
    except Exception as error:
        result = None  # unparseable input: cannot classify, do not block
        _log(args.home, args.agent, None, error)
    try:
        if result is not None:
            output = sys.stdout if stdout is None else stdout
            if hasattr(output, "buffer"):
                output.buffer.write(result)
                output.buffer.flush()
            else:
                output.write(result.decode("utf-8"))
                output.flush()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
