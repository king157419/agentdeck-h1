"""AgentDeck v0: USB keyboard input with a Windows Raw Input fallback."""
import argparse
import json
import logging
import logging.handlers
import ntpath
from pathlib import Path
import queue
import re
import signal
import socket
import subprocess
import sys
import threading
from typing import NamedTuple

import agent_lcd
import daemon

LOCK_PORT = 47614
DEFAULT_MAP = Path(__file__).with_name("deck_map.json")
log = logging.getLogger("agent_deck")
MODIFIERS = ("ctrl", "shift", "alt", "win")


class Session(NamedTuple):
    key: str
    state: str
    name: str


def parse_sessions(reply):
    headers = re.findall(r"^ok list n=(\d+)\s*$", reply, re.MULTILINE)
    if len(headers) != 1:
        raise ValueError("missing or ambiguous list reply")
    sessions = [Session(*parts) for parts in daemon.parse_sessions(reply, include_state=True)]
    if len(sessions) != int(headers[0]) or len(sessions) > 8:
        raise ValueError("incomplete list reply")
    if len({s.key for s in sessions}) != len(sessions) or any(
            not re.fullmatch(r"[A-Za-z0-9_-]+", s.key) for s in sessions):
        raise ValueError("invalid or duplicate session key")
    return sessions


def parse_action(text):
    if not isinstance(text, str):
        raise ValueError("action must be text")
    parts = text.split()
    if parts in (["next_wait"], ["approve"], ["deny"], ["auto"]):
        return parts[0], None
    if len(parts) == 2 and parts[0] == "slot" and parts[1] in tuple(map(str, range(1, 9))):
        return "slot", int(parts[1])
    if len(parts) == 2 and parts[0] == "cycle" and parts[1] in ("+1", "-1"):
        return "cycle", int(parts[1])
    raise ValueError("invalid action: %r" % text)


def normalize_key(text):
    if not isinstance(text, str):
        raise ValueError("mapping key must be text")
    text = text.strip().lower()
    if "+" in text and not text.startswith("wheel:"):
        *modifiers, key = text.split("+")
        if (not modifiers or len(set(modifiers)) != len(modifiers)
                or any(modifier not in MODIFIERS for modifier in modifiers)):
            raise ValueError("invalid modifiers: %r" % text)
        key = normalize_key(key)
        if not key.startswith(("vk:", "scan:", "hid:")):
            raise ValueError("modifiers require a keyboard binding: %r" % text)
        return "+".join(modifier for modifier in MODIFIERS if modifier in modifiers) + "+" + key
    if text in ("wheel:+1", "wheel:-1"):
        return text
    match = re.fullmatch(r"(vk|hid|consumer):0x([0-9a-f]{1,4})", text)
    if match:
        kind, digits = match.groups()
        value = int(digits, 16)
        if ((kind == "vk" and 1 <= value <= 254) or (kind == "hid" and 4 <= value <= 255)
                or (kind == "consumer" and 1 <= value <= 65535)):
            return "%s:0x%0*X" % (kind, 4 if kind == "consumer" else 2, value)
    match = re.fullmatch(r"scan:0x([0-9a-f]{1,4}):([0246])", text)
    if match:
        return "scan:0x%04X:%s" % (int(match[1], 16), match[2])
    raise ValueError("invalid mapping key: %r" % text)


def load_map(path=DEFAULT_MAP, backend="usb"):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result

    data = json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("bindings"), dict):
        raise ValueError("expected version 1 and bindings object")
    source = data.get("_rawinput_bindings", data["bindings"]) if backend == "rawinput" else data["bindings"]
    if not isinstance(source, dict):
        raise ValueError("expected bindings object for " + backend)
    bindings = {}
    for key, action in source.items():
        key = normalize_key(key)
        if key in bindings:
            raise ValueError("duplicate normalized key: " + key)
        parse_action(action)
        bindings[key] = action
    return bindings


def match_session(window, sessions):
    """安全门：只在终端/编辑器中匹配唯一会话；同项目多会话时拒绝猜测。"""
    hwnd, process, title = window
    if not hwnd or ntpath.basename(process).casefold() not in daemon.TITLE_PROCESSES:
        return None
    return match_title(title, sessions)


def match_title(title, sessions):
    text = title.casefold()
    matches = [s for s in sessions if daemon.title_contains(title, s.name)]
    if matches:
        longest = max(len(s.name) for s in matches)
        matches = [s for s in matches if len(s.name) == longest]
    tools = {target for word, target in daemon.TITLE_TARGETS if daemon.title_contains(text, word)}
    if len(tools) > 1:
        return None
    if not matches:
        matches = [s for s in sessions if s.key.split("-", 1)[0] in tools]
    elif tools:
        matches = [s for s in matches if s.key.split("-", 1)[0] in tools]
    return matches[0] if len(matches) == 1 else None


