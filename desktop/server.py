import argparse
import asyncio
import contextlib
import json
import logging
import socket
import time
from collections import defaultdict, deque
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from .browser import BrowserController
from .detection import is_client
from .native import NativeController
from .pairing import PairingCode
from .protocol import validate
from .trust import TrustStore
from .discovery import start_discovery

LOG = logging.getLogger("remote")
ASSETS = Path(__file__).resolve().parents[1] / "android/app/src/main/assets"


def operation_text(command, result):
    kind = command["cmd"]
    if kind == "toggle":
        return "已暂停" if result.get("paused") is True else "继续播放" if result.get("paused") is False else "播放 / 暂停"
    if kind == "seek":
        return f"{'快进' if command['delta'] >= 0 else '快退'} {abs(command['delta']):g} 秒"
    if kind == "seek_to":
        tenths = round(result.get("time", command["position"]) * 10)
        return f"进度 {tenths // 600:02d}:{tenths % 600 / 10:04.1f}"
    if kind == "volume":
        return f"音量 {round(result['volume'] * 100)}%" if "volume" in result else "音量增大" if command["delta"] > 0 else "音量减小"
    if kind in {"speed_start", "speed_change"}:
        return f"临时 {command['rate']:g} 倍速"
    if kind == "speed_end":
        return "恢复原播放速度"
    if kind == "open_browser":
        return "已打开哔哩哔哩播放窗口"
    return "操作完成"


