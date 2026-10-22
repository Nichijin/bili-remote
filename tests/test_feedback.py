import pytest

from desktop.feedback import DEFAULT_STYLE, normalize_style, overlay_geometry


@pytest.mark.parametrize("value", [None, [], "invalid", {"opacity": False, "font_size": float("nan"), "x": float("inf"), "color": "red"}])
def test_invalid_saved_styles_fall_back_to_readable_defaults(value):
    assert normalize_style(value) == DEFAULT_STYLE


def test_style_bounds_and_color_are_normalized():
    style = normalize_style({"x": -100, "y": 150, "font_size": 90, "opacity": 0, "color": "#12abef"})
    assert style == {"x": 0, "y": 100, "font_size": 64, "opacity": 10, "color": "#12ABEF"}
    assert DEFAULT_STYLE["font_size"] == 17


@pytest.mark.parametrize("work_area", [(0, 0, 1920, 1040), (-1920, -200, 0, 840), (300, 500, 1100, 1100)])
@pytest.mark.parametrize("position", [(0, 0), (50, 88), (100, 100)])
def test_position_stays_in_selected_work_area_including_negative_monitors(work_area, position):
    for size in [(400, 90), (4000, 2000)]:
        width, height, x, y = overlay_geometry(work_area, size, *position)
        left, top, right, bottom = work_area
        assert left <= x <= x + width <= right
        assert top <= y <= y + height <= bottom
