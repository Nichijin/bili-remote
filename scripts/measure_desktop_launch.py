"""Measure installed-style EXE launch without touching the production instance.

Includes interpreter loading and one-file extraction when present. A visible
window with constructed controls and a responsive native message pump is ready.
Screen samples observe the desktop, never trigger PrintWindow repainting.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import tempfile
import time
import uuid

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    assert 1 <= args.repeats <= 5
    executable = args.executable.resolve()
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.FindWindowW.argtypes, user.FindWindowW.restype = [wintypes.LPCWSTR, wintypes.LPCWSTR], wintypes.HWND
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                      wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    user.SendMessageTimeoutW.restype = wintypes.LPARAM
    user.WindowFromPoint.argtypes, user.WindowFromPoint.restype = [wintypes.POINT], wintypes.HWND
    user.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumChildWindows.argtypes = [wintypes.HWND, callback, wintypes.LPARAM]
    runs = []
    for iteration in range(args.repeats):
        with tempfile.TemporaryDirectory(prefix="bili-launch-") as directory:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            identity = "BiliRemote-LaunchTest-"+uuid.uuid4().hex
            env = {**os.environ, "BILI_REMOTE_DATA_DIR": directory, "BILI_REMOTE_INSTANCE_NAME": identity,
                   "BILI_REMOTE_WINDOW_TITLE": identity, "BILI_REMOTE_BIND_HOST": "127.0.0.1",
                   "BILI_REMOTE_PORT": str(port), "BILI_REMOTE_DISCOVERY_PORT": "0"}
            started = time.perf_counter()
            process = subprocess.Popen([str(executable)], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic()+25
                handle = None
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Program exited during launch")
                    handle = user.FindWindowW(None, identity)
                    if handle and user.IsWindowVisible(handle):
                        break
                    time.sleep(.002)
                else:
                    raise TimeoutError("Main window did not become visible")
                visible_ms = (time.perf_counter()-started)*1000
                handles = []
                @callback
                def collect(child, parameter):
                    handles.append(child)
                    return True
                user.EnumChildWindows(handle, collect, 0)
                assert len(handles) >= 50, "Window appeared before its real controls were constructed"
                result = ctypes.c_size_t()
                assert user.SendMessageTimeoutW(handle, 0, 0, 0, 2, 2000, ctypes.byref(result)), "Visible main window is unresponsive"
                ready_ms = (time.perf_counter()-started)*1000
                user.SetWindowPos(handle, wintypes.HWND(-1), 0, 0, 0, 0, 0x43)
                box = wintypes.RECT()
                user.GetWindowRect(handle, ctypes.byref(box))
                capture = (box.left+max(1, (box.right-box.left)//3), box.top+65, box.right-30, box.bottom-30)
                point = wintypes.POINT(capture[0]+20, capture[1]+20)
                hit = user.WindowFromPoint(point)
                screen_available = hit == handle or bool(user.IsChild(handle, hit))
                black_samples, responsiveness = [], []
                for _ in range(12):
                    sample_started = time.perf_counter()
                    assert user.SendMessageTimeoutW(handle, 0, 0, 0, 2, 2000, ctypes.byref(result))
                    responsiveness.append((time.perf_counter()-sample_started)*1000)
                    if screen_available:
                        image = ImageGrab.grab(bbox=capture).convert("L")
                        hist = image.histogram()
                        black_samples.append(round(sum(hist[:16])/(image.width*image.height), 6))
                    time.sleep(.016)
                run = {"run": iteration+1, "visible_ms": round(visible_ms, 3), "ready_ms": round(ready_ms, 3),
                       "constructed_child_windows": len(handles), "message_latency_max_ms": round(max(responsiveness), 3),
                       "screen_samples": len(black_samples), "black_pixel_fraction": black_samples,
                       "screen_limit": None if screen_available else "desktop locked or obscured"}
                runs.append(run)
                print(json.dumps(run), flush=True)
            finally:
                if process.poll() is None:
                    subprocess.run([str(executable), "--quit"], env=env, creationflags=subprocess.CREATE_NO_WINDOW,
                                   timeout=15, check=True)
                    process.wait(timeout=15)
    report = {"scenario": "sequential isolated packaged launches; no player or phone; service starts normally; includes one-file extraction if applicable",
              "measurement_limit": "OS/file cache warmness is not controlled. Native message latency is not application action latency. Screen samples do not prove every transient frame is artifact-free.",
              "visible_median_ms": round(statistics.median(run["visible_ms"] for run in runs), 3),
              "ready_median_ms": round(statistics.median(run["ready_ms"] for run in runs), 3), "runs": runs}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "runs"}), flush=True)


if __name__ == "__main__":
    main()
