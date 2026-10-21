"""Control an isolated local Edge/Chrome playback window, without extensions."""
import asyncio
import contextlib
import json
import logging
import os
import subprocess
import time
import urllib.request
import winreg
from pathlib import Path
from urllib.parse import urlsplit

import psutil
from websockets.asyncio.client import connect

from .windows import data_directory

PLAYER_SOURCE = (Path(__file__).resolve().parent / "assets/player.js").read_text(encoding="utf-8")
LOG = logging.getLogger(__name__)


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
        self.browser_process = None
        self.port = None
        self.browser_socket = None
        self.lock = asyncio.Lock()
        self.boost = None

    @property
    def running(self):
        if self.port is None:
            return False
        try:
            return bool(self.browser_process and self.browser_process.is_running())
        except psutil.Error:
            return False

    def allowed(self, url):
        host = (urlsplit(url).hostname or "").lower()
        return any(host == domain or host.endswith("." + domain) for domain in self.allowed_hosts)

    @staticmethod
    def _json_at(port, path):
        # Never inherit an HTTP proxy for the loopback debugging endpoint.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}{path}", timeout=1) as response:
            return json.load(response)

    def _json(self, path):
        return self._json_at(self.port, path)

    def _profile_process(self):
        """Only claim a browser using our exact, dedicated user-data directory."""
        expected = os.path.normcase(str(self.profile.resolve()))
        for process in psutil.process_iter(["exe", "cmdline"]):
            try:
                if not process.info["exe"] or not os.path.samefile(process.info["exe"], self.executable):
                    continue
                arguments = process.info["cmdline"] or []
                if any(argument.startswith("--type=") for argument in arguments):
                    continue
                for index, argument in enumerate(arguments):
                    value = ""
                    if argument.startswith("--user-data-dir="):
                        value = argument.partition("=")[2]
                    elif argument == "--user-data-dir" and index + 1 < len(arguments):
                        value = arguments[index + 1]
                    if value and os.path.normcase(str(Path(value).resolve())) == expected:
                        return process
            except (psutil.Error, OSError, ValueError):
                continue
        return None

    def _read_endpoint(self, owner):
        try:
            if not owner or not owner.is_running():
                return None
            lines = (self.profile / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()
            port, socket_path = int(lines[0]), lines[1]
            if not 1 <= port <= 65535 or not socket_path.startswith("/devtools/browser/"):
                return None
            expected = f"ws://127.0.0.1:{port}" + socket_path
            version = self._json_at(port, "/json/version")
            # An old file must never attach us to a different local debugging server.
            if version.get("webSocketDebuggerUrl") != expected:
                return None
            if not owner.is_running():
                return None
            return port, expected
        except (OSError, ValueError, IndexError, psutil.Error):
            return None

    def _recover_endpoint(self, owner):
        """Old builds could remove the active port file while the browser was live."""
        try:
            for connection in owner.net_connections(kind="tcp"):
                if connection.status != psutil.CONN_LISTEN or not connection.laddr or connection.laddr.ip != "127.0.0.1":
                    continue
                port = connection.laddr.port
                try:
                    socket = self._json_at(port, "/json/version").get("webSocketDebuggerUrl", "")
                except (OSError, ValueError):
                    continue
                parsed = urlsplit(socket)
                if parsed.scheme == "ws" and parsed.hostname == "127.0.0.1" and parsed.port == port and parsed.path.startswith("/devtools/browser/") and owner.is_running():
                    return port, socket
        except (psutil.Error, ValueError):
            pass
        return None

    async def _ensure(self):
        if self.running:
            try:
                version = await asyncio.to_thread(self._json, "/json/version")
                if version.get("webSocketDebuggerUrl") == self.browser_socket:
                    return
            except (OSError, ValueError):
                pass
        self.port = None
        self.browser_socket = None
        self.browser_process = None
        self.profile.mkdir(parents=True, exist_ok=True)
        self.executable = self.executable or find_browser()
        active_port = self.profile / "DevToolsActivePort"
        owner = await asyncio.to_thread(self._profile_process)
        if owner:
            endpoint = await asyncio.to_thread(self._read_endpoint, owner)
            if not endpoint:
                endpoint = await asyncio.to_thread(self._recover_endpoint, owner)
            if endpoint:
                self.port, self.browser_socket = endpoint
                self.browser_process = owner
                return
        else:
            # Remove stale metadata only after verifying no browser owns the profile.
            active_port.unlink(missing_ok=True)
        arguments = [str(self.executable), "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1", "--user-data-dir=" + str(self.profile), "--no-first-run", "--no-default-browser-check"]
        if self.headless:
            arguments += ["--headless=new", "--disable-gpu", "--autoplay-policy=no-user-gesture-required"]
        arguments += ["--new-window", self.launch_url]
        # This is an explicitly requested playback window; it remains interactive.
        # Headless verification creates no visible Windows console or browser window.
        if not owner:
            self.process = subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            # Edge/Chrome may hand the window to another process and exit with 0.
            # The verified endpoint and profile owner determine whether it started.
            owner = await asyncio.to_thread(self._profile_process)
            endpoint = await asyncio.to_thread(self._read_endpoint, owner)
            if endpoint:
                self.port, self.browser_socket = endpoint
                self.browser_process = owner
                return
            if not owner and self.process and self.process.poll() not in (None, 0):
                code = self.process.returncode
                LOG.warning("专用浏览器未能启动，退出代码：%s", code)
                raise RuntimeError(f"专用浏览器启动失败（退出代码 {code}），请关闭软件打开的播放窗口后重试")
            await asyncio.sleep(.15)
        LOG.warning("专用浏览器控制连接未就绪，浏览器进程存在：%s", bool(owner))
        if owner:
            raise RuntimeError("播放窗口已打开但遥控连接未就绪，请关闭软件打开的播放窗口后重试；仍失败时检查浏览器是否被系统策略限制")
        raise RuntimeError("未能启动专用播放窗口，请重试；仍失败时检查浏览器是否被系统策略限制")

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
                with contextlib.suppress(psutil.Error):
                    await asyncio.to_thread(self.browser_process.wait, 4)
            if self.process:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    await asyncio.to_thread(self.process.wait, 4)
            self.port = None
            self.browser_socket = None
            self.browser_process = None
