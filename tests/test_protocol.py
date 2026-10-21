import pytest
from desktop.protocol import validate


@pytest.mark.parametrize("message", [
    {"cmd": "seek", "delta": float("nan")},
    {"cmd": "seek", "delta": True},
    {"cmd": "seek", "delta": 121},
    {"cmd": "speed_start", "rate": 0},
    {"cmd": "speed_change", "rate": float("nan")},
    {"cmd": "speed_change", "rate": 5},
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
