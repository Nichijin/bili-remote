"""Exercise small windows and simulated font scaling using isolated UI instances."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.gui import Companion
from desktop.layout import FlowRow, fit_window
from tkinter import ttk


class Preview(Companion):
    def start(self):
        self.status.set("电脑已在线，等待手机连接。" * 3)
        self.addresses.set("DESKTOP-EXAMPLE · 192.168.1.10 / 192.168.20.30")

    def refresh_pin_label(self):
        self.pin_text.set("123 456")


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def main():
    report = []
    for width, height, scale in [(480, 360, 1), (640, 480, 1.25), (800, 550, 1.5), (1024, 640, 2), (1200, 780, 2), (1040, 780, 1), (1366, 900, 1.25)]:
        print(f"Layout {width}x{height}, font scale {scale}", flush=True)
        with tempfile.TemporaryDirectory(prefix="bili-layout-") as directory:
            def setup(window):
                window.tk.call("tk", "scaling", (96 / 72) * scale)
                return fit_window(window)
            with patch.dict(os.environ, {"BILI_REMOTE_DATA_DIR": directory}), patch("desktop.gui.fit_window", setup), patch("desktop.gui.startup_enabled", return_value=False):
                app = Preview(hidden=True, preferences_path=Path(directory) / "preferences.json")
            try:
                app.window.minsize(1, 1)
                app.window.geometry(f"{width}x{height}")
                app.window.deiconify(); app.window.update()
                for tab in range(4):
                    button = app.navigation[tab][0]
                    assert button.winfo_ismapped()
                    assert button.winfo_y() + button.winfo_height() <= app.sidebar_footer.winfo_y(), (width, height, scale, "sidebar overlap")
                    button.invoke(); app.window.update()
                    assert app.tabs.index(app.tabs.select()) == tab
                    page = app.tabs.nametowidget(app.tabs.select())
                    assert page.winfo_width() > 200 and page.winfo_height() > 100
                    for widget in walk(page):
                        if isinstance(widget, FlowRow):
                            for child in widget.items:
                                assert child.winfo_x() + child.winfo_width() <= widget.winfo_width() + 2, (width, height, scale, child)
                for tab, scroller in ((0, app.remote_page), (3, app.options_page)):
                    app.tabs.select(tab); app.window.update()
                    scroller.canvas.yview_moveto(1); app.window.update()
                    last = scroller.content.winfo_children()[-1]
                    bottom = last.winfo_rooty() + last.winfo_height()
                    assert bottom <= scroller.canvas.winfo_rooty() + scroller.canvas.winfo_height() + 2, (width, height, scale, bottom)
                # Horizontal/vertical table and log scrolling must be wired.
                assert app.inventory.cget("xscrollcommand") and app.inventory.cget("yscrollcommand")
                assert app.records.cget("xscrollcommand") and app.records.cget("yscrollcommand")
                # Exercise the real themed thumb: styling must preserve pointer control.
                app.tabs.select(3); app.window.update()
                slider = next(control for control in app.feedback_controls if isinstance(control, ttk.Scale))
                app.feedback_vars["x"].set(50)
                start_x, start_y = slider.coords(50)
                slider.event_generate("<ButtonPress-1>", x=start_x, y=start_y)
                slider.event_generate("<B1-Motion>", x=round(slider.winfo_width() * .25), y=start_y)
                slider.event_generate("<ButtonRelease-1>", x=round(slider.winfo_width() * .25), y=start_y)
                app.window.update()
                assert 15 < app.feedback_vars["x"].get() < 40, (width, height, scale, "slider drag")
                report.append({"window": f"{width}x{height}", "font_scale": scale, "navigation_reachable": True, "buttons_inside_rows": True, "bottom_actions_reachable": True, "slider_drag": True})
            finally:
                for timer in app.window.tk.splitlist(app.window.tk.call("after", "info")):
                    app.window.after_cancel(timer)
                app.window.destroy()
    (ROOT / ".tooling/desktop-layout-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
