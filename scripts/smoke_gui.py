"""Verify a hidden real GUI: PIN, saved reconnect and computer feedback."""
import asyncio
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["BILI_REMOTE_BIND_HOST"] = "127.0.0.1"
from desktop.gui import Companion
from PySide6.QtCore import QTimer
from websockets.asyncio.client import connect


def main():
    with tempfile.TemporaryDirectory() as temporary:
        app = Companion(hidden=True, port=18766, discovery_port=18767, trust_path=Path(temporary) / "trust.json")
        results = []
        async def probe():
            try:
                for _ in range(30):
                    try:
                        ws = await connect("ws://127.0.0.1:18766")
                        break
                    except OSError:
                        await asyncio.sleep(.1)
                else:
                    raise RuntimeError("GUI service did not start")
                async with ws:
                    await ws.send(json.dumps({"role": "remote", "device_id": "gui-test-phone", "device_name": "模拟测试手机", "pairing_code": app.pairing.current()}))
                    auth = json.loads(await ws.recv())
                    assert auth["ok"]
                    await ws.send(json.dumps({"id": 1, "cmd": "seek", "delta": 999}))
                    assert not json.loads(await ws.recv())["ok"]
                async with connect("ws://127.0.0.1:18766") as ws:
                    await ws.send(json.dumps({"role": "remote", "device_id": "gui-test-phone", "token": auth["token"]}))
                    assert json.loads(await ws.recv())["ok"]
                results.append("GUI PIN, automatic reconnect and feedback passed")
            except Exception as exc:
                results.append(exc)
        thread = threading.Thread(target=lambda: asyncio.run(probe()), daemon=True)
        thread.start()
        def finish():
            if not thread.is_alive():
                if results and isinstance(results[0], str) and app.records.count() == 0:
                    # The GUI consumes feedback on its next poll, after the WS reply.
                    QTimer.singleShot(50, finish)
                else:
                    app.close()
            else:
                QTimer.singleShot(50, finish)
        QTimer.singleShot(100, finish)
        QTimer.singleShot(10000, app.close)
        app.run()
        assert results and isinstance(results[0], str), results
        print(results[0])


if __name__ == "__main__":
    main()
