# 最小 MAX7219 8x8 驱动（单块）。接线：DIN=GPIO23, CLK=GPIO18, CS=GPIO5, VCC=5V(VIN), GND=GND
from machine import Pin, SPI


class Matrix:
    def __init__(self, sck=18, mosi=23, cs=5, brightness=3):
        self.spi = SPI(2, baudrate=1_000_000, polarity=0, phase=0, sck=Pin(sck), mosi=Pin(mosi))
        self.cs = Pin(cs, Pin.OUT, value=1)
        for reg, val in ((0x0F, 0), (0x0C, 1), (0x0B, 7), (0x09, 0), (0x0A, brightness)):
            self._w(reg, val)  # 关测试模式 / 开机 / 扫 8 行 / 不解码 / 亮度
        self.clear()

    def _w(self, reg, val):
        self.cs(0)
        self.spi.write(bytes((reg, val)))
        self.cs(1)

    def show(self, rows):
        """rows: 8 个字节，每字节一行，最高位在最左。"""
        for i, r in enumerate(rows):
            self._w(i + 1, r)

    def clear(self):
        self.show(b"\x00" * 8)

    def brightness(self, v):
        self._w(0x0A, max(0, min(15, v)))
