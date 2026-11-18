"""离线生成待机舞蹈预览：不碰串口，只跑纯 UI。输出联系表 PNG 和循环 GIF。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lcd1602"))
from PIL import Image
from ui import UI
from sim import FakeLCD
from preview import load_font, render, contact_sheet

TOOLS = (("cc", "Claude"), ("cx", "Codex"), ("ds", "DeepSeek"))
TIMES = (0, 450, 900, 1350)


def frame(tool, now, font):
    lcd = FakeLCD()
    ui = UI(lcd, lambda value: None)
    assert ui.handle("focus " + tool, 0).startswith("ok ")
    ui.render(now)
    return render(lcd.rows, lcd.glyphs, font)


def main():
    font = load_font()
    shots = [("%s idle t=%d ms" % (label, now), frame(tool, now, font))
             for tool, label in TOOLS for now in TIMES]
    png = ROOT / "lcd1602" / "preview-dance.png"
    contact_sheet(shots, columns=4).save(png)
    gif_frames = []
    for now in TIMES:
        imgs = [frame(tool, now, font) for tool, _ in TOOLS]
        w, h = imgs[0].size
        page = Image.new("RGB", (w, h * len(imgs)))
        for i, img in enumerate(imgs):
            page.paste(img, (0, i * h))
        gif_frames.append(page)
    gif = ROOT / "lcd1602" / "preview-dance.gif"
    gif_frames[0].save(gif, save_all=True, append_images=gif_frames[1:],
                       duration=450, loop=0)
    print("Wrote %s and %s" % (png, gif))


if __name__ == "__main__":
    main()
