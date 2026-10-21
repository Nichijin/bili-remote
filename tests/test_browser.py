"""Run against a real headless installed Edge/Chrome and a local video fixture."""
import asyncio
import base64
import io
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from desktop.browser import BrowserController, find_browser


@pytest.mark.asyncio
async def test_direct_browser_playback_without_extensions(tmp_path):
    try:
        executable = find_browser()
    except RuntimeError:
        pytest.skip("Edge/Chrome not installed")
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(1)
        audio.setframerate(8000)
        audio.writeframes(bytes([128]) * 8000 * 40)
    data = base64.b64encode(output.getvalue()).decode()
    html = f'<html><video style="width:640px;height:360px" src="data:audio/wav;base64,{data}" preload="auto"></video></html>'.encode()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    browser = BrowserController(profile=tmp_path / "profile", executable=executable, launch_url=f"http://127.0.0.1:{server.server_port}", allowed_hosts={"127.0.0.1"}, headless=True)
    try:
        await browser.open()
        page = await browser._page()
        for _ in range(40):
            ready = await browser._evaluate(page, "document.querySelector('video')?.readyState >= 2")
            if ready:
                break
            await asyncio.sleep(.1)
        assert ready
        await browser._evaluate(page, "document.querySelector('video').playbackRate=1.5")
        result = await browser.execute({"cmd": "toggle"}, "phone")
        assert result["paused"] is False
        result = await browser.execute({"cmd": "toggle"}, "phone")
        assert result["paused"] is True
        result = await browser.execute({"cmd": "seek", "delta": 12}, "phone")
        assert 12 <= result["time"] <= 13
        result = await browser.execute({"cmd": "volume", "delta": -.2}, "phone")
        assert result["volume"] == .8
        result = await browser.execute({"cmd": "speed_start", "rate": 3}, "phone")
        assert result["rate"] == 3
        await browser.execute({"cmd": "speed_end"}, "other-phone")
        assert (await browser.execute({"cmd": "status"}, "phone"))["rate"] == 3
        await browser.execute({"cmd": "speed_end"}, "phone")
        assert (await browser.execute({"cmd": "status"}, "phone"))["rate"] == 1.5
        await browser.execute({"cmd": "speed_start", "rate": 2}, "phone")
        browser.boost["deadline"] = 0
        assert await browser.expire()
        assert (await browser.execute({"cmd": "status"}, "phone"))["rate"] == 1.5
        await browser.execute({"cmd": "speed_start", "rate": 2}, "phone")
        page = browser.boost["page"]
        await browser.rpc(browser.browser_socket, "Target.closeTarget", {"targetId": page["id"]})
        await browser.execute({"cmd": "speed_end"}, "phone")
        assert browser.boost is None
    finally:
        await browser.close()
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_existing_playback_window_is_reused_and_endpoint_preserved(tmp_path, monkeypatch):
    """Reopening a live profile must not delete its port file or relaunch Edge."""
    original = BrowserController(profile=tmp_path / "profile", launch_url="about:blank", headless=True)
    reused = BrowserController(profile=original.profile, launch_url="about:blank", headless=True)
    try:
        await original.open()
        endpoint = (original.profile / "DevToolsActivePort").read_bytes()
        socket = original.browser_socket
        def unexpected_launch(*args, **kwargs):
            raise AssertionError("An existing dedicated browser must be reused")
        with monkeypatch.context() as context:
            context.setattr("desktop.browser.subprocess.Popen", unexpected_launch)
            assert (await reused.open())["opened"]
        assert reused.running
        assert reused.browser_socket == socket
        assert (original.profile / "DevToolsActivePort").read_bytes() == endpoint
        await reused.rpc(reused.browser_socket, "Target.getTargets")
    finally:
        await reused.close()
        await original.close()


@pytest.mark.asyncio
async def test_missing_metadata_from_old_version_recovers_live_browser(tmp_path):
    original = BrowserController(profile=tmp_path / "profile", launch_url="about:blank", headless=True)
    recovered = BrowserController(profile=original.profile, launch_url="about:blank", headless=True)
    try:
        await original.open()
        (original.profile / "DevToolsActivePort").unlink()
        assert (await recovered.open())["opened"]
        assert recovered.browser_socket == original.browser_socket
        assert recovered.process is None, "Recover the existing process instead of relaunching"
        assert recovered.running
    finally:
        await recovered.close()
        await original.close()


@pytest.mark.asyncio
async def test_launcher_exit_zero_does_not_mean_browser_failure(tmp_path, monkeypatch):
    """A browser can hand off to a real profile process then exit its launcher."""
    import subprocess
    real_launch = subprocess.Popen
    launched = []
    class CompletedLauncher:
        returncode = 0
        def poll(self): return 0
        def wait(self, timeout=None): return 0
    def handoff(*args, **kwargs):
        launched.append(real_launch(*args, **kwargs))
        return CompletedLauncher()
    browser = BrowserController(profile=tmp_path / "profile", launch_url="about:blank", headless=True)
    monkeypatch.setattr("desktop.browser.subprocess.Popen", handoff)
    try:
        assert (await browser.open())["opened"]
        assert browser.process.poll() == 0
        assert browser.running
        assert (await browser.rpc(browser.browser_socket, "Target.getTargets"))["targetInfos"]
    finally:
        await browser.close()
        for process in launched:
            process.wait(timeout=5)


@pytest.mark.asyncio
async def test_unrelated_browser_profile_is_never_claimed_or_closed(tmp_path):
    original = BrowserController(profile=tmp_path / "other-profile", launch_url="about:blank", headless=True)
    isolated = BrowserController(profile=tmp_path / "remote-profile", launch_url="about:blank", headless=True)
    try:
        await original.open()
        isolated.executable = original.executable
        assert isolated._profile_process() is None
        # Even a stale copy of a different profile's endpoint must not be trusted.
        isolated.profile.mkdir()
        (isolated.profile / "DevToolsActivePort").write_bytes((original.profile / "DevToolsActivePort").read_bytes())
        await isolated.open()
        assert isolated.browser_socket != original.browser_socket
        await isolated.close()
        assert original.running
        assert (await original.rpc(original.browser_socket, "Target.getTargets"))["targetInfos"]
    finally:
        await isolated.close()
        await original.close()
