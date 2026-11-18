"""Run the real USB CLI for three seconds, then request normal console shutdown."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "research" / "deck-usb-smoke.log"
RESULT = LOG.with_suffix(".json")


def main():
    if os.name != "nt":
        raise OSError("This smoke requires Windows CTRL_BREAK support")
    command = [sys.executable, str(ROOT / "pc" / "deck.py"), "run", "--backend", "usb", "-v"]
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    summary = {"command": command, "normal_exit": False, "passed": False}
    started = time.monotonic()
    with LOG.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(command, cwd=ROOT, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            time.sleep(3)
            summary["duration_seconds"] = round(time.monotonic() - started, 3)
            if process.poll() is not None:
                raise RuntimeError("deck exited before the three-second check completed")
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=5)
            summary["exit_code"] = process.returncode
            summary["normal_exit"] = process.returncode == 0
        except Exception as error:
            summary["error"] = str(error)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
                summary["forced_cleanup"] = True
            summary["exit_code"] = process.returncode
    transcript = LOG.read_text(encoding="utf-8")
    summary["zadig_hint"] = "请先用 Zadig 把 4132:2107 接口0 换成 WinUSB" in transcript
    summary["started"] = "AgentDeck started; backend=usb; exclusive=False" in transcript
    summary["action_thread_joined"] = "AgentDeck stopped; action thread joined" in transcript
    sys.path.insert(0, str(ROOT / "pc"))
    from deck import SingleInstance
    lock = SingleInstance()
    try:
        summary["lock_released"] = lock.acquire()
    finally:
        lock.close()
    summary["passed"] = all(summary.get(key, False) for key in (
        "normal_exit", "zadig_hint", "started", "action_thread_joined", "lock_released")) and (
            "forced_cleanup" not in summary and "Traceback" not in transcript)
    RESULT.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(transcript, end="")
    print(("SMOKE PASS: " if summary["passed"] else "SMOKE FAILED: ") + json.dumps(summary, ensure_ascii=False))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
