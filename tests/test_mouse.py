import ctypes
import pytest
from desktop.mouse import MouseController, WindowsMouse, absolute_point, INPUT, MOUSEINPUT
from desktop.protocol import validate


class FakeMouse:
    def __init__(self):
        self.calls = []
    def move(self, dx, dy):
        self.calls.append((dx, dy))
    def click(self, button):
        self.calls.append(button)


def test_session_scopes_input_and_rejects_old_mode_or_another_phone():
    backend = FakeMouse()
    mouse = MouseController(backend)
    session = mouse.execute({"cmd": "mouse_start"}, "a")["mouse_session"]
    move = {"cmd": "mouse_move", "dx": 12, "dy": -5, "mouse_session": session}
    with pytest.raises(RuntimeError):
        mouse.execute(move, "b")
    with pytest.raises(RuntimeError):
        mouse.execute({"cmd": "mouse_start"}, "b")
    mouse.execute(move, "a")
    mouse.execute({"cmd": "mouse_click", "button": "right", "mouse_session": session}, "a")
    assert backend.calls == [(12, -5), "right"]
    mouse.release("a")
    mouse.execute({"cmd": "mouse_start"}, "a")
    with pytest.raises(RuntimeError):
        mouse.execute(move, "a")
    mouse.execute({"cmd": "mouse_end", "mouse_session": session}, "a")
    assert mouse.owner == "a"  # stale teardown cannot stop the newer session


def test_idle_lease_and_heartbeat():
    clock = [0]
    mouse = MouseController(FakeMouse(), clock=lambda: clock[0])
    session = mouse.execute({"cmd": "mouse_start"}, "a")["mouse_session"]
    clock[0] = 3
    mouse.execute({"cmd": "mouse_keep", "mouse_session": session}, "a")
    clock[0] = 6
    assert not mouse.expire()
    clock[0] = 8
    assert mouse.expire() and mouse.owner is None
    with pytest.raises(RuntimeError):
        mouse.execute({"cmd": "mouse_click", "button": "left", "mouse_session": session}, "a")


@pytest.mark.parametrize("value", [True, 1.2, float("nan"), float("inf"), 8193, -8193, "2", None, {}])
def test_invalid_motion_rejected(value):
    with pytest.raises(ValueError):
        validate({"cmd": "mouse_move", "mouse_session": "a"*24, "dx": value, "dy": 1})


@pytest.mark.parametrize("message", [
    {"cmd": "mouse_click", "button": "middle", "mouse_session": "a"*24},
    {"cmd": "mouse_click", "button": {}, "mouse_session": "a"*24},
    {"cmd": "mouse_keep", "mouse_session": "z"*24},
    {"cmd": "mouse_end", "mouse_session": None},
    {"cmd": "mouse_move", "dx": 1, "dy": 1},
])
def test_invalid_mouse_fields_rejected(message):
    with pytest.raises(ValueError):
        validate(message)


def test_input_abi_and_pixel_mapping_for_negative_origin_multi_monitor():
    assert ctypes.sizeof(INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
    bounds = (-1920, -1080, 5760, 3240)
    for x, y in [(-1920, -1080), (0, 0), (3839, 2159)]:
        ax, ay = absolute_point(x, y, bounds)
        assert ax*5760//65536 - 1920 == x
        assert ay*3240//65536 - 1080 == y
    assert absolute_point(-99999, 99999, bounds) == absolute_point(-1920, 2159, bounds)


def test_click_injects_down_up_in_one_batch_and_attempts_release_on_partial_failure():
    mouse = object.__new__(WindowsMouse)
    calls = []
    def inject(*items):
        calls.append([item.dwFlags for item in items])
        if len(items) == 2:
            raise RuntimeError("partial")
    mouse.inject = inject
    with pytest.raises(RuntimeError):
        mouse.click("right")
    assert calls == [[8, 16], [16]]


def test_protocol_does_not_inherit_media_selection_for_mouse():
    assert validate({"cmd": "mouse_start", "target": "native", "session_id": "a"}) == {"cmd": "mouse_start"}
    assert validate({"cmd": "mouse_move", "dx": -3, "dy": 4, "mouse_session": "a"*24})["dx"] == -3
