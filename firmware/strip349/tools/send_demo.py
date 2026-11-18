#!/usr/bin/env python3
"""AgentDeck v2 (Waveshare ESP32-S3-Touch-LCD-3.49) Host Serial Demo [待实测].

Uses pyserial over ESP32-S3 native USB CDC (baudrate-independent) to exercise:
  - PING -> PONG handshake & HELLO capability query
  - 6 horizontal agent slots: RUN / ASK / DONE / ERR / IDLE / GATE
  - Bottom prompt bar: low, high (red + 2-press HINT), critical (LOCKED: use terminal)
  - Optional interactive listener for incoming touch/button KEY events

Usage:
  python tools/send_demo.py --dry-run
  python tools/send_demo.py --port COM7
  python tools/send_demo.py --port COM7 --listen
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Iterable, List, Optional, Tuple

import serial
from serial.tools import list_ports

ESPRESSIF_USB_VID = 0x303A  # ESP32-S3 native USB CDC / JTAG


# (delay_after_sec, stage_title, commands)
DEMO_STAGES: List[Tuple[float, str, List[str]]] = [
    (
        1.0,
        "1. Handshake & clean slate",
        [
            "PING",
            "HELLO",
            "CLEAR",
            "HEARTBEAT 1",
        ],
    ),
    (
        2.5,
        "2. Populate all 6 slots (RUN / ASK / DONE / ERR / IDLE / GATE)",
        [
            "SLOT 1 RUN cc-a1b2",
            "SLOT 2 ASK cx-9f04",
            "SLOT 3 DONE cursor",
            "SLOT 4 ERR gemini",
            "SLOT 5 IDLE qwen-cli",
            "SLOT 6 GATE cc-prod",
            "SELECT 2",
        ],
    ),
    (
        2.5,
        "3. Low-risk approval on Slot #2",
        [
            "HEARTBEAT 2",
            "APPROVAL 2 low n1001 pytest tests/test_hub.py -q",
        ],
    ),
    (
        2.0,
        "4. High-risk gate on Slot #6 (red bar)",
        [
            "SELECT 6",
            "HEARTBEAT 3",
            "APPROVAL 6 high n2002 git push --force origin main",
        ],
    ),
    (
        2.5,
        "5. High-risk 1st press feedback (HINT overlay)",
        [
            "APPROVAL_HINT n2002 HOLD! press again within 1.5s",
        ],
    ),
    (
        3.0,
        "6. Critical-risk request (displays LOCKED: use terminal)",
        [
            "SLOT 4 ASK gemini",
            "SELECT 4",
            "HEARTBEAT 4",
            "APPROVAL 4 critical n3003 rm -rf /srv/prod/data",
        ],
    ),
    (
        1.5,
        "7. Clear approval & show steady summary hint",
        [
            "APPROVAL_CLEAR n3003 fallback",
            "SLOT 6 RUN cc-prod",
            "SLOT 2 RUN cx-9f04",
            "HINT Demo complete - tap slots 1..6 or press BOOT/PWR",
            "STATE",
        ],
    ),
]


def detect_esp32s3_port() -> Optional[str]:
    env_port = os.environ.get("AGENTDECK_PORT")
    if env_port:
        return env_port
    ports = list(list_ports.comports())
    for p in ports:
        if p.vid == ESPRESSIF_USB_VID:
            return p.device
    return None


def drain_lines(ser: serial.Serial, duration_s: float) -> List[str]:
    """Read and print any replies or async KEY events arriving within duration_s."""
    received: List[str] = []
    deadline = time.monotonic() + max(0.05, duration_s)
    buf = b""
    while time.monotonic() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    print(f"  RX << {line}")
                    received.append(line)
        else:
            time.sleep(0.01)
    if buf.strip():
        line = buf.decode("utf-8", errors="replace").strip()
        print(f"  RX << {line}")
        received.append(line)
    return received


def send_commands(ser: serial.Serial, commands: Iterable[str], wait_each_s: float = 0.08) -> List[str]:
    replies: List[str] = []
    for cmd in commands:
        print(f"  TX >> {cmd}")
        ser.write((cmd + "\r\n").encode("utf-8"))
        ser.flush()
        replies.extend(drain_lines(ser, wait_each_s))
    return replies


def run_dry(scale: float) -> int:
    print("[DRY-RUN] Previewing AgentDeck v2 USB CDC protocol transcript (no serial port opened):")
    for pause_s, title, cmds in DEMO_STAGES:
        print(f"\n--- {title} (hold {pause_s * scale:.1f}s) ---")
        for cmd in cmds:
            print(f"  TX >> {cmd}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Send AgentDeck v2 demo sequence over USB CDC.")
    parser.add_argument("--port", help="Serial port (e.g. COM7 or /dev/ttyACM0). Auto-detects VID 0x303A if omitted.")
    parser.add_argument("--baud", type=int, default=115200, help="Nominal baudrate (ignored by native USB CDC).")
    parser.add_argument("--step-scale", type=float, default=1.0, help="Scale factor for pauses between demo stages.")
    parser.add_argument("--listen", action="store_true", help="Stay open after demo to print touch/button KEY events.")
    parser.add_argument("--dry-run", action="store_true", help="Print protocol lines without opening a serial port.")
    args = parser.parse_args(argv)

    if args.dry_run:
        return run_dry(args.step_scale)

    port = args.port or detect_esp32s3_port()
    if not port:
        print(
            "ERROR: No ESP32-S3 USB CDC port (VID 0x303A) detected. Pass --port COMx or use --dry-run.",
            file=sys.stderr,
        )
        return 2

    print(f"Opening {port} (USB CDC) ... [待实测]")
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = args.baud
    ser.timeout = 0.03
    ser.dtr = False
    ser.rts = False
    ser.open()

    try:
        drain_lines(ser, 0.15)
        for idx, (pause_s, title, cmds) in enumerate(DEMO_STAGES):
            print(f"\n=== {title} ===")
            replies = send_commands(ser, cmds)
            if idx == 0 and not any(r.startswith("PONG") for r in replies):
                print("  WARN: Did not see PONG reply yet (check firmware / USB CDC port).")
            drain_lines(ser, max(0.1, pause_s * args.step_scale))

        if args.listen:
            print("\nListening for KEY events (Ctrl+C to exit)...")
            last_hb = time.monotonic()
            hb_seq = 100
            while True:
                drain_lines(ser, 0.2)
                if time.monotonic() - last_hb >= 1.0:
                    hb_seq += 1
                    ser.write(f"HEARTBEAT {hb_seq}\r\n".encode("utf-8"))
                    ser.flush()
                    last_hb = time.monotonic()
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        ser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
