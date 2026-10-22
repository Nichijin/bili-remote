import asyncio
import queue
import threading
from types import SimpleNamespace

import pytest

from desktop.gui import Companion


@pytest.mark.asyncio
async def test_background_does_not_scan_or_initialize_media_until_requested():
    scans, media = [], []
    def scan(force):
        scans.append(force)
        return [], []
    async def discover():
        media.append(True)
        return {"sessions": []}
    request = asyncio.Event()
    app = SimpleNamespace(inventory_visible=threading.Event(), inventory_force=threading.Event(), detection_request=request, inventory_signature=None,
                          detector=SimpleNamespace(scan=scan), events=queue.Queue(),
                          relay=SimpleNamespace(native=SimpleNamespace(discover=discover, manager=None), browser=SimpleNamespace(running=False)))
    task = asyncio.create_task(Companion.monitor_targets(app))
    try:
        await asyncio.sleep(.02)
        assert scans == media == []
        request.set()
        for _ in range(50):
            if not app.events.empty():
                break
            await asyncio.sleep(.005)
        assert scans == [False] and media == []
        assert app.events.get_nowait() == ("inventory", [])
        assert app.events.get_nowait() == ("inventory_done", 0)
        app.inventory_force.set()
        request.set()
        for _ in range(50):
            if len(scans) == 2:
                break
            await asyncio.sleep(.005)
        await asyncio.sleep(.01)
        assert scans == [False, True] and media == []
        assert app.events.get_nowait() == ("inventory_done", 0), "Unchanged detection must still finish"
        assert app.events.empty(), "Identical inventory must not rebuild the table"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_installed_client_still_queries_media_capabilities():
    request = asyncio.Event()
    request.set()
    media = []
    async def discover():
        media.append(True)
        return {"sessions": []}
    installed = [{"name": "bilibili", "version": "1.0", "kind": "client", "path": "", "running": False}]
    app = SimpleNamespace(inventory_visible=threading.Event(), inventory_force=threading.Event(), detection_request=request,
                          inventory_signature=None, detector=SimpleNamespace(scan=lambda force: (installed, [])), events=queue.Queue(),
                          relay=SimpleNamespace(native=SimpleNamespace(discover=discover, manager=None), browser=SimpleNamespace(running=False)))
    task = asyncio.create_task(Companion.monitor_targets(app))
    try:
        for _ in range(50):
            if not app.events.empty():
                break
            await asyncio.sleep(.005)
        assert media == [True]
        assert app.events.get_nowait()[0] == "inventory"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