class Relay:
    def __init__(self, native=None, trust=None, pairing=None, browser=None, notify=None, feedback=None):
        self.native = native or NativeController()
        self.browser = browser or BrowserController()
        self.trust = trust or TrustStore()
        self.pairing = pairing or PairingCode()
        self.notify = notify or (lambda text: None)
        self.feedback = feedback or (lambda event: None)
        self.remote_peers = {}
        self.failed_pins = defaultdict(deque)
        self.total_failures = deque()
        self.held_targets = {}
        self.command_lock = asyncio.Lock()

    async def http(self, connection, request):
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return None
        names = {"/": "index.html", "/app.js": "app.js", "/gestures.js": "gestures.js", "/connection.js": "connection.js", "/remote.js": "remote.js", "/app.css": "app.css"}
        name = names.get(request.path.split("?", 1)[0])
        if not name:
            return connection.respond(HTTPStatus.NOT_FOUND, "Not found")
        response = connection.respond(HTTPStatus.OK, (ASSETS / name).read_text(encoding="utf-8"))
        response.headers["Content-Type"] = "application/javascript; charset=utf-8" if name.endswith(".js") else "text/css; charset=utf-8" if name.endswith(".css") else "text/html; charset=utf-8"
        response.headers["Cache-Control"] = "no-store"
        return response

    def pin_limited(self, ip):
        now = time.monotonic()
        for queue in (self.failed_pins[ip], self.total_failures):
            while queue and queue[0] < now - 60:
                queue.popleft()
        return len(self.failed_pins[ip]) >= 5 or len(self.total_failures) >= 20

    async def authenticate(self, websocket):
        auth = json.loads(await asyncio.wait_for(websocket.recv(), 5))
        if not isinstance(auth, dict) or auth.get("role") != "remote":
            await websocket.close(1008, "请使用新版手机遥控器")
            return None
        origin = websocket.request.headers.get("Origin", "")
        parsed = urlsplit(origin)
        if origin not in {"", "null", "file://"} and not (parsed.scheme in {"http", "https"} and parsed.netloc == websocket.request.headers.get("Host", "")):
            await websocket.close(1008, "连接来源不受支持")
            return None
        device_id, name = auth.get("device_id", ""), auth.get("device_name", "安卓手机")
        if not isinstance(device_id, str) or not 8 <= len(device_id) <= 128 or not isinstance(name, str):
            raise ValueError("无效设备信息")
        name = "".join(c for c in name[:80] if c.isprintable()) or "安卓手机"
        token = auth.get("token", "")
        if not self.trust.authenticate(device_id, token):
            ip = websocket.remote_address[0]
            pin = auth.get("pairing_code", "")
            if self.pin_limited(ip):
                error, code = "配对失败过多，请一分钟后重试", "rate_limited"
            elif not pin:
                error, code = "首次连接，请输入电脑显示的 6 位配对码", "pair_required"
            elif not self.pairing.verify(pin):
                self.failed_pins[ip].append(time.monotonic())
                self.total_failures.append(time.monotonic())
                error, code = "配对码错误或已过期，请查看电脑端", "pair_invalid"
            else:
                error, code = "", ""
            if error:
                await websocket.send(json.dumps({"type": "auth", "ok": False, "code": code, "error": error, "computer_id": self.trust.computer_id}, ensure_ascii=False))
                await websocket.close(1008, code)
                return None
            token = self.trust.allow(device_id, name)
        await websocket.send(json.dumps({"type": "auth", "ok": True, "token": token, "computer_id": self.trust.computer_id, "computer_name": socket.gethostname()}))
        self.remote_peers[websocket] = device_id
        self.notify(f"手机已连接：{name}")
        return device_id

    async def choose_target(self, message):
        if message["target"] == "native":
            return self.native
        if message["target"] == "auto":
            if getattr(self.browser, "running", False):
                return self.browser
            try:
                sessions = (await self.native.discover())["sessions"]
                if any(is_client(s["id"]) for s in sessions):
                    return self.native
            except Exception:
                pass
        return self.browser

    async def execute(self, message, owner):
        async with self.command_lock:
            kind = message["cmd"]
            if kind == "discover":
                return await self.native.discover()
            if kind == "open_browser":
                return await self.browser.open()
            if kind in {"speed_keep", "speed_end", "speed_change"}:
                controller = self.held_targets.get(owner)
                if controller:
                    result = await controller.execute(message, owner)
                    if kind == "speed_end":
                        self.held_targets.pop(owner, None)
                    return result
                if kind == "speed_change":
                    raise RuntimeError("临时倍速已结束，请重新长按")
                return {}
            controller = await self.choose_target(message)
            if kind == "speed_start":
                previous = self.held_targets.get(owner)
                if previous:
                    await previous.execute({"cmd": "speed_end"}, owner)
                self.held_targets[owner] = controller
            try:
                return await controller.execute(message, owner)
            except Exception:
                if kind == "speed_start" and not getattr(controller, "boost", None):
                    self.held_targets.pop(owner, None)
                raise

    async def release(self, owner):
        async with self.command_lock:
            controller = self.held_targets.pop(owner, None)
            if controller:
                try:
                    await controller.execute({"cmd": "speed_end"}, owner)
                    self.feedback({"ok": True, "text": "连接结束，恢复原播放速度", "cmd": "speed_end"})
                except Exception as exc:
                    LOG.warning("断线恢复速度失败，将由超时监控重试：%s", exc)

    async def handle(self, websocket):
        import secrets
        owner = secrets.token_hex(12)
        authenticated = False
        try:
            authenticated = bool(await self.authenticate(websocket))
            if not authenticated:
                return
            async for raw in websocket:
                message = {}
                command = None
                try:
                    message = json.loads(raw)
                    if not isinstance(message, dict):
                        raise ValueError("指令必须是 JSON 对象")
                    if message.get("cmd") == "ping":
                        continue
                    command = validate(message)
                    result = await self.execute(command, owner)
                    reply = {"id": message.get("id"), "ok": True, "result": result}
                    text = operation_text(command, result)
                except (ValueError, RuntimeError) as exc:
                    reply = {"id": message.get("id") if isinstance(message, dict) else None, "ok": False, "error": str(exc)}
                    text = str(exc)
                except Exception as exc:
                    LOG.exception("播放器操作失败：%s", exc)
                    reply = {"id": message.get("id") if isinstance(message, dict) else None, "ok": False, "error": "播放器操作失败，请在电脑上查看状态"}
                    text = reply["error"]
                if not command or command["cmd"] not in {"speed_keep", "status", "discover"}:
                    self.feedback({"ok": reply["ok"], "text": text, "cmd": command["cmd"] if command else "error"})
                await websocket.send(json.dumps(reply, ensure_ascii=False))
        except (ConnectionClosed, asyncio.TimeoutError, ValueError):
            pass
        finally:
            if authenticated:
                self.remote_peers.pop(websocket, None)
                await self.release(owner)
                self.notify("手机已断开，等待自动重连")

    async def revoke_all(self):
        self.trust.revoke_all()
        for peer in list(self.remote_peers):
            await peer.close(1008, "电脑已取消授权")

    async def close(self):
        for peer in list(self.remote_peers):
            await peer.close(1001, "电脑端已停止")
        for owner in list(self.held_targets):
            await self.release(owner)
        await self.browser.close()
        if getattr(self.native, "boost", None):
            await self.native.execute({"cmd": "speed_end"}, self.native.boost["owner"])

    async def watchdog(self):
        while True:
            active = getattr(self.native, "boost", None) or getattr(self.browser, "boost", None)
            await asyncio.sleep(.25 if active else 1)
            for controller in (self.native, self.browser):
                try:
                    if await controller.expire():
                        self.feedback({"ok": True, "cmd": "speed_end", "text": "连接中断，恢复原播放速度"})
                except Exception as exc:
                    LOG.warning("恢复临时速度失败，将重试：%s", exc)


async def run(args):
    relay = Relay(NativeController(args.audio_process), notify=print, feedback=lambda event: print(event["text"]))
    print(f"配对码：{relay.pairing.current()}（首次连接输入，有效 10 分钟；重启可刷新）")
    async with serve(relay.handle, args.host, args.port, process_request=relay.http, max_size=16_384, ping_interval=10, ping_timeout=5):
        discovery = await start_discovery(relay.trust.public_info(args.port), host=args.host)
        watchdog = asyncio.create_task(relay.watchdog())
        try:
            await asyncio.Future()
        finally:
            discovery.close()
            watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog
            await relay.close()


def main():
    parser = argparse.ArgumentParser(description="哔哩哔哩局域网遥控")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--audio-process", action="append", default=[])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
