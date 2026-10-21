from datetime import timedelta
from types import SimpleNamespace
import pytest
from desktop.native import NativeController


class Session:
    source_app_user_model_id = "bilibili.exe"

    def __init__(self):
        self.rate = 1.5
        self.position = timedelta(seconds=50)
        self.seek_ticks = None
        self.controls = SimpleNamespace(is_playback_rate_enabled=True, is_playback_position_enabled=True, is_play_pause_toggle_enabled=True)

    def get_playback_info(self):
        return SimpleNamespace(controls=self.controls, playback_rate=self.rate)

    def get_timeline_properties(self):
        return SimpleNamespace(position=self.position, min_seek_time=timedelta(), max_seek_time=timedelta(seconds=100))

    async def try_change_playback_rate_async(self, rate):
        self.rate = rate
        return True

    async def try_change_playback_position_async(self, ticks):
        self.seek_ticks = ticks
        return True


def controller():
    session = Session()
    native = NativeController()
    native.manager = SimpleNamespace(get_sessions=lambda: [session])
    return native, session


def cmd(command, **fields):
    return {"cmd": command, "session_id": "", **fields}


@pytest.mark.asyncio
async def test_restore_original_speed_and_ignore_other_owner():
    native, session = controller()
    await native.execute(cmd("speed_start", rate=2), "phone1")
    assert session.rate == 2
    await native.execute(cmd("speed_end"), "phone2")
    assert session.rate == 2
    await native.execute(cmd("speed_end"), "phone1")
    assert session.rate == 1.5


@pytest.mark.asyncio
async def test_second_hold_does_not_save_temporary_rate():
    native, session = controller()
    await native.execute(cmd("speed_start", rate=2), "phone1")
    await native.execute(cmd("speed_start", rate=3), "phone2")
    await native.execute(cmd("speed_end"), "phone2")
    assert session.rate == 1.5


@pytest.mark.asyncio
async def test_watchdog_restores_speed():
    native, session = controller()
    await native.execute(cmd("speed_start", rate=2), "phone")
    native.boost["deadline"] = 0
    await native.expire()
    assert session.rate == 1.5


@pytest.mark.asyncio
async def test_seek_uses_ticks_and_clamps_to_end():
    native, session = controller()
    await native.execute(cmd("seek", delta=80), "phone")
    assert session.seek_ticks == 1_000_000_000


@pytest.mark.asyncio
async def test_unavailable_speed_has_clear_error():
    native, session = controller()
    session.controls.is_playback_rate_enabled = False
    with pytest.raises(RuntimeError, match="未开放倍速"):
        await native.execute(cmd("speed_start", rate=2), "phone")
