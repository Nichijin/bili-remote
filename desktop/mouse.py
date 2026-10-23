"""Authenticated mouse sessions; Windows input stays separate from media routing."""
import ctypes
import math
import os
import secrets
import time
from contextlib import contextmanager
from ctypes import wintypes


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", INPUTUNION)]


def absolute_point(x, y, bounds):
    """Map physical pixel centres onto SendInput's entire virtual desktop."""
    left, top, width, height = bounds
    x = max(left, min(left + width - 1, x))
    y = max(top, min(top + height - 1, y))
    return (min(65535, math.floor((x - left + .5) * 65536 / width)),
            min(65535, math.floor((y - top + .5) * 65536 / height)))


class WindowsMouse:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("鼠标模式需要 Windows 电脑端")
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.api.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.api.SendInput.restype = wintypes.UINT
        self.api.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.api.GetCursorPos.restype = wintypes.BOOL
        self.api.GetSystemMetrics.argtypes = [ctypes.c_int]
        self.api.GetSystemMetrics.restype = ctypes.c_int
        self.api.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.api.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p

    @contextmanager
    def physical_pixels(self):
        previous = self.api.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        try:
            yield
        finally:
            if previous:
                self.api.SetThreadDpiAwarenessContext(previous)

    def inject(self, *events):
        inputs = (INPUT * len(events))(*(INPUT(type=0, mi=event) for event in events))
        count = self.api.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT))
        if count != len(inputs):
            raise RuntimeError("Windows 未接受鼠标输入；锁屏、安全桌面或权限更高的窗口无法由普通权限遥控")

    def move(self, dx, dy):
        if not dx and not dy:
            return
        with self.physical_pixels():
            point = wintypes.POINT()
            if not self.api.GetCursorPos(ctypes.byref(point)):
                raise RuntimeError("无法读取鼠标位置，请确认电脑桌面已解锁")
            bounds = tuple(self.api.GetSystemMetrics(index) for index in (76, 77, 78, 79))
            if bounds[2] <= 0 or bounds[3] <= 0:
                raise RuntimeError("无法读取电脑显示区域")
            x, y = absolute_point(point.x + dx, point.y + dy, bounds)
            # Absolute movement bypasses Windows relative pointer acceleration:
            # the phone's continuous gain must be applied exactly once.
            self.inject(MOUSEINPUT(dx=x, dy=y, dwFlags=0x0001 | 0x8000 | 0x4000))

    def click(self, button):
        down, up = (0x0002, 0x0004) if button == "left" else (0x0008, 0x0010)
        try:
            # A click is one atomic batch; no remote message holds a button down.
            self.inject(MOUSEINPUT(dwFlags=down), MOUSEINPUT(dwFlags=up))
        except RuntimeError:
            # A partial injection must never leave our synthetic button pressed.
            try:
                self.inject(MOUSEINPUT(dwFlags=up))
            except RuntimeError:
                pass
            raise


class MouseController:
    LEASE_SECONDS = 4

    def __init__(self, backend=None, clock=time.monotonic):
        self.backend, self.clock = backend, clock
        self.owner = self.session = None
        self.last_input = 0

    def release(self, owner):
        if self.owner == owner:
            self.owner = self.session = None

    def expire(self):
        if self.owner is not None and self.clock() - self.last_input > self.LEASE_SECONDS:
            self.release(self.owner)
            return True
        return False

    def execute(self, message, owner):
        self.expire()
        kind = message["cmd"]
        if kind == "mouse_start":
            if self.owner is not None and self.owner != owner:
                raise RuntimeError("另一台手机正在使用鼠标模式，请先在该手机退出")
            if self.backend is None:
                self.backend = WindowsMouse()
            self.owner, self.session = owner, secrets.token_hex(12)
            self.last_input = self.clock()
            return {"mouse_session": self.session}
        matches = self.owner == owner and self.session == message["mouse_session"]
        if kind == "mouse_end":
            if matches:
                self.release(owner)
            return {}
        if not matches:
            raise RuntimeError("鼠标模式已结束，请重新进入")
        self.last_input = self.clock()
        if kind == "mouse_move":
            self.backend.move(message["dx"], message["dy"])
        elif kind == "mouse_click":
            self.backend.click(message["button"])
        return {}
