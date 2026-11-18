"""只运行纯 UI，用假 LCD 生成与硬件预览相同场景的图片，不访问串口。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lcd1602"))
from ui import UI
from preview import SHEET, load_font, render, contact_sheet


class FakeLCD:
    def __init__(self):
        self.rows = [b" " * 16, b" " * 16]
        self.glyphs = [bytes(8) for _ in range(8)]

    def show(self, row, data):
        self.rows[row] = (bytes(data) + b" " * 16)[:16]

    def glyph(self, idx, rows):
        self.glyphs[idx] = bytes(rows)


def simulate():
    font, shots = load_font(), []
    for label, commands, delay in SHEET:
        lcd = FakeLCD()
        ui = UI(lcd, lambda value: None)
        for command in commands:
            reply = ui.handle(command, 0)
            assert reply and reply.startswith("ok "), (command, reply)
        ui.render(0)
        ui.render(round(delay * 1000))
        assert all(len(row) == 16 for row in lcd.rows)
        shots.append((label, render(lcd.rows, lcd.glyphs, font)))
    return contact_sheet(shots)


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "lcd1602" / "preview-sim.png"
    simulate().save(output)
    print("Rendered %d scenarios -> %s" % (len(SHEET), output))


if __name__ == "__main__":
    main()
