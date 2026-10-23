"""Regression: ordinary browser discovery, no background hijack, and target identity."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from desktop.browser import BrowserController, BrowserManager
from desktop.native import NativeController
from desktop.server import Relay
from desktop.targets import NativeRoute, browser_name
from desktop.trust import TrustStore
from tests.test_native import Session


@pytest.fixture
def context(monkeypatch):
    value = {"foreground": None, "windows": []}
    monkeypatch.setattr("desktop.server.browser_windows", lambda: value)
    return value


def manager_with_page(browser="msedge.exe", pid=100, visible=False, playing=False):
    controller = SimpleNamespace(executable=Path(browser), browser_process=SimpleNamespace(pid=pid), page_hint=None)
    manager = BrowserManager()
    manager.candidates = AsyncMock(return_value=[{"controller": controller, "page": {"id": "page-1"}, "visible": visible, "playing": playing}])
    return manager, controller


def relay(tmp_path, manager, sessions):
    native = SimpleNamespace(discover=AsyncMock(return_value={"sessions": sessions}))
    return Relay(native=native, browser=manager, trust=TrustStore(tmp_path/"trust.json"))


def command(kind="toggle", **values):
    return {"cmd": kind, "target": "auto", "session_id": "", **values}


@pytest.mark.asyncio
async def test_foreground_chrome_never_falls_back_to_background_edge(tmp_path, context):
    manager, edge = manager_with_page(playing=True)
    context["foreground"] = {"source": "chrome.exe", "pid": 200, "bilibili": True}
    remote = relay(tmp_path, manager, [])
    with pytest.raises(RuntimeError, match="未切换到后台窗口"):
        await remote.choose_target(command())
    assert edge.page_hint is None


@pytest.mark.asyncio
async def test_same_browser_brand_different_profile_does_not_bypass_guard(tmp_path, context):
    manager, edge = manager_with_page(playing=True)
    context["foreground"] = {"source": "msedge.exe", "pid": 999, "bilibili": True}
    remote = relay(tmp_path, manager, [{"id": "msedge.exe", "bilibili": True, "foreground": False}])
    with pytest.raises(RuntimeError, match="未切换到后台窗口"):
        await remote.choose_target(command())


@pytest.mark.asyncio
async def test_foreground_matching_browser_session_selected_over_hidden_page(tmp_path, context):
    manager, edge = manager_with_page()
    context["foreground"] = {"source": "chrome.exe", "pid": 200, "bilibili": True}
    remote = relay(tmp_path, manager, [{"id": "chrome.exe", "bilibili": True, "foreground": True, "playing": True}])
    route = await remote.choose_target(command())
    assert isinstance(route, NativeRoute) and route.session_id == "chrome.exe"


@pytest.mark.asyncio
async def test_native_bilibili_playing_beats_hidden_paused_webpage(tmp_path, context):
    manager, edge = manager_with_page()
    remote = relay(tmp_path, manager, [{"id": "bilibili.exe", "playing": True}])
    assert (await remote.choose_target(command())).session_id == "bilibili.exe"


@pytest.mark.asyncio
async def test_multiple_distinct_playbacks_require_selection(tmp_path, context):
    manager, edge = manager_with_page(playing=True)
    remote = relay(tmp_path, manager, [{"id": "chrome.exe", "bilibili": True, "playing": True}])
    with pytest.raises(RuntimeError, match="多个"):
        await remote.choose_target(command())


@pytest.mark.asyncio
async def test_same_brand_normal_browser_is_not_treated_as_managed_duplicate(tmp_path, context):
    manager, edge = manager_with_page(playing=True)
    remote = relay(tmp_path, manager, [{"id": "msedge.exe", "bilibili": True, "playing": True, "matching_window_pids": [999]}])
    with pytest.raises(RuntimeError, match="多个"):
        await remote.choose_target(command())


@pytest.mark.asyncio
async def test_foreground_managed_page_uses_full_interface(tmp_path, context):
    manager, edge = manager_with_page(visible=True)
    context["foreground"] = {"source": "msedge.exe", "pid": 100, "bilibili": True}
    remote = relay(tmp_path, manager, [{"id": "msedge.exe", "bilibili": True, "foreground": True, "matching_window_pids": [100]}])
    assert await remote.choose_target(command()) is edge
    assert edge.page_hint == "page-1"


@pytest.mark.asyncio
async def test_explicit_session_error_never_falls_back_to_browser(tmp_path, context):
    manager, edge = manager_with_page(playing=True)
    remote = relay(tmp_path, manager, [])
    remote.native.execute = AsyncMock(side_effect=RuntimeError("未开放倍速接口"))
    with pytest.raises(RuntimeError, match="Chrome.*未开放倍速"):
        await remote.execute(command("speed_start", target="native", session_id="chrome.exe", rate=2), "phone")
    assert not remote.held_targets
    manager.candidates.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_hold_restores_original_session_after_selection_changes(tmp_path, context):
    manager, _ = manager_with_page()
    remote = relay(tmp_path, manager, [])
    remote.native.boost = {"owner": "phone"}
    remote.native.execute = AsyncMock(return_value={})
    await remote.execute(command("speed_start", target="native", session_id="chrome.exe", rate=2), "phone")
    await remote.execute(command("speed_change", target="native", session_id="msedge.exe", rate=3), "phone")
    await remote.execute(command("speed_end", target="browser"), "phone")
    assert [call.args[0]["session_id"] for call in remote.native.execute.await_args_list] == ["chrome.exe"]*3


@pytest.mark.asyncio
async def test_discover_browser_requires_matching_media_title_and_reports_capabilities():
    session = Session()
    session.source_app_user_model_id = "msedge.exe"
    session.controls.is_playback_rate_enabled = False
    native = NativeController()
    native.manager = SimpleNamespace(get_sessions=lambda: [session])
    window = {"source": "msedge.exe", "pid": 10, "bilibili": True, "title": "test video_哔哩哔哩"}
    found = (await native.discover({"foreground": window, "windows": [window]}))["sessions"][0]
    assert found["bilibili"] and found["foreground"] and found["seek"] and not found["speed"]
    window["title"] = "another video_哔哩哔哩"
    found = (await native.discover({"foreground": window, "windows": [window]}))["sessions"][0]
    assert not found["bilibili"] and not found["foreground"]


@pytest.mark.asyncio
async def test_browser_system_route_reports_target_and_rejects_speed_and_shared_volume():
    session = Session()
    session.source_app_user_model_id = "chrome.exe"
    session.controls.is_playback_rate_enabled = False
    native = NativeController()
    native.manager = SimpleNamespace(get_sessions=lambda: [session])
    result = await native.execute(command("status", session_id="chrome.exe"), "phone")
    assert result["control_target"]["name"].startswith("Chrome")
    assert not result["control_target"]["speed"]
    for kind, fields in (("speed_start", {"rate": 2}), ("volume", {"delta": .1})):
        with pytest.raises(RuntimeError, match="专用|完整控制"):
            await native.execute(command(kind, session_id="chrome.exe", **fields), "phone")
    assert session.rate == 1.5


@pytest.mark.asyncio
async def test_duplicate_browser_media_ids_are_not_selected_arbitrarily():
    native = NativeController()
    session = Session()
    session.source_app_user_model_id = "msedge.exe"
    native.manager = SimpleNamespace(get_sessions=lambda: [session, session])
    with pytest.raises(RuntimeError, match="多个媒体会话"):
        await native._session("msedge.exe")


@pytest.mark.asyncio
async def test_browser_choice_reuses_separate_profiles_and_failed_open_keeps_choice(monkeypatch, tmp_path):
    manager = BrowserManager()
    monkeypatch.setattr("desktop.browser.data_directory", lambda: tmp_path)
    monkeypatch.setattr("desktop.browser.find_browser", lambda choice: Path("chrome.exe" if choice == "chrome" else "msedge.exe"))
    edge = manager.controller("edge")[1]
    chrome = manager.controller("chrome")[1]
    assert edge.profile == tmp_path/"browser-profile" and chrome.profile == tmp_path/"browser-profile-chrome"
    edge.open = AsyncMock(return_value={"opened": True})
    chrome.open = AsyncMock(side_effect=RuntimeError("failed"))
    await manager.open("edge")
    with pytest.raises(RuntimeError):
        await manager.open("chrome")
    assert manager.preferred == "edge"
    assert manager.controller("edge")[1] is edge


@pytest.mark.parametrize("source,expected", [("msedge.exe", "Edge"), ("Chrome.EXE", "Chrome"), ("Microsoft.MicrosoftEdge.Stable_abc!App", "Edge"), ("fake-chrome-player.exe", ""), ("SodaMusic.exe", "")])
def test_browser_id_matching_does_not_match_unrelated_processes(source, expected):
    assert browser_name(source) == expected
