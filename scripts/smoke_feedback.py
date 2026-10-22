"""Verify real overlay settings without activating a window or touching app data."""
import ctypes
import json
import os
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.feedback import DEFAULT_STYLE, overlay_geometry
from desktop.gui import Companion
from desktop.windows import Preferences


class Preview(Companion):
    def start(self):
        pass


def main():
    with tempfile.TemporaryDirectory(prefix="bili-feedback-") as directory:
        path = Path(directory) / "settings.json"
        with patch.dict(os.environ, {"BILI_REMOTE_DATA_DIR": directory}), patch("desktop.gui.startup_enabled", return_value=False):
            app = Preview(hidden=True, preferences_path=path)
        try:
            assert app.overlay is None, "Overlay must not allocate a window on startup"
            app.window.update_idletasks()
            user = ctypes.WinDLL("user32", use_last_error=True)
            user.GetForegroundWindow.restype = wintypes.HWND
            user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            foreground = user.GetForegroundWindow()
            app.feedback_vars["font_size"].set(32)
            app.feedback_vars["color"].set("#75e1eb")
            app.feedback_vars["opacity"].set(65)
            app.feedback_position.set("右上"); app.choose_feedback_position()
            app.preview_feedback(); app.window.update_idletasks()
            overlay = app.overlay
            assert overlay.style == {"font_size": 32, "color": "#75E1EB", "opacity": 65, "x": 95, "y": 5}
            assert overlay.label.cget("fg") == "#75E1EB"
            assert abs(float(overlay.window.attributes("-alpha")) - .65) < .01
            assert user.GetForegroundWindow() == foreground, "Overlay must not take focus"
            area, _ = overlay.work_area()
            rect = wintypes.RECT(); user.GetWindowRect(overlay.handle, ctypes.byref(rect))
            assert area[0] <= rect.left < rect.right <= area[2]
            assert area[1] <= rect.top < rect.bottom <= area[3]
            style = Preferences(path).values["feedback_style"]
            assert style == overlay.style
            # Changing a visible style updates it without recreating the overlay.
            app.feedback_vars["opacity"].set(40); app.feedback_vars["x"].set(0)
            assert app.overlay is overlay and app.overlay.style["x"] == 0
            app.show_feedback.set(False); app.change_feedback_enabled()
            assert app.overlay is None and Preferences(path).values["show_feedback"] is False
            app.show_overlay("must remain disabled")
            assert app.overlay is None
            app.show_feedback.set(True); app.change_feedback_enabled(); app.preview_feedback()
            assert app.overlay and app.overlay is not overlay
            app.reset_feedback_style()
            assert app.overlay.style == DEFAULT_STYLE
            handle = app.overlay.handle
            for index in range(300):
                app.show_overlay(f"连续操作 {index} · 音量 50%")
            assert app.overlay.handle == handle and app.overlay.timer is not None
            pending = app.window.tk.splitlist(app.window.tk.call("after", "info"))
            assert len(pending) <= 3, "Repeated feedback must not accumulate hide timers"
            app.feedback_vars["font_size"].set(100)
            app.finish_feedback_edit()
            assert app.feedback_vars["font_size"].get() == 64
            app.feedback_vars["color"].set("not a color")
            app.finish_feedback_edit()
            assert app.feedback_vars["color"].get() == "#FFFFFF"
            app.overlay.hide(); assert not app.overlay.visible
            assert user.GetForegroundWindow() == foreground
            report = {"lazy_creation": True, "position_size_color_opacity_applied": True, "preferences_saved": True,
                      "disabled_hides_and_releases_overlay": True, "reusable_window": True, "focus_preserved": True, "defaults_restored": True,
                      "repeated_updates_reuse_window_and_timer": True, "invalid_input_normalized": True}
            (ROOT / ".tooling/feedback-test-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
        finally:
            if app.overlay:
                app.overlay.close()
            for timer in app.window.tk.splitlist(app.window.tk.call("after", "info")):
                app.window.after_cancel(timer)
            app.window.destroy()


if __name__ == "__main__":
    main()
