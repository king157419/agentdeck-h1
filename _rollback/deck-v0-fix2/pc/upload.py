"""把 .py 文件传到跑 MicroPython 的板子上，然后软重启。
用法： python upload.py COM4 ..\\lcd1602\\lcd1602.py ..\\lcd1602\\ui.py ..\\lcd1602\\main.py
"""
import os
import sys
import time

import serial


def open_port(port):
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 115200, 1
    s.dtr = False  # CH340 板子：不拉 DTR/RTS，避免打开串口时把 ESP32 复位
    s.rts = False
    t0 = time.time()
    while True:                    # 上报钩子可能正好占着串口，等它一下
        try:
            s.open()
            return s
        except serial.SerialException:
            if time.time() - t0 > 5:
                raise
            time.sleep(0.1)


def read_until(s, token, timeout=8):
    data, t0 = b"", time.time()
    while token not in data and time.time() - t0 < timeout:
        data += s.read(max(1, s.in_waiting))
    return data


def raw_exec(s, code):
    s.write(code.encode() + b"\x04")
    out = read_until(s, b"\x04>")
    if not out.startswith(b"OK") or b"Traceback" in out:
        raise RuntimeError(out.decode(errors="replace"))
    return out


def main():
    port, files = sys.argv[1], sys.argv[2:]
    s = open_port(port)
    s.write(b"\r\x03\x03")          # 打断正在跑的 main.py
    time.sleep(0.3)
    s.write(b"\x01")                # 进入 raw REPL
    read_until(s, b"raw REPL; CTRL-B to exit\r\n>", 3)
    s.reset_input_buffer()
    for path in files:
        data = open(path, "rb").read()
        name = os.path.basename(path)
        raw_exec(s, "f=open(%r,'wb')" % name)
        for i in range(0, len(data), 256):
            raw_exec(s, "f.write(%r)" % data[i:i + 256])
        raw_exec(s, "f.close()")
        print("uploaded", name, len(data), "bytes")
    s.write(b"\x02")                # 退出 raw REPL
    time.sleep(0.2)
    s.write(b"\x04")                # 软重启，运行新的 main.py
    time.sleep(1.5)
    print(s.read(s.in_waiting or 1).decode(errors="replace").strip()[-300:])
    s.close()


if __name__ == "__main__":
    main()
