"""Replay real factory key reports through USB decode -> bindings -> action queue -> board.

Covers everything except the physical libusb read. Run: python research/selftest_deck_replay.py
"""
import sys
import time
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pc"))
import agent_lcd  # noqa: E402
import deck  # noqa: E402
import deck_usb  # noqa: E402
from selftest_deck_live import SCENARIO, TOOLS, TestWindows, checked_send, parse_screen  # noqa: E402

CTRL = 0x01
UP = bytes(8)


def rep(mod=0, *keys):
    return bytes([mod, 0] + list(keys) + [0] * (6 - len(keys)))


# (label, reports, expected session key or None for "no screen change expected")
CASES = [
    ("E key (tool cc)", [rep(0, 0x08), UP], "cc-test1"),
    ("E again (next Claude)", [rep(0, 0x08), UP], "cc-test2"),
    ("B key (tool cx)", [rep(0, 0x05), UP], "cx-test1"),
    ("Ctrl+Z (tool ds)", [rep(CTRL), rep(CTRL, 0x1D), rep(CTRL), UP], "ds-test1"),
    ("knob4 ] x1", [rep(0, 0x30), UP], "cc-test2"),
    ("knob4 [ x1", [rep(0, 0x2F), UP], "ds-test1"),
    ("knob1 S,S fast (+2 from ds)", [rep(0, 0x16), UP, rep(0, 0x16), UP], "cc-test1"),
    ("Space (next_wait)", [rep(0, 0x2C), UP], "cx-test1"),
    ("unbound M", [rep(0, 0x10), UP], "cx-test1"),
    ("Ctrl+Z then held Ctrl + knob1 F => cycle -1",
     [rep(CTRL), rep(CTRL, 0x1D), rep(CTRL), rep(CTRL, 0x09), rep(CTRL), UP], "cx-test1"),
]


def main():
    send = partial(checked_send, agent_lcd.send)
    hold = Path(deck.daemon.DECK_HOLD)
    rows, saved = [], None
    controller = deck.Controller(TestWindows(), sender=send, hold_path=hold)
    actions = deck.ActionQueue(deck.load_map(), controller)
    actions.thread.start()
    state = deck_usb.ReportState()
    try:
        saved = deck.parse_sessions(send(["list"], wait_reply=0.3, retry_for=0.0))
        hold.touch()
        send(["clear"]); send(["focus -"])
        for s in SCENARIO:
            send(["set %s %s %s" % s])
        for label, reports, key in CASES:
            for r in reports:
                for ev in state.feed(r):
                    ev.update({"hwnd": 0, "t": time.monotonic()})
                    actions.enqueue(ev)
                time.sleep(0.03)
            actions.events.join()
            time.sleep(0.8)
            exp = next(s for s in SCENARIO if s.key == key)
            target = (TOOLS[key[:2]], exp.name, exp.state)
            got = parse_screen(send(["dump"], wait_reply=0.4))
            ok = got[0] == target[0] and got[2] == target[2] and got[1][:5] == target[1][:5]
            rows.append((label, ok, "screen=%s/%s/%s expected=%s/%s/%s" % (got + target)))
    except Exception as error:
        rows.append(("run", False, "%s: %s" % (type(error).__name__, error)))
    finally:
        actions.close()
        if saved is not None:
            hold.touch()
            for cmd in ["clear"] + ["set %s %s %s" % s for s in saved] + ["focus -"]:
                try:
                    send([cmd])
                except Exception as error:
                    rows.append(("restore " + cmd, False, str(error)))
        hold.unlink(missing_ok=True)
    for label, ok, detail in rows:
        print("%-42s %s  %s" % (label, "PASS" if ok else "FAIL", detail))
    failed = sum(not ok for _, ok, _ in rows)
    print("replay self-test: %d passed, %d failed" % (len(rows) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
