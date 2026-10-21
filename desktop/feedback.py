"""A small non-activating Windows overlay; called only from Tk's UI thread."""
import ctypes
import tkinter as tk
from ctypes import wintypes


class OperationOverlay:
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        # Tk otherwise inherits the parent's title, making FindWindow-based
        # single-instance/quit messages land on this overlay instead of the app.
        self.window.title("BiliRemote operation feedback")
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", .94)
        self.window.configure(bg="#191D2B")
        self.label = tk.Label(self.window, bg="#191D2B", fg="white", font=("Microsoft YaHei", 17), padx=28, pady=14)
        self.label.pack()
        self.timer = None
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
        style = self.user.GetWindowLongPtrW(self.handle, -20)
        self.user.SetWindowLongPtrW(self.handle, -20, style | 0x08000000 | 0x00000080 | 0x00000020)

    def show(self, text, success=True):
        self.label.configure(text=text, fg="#FFFFFF" if success else "#FFB0BF")
        self.window.update_idletasks()
        width, height = self.window.winfo_reqwidth(), self.window.winfo_reqheight()
        x = (self.window.winfo_screenwidth() - width) // 2
        y = self.window.winfo_screenheight() - height - 110
        self.window.geometry(f"{width}x{height}+{x}+{y}")
        self.user.ShowWindow(self.handle, 4)  # SW_SHOWNOACTIVATE
        self.user.SetWindowPos(self.handle, ctypes.c_void_p(-1), x, y, width, height, 0x0010 | 0x0040)
        if self.timer:
            self.window.after_cancel(self.timer)
        self.timer = self.window.after(1500, self.hide)

    def hide(self):
        self.timer = None
        self.user.ShowWindow(self.handle, 0)

    def close(self):
        if self.timer:
            self.window.after_cancel(self.timer)
        self.window.destroy()
