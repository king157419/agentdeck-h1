"""Generate AgentDeck's original keyboard/status icon using installed Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw


def create_icon(size=256, color="#26a269"):
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    scale = size / 256

    def box(coords):
        return tuple(round(value * scale) for value in coords)

    draw.rounded_rectangle(box((12, 35, 244, 221)), radius=round(32 * scale), fill="#202a36")
    for row in range(2):
        for column in range(3):
            left, top = 35 + column * 62, 76 + row * 60
            draw.rounded_rectangle(box((left, top, left + 43, top + 40)),
                                   radius=max(1, round(8 * scale)), fill="#f2f5f8")
    draw.ellipse(box((163, 14, 245, 96)), fill=color, outline="#ffffff",
                 width=max(1, round(7 * scale)))
    return image


def main():
    target = Path(__file__).with_name("agentdeck.ico")
    create_icon().save(target, format="ICO", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    print(target)


if __name__ == "__main__":
    main()
