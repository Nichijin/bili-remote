"""Draw the desktop icon and its editable SVG; Pillow is a build-time tool only."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "desktop/assets"


def draw_icon(size, compact=False):
    scale = 4
    side = size * scale
    unit = side / 512
    image = Image.new("RGBA", (side, side))
    mask = Image.new("L", (side, side))
    ImageDraw.Draw(mask).rounded_rectangle([24 * unit, 24 * unit, 488 * unit, 488 * unit], radius=112 * unit, fill=255)
    fill = Image.new("RGBA", (side, side))
    background = ImageDraw.Draw(fill)
    for y in range(side):
        amount = y / side
        color = tuple(round(a + (b - a) * amount) for a, b in zip((36, 40, 57), (13, 15, 24)))
        background.line([(0, y), (side, y)], fill=(*color, 255))
    image.paste(fill, (0, 0), mask)
    draw = ImageDraw.Draw(image)

    def line(points, color, width):
        points = [(x * unit, y * unit) for x, y in points]
        draw.line(points, fill=color, width=round(width * unit), joint="curve")
        radius = width * unit / 2
        for x, y in points:
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=color)

    def curve(start, control1, control2, end):
        points = []
        for i in range(33):
            t = i / 32
            points.append(tuple((1 - t) ** 3 * start[d] + 3 * (1 - t) ** 2 * t * control1[d] + 3 * (1 - t) * t * t * control2[d] + t ** 3 * end[d] for d in (0, 1)))
        return points

    pink, cyan = "#FB7299", "#75E1EB"
    stroke = 30 if compact else 26
    # The open corner of the screen leaves room for the wireless signal.
    screen = [(370, 274), (370, 326)]
    screen += curve((370, 326), (370, 346), (354, 362), (334, 362))
    screen += [(150, 362)]
    screen += curve((150, 362), (130, 362), (114, 346), (114, 326))
    screen += [(114, 214)]
    screen += curve((114, 214), (114, 194), (130, 178), (150, 178))
    screen += [(248, 178)]
    line(screen, pink, stroke)
    # A solid play glyph remains recognizable at 16 pixels.
    triangle = [(203, 228), (203, 310), (269, 269)]
    draw.polygon([(x * unit, y * unit) for x, y in triangle], fill="#FFFFFF")
    if not compact:
        line([(214, 404), (294, 404)], pink, 18)
        line(curve((291, 128), (356, 128), (408, 180), (408, 245)), cyan, 23)
    line(curve((291, 177), (329, 177), (359, 207), (359, 245)), cyan, 25 if compact else 23)
    dot_radius = 16 if compact else 14
    draw.ellipse([(291 - dot_radius) * unit, (245 - dot_radius) * unit, (291 + dot_radius) * unit, (245 + dot_radius) * unit], fill=cyan)
    return image.resize((size, size), Image.Resampling.LANCZOS)


SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" fill="none">
  <title>哔哩哔哩手势遥控 · 电脑端</title>
  <desc>深色圆角底，粉色视频屏幕与白色播放符号，青色无线信号。</desc>
  <defs><linearGradient id="background" x1="256" y1="0" x2="256" y2="512" gradientUnits="userSpaceOnUse"><stop stop-color="#242839"/><stop offset="1" stop-color="#0D0F18"/></linearGradient></defs>
  <rect x="24" y="24" width="464" height="464" rx="112" fill="url(#background)"/>
  <path d="M370 274V326C370 346 354 362 334 362H150C130 362 114 346 114 326V214C114 194 130 178 150 178H248" stroke="#FB7299" stroke-width="26" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M203 228V310L269 269Z" fill="white"/>
  <path d="M214 404H294" stroke="#FB7299" stroke-width="18" stroke-linecap="round"/>
  <path d="M291 128C356 128 408 180 408 245M291 177C329 177 359 207 359 245" stroke="#75E1EB" stroke-width="23" stroke-linecap="round"/>
  <circle cx="291" cy="245" r="14" fill="#75E1EB"/>
</svg>
'''


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "bili-remote.svg").write_text(SVG, encoding="utf-8")
    draw_icon(512).save(OUTPUT / "bili-remote.png")
    draw_icon(256).save(OUTPUT / "icon-preview.png")
    sizes = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
    frames = [draw_icon(size, compact=size <= 24) for size in sizes]
    frames[-1].save(OUTPUT / "bili-remote.ico", format="ICO", sizes=[(size, size) for size in sizes], append_images=frames[:-1])
    sheet = Image.new("RGB", (880, 460), "#EEF1F6")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 16)
    for row, background in enumerate(("#EEF1F6", "#131722")):
        draw.rectangle((0, row * 230, 880, (row + 1) * 230), fill=background)
        x = 26
        for size in (16, 24, 32, 48, 64, 128, 192):
            icon = draw_icon(size, compact=size <= 24)
            sheet.paste(icon, (x, row * 230 + 15 + (192 - size) // 2), icon)
            draw.text((x, row * 230 + 208), str(size) + " px", fill="#697386" if row == 0 else "#A4ADBE", font=font)
            x += max(size + 35, 80)
    sheet.save(OUTPUT / "icon-sizes.png")
    print(OUTPUT)


if __name__ == "__main__":
    main()
