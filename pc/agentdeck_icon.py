"""Generate AgentDeck's original keyboard/status icon using installed Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw


def create_icon(size=256, color="#26a269"):
    """Dark rounded tile, a 3x2 key grid, one large status dot. Drawn 4x and downsampled."""
    big = size * 4
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    unit = big / 256

    def box(*coords):
        return tuple(round(value * unit) for value in coords)

    draw.rounded_rectangle(box(6, 6, 250, 250), radius=round(60 * unit), fill="#1b1e25")
    for row in range(2):
        for column in range(3):
            left, top = 40 + column * 62, 128 + row * 56
            draw.rounded_rectangle(box(left, top, left + 50, top + 44), radius=round(10 * unit),
                                   fill="#d9dde4")
    draw.ellipse(box(88, 28, 168, 108), fill=color)
    return image.resize((size, size), Image.LANCZOS)


def main():
    target = Path(__file__).with_name("agentdeck.ico")
    create_icon().save(target, format="ICO", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    print(target)


if __name__ == "__main__":
    main()
