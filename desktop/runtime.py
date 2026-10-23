"""UI-independent service lifecycle. Worker results cross a queue, never widgets."""
import asyncio
import contextlib
import logging
import os
import socket
import threading
from websockets.asyncio.server import serve
from .detection import ClientDetector, combine
from .discovery import start_discovery
from .pairing import PairingCode
from .server import Relay
from .trust import TrustStore

class ServiceRuntime:
    def __init__(self, events, port=8765, discovery_port=8766, trust_path=None):
        self.events, self.port, self.discovery_port, self.trust_path = events, port, discovery_port, trust_path
        self.thread = self.loop = self.stop_event = self.relay = self.detection_request = None
        self.closing = self.request_stop = False
        self.detector = ClientDetector()
        self.inventory_visible = threading.Event()
        self.inventory_force = threading.Event()
        self.inventory_signature = None
        self.pairing = PairingCode()

    def start_service(self):
        if self.thread and self.thread.is_alive():
            return
        self.request_stop = False
        self.thread = threading.Thread(target=self.worker, name="remote-service", daemon=True)
        self.thread.start()

    def stop_service(self):
        self.request_stop = True
        if self.loop and self.stop_event:
            self.loop.call_soon_threadsafe(self.stop_event.set)

    def worker(self):
        try:
            asyncio.run(self.serve())
        except Exception as exc:
            logging.exception("电脑服务失败")
            self.events.put(("error", f"服务启动失败：{exc}；请检查端口 8765 / 8766 是否被占用。"))
        finally:
            self.events.put(("stopped", None))

    async def serve(self):
        self.loop = asyncio.get_running_loop()
        self.stop_event, self.detection_request = asyncio.Event(), asyncio.Event()
        self.inventory_signature = None
        if self.inventory_visible.is_set():
            self.detection_request.set()
        if self.closing or self.request_stop:
            self.stop_event.set()
        self.relay = Relay(trust=TrustStore(self.trust_path), pairing=self.pairing, notify=lambda text: self.events.put(("status", text)), feedback=lambda event: self.events.put(("operation", event)))
        discovery = None
        watchdog = asyncio.create_task(self.relay.watchdog())
        monitor = asyncio.create_task(self.monitor_targets())
        try:
            host = os.environ.get("BILI_REMOTE_BIND_HOST", "0.0.0.0")
            async with serve(self.relay.handle, host, self.port, process_request=self.relay.http, max_size=16_384, ping_interval=10, ping_timeout=5, close_timeout=2) as server:
                discovery = await start_discovery(self.relay.trust.public_info(self.port), host=host, port=self.discovery_port)
                self.events.put(("status", "电脑已在线 · 等待手机连接"))
                addresses = sorted({r[4][0] for r in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET) if not r[4][0].startswith("127.")})
                self.events.put(("addresses", socket.gethostname() + " · " + " / ".join(addresses)))
                await self.stop_event.wait()
                await self.relay.close()
                server.close()
        finally:
            if discovery:
                discovery.close()
            for task in (watchdog, monitor):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self.loop = None

    async def monitor_targets(self):
        while True:
            if not self.inventory_visible.is_set() and not self.detection_request.is_set():
                await self.detection_request.wait()
            force = self.inventory_force.is_set()
            self.inventory_force.clear()
            self.detection_request.clear()
            try:
                installed, running = await asyncio.to_thread(self.detector.scan, force)
                sessions = []
                # Loading the WinRT media DLLs for a browser-only table used
                # to cause a Python-wide import pause and retain unused DLLs.
                native = self.relay.native
                if installed or any(row["kind"] == "client" for row in running) or native.manager is not None:
                    try:
                        sessions = (await asyncio.wait_for(native.discover(), 3))["sessions"]
                    except Exception:
                        pass
                browser = self.relay.browser
                name = browser.executable.name.lower() if browser.running and browser.executable else ""
                rows = combine(installed, running, sessions, name)
                if rows != self.inventory_signature:
                    self.inventory_signature = rows
                    self.events.put(("inventory", rows))
                self.events.put(("inventory_done", len(rows)))
            except Exception as exc:
                logging.warning("客户端检测失败：%s", exc)
                self.events.put(("inventory_error", "播放器检测失败，请重试。"))
            try:
                await asyncio.wait_for(self.detection_request.wait(), 15)
            except asyncio.TimeoutError:
                pass
