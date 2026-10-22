"""Small retained Windows page surfaces; transforms preserve live input."""
import contextlib
import ctypes
from ctypes import wintypes
import sys


class PageCompositor:
    """Let Windows retain the complete child page instead of repainting on raise.

    No screenshots, additional windows, render thread or runtime dependencies.
    If child layering is unavailable, restore the original styles and let Tk
    continue to draw the same live controls normally.
    """
    LAYERED = 0x80000

    def __init__(self, pages):
        self.surfaces = {}
        self.user = None
        self.animate = False
        self.paused = set()
        self.motion_clock = None
        self.motion_clock_active = False
        if sys.platform != "win32":
            return
        try:
            user = ctypes.WinDLL("user32", use_last_error=True)
            pointer = ctypes.sizeof(ctypes.c_void_p) == 8
            self.get_style = user.GetWindowLongPtrW if pointer else user.GetWindowLongW
            self.set_style = user.SetWindowLongPtrW if pointer else user.SetWindowLongW
            for function in (self.get_style, self.set_style):
                function.restype = ctypes.c_ssize_t
            self.get_style.argtypes = [wintypes.HWND, ctypes.c_int]
            self.set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            user.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD]
            user.SetLayeredWindowAttributes.restype = wintypes.BOOL
            user.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
            user.SystemParametersInfoW.restype = wintypes.BOOL
            user.IsWindowVisible.argtypes = [wintypes.HWND]
            user.IsWindowVisible.restype = wintypes.BOOL
            user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user.SendMessageW.restype = wintypes.LPARAM
            user.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
            user.RedrawWindow.restype = wintypes.BOOL
            user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user.SetWindowPos.restype = wintypes.BOOL
            self.user = user
            for page in pages:
                handle = page.winfo_id()
                style = self.get_style(handle, -20)
                self.surfaces[page] = handle, style
                self.set_style(handle, -20, style | self.LAYERED)
                if not self.opacity(page, 255):
                    raise OSError("Child page composition unavailable")
            enabled = wintypes.BOOL()
            self.animate = bool(user.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0) and enabled.value)
            with contextlib.suppress(OSError, AttributeError):
                self.motion_clock = ctypes.WinDLL("winmm")
                self.motion_clock.timeBeginPeriod.argtypes = [wintypes.UINT]
                self.motion_clock.timeEndPeriod.argtypes = [wintypes.UINT]
        except (AttributeError, OSError):
            self.close()

    def opacity(self, page, alpha):
        surface = self.surfaces.get(page)
        return bool(surface and self.user.SetLayeredWindowAttributes(surface[0], 0, alpha, 2))

    def move(self, page, y):
        surface = self.surfaces.get(page)
        # Only translate the retained HWND surface. No geometry manager call,
        # child resize or image generation belongs in an animation frame.
        return bool(surface and self.user.SetWindowPos(surface[0], None, 0, round(y), 0, 0, 0x15))

    def begin_motion(self):
        # Request precise timers only while moving; the default coarse Windows
        # timer can round one frame into two. Balance on completion/cancel/hide.
        if self.motion_clock and not self.motion_clock_active:
            self.motion_clock_active = self.motion_clock.timeBeginPeriod(1) == 0

    def end_motion(self):
        if self.motion_clock_active:
            self.motion_clock.timeEndPeriod(1)
            self.motion_clock_active = False

    def pause_layout(self):
        # Batch the intermediate geometry paints, rather than submitting a
        # complete layered surface for every child resize. Tk still lays out
        # all live controls; idle or navigation resumes painting without a wait.
        for handle, _ in self.surfaces.values():
            if handle not in self.paused and self.user.IsWindowVisible(handle):
                self.paused.add(handle)
                self.user.SendMessageW(handle, 11, 0, 0)  # WM_SETREDRAW

    def resume_layout(self):
        for handle in self.paused:
            self.user.SendMessageW(handle, 11, 1, 0)
            # Invalidate together; do not synchronously paint each child HWND.
            self.user.RedrawWindow(handle, None, None, 0x485)
        self.paused.clear()

    def close(self):
        self.end_motion()
        self.resume_layout()
        for handle, style in self.surfaces.values():
            with contextlib.suppress(OSError):
                self.set_style(handle, -20, style)
        self.surfaces.clear()
        self.animate = False
