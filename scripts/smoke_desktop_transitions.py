"""Exercise live Windows hit testing during fades, cancellation and cached resize.

An isolated window is raised briefly; no player, network or production data.
A real mouse click exercises Windows routing; the pointer is restored afterward.
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from tkinter import ttk
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.gui import Companion
from desktop.rendering import PageCompositor


class Preview(Companion):
    def start(self):
        pass


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def main():
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.WindowFromPoint.argtypes, user.WindowFromPoint.restype = [wintypes.POINT], wintypes.HWND
    user.GetLayeredWindowAttributes.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.POINTER(wintypes.BYTE), ctypes.POINTER(wintypes.DWORD)]
    user.GetGuiResources.argtypes, user.GetGuiResources.restype = [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD
    user.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    cursor = wintypes.POINT()
    user.GetCursorPos(ctypes.byref(cursor))
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    with tempfile.TemporaryDirectory(prefix="bili-transitions-") as directory:
        with patch.dict(os.environ, {"BILI_REMOTE_DATA_DIR": directory}), patch("desktop.gui.startup_enabled", return_value=False):
            app = Preview(hidden=True)
        errors = []
        app.window.report_callback_exception = lambda *error: errors.append(str(error[1]))
        try:
            app.window.geometry("1040x780+30+30")
            app.window.attributes("-topmost", True)
            app.window.deiconify()
            app.window.lift()
            app.window.focus_force()
            app.window.update()
            assert len(app.tabs.compositor.surfaces) == 4, "Windows page surfaces unavailable"
            app.tabs.compositor.animate = True  # Test fades even if the OS prefers reduced motion.
            switch = next(w for w in walk(app.tabs.pages[3]) if isinstance(w, ttk.Checkbutton)
                          and str(w.cget("variable")) == str(app.close_to_tray))
            app.tabs.select(3)
            app.window.update()
            assert app.tabs.transition_timer is not None, "No fade to exercise"
            previous = app.close_to_tray.get()
            point = wintypes.POINT(switch.winfo_rootx() + switch.winfo_width() // 2,
                                  switch.winfo_rooty() + switch.winfo_height() // 2)
            hit = user.WindowFromPoint(point)
            name = ctypes.create_unicode_buffer(256)
            user.GetClassNameW(wintypes.HWND(hit), name, 256)
            desktop_locked = name.value.startswith("LockScreen")
            if desktop_locked:
                # A locked Windows session cannot route physical input to the
                # app. Exercise Tk input but report native routing as untested.
                switch.event_generate("<ButtonPress-1>", x=8, y=8)
                switch.event_generate("<ButtonRelease-1>", x=8, y=8)
            else:
                assert hit == switch.winfo_id(), f"Fade intercepted input: {hit} != {switch.winfo_id()}"
                user.SetCursorPos(point.x, point.y)
                app.window.update()
                user.mouse_event(2, 0, 0, 0, 0)
                user.mouse_event(4, 0, 0, 0, 0)
            app.window.update()
            assert app.close_to_tray.get() != previous, "Immediate native click was ignored"
            assert app.tabs.transition_timer is not None, "Click only worked after animation ended"
            # Repeated changes must reuse controls and a single transition timer.
            identities = {str(w): w.winfo_id() for w in walk(app.tabs)}
            images = app.window.tk.call("image", "names")
            gdi_before = user.GetGuiResources(kernel.GetCurrentProcess(), 0)
            for _ in range(30):
                for index in (0, 1, 2, 3):
                    app.tabs.select(index)
                    app.window.update()
            timer = app.tabs.transition_timer
            app.tabs.select(3)
            assert app.tabs.transition_timer == timer, "Selecting the same menu restarted its transition"
            deadline = time.monotonic() + 2
            while app.tabs.transition_timer is not None and time.monotonic() < deadline:
                app.window.update()
                time.sleep(.002)
            assert app.tabs.transition_timer is None
            for handle, _ in app.tabs.compositor.surfaces.values():
                alpha, flags = wintypes.BYTE(), wintypes.DWORD()
                assert user.GetLayeredWindowAttributes(handle, None, ctypes.byref(alpha), ctypes.byref(flags))
                assert alpha.value == 255, "A cancelled page remained translucent"
            assert identities == {str(w): w.winfo_id() for w in walk(app.tabs)}
            assert images == app.window.tk.call("image", "names"), "Transitions allocated more images"
            gdi_delta = user.GetGuiResources(kernel.GetCurrentProcess(), 0) - gdi_before
            assert gdi_delta < 8, f"GDI resources grew by {gdi_delta}"
            # Every page has its new geometry before navigation; no Configure
            # events or layout work should be deferred until a menu is clicked.
            app.window.geometry("1120x780+30+30")
            app.window.update()
            size = min(app.tabs.winfo_width(), app.tabs.max_page_width), app.tabs.winfo_height()
            assert all((page.winfo_width(), page.winfo_height()) == size for page in app.tabs.pages)
            configured = []
            for page in app.tabs.pages:
                for widget in walk(page):
                    widget.bind("<Configure>", lambda event: configured.append(str(event.widget)), add=True)
            resized_switches = []
            for index in (0, 1, 2, 3):
                started = time.perf_counter()
                app.tabs.select(index)
                app.window.update()
                resized_switches.append(round((time.perf_counter() - started) * 1000, 3))
            assert not configured, "Navigation triggered a deferred layout"
            point = wintypes.POINT(switch.winfo_rootx() + switch.winfo_width() // 2,
                                  switch.winfo_rooty() + switch.winfo_height() // 2)
            if not desktop_locked:
                assert user.WindowFromPoint(point) == switch.winfo_id(), "Resizing broke native control input"
            app.tabs.select(0)
            app.window.withdraw()
            app.window.update()
            assert app.tabs.transition_timer is None and not app.tabs.compositor.paused
            app.window.deiconify()
            app.window.update()
            app.tabs.compositor.animate = False
            app.tabs.select(3)
            app.window.update()
            assert app.tabs.transition_timer is None, "Reduced motion still animated"
            app.tabs.compositor.close()
            app.tabs.select(0)
            app.window.update()
            assert app.tabs.select() == str(app.tabs.pages[0]), "Fallback failed"
            report = {"native_hit_test_and_click_during_fade": not desktop_locked,
                      "native_input_limitation": "Windows session locked" if desktop_locked else None,
                      "tk_input_during_fade": True, "rapid_switches": 120,
                      "cancelled_pages_opaque": True, "same_page_no_restart": True,
                      "controls_and_images_reused": True, "gdi_object_delta": gdi_delta,
                      "all_pages_prepared_after_resize": True, "navigation_configure_events": len(configured),
                      "post_resize_switches_ms": resized_switches, "hide_cancels_transition": True,
                      "reduced_motion_and_native_fallback": True}
        finally:
            user.SetCursorPos(cursor.x, cursor.y)
            # Destroy during an outstanding transition and geometry update.
            app.tabs.compositor = PageCompositor(app.tabs.pages)
            app.tabs.compositor.animate = True
            app.tabs.select(1)
            app.window.update()
            assert app.tabs.transition_timer is not None
            app.window.geometry("1100x780")
            app.window.destroy()
        assert not errors, errors
        report["destroy_without_pending_callbacks"] = True
        (ROOT / ".tooling/desktop-transitions-smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
