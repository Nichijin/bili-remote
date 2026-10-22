"""Check page state, keyboard traversal and bounded event processing in real Tk."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.gui import Companion


class Preview(Companion):
    def start(self):
        pass


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def main():
    with tempfile.TemporaryDirectory(prefix="bili-ui-state-") as directory:
        with patch.dict(os.environ, {"BILI_REMOTE_DATA_DIR": directory}), patch("desktop.gui.startup_enabled", return_value=False):
            app = Preview(hidden=True)
        try:
            app.window.deiconify()
            app.window.update()
            identities = {str(w): w.winfo_id() for w in walk(app.tabs)}
            app.tabs.select(3)
            app.window.update()
            app.feedback_vars["font_size"].set(26)
            app.feedback_vars["color"].set("#44AACC")
            app.options_page.canvas.yview_moveto(.4)
            app.window.update()
            scroll = app.options_page.canvas.yview()[0]
            for _ in range(4):
                for tab in range(4):
                    app.navigation[tab][0].invoke()
                    app.window.update()
                    start = current = str(app.navigation[tab][0])
                    visited = set()
                    while current not in visited:
                        visited.add(current)
                        current = str(app.window.tk.call("tk_focusNext", current))
                        widget = app.window.nametowidget(current)
                        while widget is not None and widget.master is not app.tabs:
                            widget = getattr(widget, "master", None)
                        if widget is not None:
                            assert widget is app.tabs.pages[tab], "Tab reached an inactive page"
            assert identities == {str(w): w.winfo_id() for w in walk(app.tabs)}, "Switching recreated controls"
            assert abs(app.options_page.canvas.yview()[0] - scroll) < .01, "Lost settings scroll position"
            assert app.feedback_vars["font_size"].get() == 26 and app.feedback_vars["color"].get() == "#44AACC"
            app.flush_feedback_style()
            for timer in app.window.tk.splitlist(app.window.tk.call("after", "info")):
                app.window.after_cancel(timer)
            for index in range(1200):
                app.events.put(("operation", {"ok": index % 17 != 0, "text": f"性能测试 {index}", "cmd": "seek_to"}))
            heartbeat = []
            app.window.after(0, lambda: heartbeat.append(not app.events.empty()))
            app.poll()
            assert not app.events.empty(), "One poll monopolized the entire operation backlog"
            deadline = time.monotonic() + 8
            while (not heartbeat or not app.events.empty()) and time.monotonic() < deadline:
                app.window.update()
                time.sleep(.002)
            assert heartbeat == [True], "UI callback was starved by the operation backlog"
            assert app.events.empty() and app.records.size() == 100
            assert app.last_operation.get() == "性能测试 1199", "Operations were dropped or reordered"
            for row, index in enumerate(reversed(range(1100, 1200))):
                failed = index % 17 == 0
                assert ("失败 · " in app.records.get(row)) == failed
                if failed:
                    assert app.records.itemcget(row, "foreground") == "#C23B45"
            # Exit while a hover tip is open: its Destroy/Unmap handlers must not
            # destroy its Tcl callbacks a second time.
            app.navigation[0][0].event_generate("<Enter>")
            deadline = time.monotonic() + .7
            while time.monotonic() < deadline:
                app.window.update()
                time.sleep(.01)
            report = {"cached_controls_retained": True, "settings_and_scroll_retained": True,
                      "tab_skips_inactive_pages": True, "queue_yields_to_ui": True,
                      "all_operations_ordered_and_log_bounded": True}
        finally:
            for timer in app.window.tk.splitlist(app.window.tk.call("after", "info")):
                app.window.after_cancel(timer)
            app.window.destroy()
        report["exit_with_tooltip"] = True
        (ROOT / ".tooling/desktop-responsiveness-smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
