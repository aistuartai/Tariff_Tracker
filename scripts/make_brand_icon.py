"""Generate an original brand icon for Tariff Tracker (no trademarked marks).

Design: a circle split into four wedges (representing peak/off-peak/shoulder/
free time-of-use periods) with a bold "$" centered on top, representing cost
tracking across time-of-use periods.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).parent.parent / "custom_components" / "tariff_tracker" / "brand"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Four TOU-period colors: peak (warm red-orange), shoulder (amber),
# off-peak (blue), free (green).
WEDGE_COLORS = ["#E85D4B", "#F0A93B", "#3B6FE0", "#3BB273"]

FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = round(size * 0.04)
    bbox = [margin, margin, size - margin, size - margin]

    # Four equal wedges, each a different TOU period color.
    for i, color in enumerate(WEDGE_COLORS):
        start = -90 + i * 90
        end = start + 90
        draw.pieslice(bbox, start=start, end=end, fill=color)

    # Thin white spokes between wedges for separation.
    center = size / 2
    radius = center - margin
    import math

    for angle_deg in (0, 90, 180, 270):
        angle = math.radians(angle_deg - 90)
        x = center + radius * math.cos(angle)
        y = center + radius * math.sin(angle)
        draw.line([(center, center), (x, y)], fill="white", width=max(1, size // 128))

    # White dollar sign centered on top.
    font = _load_font(round(size * 0.5))
    text = "$"
    tb = draw.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    draw.text(
        (center - tw / 2 - tb[0], center - th / 2 - tb[1]),
        text,
        font=font,
        fill="white",
        stroke_width=max(1, size // 80),
        stroke_fill=(0, 0, 0, 90),
    )

    return img


for size, name in [(256, "icon.png"), (512, "icon@2x.png")]:
    draw_icon(size).save(OUT_DIR / name)
    print(f"wrote {OUT_DIR / name}")
