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
