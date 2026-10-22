"""Measure equal pixel scrolls and compare screen pixels against a fresh paint.

Run GUI checks sequentially on an unlocked Windows desktop. Screen capture uses
ImageGrab, never PrintWindow (which could repair the defect being measured).
Uses isolated settings, with no service, player or production data.
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
import time
from tkinter import ttk
from unittest.mock import patch

from PIL import ImageChops, ImageGrab, ImageStat

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
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_root.resolve()))
    from desktop.gui import Companion

    class Preview(Companion):
        def start(self):
            pass

    user = ctypes.WinDLL("user32", use_last_error=True)
    user.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    user.WindowFromPoint.argtypes, user.WindowFromPoint.restype = [wintypes.POINT], wintypes.HWND
    user.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
    user.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    dwm = ctypes.WinDLL("dwmapi")
    cursor = wintypes.POINT()
    user.GetCursorPos(ctypes.byref(cursor))
    if args.captures:
        args.captures.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bili-scroll-measure-") as directory:
        with patch.dict(os.environ, {"BILI_REMOTE_DATA_DIR": directory}), patch("desktop.gui.startup_enabled", return_value=False):
            app = Preview(hidden=True)
        errors = []
        app.window.report_callback_exception = lambda *error: errors.append(str(error[1]))
        try:
            app.window.geometry("1040x780+20+20")
            app.window.attributes("-topmost", True)
            app.window.deiconify()
            app.window.update()
            app.tabs.select(3)
            getattr(app.tabs, "finish_transition", lambda: None)()
            app.window.update()
            app.window.lift()
            deadline = time.monotonic()+.15
            while time.monotonic() < deadline:
                app.window.update()
                time.sleep(.001)
            viewport = app.options_page.canvas
            content = app.options_page.content
            box = (viewport.winfo_rootx(), viewport.winfo_rooty(),
                   viewport.winfo_rootx()+viewport.winfo_width(), viewport.winfo_rooty()+viewport.winfo_height())
            point = wintypes.POINT(box[0]+30, box[1]+60)
            hit = user.WindowFromPoint(point)
            screen_available = hit == viewport.winfo_id() or user.IsChild(viewport.winfo_id(), hit)
            if not screen_available:
                name = ctypes.create_unicode_buffer(128)
                user.GetClassNameW(wintypes.HWND(hit), name, 128)
                raise AssertionError("Screen viewport is obscured; unlock/uncover the desktop before pixel measurements: "+name.value)
            dwm.DwmFlush()
            controls = tuple(child.winfo_id() for child in content.winfo_children())
            dimensions = content.winfo_width(), content.winfo_height()
            samples, presentations, positions, comparisons = [], [], [], []
            for index, delta in enumerate([24]*32+[-24]*32):
                previous = viewport.yview()[0]
                started = time.perf_counter()
                viewport.yview_moveto(previous+delta/content.winfo_height())
                app.window.update()
                samples.append((time.perf_counter()-started)*1000)
                assert abs(viewport.yview()[0]-previous) > .001, "Sample reached an edge instead of scrolling"
                dwm.DwmFlush()
                presentations.append((time.perf_counter()-started)*1000)
                positions.append(round(viewport.yview()[0]*content.winfo_height(), 2))
                if index in (0, 7, 15, 23, 31, 32, 39, 47, 55, 63):
                    actual = ImageGrab.grab(bbox=box)
                    # Capture first, then explicitly invalidate the entire live
                    # content subtree as an independent freshly painted oracle.
                    user.RedrawWindow(content.winfo_id(), None, None, 0x185)
                    app.window.update()
                    dwm.DwmFlush()
                    reference = ImageGrab.grab(bbox=box)
                    diff = ImageChops.difference(actual, reference)
                    comparisons.append({"step": index, "different_bounds": diff.getbbox(),
                                        "mean_abs_error": round(sum(ImageStat.Stat(diff).mean)/3, 6)})
                    if args.captures:
                        actual.save(args.captures/f"scroll-{index:02d}.png")
                        reference.save(args.captures/f"reference-{index:02d}.png")
                time.sleep(.008)
            assert dimensions == (content.winfo_width(), content.winfo_height()), "Scroll resized contents"
            assert controls == tuple(child.winfo_id() for child in content.winfo_children()), "Scroll recreated controls"
            assert not any(sample["different_bounds"] for sample in comparisons), comparisons
            # Route a real Windows wheel notch to the live scrolled widget.
            app.navigation[3][0].focus_set()
            app.window.update()
            user.SetCursorPos(point.x, point.y)
            before = viewport.yview()[0]*content.winfo_height()
            user.mouse_event(0x800, 0, 0, (-120) & 0xffffffff, 0)
            deadline = time.monotonic()+.35
            while time.monotonic() < deadline:
                app.window.update()
                time.sleep(.001)
            moved = viewport.yview()[0]*content.winfo_height()-before
            assert moved > 1, "Physical wheel input did not reach the viewport"
            wheel_moved = moved
            def walk(widget):
                yield widget
                for child in widget.winfo_children():
                    yield from walk(child)
            switch = next(widget for widget in walk(content) if isinstance(widget, ttk.Checkbutton)
                          and str(widget.cget("variable")) == str(app.close_to_tray))
            rect = wintypes.RECT()
            user.GetWindowRect(switch.winfo_id(), ctypes.byref(rect))
            target = wintypes.POINT((rect.left+rect.right)//2, (rect.top+rect.bottom)//2)
            assert user.WindowFromPoint(target) == switch.winfo_id(), "Scrolled child hit test is stale"
            previous = app.close_to_tray.get()
            user.SetCursorPos(target.x, target.y)
            user.mouse_event(2, 0, 0, 0, 0)
            user.mouse_event(4, 0, 0, 0, 0)
            app.window.update()
            assert previous != app.close_to_tray.get(), "Scrolled control did not accept native input"
            if hasattr(viewport, "motion_timer"):
                viewport.compositor.animate = True
                # A wheel burst must retain only the latest destination, reverse
                # immediately, stop when changing pages, and release timer precision.
                for _ in range(8):
                    viewport.wheel(-30)
                app.window.update()
                viewport.wheel(120)
                assert viewport.target <= viewport.offset, "Wheel reversal queued old downward motion"
                app.tabs.select(0)
                app.window.update()
                assert viewport.motion_timer is None and not viewport.compositor.motion_clock_active
                getattr(app.tabs, "finish_transition", lambda: None)()
                app.tabs.select(3)
                getattr(app.tabs, "finish_transition", lambda: None)()
                viewport.compositor.animate = False
                viewport.yview_moveto(0)
                viewport.wheel(-120)
                app.window.update()
                assert viewport.offset > 0 and viewport.motion_timer is None
                viewport.compositor.animate = True
            assert not errors, errors
            report = {"scenario": "isolated 1040x780 source UI, 64 equal 24px moves, 10 screen/oracle comparisons; physical Windows wheel",
                      "source_root": str(args.source_root.resolve()), "ui_scale": app.ui_scale,
                      "pixel_step": 24, "moving_samples": len(samples), "scroll_update": summary(samples),
                      "update_and_dwm_flush": summary(presentations), "positions": positions,
                      "update_samples_ms": [round(value, 3) for value in samples],
                      "screen_capture_method": "ImageGrab after Tk event drain and DwmFlush, before forced redraw; not PrintWindow or optical scanout",
                      "screen_comparisons": comparisons, "screen_matches_full_repaint": True,
                      "physical_wheel_pixels_per_notch": round(wheel_moved, 2),
                      "wheel_after_menu_focus": True,
                      "native_click_after_scroll": True,
                      "controls_and_dimensions_preserved": True, "callback_errors": errors}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({key: value for key, value in report.items()
                              if key not in {"positions", "update_samples_ms", "screen_comparisons"}}), flush=True)
        finally:
            user.SetCursorPos(cursor.x, cursor.y)
            app.window.destroy()


if __name__ == "__main__":
    main()
