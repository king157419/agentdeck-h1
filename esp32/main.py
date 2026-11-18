# Agent 状态灯 v0：从串口（USB）读一行状态名，显示对应图标。
# 电脑端发送：idle / thinking / tool / waiting / done / error
import sys, time, select
from machine import Pin
from max7219 import Matrix

led = Pin(2, Pin.OUT)
m = Matrix()

# 每个状态 = 若干帧（每帧 8 字节）+ 帧间隔(ms) + 板载 LED 闪法(亮ms, 灭ms)
B = lambda *r: bytes(r)
STATES = {
    "idle":     ([B(0x00, 0x00, 0x66, 0x66, 0x00, 0x42, 0x3C, 0x00),   # 笑脸
                  B(0x00, 0x00, 0x00, 0x66, 0x00, 0x42, 0x3C, 0x00)],  # 眨眼
                 [2500, 150], (50, 2950)),
    "thinking": ([B(0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xC0, 0xC0),
                  B(0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xD8, 0xD8),
                  B(0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xDB, 0xDB),
                  B(0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)],  # 三个点依次出现
                 [250], (100, 300)),
    "tool":     ([B(0x18, 0x7E, 0x66, 0xC3, 0xC3, 0x66, 0x7E, 0x18),   # 齿轮两帧
                  B(0x99, 0x7E, 0x42, 0x42, 0x42, 0x42, 0x7E, 0x99)],
                 [200], (60, 60)),
    "waiting":  ([B(0x3C, 0x66, 0x06, 0x0C, 0x18, 0x18, 0x00, 0x18),   # 问号，闪烁求关注
                  B(0x00) * 8],
                 [500], (500, 500)),
    "done":     ([B(0x00, 0x01, 0x03, 0x06, 0x8C, 0xD8, 0x70, 0x20)],  # 对勾
                 [1000], (1000, 0)),
    "error":    ([B(0xC3, 0x66, 0x3C, 0x18, 0x18, 0x3C, 0x66, 0xC3),   # 叉
                  B(0x00) * 8],
                 [300], (150, 150)),
}

state = "idle"
fi = 0
t_frame = t_led = time.ticks_ms()
led_on = False
poll = select.poll()
poll.register(sys.stdin, select.POLLIN)
buf = ""
print("agent-light ready; states:", " ".join(STATES))

while True:
    # 1) 非阻塞读串口
    while poll.poll(0):
        ch = sys.stdin.read(1)
        if ch in "\r\n":
            cmd = buf.strip().lower(); buf = ""
            if cmd in STATES:
                state, fi = cmd, 0
                t_frame = 0
                print("ok", state)
            elif cmd:
                print("unknown", cmd)
        else:
            buf += ch
    frames, delays, (on_ms, off_ms) = STATES[state]
    now = time.ticks_ms()
    # 2) 点阵动画
    d = delays[fi % len(delays)]
    if t_frame == 0 or time.ticks_diff(now, t_frame) >= d:
        m.show(frames[fi % len(frames)])
        fi += 1
        t_frame = now
    # 3) 板载 LED 闪法（没接屏也能看出状态）
    if time.ticks_diff(now, t_led) >= (on_ms if led_on else off_ms):
        led_on = not led_on if off_ms else True
        led.value(led_on)
        t_led = now
    time.sleep_ms(10)