def select_session(sessions, action, current=None):
    command, argument = parse_action(action)
    if command == "slot":
        return sessions[argument - 1] if argument <= len(sessions) else None
    if not sessions:
        return None
    keys = [s.key for s in sessions]
    if command == "cycle":
        index = keys.index(current) if current in keys else (-1 if argument == 1 else 0)
        return sessions[(index + argument) % len(sessions)]
    if command == "next_wait":
        index = keys.index(current) if current in keys else -1
        return next((sessions[(index + step) % len(sessions)] for step in range(1, len(sessions) + 1)
                     if sessions[(index + step) % len(sessions)].state == "wait"), None)
    return None


def find_window(session, windows, sessions):
    # 优先精确项目匹配；次选工具标题。后一种只用于拉前台，不绕过审批安全门。
    allowed = daemon.TITLE_PROCESSES | daemon.PROCESS_TARGETS.keys()
    candidates = [w for w in windows if ntpath.basename(w[1]).casefold() in allowed]
    by_project = [w for w in candidates if daemon.title_contains(w[2], session.name)
                  and match_title(w[2], sessions) == session]
    if by_project:
        return by_project[0]
    words = [word for word, target in daemon.TITLE_TARGETS if session.key.startswith(target + "-")]
    return next((w for w in candidates if any(daemon.title_contains(w[2], word) for word in words)
                 and match_title(w[2], sessions) in (None, session)), None)


class Controller:
    def __init__(self, windows, sender=None):
        self.windows = windows
        self.sender = agent_lcd.send if sender is None else sender
        self.selected = None

    def execute(self, action):
        try:
            result = self._execute(action)
        except Exception as error:
            result = "blocked: %s" % error
        log.debug("%s -> %s", action, result)
        return result

    def _execute(self, action):
        command, unused = parse_action(action)
        if command == "auto":
            self.sender(["focus -"], retry_for=0.0)
            Path(daemon.DECK_HOLD).unlink(missing_ok=True)
            self.selected = None
            return "focus -"
        before = self.windows()
        sessions = parse_sessions(self.sender(["list"], wait_reply=0.3, retry_for=0.0))
        foreground = match_session(before, sessions)
        if command in ("approve", "deny"):
            if foreground is None or foreground.state != "wait":
                return "blocked: foreground is not a unique waiting agent session"
            if self.windows() != before:
                return "blocked: foreground changed during list query"
            key = 0x0D if command == "approve" else 0x1B
            return ("sent %s to %s" % ("Enter" if key == 0x0D else "Esc", foreground.key)
                    if self.windows.send_key(key, before) else "blocked: SendInput or foreground guard failed")
        current = self.selected if any(s.key == self.selected for s in sessions) else (
            foreground.key if foreground else None)
        session = select_session(sessions, action, current)
        if session is None:
            return "no matching session"
        self.sender(["focus " + session.key], retry_for=0.0)
        Path(daemon.DECK_HOLD).touch()
        self.selected = session.key
        window = find_window(session, self.windows.windows(), sessions)
        if window is None:
            return "focus %s; no matching window" % session.key
        active = self.windows.activate(window[0])
        return "focus %s; foreground %s" % (session.key, "ok" if active else "denied by Windows")


class SingleInstance:
    def __init__(self):
        self.socket = None

    def acquire(self):
        if self.socket is not None:
            return True
        lock = socket.socket()
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                lock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            lock.bind(("127.0.0.1", LOCK_PORT))
        except OSError:
            lock.close()
            return False
        self.socket = lock
        return True

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None


def ensure_running():
    lock = SingleInstance()
    if not lock.acquire():
        return False
    lock.close()
    pyw = Path(sys.executable).with_name("pythonw.exe")
    command = [str(pyw if pyw.exists() else sys.executable), str(Path(__file__).resolve()), "run"]
    subprocess.Popen(command, creationflags=0x00000008 | 0x00000200 | 0x08000000,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True)
    return True


def learn_event(event):
    if event.get("down") is False or event.get("modifier"):
        return
    print("%s %s" % (" / ".join(event["keys"]),
                       " ".join("%s=%s" % item for item in event.items() if item[0] != "keys")), flush=True)


class ActionQueue:
    """Only enqueue on the input thread; actions and logging run separately."""

    def __init__(self, bindings, controller):
        self.bindings, self.controller = bindings, controller
        self.events = queue.SimpleQueue()
        self.thread = threading.Thread(target=self._run, name="AgentDeck actions")

    def _run(self):
        while True:
            event = self.events.get()
            if event is None:
                return
            try:
                if event.get("kind") == "hook":
                    # Do not turn ordinary main-keyboard activity into a key log.
                    if event["decision"] in ("installed", "uninstalled", "suppressed", "injected", "error"):
                        log.debug("hook %s %s", event["decision"], event["keys"])
                    continue
                if event.get("down") is False or (event.get("modifier") and "usage" in event):
                    continue
                action = next((self.bindings[key] for key in event["keys"] if key in self.bindings), None)
                if action:
                    self.controller.execute(action)
                else:
                    log.debug("unbound %s", event["keys"])
            except Exception:
                log.exception("AgentDeck action failed")

    def close(self):
        self.events.put(None)
        self.thread.join()


