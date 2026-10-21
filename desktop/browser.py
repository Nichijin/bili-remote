"""Control an isolated local Edge/Chrome playback window, without extensions."""
import asyncio
import contextlib
import json
import os
import subprocess
import time
import urllib.request
import winreg
from pathlib import Path
from urllib.parse import urlsplit

from websockets.asyncio.client import connect

from .windows import data_directory

PLAYER_SOURCE = (Path(__file__).resolve().parent / "assets/player.js").read_text(encoding="utf-8")


def find_browser():
    for name in ("msedge.exe", "chrome.exe"):
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, "Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + name) as key:
                    candidate = Path(winreg.QueryValueEx(key, None)[0])
                    if candidate.is_file():
                        return candidate
            except OSError:
                pass
    for root in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
        if root:
            for relative in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
                candidate = Path(root) / relative
                if candidate.is_file():
                    return candidate
    raise RuntimeError("未找到 Edge 或 Chrome，请先安装其中一个浏览器")


class BrowserController:
    def __init__(self, profile=None, executable=None, launch_url="https://www.bilibili.com", allowed_hosts=None, headless=False):
        self.profile = Path(profile) if profile else data_directory() / "browser-profile"
        self.executable = Path(executable) if executable else None
        self.launch_url = launch_url
        self.allowed_hosts = allowed_hosts or {"bilibili.com"}
        self.headless = headless
        self.process = None
        self.port = None
        self.browser_socket = None
        self.lock = asyncio.Lock()
        self.boost = None

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None and self.port is not None

    def allowed(self, url):
        host = (urlsplit(url).hostname or "").lower()
        return any(host == domain or host.endswith("." + domain) for domain in self.allowed_hosts)

    def _json(self, path):
        # Never inherit an HTTP proxy for the loopback debugging endpoint.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{self.port}{path}", timeout=2) as response:
            return json.load(response)

    async def _ensure(self):
        if self.running:
            return
        self.port = None
        self.profile.mkdir(parents=True, exist_ok=True)
        self.executable = self.executable or find_browser()
        active_port = self.profile / "DevToolsActivePort"
        active_port.unlink(missing_ok=True)
        arguments = [str(self.executable), "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1", "--user-data-dir=" + str(self.profile), "--no-first-run", "--no-default-browser-check"]
        if self.headless:
            arguments += ["--headless=new", "--disable-gpu", "--autoplay-policy=no-user-gesture-required"]
        arguments += ["--new-window", self.launch_url]
        # This is an explicitly requested playback window; it remains interactive.
        # Headless verification creates no visible Windows console or browser window.
        self.process = subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(100):
            if self.process.poll() is not None:
                raise RuntimeError("浏览器启动失败，请重试打开哔哩哔哩")
            try:
                lines = active_port.read_text(encoding="utf-8").splitlines()
                port = int(lines[0])
                if not 1 <= port <= 65535 or not lines[1].startswith("/devtools/browser/"):
                    raise ValueError("invalid local debug endpoint")
                self.port = port
                self.browser_socket = f"ws://127.0.0.1:{port}" + lines[1]
                await asyncio.to_thread(self._json, "/json/version")
                return
            except (OSError, ValueError, IndexError):
                await asyncio.sleep(.1)
        raise RuntimeError("浏览器没有及时启动，请检查系统策略是否禁用了自动化控制")

    async def open(self):
        async with self.lock:
            await self._ensure()
            if self.browser_socket:
                pages = await asyncio.to_thread(self._json, "/json/list")
                pages = [page for page in pages if page.get("type") == "page" and self.allowed(page.get("url", ""))]
                if pages:
                    await self.rpc(self.browser_socket, "Target.activateTarget", {"targetId": pages[0]["id"]})
                else:
                    await self.rpc(self.browser_socket, "Target.createTarget", {"url": self.launch_url})
            return {"opened": True, "browser": self.executable.name}

    @staticmethod
    async def rpc(url, method, params=None):
        parsed = urlsplit(url)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise RuntimeError("拒绝非本机浏览器控制地址")
        async with connect(url, max_size=2_000_000, open_timeout=2, proxy=None) as ws:
            await ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), 4))
                if message.get("id") == 1:
                    if "error" in message:
                        raise RuntimeError("浏览器控制失败：" + message["error"].get("message", "未知错误"))
                    return message.get("result", {})

    async def _evaluate(self, page, expression):
        result = await self.rpc(page["webSocketDebuggerUrl"], "Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True, "userGesture": True})
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            description = details.get("exception", {}).get("description", details.get("text", "播放器操作失败"))
            raise RuntimeError(description.split("\n", 1)[0].removeprefix("Error: "))
        return result.get("result", {}).get("value")

    async def _page(self):
        await self._ensure()
        pages = await asyncio.to_thread(self._json, "/json/list")
        pages = [p for p in pages if p.get("type") == "page" and self.allowed(p.get("url", ""))]
        best, best_score = None, -1
        for page in pages:
            try:
                score = await self._evaluate(page, "(() => { const v=[...document.querySelectorAll('video')]; return (v.some(v=>!v.paused)?100:0)+(document.visibilityState==='visible'?10:0)+(v.length?1:0); })()")
                if score > best_score:
                    best, best_score = page, score
            except Exception:
                continue
        if not best:
            raise RuntimeError("已打开遥控播放窗口，请在该窗口中打开哔哩哔哩视频")
        return best

    async def _send(self, page, message, owner):
        payload = json.dumps({**message, "owner": owner}, ensure_ascii=True)
        expression = """(async () => {
          if (!globalThis.__biliGestureRemote) {
            SOURCE
            globalThis.__biliGestureRemote = createPlayerController(() => {
              const videos = [...document.querySelectorAll('video')];
              videos.sort((a,b) => {
                const score=v=>{const r=v.getBoundingClientRect();return (!v.paused?1e9:0)+r.width*r.height;};
                return score(b)-score(a);
              });
              return videos[0];
            });
            setInterval(() => { try { __biliGestureRemote.expire(); } catch {} }, 250);
            addEventListener('pagehide', () => { try { __biliGestureRemote.restore(); } catch {} });
          }
          return await __biliGestureRemote.execute(PAYLOAD);
        })()""".replace("SOURCE", PLAYER_SOURCE).replace("PAYLOAD", payload)
        return await self._evaluate(page, expression) or {}

    async def _restore(self):
        if self.boost:
            boost = self.boost
            try:
                await self._send(boost["page"], {"cmd": "speed_end"}, boost["owner"])
            except Exception:
                if not self.running:
                    self.boost = None
                    return
                pages = await asyncio.to_thread(self._json, "/json/list")
                if not any(page.get("id") == boost["page"].get("id") for page in pages):
                    # A closed tab no longer has a player to restore. Do not block
                    # subsequent videos forever on its defunct debugging socket.
                    self.boost = None
                    return
                raise
            self.boost = None

    async def execute(self, message, owner):
        async with self.lock:
            command = message["cmd"]
            if command in {"speed_end", "speed_keep"}:
                if self.boost and self.boost["owner"] == owner:
                    if command == "speed_end":
                        await self._restore()
                    else:
                        self.boost["deadline"] = time.monotonic() + 1.8
                        await self._send(self.boost["page"], message, owner)
                return {}
            page = await self._page()
            if command == "speed_start":
                await self._restore()
                self.boost = {"page": page, "owner": owner, "deadline": time.monotonic() + 1.8}
            return await self._send(page, message, owner)

    async def expire(self):
        async with self.lock:
            if self.boost and time.monotonic() > self.boost["deadline"]:
                await self._restore()
                return True
        return False

    async def close(self):
        async with self.lock:
            with contextlib.suppress(Exception):
                await self._restore()
            if self.running and self.browser_socket:
                with contextlib.suppress(Exception):
                    await self.rpc(self.browser_socket, "Browser.close")
            if self.process:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    await asyncio.to_thread(self.process.wait, 4)
            self.port = None
