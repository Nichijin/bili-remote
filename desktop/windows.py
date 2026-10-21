"""Small Windows integrations; no service or administrator rights required."""
import ctypes
import json
import os
import subprocess
import sys
import winreg
from ctypes import wintypes
from pathlib import Path

APP_NAME = os.environ.get("BILI_REMOTE_INSTANCE_NAME", "BiliGestureRemote")
WINDOW_TITLE = os.environ.get("BILI_REMOTE_WINDOW_TITLE", "哔哩哔哩手势遥控 · 电脑端")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVAL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{36D44CC8-86ED-4E16-92B9-C3F073F4EE78}_is1"
WM_SHOW = 0x8000 + 82
WM_QUIT = 0x8000 + 83


def icon_path():
    return Path(__file__).resolve().parent / "assets" / "bili-remote.ico"


def data_directory():
    return Path(os.environ.get("BILI_REMOTE_DATA_DIR") or (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME))


def startup_command():
    if getattr(sys, "frozen", False):
        return subprocess.list2cmdline([sys.executable, "--background"])
    return subprocess.list2cmdline([sys.executable, str(Path(__file__).resolve().parents[1] / "run_desktop.py"), "--background"])


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            enabled = bool(winreg.QueryValueEx(key, APP_NAME)[0])
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVAL_KEY) as key:
                state = winreg.QueryValueEx(key, APP_NAME)[0]
                if isinstance(state, bytes) and state and state[0] in {3, 7}:
                    return False
        except FileNotFoundError:
            pass
        return enabled
    except FileNotFoundError:
        return False


def set_startup(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
    # Clear only our application's previous disabled/approved state. Windows
    # recreates it for the new Run entry; other startup applications are untouched.
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVAL_KEY, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass


def installed_uninstaller():
    if not getattr(sys, "frozen", False):
        return None
    directory = Path(sys.executable).resolve().parent
    candidate = directory / "unins000.exe"
    if not candidate.is_file():
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            registered = winreg.QueryValueEx(key, "InstallLocation")[0]
        if os.path.normcase(str(Path(registered).resolve())) == os.path.normcase(str(directory)):
            return candidate
    except OSError:
        pass
    return None


class Preferences:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_directory() / "settings.json"
        try:
            self.values = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.values, dict):
                self.values = {}
        except (OSError, ValueError):
            self.values = {}

    def set(self, name, value):
        self.values[name] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.values, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)


class InstanceGuard:
    def __init__(self, name=APP_NAME):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        self.handle = kernel.CreateMutexW(None, False, name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.already_running = ctypes.get_last_error() == 183

    def close(self):
        if self.handle:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(self.handle)
            self.handle = None


def signal_existing(quit=False):
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user.FindWindowW.restype = wintypes.HWND
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    handle = user.FindWindowW(None, WINDOW_TITLE)
    if handle:
        user.PostMessageW(handle, WM_QUIT if quit else WM_SHOW, 0, 0)
    return bool(handle)


class NativeTray:
    """Use the Windows shell directly instead of bundling Pillow/pystray."""
    WM_TRAY = 0x8000 + 81

    def __init__(self, window, post):
        self.window = window
        self.post = post
        self.visible = False
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.shell = ctypes.WinDLL("shell32", use_last_error=True)
        self.wndproc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self.user.GetParent.argtypes = [wintypes.HWND]
        self.user.GetParent.restype = wintypes.HWND
        self.user.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        self.user.LoadIconW.restype = wintypes.HICON
        self.user.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.user.LoadImageW.restype = wintypes.HANDLE
        self.user.DestroyIcon.argtypes = [wintypes.HICON]
        self.user.DestroyIcon.restype = wintypes.BOOL
        self.user.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        self.user.SetWindowLongPtrW.restype = ctypes.c_void_p
        self.user.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user.CallWindowProcW.restype = ctypes.c_ssize_t
        self.user.CreatePopupMenu.restype = wintypes.HMENU
        self.user.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
        self.user.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
        self.user.TrackPopupMenu.restype = wintypes.UINT
        self.user.DestroyMenu.argtypes = [wintypes.HMENU]
        self.user.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
        self.user.RegisterWindowMessageW.restype = wintypes.UINT
        self.taskbar_created = self.user.RegisterWindowMessageW("TaskbarCreated")
        window.update_idletasks()
        self.handle = self.user.GetParent(window.winfo_id()) or window.winfo_id()
        class NotifyIconData(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]
        self.data = NotifyIconData()
        self.data.cbSize = ctypes.sizeof(NotifyIconData)
        self.data.hWnd, self.data.uID = self.handle, 1
        self.data.uFlags, self.data.uCallbackMessage = 1 | 2 | 4, self.WM_TRAY
        self.owned_icon = self.user.LoadImageW(None, str(icon_path()), 1, self.user.GetSystemMetrics(49), self.user.GetSystemMetrics(50), 0x0010)
        self.data.hIcon = self.owned_icon or self.user.LoadIconW(None, ctypes.c_void_p(32512))
        self.data.szTip = "哔哩哔哩手势遥控 · 双击打开"
        self.shell.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NotifyIconData)]
        self.shell.Shell_NotifyIconW.restype = wintypes.BOOL
        self.callback = self.wndproc_type(self._procedure)
        ctypes.set_last_error(0)
        self.previous = self.user.SetWindowLongPtrW(self.handle, -4, ctypes.cast(self.callback, ctypes.c_void_p))
        if not self.previous:
            error = ctypes.get_last_error()
            if self.owned_icon:
                self.user.DestroyIcon(self.owned_icon)
                self.owned_icon = None
            raise ctypes.WinError(error)
        self.add()

    def add(self):
        self.visible = bool(self.shell.Shell_NotifyIconW(0, ctypes.byref(self.data)))

    def _procedure(self, handle, message, wparam, lparam):
        try:
            if message == WM_SHOW:
                self.post("show")
                return 0
            if message == WM_QUIT:
                self.post("quit")
                return 0
            if message == self.taskbar_created:
                self.add()
            if message == self.WM_TRAY:
                if lparam == 0x0203:  # WM_LBUTTONDBLCLK
                    self.post("show")
                elif lparam == 0x0205:  # WM_RBUTTONUP
                    point = wintypes.POINT()
                    self.user.GetCursorPos(ctypes.byref(point))
                    menu = self.user.CreatePopupMenu()
                    try:
                        self.user.AppendMenuW(menu, 0, 1, "打开设置")
                        self.user.AppendMenuW(menu, 0, 2, "退出")
                        self.user.SetForegroundWindow(handle)
                        chosen = self.user.TrackPopupMenu(menu, 0x0100 | 0x0080 | 0x0002, point.x, point.y, 0, handle, None)
                        if chosen:
                            self.post("show" if chosen == 1 else "quit")
                        self.user.PostMessageW(handle, 0, 0, 0)
                    finally:
                        self.user.DestroyMenu(menu)
                return 0
        except Exception:
            logging = __import__("logging")
            logging.getLogger(__name__).exception("托盘操作失败")
        return self.user.CallWindowProcW(self.previous, handle, message, wparam, lparam)

    def close(self):
        if self.visible:
            self.shell.Shell_NotifyIconW(2, ctypes.byref(self.data))
            self.visible = False
        if self.previous:
            self.user.SetWindowLongPtrW(self.handle, -4, self.previous)
            self.previous = None
        if self.owned_icon:
            self.user.DestroyIcon(self.owned_icon)
            self.owned_icon = None
