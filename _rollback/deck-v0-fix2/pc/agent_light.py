"""电脑端：把 Agent 状态发给 ESP32。
用法： python agent_light.py thinking
后续接 Claude Code hooks：在 hook 里调用这个脚本即可。
"""
import sys
import serial

PORT = "COM3"


def send(state: str, port: str = PORT) -> str:
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 115200, 0.5
    s.dtr = False  # CH340 板子：打开串口时别拉 DTR/RTS，否则会把 ESP32 复位
    s.rts = False
    s.open()
    s.write((state + "\r\n").encode())
    reply = s.read(64).decode(errors="replace")
    s.close()
    return reply


if __name__ == "__main__":
    print(send(sys.argv[1] if len(sys.argv) > 1 else "idle"))
