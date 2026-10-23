"""Shared Qt measurements; legacy source-root comparisons retain their Tk path."""
import json
import os
import statistics
import tempfile
import time
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from desktop.gui import Companion


def summary(values):
    return {"median_ms": round(statistics.median(values), 3),
            "p95_ms": round(sorted(values)[max(0, int(len(values)*.95)-1)], 3),
            "max_ms": round(max(values), 3)}


class Preview(Companion):
    def start(self):
        pass


def run(args, scrolling=False):
    with tempfile.TemporaryDirectory(prefix="bili-qt-measure-") as directory:
        with patch.dict(os.environ, {"BILI_REMOTE_DATA_DIR": directory}), patch("desktop.gui.startup_enabled", return_value=False):
            started = time.perf_counter()
            app = Preview(hidden=True)
        try:
            app.window.resize(1040, 780)
            app.window.show()
            QTest.qWait(50)
            startup = (time.perf_counter()-started)*1000
            app.select_page(3)
            QTest.qWait(20)
            if scrolling:
                from PIL import Image, ImageChops, ImageStat
                from mss import MSS
                import ctypes
                from ctypes import wintypes
                user = ctypes.WinDLL("user32")
                user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
                origin = wintypes.POINT()
                user.ClientToScreen(int(app.window.winId()), ctypes.byref(origin))
                app.window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
                app.window.show()
                QTest.qWait(50)
                viewport = app.tabs.widget(3).viewport()
                pos = viewport.mapTo(app.window, QPoint(0, 0))
                dpr = app.window.devicePixelRatioF()
                user.ClientToScreen(int(app.window.winId()), ctypes.byref(origin))
                box = {"left": origin.x+round(pos.x()*dpr), "top": origin.y+round(pos.y()*dpr),
                       "width": round(viewport.width()*dpr), "height": round(viewport.height()*dpr)}
                bar = app.tabs.widget(3).verticalScrollBar()
                # Start away from an edge so every sample is an equal move.
                step = min(24, max(1, bar.maximum()//40))
                bar.setValue(step*2)
                samples, comparisons = [], []
                with MSS() as capture:
                    def grab():
                        shot = capture.grab(box)
                        return Image.frombytes("RGB", shot.size, shot.rgb)
                    for index, delta in enumerate([step]*32+[-step]*32):
                        before = bar.value()
                        started = time.perf_counter()
                        bar.setValue(before+delta)
                        app.app.processEvents()
                        samples.append((time.perf_counter()-started)*1000)
                        assert bar.value()-before == delta
                        QTest.qWait(40)
                        if index in (0, 7, 15, 23, 31, 32, 39, 47, 55, 63):
                            actual = grab()
                            app.pages[3].update()
                            viewport.update()
                            app.app.processEvents()
                            QTest.qWait(40)
                            reference = grab()
                            difference = ImageChops.difference(actual, reference)
                            error = sum(ImageStat.Stat(difference).mean)/3
                            comparisons.append({"step": index, "mean_abs_error": round(error, 6)})
                            assert error < .05, comparisons
                report = {"scenario": "Qt raster UI, equal logical-pixel steps; actual screen before/after full update",
                          "pixel_step": step, "moving_samples": len(samples), "scroll_update": summary(samples),
                          "screen_comparisons": comparisons, "screen_matches_full_repaint": True}
            else:
                switches, settings, resize, drag = [], [], [], []
                for _ in range(args.rounds):
                    for index in (1, 2, 3, 0):
                        started = time.perf_counter()
                        app.navigation[index].click()
                        app.app.processEvents()
                        switches.append((time.perf_counter()-started)*1000)
                        if index == 3:
                            previous = app.close_to_tray.isChecked()
                            app.close_to_tray.click()
                            app.app.processEvents()
                            assert app.close_to_tray.isChecked() != previous
                            settings.append((time.perf_counter()-started)*1000)
                app.select_page(3)
                slider = app.feedback_vars["x"]
                app.tabs.widget(3).ensureWidgetVisible(slider)
                QTest.qWait(30)
                QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width()//2, slider.height()//2))
                for index in range(30):
                    started = time.perf_counter()
                    QTest.mouseMove(slider, QPoint(round(slider.width()*(.2+index*.02)), slider.height()//2))
                    app.app.processEvents()
                    drag.append((time.perf_counter()-started)*1000)
                QTest.mouseRelease(slider, Qt.MouseButton.LeftButton)
                for step in [*range(args.resize_steps), *reversed(range(args.resize_steps))]:
                    width = round(args.min_width+step*(args.max_width-args.min_width)/max(1, args.resize_steps-1))
                    started = time.perf_counter()
                    app.window.resize(width, 780)
                    app.app.processEvents()
                    resize.append((time.perf_counter()-started)*1000)
                report = {"scenario": "Isolated Qt source UI; button/input plus processEvents, no service or network",
                          "ui_startup_ms": round(startup, 3), **summary(switches),
                          "first_settings_action": summary(settings), "slider_drag": summary(drag),
                          "window_resize": summary(resize), "native_page_surfaces": False,
                          "resize_width_range": [args.min_width, args.max_width]}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report), flush=True)
        finally:
            app.dispose()
