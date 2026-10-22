"""Exercise persistent preview, live drag and cleanup using isolated settings."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.gui import Companion
from desktop.windows import Preferences


class Preview(Companion):
    def start(self):
        pass


def main():
    with tempfile.TemporaryDirectory(prefix="bili-subtitle-editor-") as directory:
        path = Path(directory) / "settings.json"
        with patch.dict(os.environ, {"BILI_REMOTE_DATA_DIR": directory}), patch("desktop.gui.startup_enabled", return_value=False):
            app = Preview(hidden=True, preferences_path=path)
        errors = []
        app.window.report_callback_exception = lambda *error: errors.append(str(error[1]))
        user = ctypes.WinDLL("user32")
        user.GetForegroundWindow.restype = wintypes.HWND
        user.GetWindowLongPtrW.argtypes, user.GetWindowLongPtrW.restype = [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        try:
            app.window.geometry("1040x780+30+30")
            app.window.deiconify()
            app.tabs.select(3)
            app.window.update()
            surface = app.subtitle_preview
            surface.begin_drag(SimpleNamespace(x=10, y=10))
            surface.drag(SimpleNamespace(x_root=surface.surface.winfo_rootx()+surface.surface.winfo_width()*.25,
                                         y_root=surface.surface.winfo_rooty()+surface.surface.winfo_height()*.35))
            surface.end_drag()
            app.window.update()
            assert 10 < app.feedback_style["x"] < 40 and 10 < app.feedback_style["y"] < 50
            x = app.feedback_style["x"]
            surface.nudge(1, 0)
            assert app.feedback_style["x"] == x+1
            foreground = user.GetForegroundWindow()
            app.preview_feedback()
            editor = app.feedback_editor
            assert editor is not None and editor.timer is None
            assert user.GetWindowLongPtrW(editor.handle, -20) & 0x08000000, "Editor could activate"
            assert not user.GetWindowLongPtrW(editor.handle, -20) & 0x20, "Editor is click-through"
            assert user.GetForegroundWindow() == foreground, "Preview took focus"
            deadline = time.monotonic() + 1.7
            while time.monotonic() < deadline:
                app.window.update()
                time.sleep(.01)
            assert editor.visible and editor.timer is None, "Preview expired during editing"
            app.feedback_vars["font_size"].set(26)
            app.feedback_vars["color"].set("#75E1EB")
            app.feedback_vars["opacity"].set(65)
            assert editor.style == app.feedback_style
            assert surface.style == app.feedback_style
            rect = wintypes.RECT()
            user.GetWindowRect(editor.handle, ctypes.byref(rect))
            editor.begin_drag(SimpleNamespace(x_root=rect.left+12, y_root=rect.top+12))
            area, _ = editor.work_area()
            editor.drag(SimpleNamespace(x_root=area[2]+500, y_root=area[1]-500))
            editor.end_drag()
            assert (app.feedback_style["x"], app.feedback_style["y"]) == (100, 0)
            assert user.GetForegroundWindow() == foreground
            app.flush_feedback_style()
            assert Preferences(path).values["feedback_style"] == editor.style
            # Normal feedback remains a timed, click-through overlay.
            app.show_overlay("音量 50%")
            assert app.overlay is not editor and app.overlay.timer is not None
            assert user.GetWindowLongPtrW(app.overlay.handle, -20) & 0x20
            app.tabs.select(0)
            app.window.update()
            assert app.feedback_editor is None
            app.tabs.select(3)
            app.preview_feedback()
            app.window.withdraw()
            app.window.update()
            assert app.feedback_editor is None
            app.window.deiconify()
            app.window.update()
            app.preview_feedback()
            app.show_feedback.set(False)
            app.change_feedback_enabled()
            assert app.feedback_editor is None and app.overlay is None
            old = dict(app.feedback_style)
            surface.nudge(20, 20)
            assert app.feedback_style == old, "Disabled preview still edited settings"
            app.show_feedback.set(True)
            app.change_feedback_enabled()
            for _ in range(20):
                app.preview_feedback()
                app.preview_feedback()
            assert app.feedback_editor is None
            assert not errors, errors
            report = {"inline_drag_and_keyboard_nudge": True, "persistent_desktop_preview": True,
                      "style_changes_live": True, "drag_bounds_and_save": True, "focus_preserved": True,
                      "normal_feedback_stays_click_through": True, "leave_hide_disable_cleanup": True,
                      "preview_toggle_repeated": 20}
        finally:
            app.end_feedback_preview()
            if app.overlay:
                app.overlay.close()
            for timer in app.window.tk.splitlist(app.window.tk.call("after", "info")):
                app.window.after_cancel(timer)
            app.window.destroy()
        assert not errors, errors
        (ROOT / ".tooling/subtitle-editor-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
