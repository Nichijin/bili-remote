"""Shared subtitle validation and geometry in logical display coordinates."""
import math
import re

DEFAULT_STYLE = {"x": 50, "y": 88, "font_size": 17, "color": "#FFFFFF", "opacity": 94}


def normalize_style(value):
    value = value if isinstance(value, dict) else {}
    result = dict(DEFAULT_STYLE)
    for key, low, high in (("x", 0, 100), ("y", 0, 100), ("font_size", 10, 64), ("opacity", 10, 100)):
        number = value.get(key)
        if not isinstance(number, bool) and isinstance(number, (int, float)) and math.isfinite(number):
            result[key] = max(low, min(high, round(number)))
    color = value.get("color")
    if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        result["color"] = color.upper()
    return result


def overlay_geometry(work_area, size, x, y):
    left, top, right, bottom = work_area
    width, height = min(size[0], right - left), min(size[1], bottom - top)
    return width, height, round(left + (right - left - width) * x / 100), round(top + (bottom - top - height) * y / 100)


def overlay_position(work_area, size, left, top):
    """Inverse placement used by both live desktop and miniature drag editors."""
    x1, y1, x2, y2 = work_area
    return tuple(max(0, min(100, round((value - origin) * 100 / available))) if available > 0 else 50
                 for value, origin, available in ((left, x1, x2 - x1 - size[0]), (top, y1, y2 - y1 - size[1])))
