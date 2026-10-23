"""Continuously capture the real screen during navigation, without forcing paint.

Optional test dependency: mss. Run sequentially on an unlocked Windows desktop.
References are settled real pages; intermediate frames must match either page,
not just pass a black-pixel threshold. Minimized/covered screen pixels are never
counted as application failures. Captures are sampling, not optical scanout proof.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
from unittest.mock import patch

from PIL import Image, ImageChops, ImageStat
from mss import MSS

ROOT = Path(__file__).resolve().parents[1]


def summary(values):
    return {"median_ms": round(statistics.median(values), 3),
            "p95_ms": round(sorted(values)[max(0, int(len(values)*.95)-1)], 3),
            "max_ms": round(max(values), 3)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--captures", type=Path)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--assert-clean", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_root.resolve()))
    from desktop.gui import Companion

    class Preview(Companion):
        def start(self):
            pass
        def check_updates(self, *args, **kwargs):
            pass

    user = ctypes.WinDLL("user32")
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user.WindowFromPoint.argtypes, user.WindowFromPoint.restype = [wintypes.POINT], wintypes.HWND
    user.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumChildWindows.argtypes = [wintypes.HWND, callback, wintypes.LPARAM]
    with tempfile.TemporaryDirectory(prefix="bili-rendering-") as directory:
        with patch.dict(os.environ, {"BILI_REMOTE_DATA_DIR": directory}), patch("desktop.gui.startup_enabled", return_value=False):
            app = Preview(hidden=True)
        qt = hasattr(app, "app")
        frames, actions, references = [], [], {}
        stop, ready = threading.Event(), threading.Event()
        phase = {"kind": "reference", "page": 0, "previous": 0}
        capture_errors = []
        thread = None
        try:
            if qt:
                from PySide6.QtCore import QPoint, Qt
                dpr = app.window.devicePixelRatioF()
                app.window.resize(round(1040/dpr), round(780/dpr))
                app.window.move(20, 20)
                app.window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
                app.window.show()
                handle = int(app.window.winId())
                update, select = app.app.processEvents, app.select_page
                def scroll(index, value):
                    bar = app.tabs.widget(index).verticalScrollBar()
                    bar.setValue(round(value*bar.maximum()))
            else:
                app.window.geometry("1040x780+20+20")
                app.window.attributes("-topmost", True)
                app.window.deiconify()
                handle = app.window.winfo_id()
                update, select = app.window.update, app.tabs.select
                def scroll(index, value):
                    for view in app.tabs.scroll_views.get(index, ()):
                        view.yview_moveto(value)

            def pump(seconds):
                deadline = time.perf_counter()+seconds
                while time.perf_counter() < deadline:
                    update()
                    time.sleep(.001)

            pump(.25)
            if qt:
                point = app.tabs.mapTo(app.window, QPoint(0, 0))
                origin = wintypes.POINT()
                user.ClientToScreen(handle, ctypes.byref(origin))
                box = {"left": origin.x+round(point.x()*dpr), "top": origin.y+round(point.y()*dpr),
                       "width": round(app.tabs.width()*dpr), "height": round(app.tabs.height()*dpr)}
            else:
                rect = wintypes.RECT()
                user.GetWindowRect(app.tabs.winfo_id(), ctypes.byref(rect))
                box = {"left": rect.left, "top": rect.top, "width": rect.right-rect.left, "height": rect.bottom-rect.top}
            hit = user.WindowFromPoint(wintypes.POINT(box["left"]+40, box["top"]+40))
            assert hit == handle or user.IsChild(handle, hit), "Unlock/uncover the Windows desktop before measuring"
            if args.captures:
                args.captures.mkdir(parents=True, exist_ok=True)

            def grab(sct):
                shot = sct.grab(box)
                return Image.frombytes("RGB", shot.size, shot.rgb).resize((320, 300))

            with MSS() as sct:
                for index in range(4):
                    select(index)
                    scroll(index, 0)
                    pump(.15)
                    references[index] = grab(sct)
                    if args.captures:
                        references[index].save(args.captures/f"reference-{index}.png")

            def capture():
                try:
                    with MSS() as sct:
                        ready.set()
                        while not stop.is_set():
                            started = time.perf_counter()
                            state = dict(phase)
                            frame = grab(sct)
                            # A grab can span a UI action on the other thread.
                            # Keep it, but never mislabel its old-page pixels as
                            # a malformed new page when the action changed mid-grab.
                            if state != phase:
                                state["kind"] = "excluded-action-boundary"
                            frames.append((started, state, frame))
                            stop.wait(max(0, .008-(time.perf_counter()-started)))
                except Exception as exc:
                    capture_errors.append(str(exc))
                    ready.set()

            thread = threading.Thread(target=capture, name="screen-observer")
            thread.start()
            assert ready.wait(5)
            samples = []
            previous = 3
            for iteration in range(args.rounds):
                for index in (3, 1, 0, 2, 0, 1, 3, 2):
                    started = time.perf_counter()
                    phase.update(kind="switch", page=index, previous=previous, started=started)
                    select(index)
                    update()
                    samples.append((time.perf_counter()-started)*1000)
                    actions.append({"t": started, "page": index})
                    pump(.10)
                    if index in (0, 1, 3) and iteration == 0:
                        phase["kind"] = "scroll"
                        for value in (.1, .2, .3, .2, .1, 0):
                            scroll(index, value)
                            pump(.035)
                        pump(.12)
                    previous = index
            phase["kind"] = "excluded-minimized"
            if qt:
                app.window.showMinimized()
                pump(.15)
                app.window.showNormal()
            else:
                app.window.iconify()
                pump(.15)
                app.window.deiconify()
            # Exclude the native shell restore transition (it may expose other
            # applications), then continue page identity measurements.
            pump(.25)
            phase.update(kind="switch", page=2, previous=2)
            pump(.15)
            stop.set()
            thread.join(5)
            assert not thread.is_alive() and not capture_errors, capture_errors
            suspicious, black, wrong_pages = [], [], []
            for index, (timestamp, state, frame) in enumerate(frames):
                if state["kind"] != "switch":
                    continue
                allowed = references.values()
                error = min(sum(ImageStat.Stat(ImageChops.difference(frame, reference)).mean)/3 for reference in allowed)
                fraction = sum(frame.convert("L").histogram()[:16])/(frame.width*frame.height)
                if fraction > .2:
                    black.append(index)
                target_error = sum(ImageStat.Stat(ImageChops.difference(frame, references[state["page"]])).mean)/3
                if timestamp-state.get("started", timestamp) > .080 and target_error > 2:
                    wrong_pages.append({"frame": index, "page": state["page"], "mean_error": round(target_error, 3)})
                if error > 2:
                    suspicious.append({"frame": index, "page": state["page"], "previous": state["previous"], "mean_error": round(error, 3)})
                    if args.captures:
                        frame.save(args.captures/f"intermediate-{index:04}.png")
            handles = []
            @callback
            def collect(hwnd, param):
                handles.append(hwnd)
                return True
            user.EnumChildWindows(handle, collect, 0)
            intervals = [(second[0]-first[0])*1000 for first, second in zip(frames, frames[1:])]
            report = {"renderer": "Qt raster backing store" if qt else "Tk native children",
                      "source_root": str(args.source_root.resolve()), "switches": len(samples),
                      "switch": summary(samples), "frames": len(frames), "capture_interval": summary(intervals),
                      "black_frames_during_switches": black, "intermediate_frames": suspicious,
                      "wrong_pages_after_80ms": wrong_pages,
                      "native_descendant_windows": len(handles),
                      "capture": "Continuous independent MSS screen captures; no PrintWindow, DwmFlush or forced redraw. Old/new real-page references; mean RGB error > 2/255 flags intermediate frames. Minimized shell transition excluded; finite sampling."}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            if args.captures:
                images = [frame for _, state, frame in frames if state["kind"] != "excluded-minimized"]
                images[0].save(args.captures/"continuous.gif", save_all=True, append_images=images[1:], duration=15, loop=0)
            print(json.dumps({key: value for key, value in report.items() if key != "intermediate_frames"} |
                             {"intermediate_frame_count": len(suspicious)}), flush=True)
            if args.assert_clean:
                assert len(frames) >= len(samples)*2, "Insufficient continuous screen samples"
                assert not black and not suspicious and not wrong_pages, "Intermediate/black/wrong page captured; inspect report"
        finally:
            stop.set()
            if thread:
                thread.join(5)
            app.dispose() if qt else app.window.destroy()


if __name__ == "__main__":
    main()
