"""A small non-activating Windows overlay; called only from Tk's UI thread."""
import ctypes
import math
import re
import tkinter as tk
from ctypes import wintypes

DEFAULT_STYLE = {"x": 50, "y": 88, "font_size": 17, "color": "#FFFFFF", "opacity": 94}


def normalize_style(value):
    value = value if isinstance(value, dict) else {}
    result = dict(DEFAULT_STYLE)
    for key, low, high in (("x", 0, 100), ("y", 0, 100), ("font_size", 10, 64), ("opacity", 10, 100)):
        number = value.get(key)
        if not isinstance(number, bool) and isinstance(number, (int, float)) and math.isfinite(number):
            result[key] = max(low, min(high, round(number)))
    color = value.get("color")
    if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        result["color"] = color.upper()
    return result


def overlay_geometry(work_area, size, x, y):
    left, top, right, bottom = work_area
    width, height = min(size[0], right - left), min(size[1], bottom - top)
    return width, height, round(left + (right - left - width) * x / 100), round(top + (bottom - top - height) * y / 100)


def overlay_position(work_area, size, left, top):
    """Inverse placement used by both live desktop and miniature drag editors."""
    x1, y1, x2, y2 = work_area
    return tuple(max(0, min(100, round((value - origin) * 100 / available))) if available > 0 else 50
                 for value, origin, available in ((left, x1, x2 - x1 - size[0]), (top, y1, y2 - y1 - size[1])))


class MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


class OperationOverlay:
    def __init__(self, parent, style=None, on_drag=None):
        self.parent = parent
        self.style = normalize_style(style)
        self.on_drag = on_drag
        self.drag_origin = None
        self.measurement = None
        self.window = tk.Toplevel(parent)
        # Tk otherwise inherits the parent's title, making FindWindow-based
        # single-instance/quit messages land on this overlay instead of the app.
        self.window.title("BiliRemote operation feedback")
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#191D2B")
        self.label = tk.Label(self.window, bg="#191D2B", justify="center")
        self.label.pack()
        if on_drag:
            self.label.configure(cursor="fleur")
            self.label.bind("<ButtonPress-1>", self.begin_drag)
            self.label.bind("<B1-Motion>", self.drag)
            self.label.bind("<ButtonRelease-1>", self.end_drag)
        self.timer = None
        self.visible = False
        self.window.update_idletasks()
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.GetParent.argtypes = [wintypes.HWND]
        self.user.GetParent.restype = wintypes.HWND
        self.handle = self.user.GetParent(self.window.winfo_id()) or self.window.winfo_id()
        self.user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.user.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self.user.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.user.MonitorFromWindow.restype = wintypes.HANDLE
        self.user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        self.user.GetDpiForWindow.argtypes = [wintypes.HWND]
        self.user.GetDpiForWindow.restype = wintypes.UINT
        self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.set_style(self.style)

    def work_area(self):
        handle = self.user.GetParent(self.parent.winfo_id()) or self.parent.winfo_id()
        monitor = self.user.MonitorFromWindow(handle, 2)
        info = MonitorInfo(); info.size = ctypes.sizeof(info)
        if self.user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            area = (info.work.left, info.work.top, info.work.right, info.work.bottom)
        else:
            area = (0, 0, self.window.winfo_screenwidth(), self.window.winfo_screenheight())
        return area, max(96, self.user.GetDpiForWindow(handle))

    def set_style(self, style):
        self.style = normalize_style(style)
        self.window.attributes("-alpha", self.style["opacity"] / 100)
        if self.visible:
            self.position()

    def position(self):
        area, dpi = self.work_area()
        scale = dpi / 96
        measurement = dpi, area, self.style["font_size"], self.label.cget("text")
        self.label.configure(fg=self.style["color"])
        if measurement != self.measurement:
            self.measurement = measurement
            self.label.configure(font=("Microsoft YaHei UI", -round(self.style["font_size"] * dpi / 72)),
                                 padx=round(20 * scale), pady=round(10 * scale), wraplength=max(60, area[2] - area[0] - round(96 * scale)))
            self.window.update_idletasks()
            self.measured_size = self.window.winfo_reqwidth(), self.window.winfo_reqheight()
        width, height, x, y = overlay_geometry(area, self.measured_size, self.style["x"], self.style["y"])
        self.window.geometry(f"{width}x{height}")
        # Tk applies its own extended styles when the alpha window first maps.
        # Reapply input policy afterward, keeping normal feedback passive and
        # only the explicit edit preview draggable.
        style = self.user.GetWindowLongPtrW(self.handle, -20) | 0x08000000 | 0x00000080
        style = style & ~0x20 if self.on_drag else style | 0x20
        self.user.SetWindowLongPtrW(self.handle, -20, style)
        self.user.SetWindowPos(self.handle, ctypes.c_void_p(-1), x, y, width, height, 0x0010 | 0x0040)

    def show(self, text, success=True):
        self.label.configure(text=text if success else "失败 · " + text)
        self.visible = True
        self.position()
        self.user.ShowWindow(self.handle, 4)  # SW_SHOWNOACTIVATE
        if self.timer:
            self.window.after_cancel(self.timer)
        self.timer = None if self.on_drag else self.window.after(1500, self.hide)

    def begin_drag(self, event):
        rect = wintypes.RECT()
        self.user.GetWindowRect(self.handle, ctypes.byref(rect))
        self.drag_origin = event.x_root - rect.left, event.y_root - rect.top
        self.label.grab_set()

    def drag(self, event):
        if self.drag_origin is None:
            return
        area, _ = self.work_area()
        x, y = overlay_position(area, self.measured_size, event.x_root - self.drag_origin[0], event.y_root - self.drag_origin[1])
        self.on_drag(x, y)

    def end_drag(self, event=None):
        self.drag_origin = None
        if self.label.grab_current() is self.label:
            self.label.grab_release()

    def hide(self):
        if self.on_drag:
            self.end_drag()
        if self.timer:
            self.window.after_cancel(self.timer)
        self.timer = None
        self.visible = False
        self.user.ShowWindow(self.handle, 0)

    def close(self):
        if self.on_drag:
            self.end_drag()
        if self.timer:
            self.window.after_cancel(self.timer)
        self.window.destroy()
