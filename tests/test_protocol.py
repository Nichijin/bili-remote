import pytest
from desktop.protocol import validate


@pytest.mark.parametrize("message", [
    {"cmd": "seek", "delta": float("nan")},
    {"cmd": "seek", "delta": True},
    {"cmd": "seek", "delta": 121},
    {"cmd": "speed_start", "rate": 0},
    {"cmd": "speed_change", "rate": float("nan")},
    {"cmd": "speed_change", "rate": 5},
    {"cmd": "speed_start", "rate": 1.6},
    {"cmd": "seek_to", "position": 3},
    {"cmd": "seek_to", "position": float("nan"), "media_key": "video"},
    {"cmd": "volume", "delta": 0.5},
    {"cmd": "shell", "command": "anything"},
    {"cmd": "toggle", "target": "arbitrary-app"},
])
def test_reject_invalid_commands(message):
    with pytest.raises(ValueError):
        validate(message)


def test_valid_seek_is_normalized():
    assert validate({"cmd": "seek", "delta": -30}) == {"cmd": "seek", "target": "browser", "session_id": "", "delta": -30.0}


def test_valid_gear_change_is_normalized():
    assert validate({"cmd": "speed_change", "rate": 3})["rate"] == 3.0


@pytest.mark.parametrize("browser", ["auto", "edge", "chrome"])
def test_explicit_browser_choice_is_preserved(browser):
    assert validate({"cmd": "open_browser", "browser": browser})["browser"] == browser


@pytest.mark.parametrize("browser", ["firefox", "arbitrary.exe", {}, None])
def test_browser_choice_rejects_arbitrary_paths_and_invalid_types(browser):
    with pytest.raises(ValueError):
        validate({"cmd": "open_browser", "browser": browser})


@pytest.mark.parametrize("rate", [.5, .75, 1, 1.25, 1.5, 2, 2.25, 2.5, 2.75, 3])
def test_custom_gears_and_fractional_seeks_are_supported(rate):
    assert validate({"cmd": "speed_start", "rate": rate})["rate"] == rate
    assert validate({"cmd": "seek_to", "position": 123.375, "media_key": "video"})["position"] == 123.375
