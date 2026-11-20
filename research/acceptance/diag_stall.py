"""Diagnostic only: run the source hub + overlay on an isolated port/home and log where the Tk loop stalls.

    D:\\conda\\miniconda3\\python.exe -X utf8 research\\acceptance\\diag_stall.py --home D:\\tmp\\iso [--app]

Writes <home>/diag_stall.jsonl:
  {"poll": [start, end]}            every Overlay._poll run (monotonic seconds)
  {"msgs": {...}, "t": ...}         window messages the overlay WNDPROC saw per 0.5 s bucket
  {"gap": s, "main_stack": [...]}   main-thread Python stack sampled while no _poll ran for > 1 s
Nothing in pc/ is modified; the patches live only in this process.
"""
import argparse
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pc"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--port", type=int, default=47891)
    parser.add_argument("--app", action="store_true", help="full tray app UI (status window) instead of bare overlay")
    args = parser.parse_args()
    home = args.home.resolve()
    (home / ".agentdeck").mkdir(parents=True, exist_ok=True)
    out = open(home / "diag_stall.jsonl", "a", encoding="utf-8", buffering=1)
    lock = threading.Lock()

    def emit(record):
        with lock:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")

    import hub_overlay
    state = {"last_poll": time.monotonic(), "in_poll": False, "msgs": {}, "bucket": time.monotonic()}
    original_poll = hub_overlay.Overlay._poll

    def poll(self):
        start = time.monotonic()
        state["in_poll"] = True
        state["last_poll"] = start
        try:
            return original_poll(self)
        finally:
            end = time.monotonic()
            state["in_poll"] = False
            emit({"poll": [round(start, 3), round(end, 3)]})

    hub_overlay.Overlay._poll = poll
    original_message = hub_overlay.NoActivateWindow._message

    def message(self, hwnd, msg, wparam, lparam):
        key = "0x%04x" % msg
        state["msgs"][key] = state["msgs"].get(key, 0) + 1
        start = time.monotonic()
        try:
            return original_message(self, hwnd, msg, wparam, lparam)
        finally:
            spent = time.monotonic() - start
            if spent > 0.5:
                emit({"slow_msg": key, "seconds": round(spent, 3), "t": round(start, 3)})

    hub_overlay.NoActivateWindow._message = message
    main_id = threading.get_ident()

    def sampler():
        while True:
            time.sleep(0.25)
            now = time.monotonic()
            if now - state["bucket"] >= 0.5:
                if state["msgs"]:
                    emit({"t": round(now, 3), "msgs": state["msgs"]})
                state["msgs"] = {}
                state["bucket"] = now
            gap = now - state["last_poll"]
            if gap > 1.0:
                frame = sys._current_frames().get(main_id)
                stack = traceback.format_stack(frame)[-6:] if frame is not None else []
                emit({"t": round(now, 3), "gap": round(gap, 2), "in_poll": state["in_poll"],
                      "main_stack": [line.strip() for line in stack]})

    threading.Thread(target=sampler, name="diag sampler", daemon=True).start()
    import hub
    argv = ["--port", str(args.port), "--home", str(home), "--overlay", "--require-nonce",
            "--backend", "none", "--no-lcd"]
    if not args.app:
        return hub.main(argv)
    import agentdeck_app
    from queue import SimpleQueue
    prefs = agentdeck_app.Preferences(home)
    keys, prompts = agentdeck_app.prepare_configs(home)

    class NoAutoStart:
        legacy = None

        def upgrade(self):
            return False

        def enabled(self):
            return False

        def set_enabled(self, enabled):
            raise RuntimeError("diagnostic instance never touches autostart")

    argv += ["--keys", str(keys), "--prompts", str(prompts)]
    return hub.main(argv, ui_factory=lambda engine: agentdeck_app.TrayApplication(
        engine, commands=SimpleQueue(), prefs=prefs, keys_path=keys, autostart=NoAutoStart()))


if __name__ == "__main__":
    raise SystemExit(main())
