"""Draw Android launcher artwork and native vector/adaptive icon resources.

Pillow is needed only to export previews and legacy PNGs, never at runtime.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ARTWORK = ROOT / "android/artwork"
RESOURCES = ROOT / "android/app/src/main/res"
BACKGROUND = "#191D2B"
PATHS = [
    ("M68,51 L68,74 C68,77.866 64.866,81 61,81 L42,81 C38.134,81 35,77.866 35,74 L35,34 C35,30.134 38.134,27 42,27 L56,27", "#FB7299", 4),
    ("M47,71 L57,71", "#FB7299", 2.8),
    ("M64,25 C73.941,25 82,33.059 82,43", "#75E1EB", 3.3),
    ("M64,33 C69.523,33 74,37.477 74,43", "#75E1EB", 3.3),
]
TRIANGLE = "M45,44 L45,61 L59,52.5 Z"
DOT = "M66.3,43 A2.3,2.3 0,1 1,61.7,43 A2.3,2.3 0,1 1,66.3,43 Z"


def curve(start, first, second, end):
    return [tuple((1 - t) ** 3 * start[d] + 3 * (1 - t) ** 2 * t * first[d] + 3 * (1 - t) * t * t * second[d] + t ** 3 * end[d] for d in (0, 1)) for t in (i / 40 for i in range(41))]


def foreground(size, monochrome=False):
    unit = size * 4 / 108
    image = Image.new("RGBA", (size * 4, size * 4))
    draw = ImageDraw.Draw(image)

    def stroke(points, color, width):
        if monochrome:
            color = "white"
        points = [(x * unit, y * unit) for x, y in points]
        draw.line(points, fill=color, width=round(width * unit), joint="curve")
        radius = width * unit / 2
        for x, y in points:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)

    phone = [(68, 51), (68, 74)]
    phone += curve((68, 74), (68, 77.866), (64.866, 81), (61, 81))
    phone += [(42, 81)] + curve((42, 81), (38.134, 81), (35, 77.866), (35, 74))
    phone += [(35, 34)] + curve((35, 34), (35, 30.134), (38.134, 27), (42, 27)) + [(56, 27)]
    stroke(phone, "#FB7299", 4)
    stroke([(47, 71), (57, 71)], "#FB7299", 2.8)
    stroke(curve((64, 25), (73.941, 25), (82, 33.059), (82, 43)), "#75E1EB", 3.3)
    stroke(curve((64, 33), (69.523, 33), (74, 37.477), (74, 43)), "#75E1EB", 3.3)
    draw.polygon([(45 * unit, 44 * unit), (45 * unit, 61 * unit), (59 * unit, 52.5 * unit)], fill="white")
    draw.ellipse((61.7 * unit, 40.7 * unit, 66.3 * unit, 45.3 * unit), fill="white" if monochrome else "#75E1EB")
    return image.resize((size, size), Image.Resampling.LANCZOS)


def launcher(size, shape="squircle", themed=False):
    # Android masks a 72dp region within its 108dp adaptive layer.
    padded = foreground(size * 3, monochrome=themed)
    crop = size // 2
    glyph = padded.crop((crop, crop, crop + size * 2, crop + size * 2))
    background = Image.new("RGBA", glyph.size, "#DFE5FF" if themed else BACKGROUND)
    if themed:
        tinted = Image.new("RGBA", glyph.size, "#28334F")
        tinted.putalpha(glyph.getchannel("A"))
        glyph = tinted
    background.alpha_composite(glyph)
    mask = Image.new("L", glyph.size)
    draw = ImageDraw.Draw(mask)
    bounds = (0, 0, glyph.width - 1, glyph.height - 1)
    if shape == "circle":
        draw.ellipse(bounds, fill=255)
    else:
        draw.rounded_rectangle(bounds, radius=glyph.width * (0.22 if shape == "squircle" else 0.11), fill=255)
    background.putalpha(mask)
    return background.resize((size, size), Image.Resampling.LANCZOS)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def vector(monochrome=False):
    paths = []
    for path, color, width in PATHS:
        color = "#FFFFFF" if monochrome else color
        paths.append(f'    <path android:pathData="{path}" android:fillColor="#00000000" android:strokeColor="{color}" android:strokeWidth="{width}" android:strokeLineCap="round" android:strokeLineJoin="round" />')
    paths += [f'    <path android:pathData="{TRIANGLE}" android:fillColor="#FFFFFF" />', f'    <path android:pathData="{DOT}" android:fillColor="{"#FFFFFF" if monochrome else "#75E1EB"}" />']
    return '<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="108dp" android:height="108dp" android:viewportWidth="108" android:viewportHeight="108">\n' + "\n".join(paths) + "\n</vector>\n"


def main():
    ARTWORK.mkdir(parents=True, exist_ok=True)
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="18 18 72 72" fill="none">', '  <title>哔哩哔哩手势遥控 · 安卓端</title>', '  <desc>深色触控手机，粉色边框与白色播放符号，青色无线信号。</desc>', f'  <rect x="18" y="18" width="72" height="72" rx="16" fill="{BACKGROUND}"/>']
    svg += [f'  <path d="{path}" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>' for path, color, width in PATHS]
    svg += [f'  <path d="{TRIANGLE}" fill="white"/>', f'  <path d="{DOT}" fill="#75E1EB"/>', '</svg>\n']
    write(ARTWORK / "bili-remote-android.svg", "\n".join(svg))
    launcher(512).save(ARTWORK / "bili-remote-android.png")
    launcher(256).save(ARTWORK / "icon-preview.png")
    write(RESOURCES / "drawable/ic_launcher_foreground.xml", vector())
    write(RESOURCES / "drawable/ic_launcher_monochrome.xml", vector(monochrome=True))
    write(RESOURCES / "values/icon_colors.xml", f'<resources><color name="ic_launcher_background">{BACKGROUND}</color></resources>\n')
    for version in (26, 33):
        monochrome = '    <monochrome android:drawable="@drawable/ic_launcher_monochrome" />\n' if version == 33 else ""
        adaptive = '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n    <background android:drawable="@color/ic_launcher_background" />\n    <foreground android:drawable="@drawable/ic_launcher_foreground" />\n' + monochrome + '</adaptive-icon>\n'
        for name in ("ic_launcher", "ic_launcher_round"):
            write(RESOURCES / f"mipmap-anydpi-v{version}/{name}.xml", adaptive)
    for density, pixels in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        directory = RESOURCES / f"mipmap-{density}"
        directory.mkdir(parents=True, exist_ok=True)
        launcher(pixels).save(directory / "ic_launcher.png")
        launcher(pixels, shape="circle").save(directory / "ic_launcher_round.png")
    sheet = Image.new("RGB", (880, 330), "#EEF1F6")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 17)
    variants = [("Squircle", "squircle", False), ("Circle", "circle", False), ("Rounded square", "rounded", False), ("Android 13+ themed", "circle", True)]
    for i, (label, shape, themed) in enumerate(variants):
        icon = launcher(176, shape, themed)
        sheet.paste(icon, (22 + i * 220, 30), icon)
        draw.text((22 + i * 220, 222), label, fill="#536075", font=font)
        small = launcher(48, shape, themed)
        sheet.paste(small, (22 + i * 220, 263), small)
        draw.text((80 + i * 220, 278), "48 px", fill="#697386", font=font)
    sheet.save(ARTWORK / "icon-masks.png")
    print(ARTWORK)


if __name__ == "__main__":
    main()
