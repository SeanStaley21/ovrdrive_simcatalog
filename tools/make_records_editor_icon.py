"""Draw the Records Editor icon (a 1-2-3 podium) and write tools/records_editor.ico."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "records_editor.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]
SUPERSAMPLE = 16
CYAN = (0, 174, 239, 255)
DARK = (10, 10, 10, 255)
WHITE = (255, 255, 255, 255)
FONTS = [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\impact.ttf"]

# Each layout is (block width, first block left edge, baseline, gap, numeral scale, heights of
# places 2, 1 and 3, block colour, numeral colour); sizes are fractions of the icon size. Sizes
# up to SMALL_MAX use wider, gapless blocks and larger numerals so the digits survive.
FULL = (0.28, 0.07, 0.91, 0.015, 0.78, (0.46, 0.62, 0.34), DARK, WHITE)
SMALL = (1 / 3, 0.0, 1.0, 0.0, 1.35, (0.58, 0.80, 0.42), WHITE, DARK)
SMALL_MAX = 32


def load_font(px):
    for path in FONTS:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            continue
    return ImageFont.load_default()


# 3x5 pixel glyphs and (numeral, left, right, top) pixel extents for the 16px icon, which is
# drawn without resampling.
GLYPHS = {
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
}
TINY_SIZE = 16
TINY_BLOCKS = (("2", 0, 5, 7), ("1", 5, 11, 3), ("3", 11, 16, 9))


def draw_tiny_icon():
    im = Image.new("RGBA", (TINY_SIZE, TINY_SIZE), CYAN)
    d = ImageDraw.Draw(im)
    for numeral, x0, x1, top in TINY_BLOCKS:
        d.rectangle((x0, top, x1 - 1, TINY_SIZE - 1), fill=WHITE)
        gx = x0 + (x1 - x0 - 3) // 2
        for row, bits in enumerate(GLYPHS[numeral]):
            for col, bit in enumerate(bits):
                if bit == "1":
                    d.point((gx + col, top + 1 + row), fill=DARK)
    for x, y in ((0, 0), (TINY_SIZE - 1, 0)):
        im.putpixel((x, y), (0, 0, 0, 0))
    return im


def draw_icon(size):
    if size == TINY_SIZE:
        return draw_tiny_icon()
    big = size * SUPERSAMPLE
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    radius = 0.18 if size > SMALL_MAX else 0.12
    d.rounded_rectangle((0, 0, big - 1, big - 1), radius=round(big * radius), fill=CYAN)
    width, left, baseline, gap, numeral_scale, heights, block, ink = SMALL if size <= SMALL_MAX else FULL
    font = load_font(round(big * width * numeral_scale))
    for i, (numeral, height) in enumerate(zip("213", heights)):
        x0 = big * (left + i * width + gap)
        x1 = big * (left + (i + 1) * width - gap)
        y1 = big * baseline
        y0 = y1 - big * height
        d.rectangle((x0, y0, x1, y1), fill=block)
        d.text(((x0 + x1) / 2, y0 + big * 0.01), numeral, font=font, fill=ink, anchor="mt")
    return im.resize((size, size), Image.LANCZOS)


def main():
    images = [draw_icon(s) for s in SIZES]
    images[-1].save(OUT, format="ICO", sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
