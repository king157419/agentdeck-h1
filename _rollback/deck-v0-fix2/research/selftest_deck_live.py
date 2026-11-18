"""Assert deck actions against the real board, then restore its saved sessions.

Run manually from the project root: python research/selftest_deck_live.py
This opens the serial port. Offline checks should inject sender/windows/time.
"""
import re
import sys
import time
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pc"))
import agent_lcd  # noqa: E402
import deck  # noqa: E402
from deck_windows import WindowControl  # noqa: E402


# Four ribbon icons leave eight project-name columns: avoid marquee truncation.
SCENARIO = (
    deck.Session("cc-test1", "tool", "zz-st1"),
    deck.Session("cx-test1", "wait", "zz-cx"),
    deck.Session("ds-test1", "think", "zz-ds"),
    deck.Session("cc-test2", "idle", "zz-st2"),
)
STEPS = (
    ("tool cc", "cc-test1"),
    ("tool cc", "cc-test2"),
    ("tool cx", "cx-test1"),
    ("tool ds", "ds-test1"),
    ("cycle +1", "cc-test2"),
    ("cycle -1", "ds-test1"),
    ("next_wait", "cx-test1"),
    ("auto", "cx-test1"),
)
TOOLS = {"cc": "Claude", "cx": "Codex", "ds": "DSK"}
STATES = {"READY": "idle", "THINK": "think", "TOOL": "tool",
          "WAIT!": "wait", ">YOU<": "wait", "DONE": "done", "ERROR": "error"}


class TestWindows(WindowControl):
    def windows(self):
        # Generic Claude/Codex title fallback must not activate a real project.
        return [window for window in super().windows()
                if any(deck.daemon.title_contains(window[2], session.name)
                       for session in SCENARIO)]


def checked_send(sender, lines, **kwargs):
    """A focus ACK is required too; Controller normally sends without waiting."""
    kwargs["wait_reply"] = max(0.3, kwargs.get("wait_reply", 0.0))
    kwargs["retry_for"] = max(3.0, kwargs.get("retry_for", 0.0))  # COM4 is shared with hooks/daemon.
    reply = sender(lines, **kwargs) or ""
    if re.search(r"^err(?:\s|$)", reply, re.MULTILINE):
        raise RuntimeError(reply.replace("\n", " / "))
    for line in lines:
        parts = line.split()
        if parts[0] == "clear":
            expected = r"ok clear \d+"
        elif parts[0] == "set":
            expected = re.escape("ok set %s %s" % (parts[1], parts[2]))
        elif parts[0] == "focus":
            expected = re.escape("ok " + line)
        else:
            continue  # list and dump have their own strict parsers.
        if not re.search(r"^" + expected + r"\s*$", reply, re.MULTILINE):
            raise RuntimeError("missing acknowledgement for %s: %r" % (line, reply))
    return reply


def parse_screen(reply):
    """Return tool, project and state, ignoring sprite/ribbon animation bytes."""
    dumps = re.findall(r"^ok dump ([0-9a-fA-F]{32}) ([0-9a-fA-F]{32})(?: [^\r\n]*)?\r?$",
                       reply, re.MULTILINE)
    if len(dumps) != 1:
        raise ValueError("missing, malformed or ambiguous dump reply")
    top, bottom = (bytes.fromhex(row) for row in dumps[0])
    heading = top[3:].decode("ascii", errors="replace")
    match = re.match(r"^(Claude|Codex|DSK) (READY|THINK|TOOL|WAIT!|>YOU<|DONE|ERROR)", heading)
    if match is None:
        raise ValueError("unrecognized screen heading: %r" % heading)
    project = bottom[3:11].decode("ascii").rstrip()
    return match[1], project, STATES[match[2]]


def main(sender=None, windows=None, hold_path=None, sleep=None, monotonic=None):
    sender = agent_lcd.send if sender is None else sender
    sleep = time.sleep if sleep is None else sleep
    monotonic = time.monotonic if monotonic is None else monotonic
    hold = Path(deck.daemon.DECK_HOLD if hold_path is None else hold_path)
    send = partial(checked_send, sender)
    saved, changed, rows = None, False, []
    try:
        # Never clear the board until the entire original list is validated.
        saved = deck.parse_sessions(send(["list"], wait_reply=0.3, retry_for=0.0))
        controller = deck.Controller(TestWindows() if windows is None else windows,
                                     sender=send, hold_path=hold, sleep=sleep, monotonic=monotonic)
        hold.touch()
        changed = True  # clear may succeed even if its acknowledgement is lost.
        send(["clear"], retry_for=0.0)
        send(["focus -"], retry_for=0.0)
        for session in SCENARIO:
            send(["set %s %s %s" % session], retry_for=0.0)
        actual = deck.parse_sessions(send(["list"], wait_reply=0.3, retry_for=0.0))
        if actual != list(SCENARIO):
            raise AssertionError("scenario differs from expected: %r" % (actual,))

        for index, (action, key) in enumerate(STEPS, 1):
            expected = next(session for session in SCENARIO if session.key == key)
            target = (TOOLS[key.split("-", 1)[0]], expected.name, expected.state)
            result = controller.execute(action)
            started = monotonic()
            errors, samples = [], []
            expected_focus = "focus -" if action == "auto" else "focus " + key
            if result.split(";", 1)[0] != expected_focus:
                errors.append("action: " + result)
            for delay in (0.6, 3.0):
                sleep(max(0.0, delay - (monotonic() - started)))
                try:
                    screen = parse_screen(send(["dump"], wait_reply=0.4, retry_for=0.0))
                    samples.append("%gs=%s/%s/%s" % ((delay,) + screen))
                    # Other live sessions add ribbon icons that can truncate the name;
                    # after "auto" the daemon legitimately follows the foreground window.
                    same = (screen[0], screen[2]) == (target[0], target[2]) and \
                        screen[1][:5] == target[1][:5]
                    if action != "auto" and not same:
                        errors.append("%gs expected %s/%s/%s" % ((delay,) + target))
                except Exception as error:
                    errors.append("%gs %s" % (delay, error))
            detail = result + "; " + "; ".join(samples + errors)
            rows.append(("%d %s" % (index, action), not errors, detail))
    except (Exception, KeyboardInterrupt) as error:
        rows.append(("setup/run", False, "%s: %s" % (type(error).__name__, error)))
    finally:
        if changed:
            errors = []
            try:
                hold.touch()  # auto removed it; protect restoration from daemon.
            except OSError as error:
                errors.append("hold: " + str(error))
            commands = ["clear"] + ["set %s %s %s" % session for session in saved] + ["focus -"]
            for command in commands:
                try:
                    send([command], retry_for=0.0)
                except Exception as error:
                    errors.append("%s: %s" % (command, error))
            try:
                restored = deck.parse_sessions(send(["list"], wait_reply=0.3, retry_for=0.0))
                if restored != saved:
                    errors.append("restored list differs from saved list: %r" % (restored,))
            except Exception as error:
                errors.append("verify restoration: " + str(error))
            try:
                hold.unlink(missing_ok=True)
            except OSError as error:
                errors.append("remove hold: " + str(error))
            rows.append(("restore", not errors, "; ".join(errors) if errors else
                         "saved sessions restored; focus released; hold removed"))

    print("STEP          | STATUS | DETAILS")
    print("--------------|--------|--------")
    for label, passed, detail in rows:
        print("%-13s | %-6s | %s" % (label, "PASS" if passed else "FAIL", detail))
    failed = sum(not passed for unused, passed, detail in rows)
    print("live deck self-test: %d passed, %d failed" % (len(rows) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
