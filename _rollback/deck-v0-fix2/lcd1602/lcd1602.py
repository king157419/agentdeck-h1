# 1602A (HD44780) 字符屏，4 线模式，RW 接地（只写不读）。
from machine import Pin
import time


class LCD:
    def __init__(self, rs=21, e=22, d4=16, d5=17, d6=25, d7=26):
        self.rs = Pin(rs, Pin.OUT, value=0)
        self.e = Pin(e, Pin.OUT, value=0)
        self.d = [Pin(p, Pin.OUT, value=0) for p in (d4, d5, d6, d7)]
        self.shadow = [bytearray(b" " * 16), bytearray(b" " * 16)]
        self.init()

    def _nib(self, n):
        for i in range(4):
            self.d[i].value((n >> i) & 1)
        self.e.value(1)
        time.sleep_us(2)
        self.e.value(0)
        time.sleep_us(60)

    def _byte(self, v, rs):
        self.rs.value(rs)
        self._nib(v >> 4)
        self._nib(v & 15)

    def cmd(self, v):
        self._byte(v, 0)
        if v < 4:
            time.sleep_ms(2)

    def init(self):
        time.sleep_ms(50)
        self.rs.value(0)
        for ms in (5, 1, 1):          # 上电复位序列：先按 8 位模式敲三次
            self._nib(3)
            time.sleep_ms(ms)
        self._nib(2)                  # 切到 4 位模式
        self.cmd(0x28)                # 2 行，5x8 点阵
        self.cmd(0x0C)                # 开显示，不显示光标
        self.cmd(0x06)                # 写入后光标右移
        self.cmd(0x01)                # 清屏
        self.shadow = [bytearray(b" " * 16), bytearray(b" " * 16)]

    def glyph(self, idx, rows):
        """自定义字符 idx=0..7，rows=8 个字节（每个低 5 位有效）。"""
        self.cmd(0x40 | (idx << 3))
        for r in rows:
            self._byte(r, 1)
        self.cmd(0x80)

    def show(self, row, text):
        """把一整行设为 text（bytes，自动补空格到 16）。只重写变了的字符，不闪。"""
        buf = (bytes(text) + b" " * 16)[:16]
        sh = self.shadow[row]
        i = 0
        while i < 16:
            if buf[i] != sh[i]:
                self.cmd(0x80 | (0x40 * row + i))
                while i < 16 and buf[i] != sh[i]:
                    self._byte(buf[i], 1)
                    sh[i] = buf[i]
                    i += 1
            else:
                i += 1
