# Agent 状态屏 v0.1：这里只接硬件、累计单调时间并收发串口。
import sys
import time
import select
from machine import Pin
from lcd1602 import LCD
from ui import UI, VERSION, REINIT_MS

led = Pin(2, Pin.OUT, value=0)
lcd = LCD()
ui = UI(lcd, led.value)
poll = select.poll()
poll.register(sys.stdin, select.POLLIN)
buf = ""
overflow = False
now = 0
previous = time.ticks_ms()
last_init = 0
print("agent-lcd %s ready; commands: set end clear list ping dump focus" % VERSION)

while True:
    try:
        current = time.ticks_ms()
        now += time.ticks_diff(current, previous)
        previous = current
        # 每轮限制读入量，持续输入也不阻塞动画和过期处理。
        for _ in range(256):
            if not poll.poll(0):
                break
            char = sys.stdin.read(1)
            if char in ("\n", "\r"):
                reply = "err line too long" if overflow else ui.handle(buf, now)
                buf, overflow = "", False
                if reply:
                    print(reply)
            elif not char:
                break
            elif len(buf) < 160 and not overflow:
                buf += char
            else:
                overflow = True
        if now - last_init >= REINIT_MS:
            lcd.init()
            ui.invalidate()
            last_init = now
        ui.render(now)
    except KeyboardInterrupt:
        raise
    except Exception as error:
        buf, overflow = "", False
        print("err internal:", error)
    time.sleep_ms(40)
