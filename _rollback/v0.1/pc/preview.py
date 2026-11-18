"""把板子上屏幕的实际内容读回来，按像素画成图片（我看不到实物屏时用它检查画面）。

  python preview.py now out.png      画出屏上此刻的样子
  python preview.py sheet out.png    依次摆出各种状态，拼成一张总览图（会清空屏上的会话）

字符点阵取自 Adafruit GFX 的 5x7 字库（和 1602 的字库很接近，不完全一样）；
自定义图案（机器人、小图标）是从板子读回来的真实数据。
"""
import math
import os
import re
import sys
import time

from PIL import Image, ImageDraw

import agent_lcd

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_C = os.path.join(HERE, "..", "wokwi", ".pio", "libdeps", "esp32dev",
                      "Adafruit GFX Library", "glcdfont.c")
PX, GAP, CELL_GAP, PAD = 5, 1, 5, 14
BG, OFF, ON = (24, 52, 200), (34, 66, 222), (236, 244, 255)
ARROW = (0x00, 0x04, 0x02, 0x1F, 0x02, 0x04, 0x00, 0x00)     # 字库 A00 的 0x7E 是右箭头


def load_font():
    nums = re.findall(r"0x([0-9A-Fa-f]{2})", open(FONT_C, encoding="latin-1").read())
    data = [int(n, 16) for n in nums]
    font = {}
    for ch in range(32, 126):
        cols = data[ch * 5: ch * 5 + 5]
        font[ch] = tuple(sum(((cols[c] >> r) & 1) << (4 - c) for c in range(5)) for r in range(8))
    font[0x7E] = ARROW
    return font


def dump():
    for _ in range(5):
        m = re.search(r"ok dump (\S+) (\S+) (.+)", agent_lcd.send(["dump"], wait_reply=0.5))
        if m:
            g = [bytes.fromhex(x) if x != "-" else bytes(8) for x in m.group(3).split()]
            return bytes.fromhex(m.group(1)), bytes.fromhex(m.group(2)), g
        time.sleep(0.2)
    raise RuntimeError("no dump reply from the board")


def render(rows, glyphs, font):
    cw, chh = 5 * (PX + GAP), 8 * (PX + GAP)
    img = Image.new("RGB", (PAD * 2 + 16 * cw + 15 * CELL_GAP, PAD * 2 + 2 * chh + CELL_GAP), BG)
    d = ImageDraw.Draw(img)
    for r, row in enumerate(rows):
        for c, code in enumerate(row):
            bits = glyphs[code] if code < 8 else font.get(code, font[63])
            x0, y0 = PAD + c * (cw + CELL_GAP), PAD + r * (chh + CELL_GAP)
            for y in range(8):
                for x in range(5):
                    on = (bits[y] >> (4 - x)) & 1
                    d.rectangle([x0 + x * (PX + GAP), y0 + y * (PX + GAP),
                                 x0 + x * (PX + GAP) + PX - 1, y0 + y * (PX + GAP) + PX - 1],
                                fill=ON if on else OFF)
    return img


# 每个场景独立清空；硬件截图和纯软件模拟使用完全相同的命令及时间。
SHEET = [("Standby / robot asleep", ["focus -", "clear"], 0.1)]
for _tool, _label in (("cc", "Claude"), ("cx", "Codex"), ("ds", "DSK")):
    for _state, _phase, _delay in (
            ("idle", "mascot", 0.1), ("think", "bob up + spinner", 0.1),
            ("think", "bob down + spinner", 0.7), ("tool", "shake left >", 0.1),
            ("tool", "shake right arrow", 0.3), ("wait", "big ! / WAIT!", 0.1),
            ("wait", "mascot / >YOU<", 0.5), ("done", "big check", 0.1),
            ("done", "mascot + small check", 3.2), ("error", "big cross", 0.1),
            ("error", "mascot", 0.6)):
        SHEET.append(("%s %s / %s" % (_label, _state.upper(), _phase),
                      ["focus -", "clear", "set %s-demo %s h1-firmware" % (_tool, _state)], _delay))
SHEET.extend([
    ("Unknown tool / original robot", ["focus -", "clear", "set other idle project"], 0.1),
    ("Marquee / start pause", ["focus -", "clear", "set cc-long idle abcdefghijklmnopqrstuvwx"], 0.1),
    ("Marquee / moving", ["focus -", "clear", "set cc-long idle abcdefghijklmnopqrstuvwx"], 3.2),
    ("Marquee / end pause", ["focus -", "clear", "set cc-long idle abcdefghijklmnopqrstuvwx"], 6.5),
    ("8 sessions / ribbon", ["focus -", "clear", "set cc-a think app", "set cc-b tool notes",
                             "set cx-a wait webapp", "set ds-a done scraper", "set cx-b idle api",
                             "set ds-b error paper", "set cc-c think blog", "set ds-c tool docs"], 0.1),
    ("Focus Codex / another session waits", ["focus -", "clear", "set cc-a wait urgent",
                                           "set cx-a think webapp", "focus cx"], 0.1),
    ("Focus Codex / waiting ribbon blinks", ["focus -", "clear", "set cc-a wait urgent",
                                           "set cx-a think webapp", "focus cx"], 0.5),
    ("Focus DSK / no session", ["focus -", "clear", "focus ds"], 0.1),
])


def contact_sheet(shots, columns=3):
    """拼图不依赖板子，可同时供硬件预览和离线模拟使用。"""
    width, height = shots[0][1].size
    rows = math.ceil(len(shots) / columns)
    sheet = Image.new("RGB", (20 + (width + 20) * columns, 20 + (height + 34) * rows), (18, 18, 22))
    draw = ImageDraw.Draw(sheet)
    for index, (label, img) in enumerate(shots):
        x = 20 + (index % columns) * (width + 20)
        y = 14 + (index // columns) * (height + 34)
        draw.text((x, y), label, fill=(210, 210, 215))
        sheet.paste(img, (x, y + 16))
    return sheet


def main():
    mode, out = sys.argv[1], sys.argv[2]
    font = load_font()
    if mode == "now":
        r0, r1, g = dump()
        render((r0, r1), g, font).save(out)
        return
    shots = []
    for label, cmds, pause in SHEET:
        if cmds:
            agent_lcd.send(cmds, wait_reply=0.3)
        time.sleep(pause)
        r0, r1, g = dump()
        shots.append((label, render((r0, r1), g, font)))
    agent_lcd.send(["focus -", "clear"], wait_reply=0.2)
    contact_sheet(shots).save(out)


if __name__ == "__main__":
    main()
