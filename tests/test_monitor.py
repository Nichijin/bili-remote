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
    app = SimpleNamespace(inventory_visible=threading.Event(), detection_request=request, inventory_signature=None,
                          detector=SimpleNamespace(scan=scan), events=queue.Queue(),
                          relay=SimpleNamespace(native=SimpleNamespace(discover=discover), browser=SimpleNamespace(running=False)))
    task = asyncio.create_task(Companion.monitor_targets(app))
    try:
        await asyncio.sleep(.02)
        assert scans == media == []
        request.set()
        for _ in range(50):
            if not app.events.empty():
                break
            await asyncio.sleep(.005)
        assert scans == [True] and media == [True]
        assert app.events.get_nowait() == ("inventory", [])
        request.set()
        for _ in range(50):
            if len(media) == 2:
                break
            await asyncio.sleep(.005)
        assert len(media) == 2
        assert app.events.empty(), "Identical inventory must not rebuild the table"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
