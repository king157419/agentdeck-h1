"""Live self-test: drive deck actions against the real board and read back the screen.

No keyboard needed. Run from repo root: python research/selftest_deck_live.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pc"))
import agent_lcd  # noqa: E402
import deck  # noqa: E402
from deck_windows import WindowControl  # noqa: E402


def screen():
    reply = agent_lcd.send(["dump"], wait_reply=0.4, retry_for=0.0) or ""
    line = reply.strip().splitlines()[-1] if reply.strip() else ""
    parts = line.split()
    if len(parts) < 4:
        return "?? " + line
    rows = []
    for hexrow in parts[2:4]:
        raw = bytes.fromhex(hexrow)
        rows.append("".join(chr(b) if 32 <= b < 127 else "#" for b in raw))
    return " | ".join(rows)


def main():
    c = deck.Controller(WindowControl())
    print("list:", (agent_lcd.send(["list"], wait_reply=0.3, retry_for=0.0) or "").replace("\n", " / "))
    steps = ["slot 1", "slot 2", "slot 3", "cycle +1", "cycle +1", "cycle -1", "next_wait", "auto"]
    for action in steps:
        result = c.execute(action)
        time.sleep(0.6)
        first = screen()
        time.sleep(2.5)
        later = screen()
        flag = "" if first == later else "   <-- CHANGED after 3s"
        print("%-10s -> %-45s | now: %s | 3s: %s%s" % (action, result, first, later, flag))


if __name__ == "__main__":
    main()
