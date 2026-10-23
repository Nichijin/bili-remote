"""Measure actual Tk page switches and interactions with isolated settings.

No network service, media discovery or production data is used. Timings include
draining Tk's pending layout and paint events, rather than only the button call.
"""
import argparse
import cProfile
import json
import os
from pathlib import Path
import pstats
import statistics
import sys
import tempfile
import time
from tkinter import ttk
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--resize-steps", type=int, default=12)
    parser.add_argument("--min-width", type=int, default=900)
    parser.add_argument("--max-width", type=int, default=1230)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 30 or not 2 <= args.resize_steps <= 24:
        parser.error("rounds must be 1–30; resize-steps must be 2–24")
    if not 440 <= args.min_width < args.max_width <= 3840:
        parser.error("resize widths must satisfy 440 <= min-width < max-width <= 3840")
    sys.path.insert(0, str(args.source_root.resolve()))
    from desktop.gui import Companion
    if hasattr(Companion, "dispose"):
        from qt_measurements import run
        return run(args, scrolling=False)
    class Preview(Companion):
        def start(self):
            self.status.set("电脑已在线，正在广播；等待手机连接。")
            self.addresses.set("PERFORMANCE-PREVIEW · 192.168.1.10")
    timings, animation, first_action = [], [], []
    with tempfile.TemporaryDirectory(prefix="bili-responsiveness-") as directory:
        with patch.dict(os.environ, {"BILI_REMOTE_DATA_DIR": directory}), patch("desktop.gui.startup_enabled", return_value=False):
            startup = time.perf_counter()
            app = Preview(hidden=True)
        try:
            app.window.geometry("1040x780")
            app.window.deiconify()
            app.window.update()
            startup_ms = (time.perf_counter() - startup) * 1000
            def walk(widget):
                yield widget
                for child in widget.winfo_children():
                    yield from walk(child)
            switch = next(w for w in walk(app.tabs.pages[3]) if isinstance(w, ttk.Checkbutton)
                          and str(w.cget("variable")) == str(app.close_to_tray))
            def settle_transition():
                while getattr(app.tabs, "transition_timer", None) is not None:
                    app.window.update()
                    time.sleep(.001)
            profiler = cProfile.Profile()
            profiler.enable()
            for iteration in range(args.rounds):
                for tab in (1, 2, 3, 0):
                    started = time.perf_counter()
                    app.navigation[tab][0].invoke()
                    app.window.update()
                    elapsed = (time.perf_counter() - started) * 1000
                    timings.append({"round": iteration + 1, "tab": tab, "milliseconds": round(elapsed, 3)})
                    if tab == 3:
                        previous = app.close_to_tray.get()
                        switch.event_generate("<ButtonPress-1>", x=8, y=8)
                        switch.event_generate("<ButtonRelease-1>", x=8, y=8)
                        app.window.update()
                        assert app.close_to_tray.get() != previous, "First settings input was ignored"
                        first_action.append((time.perf_counter() - started) * 1000)
                    settle_transition()
                    animation.append((time.perf_counter() - started) * 1000)
                    print(f"round {iteration + 1}, tab {tab}: {elapsed:.1f} ms", flush=True)
            app.tabs.select(3)
            app.window.update()
            slider = next(control for control in app.feedback_controls if isinstance(control, ttk.Scale))
            scroller = app.options_page
            offset = slider.winfo_rooty() - scroller.content.winfo_rooty() - 100
            scroller.canvas.yview_moveto(max(0, offset) / max(1, scroller.content.winfo_height()))
            app.window.update()
            x, y = slider.coords(app.feedback_vars["x"].get())
            slider.event_generate("<ButtonPress-1>", x=x, y=y)
            drag = []
            for step in range(30):
                x, y = slider.coords(20 + step * 2)
                started = time.perf_counter()
                slider.event_generate("<B1-Motion>", x=x, y=y)
                app.window.update()
                drag.append((time.perf_counter() - started) * 1000)
            slider.event_generate("<ButtonRelease-1>", x=x, y=y)
            resize, resize_samples = [], []
            for step in [*range(args.resize_steps), *reversed(range(args.resize_steps))]:
                started = time.perf_counter()
                cpu_started = time.process_time()
                width = round(args.min_width + step * (args.max_width-args.min_width) / max(1, args.resize_steps - 1))
                app.window.geometry(f"{width}x780")
                app.window.update()
                elapsed = (time.perf_counter() - started) * 1000
                resize.append(elapsed)
                resize_samples.append({"width": width, "milliseconds": round(elapsed, 3), "cpu_ms": round((time.process_time() - cpu_started) * 1000, 3)})
            profiler.disable()
            if args.profile:
                profiler.dump_stats(str(args.profile))
                pstats.Stats(profiler).strip_dirs().sort_stats("cumulative").print_stats(18)
            samples = [entry["milliseconds"] for entry in timings]
            def summary(values):
                return {"median_ms": round(statistics.median(values), 3), "p95_ms": round(sorted(values)[max(0, int(len(values) * .95) - 1)], 3), "max_ms": round(max(values), 3)}
            report = {"scenario": "isolated source UI, no network or detection; button invoke plus Tk update; wait for any transition between samples",
                      "window": "1040x780", "ui_scale": app.ui_scale, "ui_startup_ms": round(startup_ms, 3),
                      "switches": timings, **summary(samples), "first_settings_action": summary(first_action),
                      "transition_complete": summary(animation),
                      "native_page_surfaces": bool(getattr(getattr(app.tabs, "compositor", None), "surfaces", {})),
                      "resize_width_range": [args.min_width, args.max_width],
                      "slider_drag": summary(drag), "window_resize": summary(resize), "resize_samples": resize_samples}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({key: value for key, value in report.items() if key not in {"switches", "resize_samples"}}), flush=True)
        finally:
            for timer in app.window.tk.splitlist(app.window.tk.call("after", "info")):
                app.window.after_cancel(timer)
            app.window.destroy()


if __name__ == "__main__":
    main()
