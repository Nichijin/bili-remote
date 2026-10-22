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


class MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


class OperationOverlay:
    def __init__(self, parent, style=None):
        self.parent = parent
        self.style = normalize_style(style)
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
        style = self.user.GetWindowLongPtrW(self.handle, -20)
        self.user.SetWindowLongPtrW(self.handle, -20, style | 0x08000000 | 0x00000080 | 0x00000020)
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
        self.label.configure(fg=self.style["color"], font=("Microsoft YaHei", -round(self.style["font_size"] * dpi / 72)),
                             padx=round(20 * scale), pady=round(10 * scale), wraplength=max(60, area[2] - area[0] - round(96 * scale)))
        self.window.update_idletasks()
        width, height, x, y = overlay_geometry(area, (self.window.winfo_reqwidth(), self.window.winfo_reqheight()), self.style["x"], self.style["y"])
        self.window.geometry(f"{width}x{height}")
        self.user.SetWindowPos(self.handle, ctypes.c_void_p(-1), x, y, width, height, 0x0010 | 0x0040)

    def show(self, text, success=True):
        self.label.configure(text=text if success else "失败 · " + text)
        self.visible = True
        self.position()
        self.user.ShowWindow(self.handle, 4)  # SW_SHOWNOACTIVATE
        if self.timer:
            self.window.after_cancel(self.timer)
        self.timer = self.window.after(1500, self.hide)

    def hide(self):
        if self.timer:
            self.window.after_cancel(self.timer)
        self.timer = None
        self.visible = False
        self.user.ShowWindow(self.handle, 0)

    def close(self):
        if self.timer:
            self.window.after_cancel(self.timer)
        self.window.destroy()
