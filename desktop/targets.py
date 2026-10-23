"""Target identities and read-only browser window evidence for automatic routing."""
import ctypes
from ctypes import wintypes
import sys

import psutil


def browser_name(source):
    source = source.lower()
    if source in {"msedge", "msedge.exe"} or source.startswith("microsoft.microsoftedge."):
        return "Edge"
    if source in {"chrome", "chrome.exe"} or source.startswith("chrome."):
        return "Chrome"
    return ""


def browser_windows():
    """Titles stay local and transient; only Bilibili evidence leaves this helper.

    Media sessions expose an application ID, not a tab URL. Auto routing requires
    a Bilibili window AND a matching media title; explicit selection can use any
    browser media session and is labelled as application-level control.
    """
    if sys.platform != "win32":
        return {"foreground": None, "windows": []}
    from .detection import is_client
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    foreground = user.GetForegroundWindow()
    result = {"foreground": None, "windows": []}
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback, wintypes.LPARAM]

    @callback
    def collect(hwnd, param):
        if not user.IsWindowVisible(hwnd):
            return True
        try:
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            source = psutil.Process(pid.value).name().lower()
            if not browser_name(source):
                return True
            length = min(4096, user.GetWindowTextLengthW(hwnd))
            title = ctypes.create_unicode_buffer(length+1)
            user.GetWindowTextW(hwnd, title, length+1)
            row = {"source": source, "pid": pid.value, "bilibili": is_client(title.value), "title": title.value}
            result["windows"].append(row)
            if hwnd == foreground:
                result["foreground"] = row
        except (psutil.Error, OSError):
            pass
        return True

    user.EnumWindows(collect, 0)
    return result


def target_info(source, channel, **extra):
    name = browser_name(source) or "哔哩哔哩客户端"
    suffix = "专用网页" if channel == "web" else "系统媒体 · 功能取决于接口"
    return {"name": name+" · "+suffix, "source": source, "channel": channel, **extra}


class NativeRoute:
    """Freeze one selected media session through a hold, never re-run auto choice."""
    def __init__(self, controller, session_id):
        self.controller, self.session_id = controller, session_id

    @property
    def boost(self):
        return self.controller.boost

    async def execute(self, message, owner):
        try:
            return await self.controller.execute({**message, "session_id": self.session_id}, owner)
        except RuntimeError as exc:
            raise RuntimeError(target_info(self.session_id, "system")["name"]+" · "+str(exc)) from exc
