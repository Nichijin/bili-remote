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
