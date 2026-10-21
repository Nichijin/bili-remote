import asyncio
import json
import time
import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from desktop.server import Relay
from desktop.browser import BrowserController
from desktop.trust import TrustStore


class NoNative:
    boost = None
    async def execute(self, message, owner):
        return {}
    async def discover(self):
        return {"sessions": []}
    async def expire(self):
        return False


class FakeBrowser:
    boost = None
    def __init__(self):
        self.calls = []
        self.released = asyncio.Event()
    async def execute(self, message, owner):
        self.calls.append((message, owner))
        if message["cmd"] == "speed_end":
            self.released.set()
        return {"paused": True, "rate": message.get("rate", 1)}
    async def close(self):
        pass


def make_relay(tmp_path, feedback=None):
    return Relay(NoNative(), trust=TrustStore(tmp_path / "trust.json"), browser=FakeBrowser(), feedback=feedback)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["auto", "browser"])
@pytest.mark.parametrize("message", [
    {"cmd": "toggle"}, {"cmd": "seek", "delta": -10}, {"cmd": "seek", "delta": 10},
    {"cmd": "volume", "delta": -.05}, {"cmd": "volume", "delta": .05},
    {"cmd": "speed_start", "rate": 2}, {"cmd": "status"},
])
async def test_remote_commands_never_launch_a_closed_browser(tmp_path, monkeypatch, target, message):
    profile = tmp_path / "profile"
    profile.mkdir()
    stale_endpoint = profile / "DevToolsActivePort"
    stale_endpoint.write_bytes(b"stale endpoint must remain unchanged")
    browser = BrowserController(profile=profile, executable=tmp_path / "msedge.exe")
    monkeypatch.setattr(browser, "_profile_process", lambda: None)
    def unexpected_launch(*args, **kwargs):
        raise AssertionError("Remote commands must never launch a browser")
    monkeypatch.setattr("desktop.browser.subprocess.Popen", unexpected_launch)
    relay = Relay(NoNative(), trust=TrustStore(tmp_path / "trust.json"), browser=browser)
    with pytest.raises(RuntimeError, match="手机设置"):
        await relay.execute({**message, "target": target}, "phone")
    await relay.release("phone")
    assert not browser.running and browser.process is None
    assert not relay.held_targets
    assert stale_endpoint.read_bytes() == b"stale endpoint must remain unchanged"


async def authenticate(ws, token="", device_id="phone-1234", pin=""):
    await ws.send(json.dumps({"role": "remote", "token": token, "device_id": device_id, "device_name": "测试手机", "pairing_code": pin}))
    return json.loads(await ws.recv())


@pytest.mark.asyncio
async def test_first_pin_then_secret_reconnect_and_id_alone_denied(tmp_path):
    relay = make_relay(tmp_path)
    async with serve(relay.handle, "127.0.0.1", 0) as server:
        url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        async with connect(url) as ws:
            first = await authenticate(ws)
            assert not first["ok"] and first["code"] == "pair_required"
        async with connect(url) as ws:
            paired = await authenticate(ws, pin=relay.pairing.current())
            assert paired["ok"] and len(paired["token"]) > 32
        relay.pairing.rotate()
        async with connect(url) as ws:
            assert (await authenticate(ws, token=paired["token"]))["ok"]
        async with connect(url) as ws:
            assert not (await authenticate(ws))["ok"]


@pytest.mark.asyncio
async def test_bad_pin_is_limited_but_saved_device_can_reconnect(tmp_path):
    relay = make_relay(tmp_path)
    secret = relay.trust.allow("known-phone", "已配对手机")
    wrong = "000000" if relay.pairing.current() != "000000" else "111111"
    async with serve(relay.handle, "127.0.0.1", 0) as server:
        url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        for _ in range(5):
            async with connect(url) as ws:
                assert (await authenticate(ws, pin=wrong))["code"] == "pair_invalid"
        async with connect(url) as ws:
            assert (await authenticate(ws, pin=relay.pairing.current()))["code"] == "rate_limited"
        async with connect(url) as ws:
            assert (await authenticate(ws, token=secret, device_id="known-phone"))["ok"]


@pytest.mark.asyncio
async def test_commands_have_computer_feedback_and_disconnect_restores_hold(tmp_path):
    events = []
    relay = make_relay(tmp_path, events.append)
    async with serve(relay.handle, "127.0.0.1", 0) as server:
        url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        async with connect(url) as ws:
            await authenticate(ws, pin=relay.pairing.current())
            await ws.send(json.dumps({"cmd": "toggle", "id": 1}))
            assert json.loads(await ws.recv())["ok"]
            assert events[-1]["text"] == "已暂停"
            await ws.send(json.dumps({"cmd": "speed_start", "rate": 2, "id": 2}))
            assert json.loads(await ws.recv())["ok"]
            await ws.send("bad-json")
            assert not json.loads(await ws.recv())["ok"]
            assert not events[-1]["ok"]
        await asyncio.wait_for(relay.browser.released.wait(), 1)


@pytest.mark.asyncio
async def test_hold_release_stays_on_original_target_if_target_changes(tmp_path):
    relay = make_relay(tmp_path)
    await relay.execute({"cmd": "speed_start", "target": "browser", "rate": 2}, "phone")
    await relay.execute({"cmd": "speed_end", "target": "native"}, "phone")
    assert relay.browser.calls[-1][0]["cmd"] == "speed_end"


@pytest.mark.asyncio
async def test_gear_changes_stay_on_held_target_and_require_active_hold(tmp_path):
    relay = make_relay(tmp_path)
    with pytest.raises(RuntimeError, match="重新长按"):
        await relay.execute({"cmd": "speed_change", "target": "browser", "rate": 3}, "phone")
    await relay.execute({"cmd": "speed_start", "target": "browser", "rate": 2}, "phone")
    await relay.execute({"cmd": "speed_change", "target": "native", "rate": 3}, "phone")
    assert relay.browser.calls[-1][0]["cmd"] == "speed_change"
    await relay.execute({"cmd": "speed_end", "target": "native"}, "phone")


@pytest.mark.asyncio
async def test_unrelated_website_cannot_authenticate_even_with_pin(tmp_path):
    relay = make_relay(tmp_path)
    async with serve(relay.handle, "127.0.0.1", 0) as server:
        url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        async with connect(url, origin="https://unrelated.example") as ws:
            with pytest.raises(ConnectionClosed):
                await authenticate(ws, pin=relay.pairing.current())


@pytest.mark.asyncio
async def test_revoking_secret_requires_pairing_again(tmp_path):
    relay = make_relay(tmp_path)
    token = relay.trust.allow("phone-1234", "测试手机")
    await relay.revoke_all()
    async with serve(relay.handle, "127.0.0.1", 0) as server:
        url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        async with connect(url) as ws:
            assert (await authenticate(ws, token=token))["code"] == "pair_required"
