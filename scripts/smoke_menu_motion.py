"""Measure shared menu/page motion, live input, reversal and cleanup in real Tk.

The sample interval includes Tk event processing, not display scanout. Run this
sequentially with other GUI checks; settings and services remain isolated.
"""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.gui import Companion


class Preview(Companion):
    def start(self):
        pass


def main():
    with tempfile.TemporaryDirectory(prefix="bili-menu-motion-") as directory:
        with patch.dict(os.environ, {"BILI_REMOTE_DATA_DIR": directory}), patch("desktop.gui.startup_enabled", return_value=False):
            app = Preview(hidden=True)
        errors = []
        app.window.report_callback_exception = lambda *error: errors.append(str(error[1]))
        user = app.tabs.compositor.user
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        def page_y(page):
            page_rect, parent_rect = wintypes.RECT(), wintypes.RECT()
            user.GetWindowRect(page.winfo_id(), ctypes.byref(page_rect))
            user.GetWindowRect(app.tabs.winfo_id(), ctypes.byref(parent_rect))
            return page_rect.top-parent_rect.top
        frames, runs = [], []
        original = app.tabs.transition_observer
        def observe(progress):
            original(progress)
            if app.tabs.transition_page is not None:
                page = app.tabs.transition_page
                frames.append({"seconds": time.perf_counter(), "progress": progress,
                               "menu_y": app.navigation_selection.y, "page_y": page_y(page)})
        try:
            app.window.geometry("1230x780")
            app.window.deiconify()
            app.window.update()
            app.tabs.compositor.animate = True
            app.tabs.transition_observer = observe
            image_count = len(app.window.tk.splitlist(app.window.tk.call("image", "names")))
            controls = [page.winfo_id() for page in app.tabs.pages]
            for target in (3, 0, 2, 1, 3, 0):
                previous = app.tabs.selected
                frames.clear()
                started = time.perf_counter()
                app.navigation[target][0].invoke()
                app.window.update()
                page = app.tabs.pages[target]
                assert page_y(page) * (1 if target > previous else -1) > 0, "Wrong page slide direction"
                assert app.tabs.transition_timer is not None
                if target == 3:
                    def walk(widget):
                        yield widget
                        for child in widget.winfo_children():
                            yield from walk(child)
                    switch = next(w for w in walk(page) if isinstance(w, ttk.Checkbutton)
                                  and str(w.cget("variable")) == str(app.close_to_tray))
                    value = app.close_to_tray.get()
                    switch.event_generate("<ButtonPress-1>", x=8, y=8)
                    switch.event_generate("<ButtonRelease-1>", x=8, y=8)
                    app.window.update()
                    assert app.close_to_tray.get() != value
                    assert app.tabs.transition_timer is not None, "Input waited for motion to finish"
                deadline = time.monotonic() + 2
                while app.tabs.transition_timer is not None and time.monotonic() < deadline:
                    app.window.update()
                    time.sleep(.001)
                assert app.tabs.transition_timer is None and page_y(page) == 0
                assert not app.tabs.compositor.motion_clock_active
                assert app.navigation_selection.y == app.navigation_selection.target()
                assert len(frames) >= 6, "Animation did not produce intermediate frames"
                deltas = [b["menu_y"]-a["menu_y"] for a, b in zip(frames, frames[1:])]
                assert all(delta * (target-previous) >= -.01 for delta in deltas), "Menu moved backwards"
                assert all(a["progress"] <= b["progress"] for a, b in zip(frames, frames[1:]))
                intervals = [(b["seconds"]-a["seconds"])*1000 for a,b in zip(frames,frames[1:])]
                runs.append({"from": previous, "to": target, "frames": len(frames),
                             "elapsed_ms": round((time.perf_counter()-started)*1000, 3),
                             "frame_intervals_ms": [round(x,3) for x in intervals]})
            assert len(app.window.tk.splitlist(app.window.tk.call("image", "names"))) == image_count, "Motion allocated image frames"
            app.tabs.select(3)
            app.window.update()
            switch.event_generate("<ButtonPress-1>", x=8, y=8)
            held_y = page_y(app.tabs.pages[3])
            deadline = time.monotonic()+.04
            while time.monotonic() < deadline:
                app.window.update()
                time.sleep(.001)
            assert page_y(app.tabs.pages[3]) == held_y, "Pressed control kept moving under the pointer"
            assert app.tabs.transition_paused_at is not None and not app.tabs.compositor.motion_clock_active
            switch.event_generate("<ButtonRelease-1>", x=8, y=8)
            app.window.update()
            assert app.tabs.transition_paused_at is None and app.tabs.transition_timer is not None
            app.tabs.finish_transition()
            app.tabs.select(0)
            app.tabs.finish_transition()
            # Retarget from the current selection position, not from the old destination.
            app.tabs.select(3)
            app.window.update()
            deadline = time.monotonic()+.055
            while time.monotonic() < deadline:
                app.window.update()
                time.sleep(.001)
            y = app.navigation_selection.y
            app.tabs.select(0)
            assert abs(app.navigation_selection.y-y) < 3, "Reversal snapped to a previous target"
            app.window.update()
            assert page_y(app.tabs.pages[3]) == 0
            app.window.geometry("1150x810")
            app.window.update()
            assert app.tabs.transition_timer is None and all(page_y(page) == 0 for page in app.tabs.pages)
            assert controls == [page.winfo_id() for page in app.tabs.pages]
            app.tabs.select(2)
            app.window.withdraw()
            app.window.update()
            assert app.tabs.transition_timer is None
            assert not app.tabs.compositor.motion_clock_active
            app.window.deiconify()
            app.window.update()
            app.tabs.compositor.animate = False
            app.tabs.select(3)
            app.window.update()
            assert app.tabs.transition_timer is None and app.navigation_selection.y == app.navigation_selection.target()
            assert not errors, errors
            intervals = [x for run in runs for x in run["frame_intervals_ms"]]
            report = {"target_fps": 60, "duration_ms": round(app.tabs.transition_duration*1000),
                      "scenario": "isolated Tk UI, no service/player; event-loop frame times, not DWM scanout",
                      "interval_median_ms": round(statistics.median(intervals),3), "interval_max_ms": round(max(intervals),3),
                      "intervals_over_25ms": sum(x>25 for x in intervals), "runs": runs,
                      "shared_page_menu_timeline": True, "live_input_during_motion": True,
                      "pressed_control_stays_under_pointer": True, "precision_timer_released_when_idle": True,
                      "forward_backward_slide": True, "reverse_without_snapping": True,
                      "no_per_frame_images_or_control_recreation": True, "resize_hide_and_reduced_motion_cleanup": True}
        finally:
            app.tabs.transition_observer = original
            app.tabs.compositor.animate = True
            app.tabs.select(1)
            app.window.destroy()
        assert not errors, errors
        report["destroy_without_callbacks"] = True
        (ROOT/".tooling/menu-motion-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(json.dumps({k:v for k,v in report.items() if k != "runs"}),flush=True)


if __name__ == "__main__":
    main()