def select_backend(callback, backend="auto", exclusive=False):
    if backend not in ("auto", "usb", "rawinput"):
        raise ValueError("invalid backend: " + backend)
    if backend != "rawinput":
        from deck_usb import USBInput
        receiver = USBInput(callback)
        if backend == "usb":
            return "usb", receiver
        try:
            receiver.open()
        except (ImportError, OSError, NotImplementedError, RuntimeError, ValueError) as error:
            receiver.close()
            log.warning("USB unavailable: %s", error)
        else:
            log.info("USB interface 0 opened; using usb backend")
            return "usb", receiver
    from deck_input import RawInput
    log.warning("Raw Input 只观察输入，不隔离系统键盘事件：宏键盘按键会漏到窗口")
    if exclusive:
        log.warning("--exclusive is experimental: the low-level hook precedes WM_INPUT; suppression is ineffective")
    return "rawinput", RawInput(callback, exclusive=exclusive)


def run(mapping=DEFAULT_MAP, exclusive=False, backend="auto"):
    lock = SingleInstance()
    if not lock.acquire():
        log.info("AgentDeck is already running (port %d)", LOCK_PORT)
        return 0
    receiver = None
    try:
        from deck_windows import WindowControl
        bindings = load_map(mapping)
        raw_bindings = load_map(mapping, backend="rawinput")
        controller = Controller(WindowControl())
        actions = ActionQueue(bindings, controller)
        selected, receiver = select_backend(actions.events.put, backend, exclusive)
        if selected == "rawinput":
            actions.bindings = raw_bindings
        actions.thread.start()
        try:
            log.info("AgentDeck started; backend=%s; exclusive=%s; map=%s",
                     selected, exclusive and selected == "rawinput", mapping)
            receiver.run()
        finally:
            actions.close()
            log.info("AgentDeck stopped; action thread joined")
    finally:
        try:
            if receiver is not None and hasattr(receiver, "close"):
                receiver.close()
        finally:
            lock.close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-v", action="store_true", dest="global_verbose")
    commands = parser.add_subparsers(dest="mode", required=True)
    for name in ("probe", "learn", "run"):
        child = commands.add_parser(name)
        child.add_argument("-v", action="store_true")
        if name == "run":
            child.add_argument("--map", default=DEFAULT_MAP, type=Path)
            exclusive = child.add_mutually_exclusive_group()
            exclusive.add_argument("--exclusive", action="store_true", help="enable the ineffective experimental Raw Input hook")
            exclusive.add_argument("--no-exclusive", dest="exclusive", action="store_false",
                                   help="disable the experimental hook (default)")
            child.set_defaults(exclusive=False)
        if name in ("run", "learn"):
            child.add_argument("--backend", choices=("auto", "usb", "rawinput"), default="auto")
        if name == "probe":
            child.add_argument("--rows", type=int)
            child.add_argument("--cols", type=int)
            child.add_argument("--definition", type=Path)
    args = parser.parse_args(argv)
    verbose = args.v or args.global_verbose
    handler = logging.StreamHandler() if verbose or args.mode != "run" else logging.handlers.RotatingFileHandler(
        Path(__file__).with_name("deck.log"), maxBytes=200_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.DEBUG if verbose or args.mode == "run" else logging.INFO,
                        format="%(asctime)s %(name)s %(message)s", handlers=[handler])
    # Windows CTRL_BREAK lets a supervising console request the same cleanup as Ctrl+C.
    previous_break = None
    if hasattr(signal, "SIGBREAK") and threading.current_thread() is threading.main_thread():
        previous_break = signal.signal(signal.SIGBREAK, signal.default_int_handler)
    try:
        if args.mode == "probe":
            from deck_probe import probe
            return probe(rows=args.rows, cols=args.cols, definition=args.definition) or 0
        if args.mode == "learn":
            print("Observe VID_4132&PID_2107 only; press each key/turn knob. Ctrl+C to stop.", flush=True)
            unused, receiver = select_backend(learn_event, args.backend)
            try:
                receiver.run()
            finally:
                if hasattr(receiver, "close"):
                    receiver.close()
            return 0
        return run(args.map, exclusive=args.exclusive, backend=args.backend)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        log.error("%s", error)
        return 1
    finally:
        if previous_break is not None:
            signal.signal(signal.SIGBREAK, previous_break)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
