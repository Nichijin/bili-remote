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
    for width, height, scale in [(480, 360, 1), (640, 480, 1.25), (800, 550, 1.5), (1024, 640, 2), (1200, 780, 2)]:
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
                    app.tabs.select(tab); app.window.update()
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
                report.append({"window": f"{width}x{height}", "font_scale": scale, "tabs_accessible": True, "buttons_inside_rows": True, "bottom_actions_reachable": True})
            finally:
                for timer in app.window.tk.splitlist(app.window.tk.call("after", "info")):
                    app.window.after_cancel(timer)
                app.window.destroy()
    (ROOT / ".tooling/desktop-layout-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
