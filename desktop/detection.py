"""Read running executable and registered package versions without launching players."""
import ctypes
import re
import time
import winreg
from ctypes import wintypes
from pathlib import Path

import psutil
from .targets import browser_name

CLIENT_PATTERN = re.compile(r"bilibili|哔哩|(?:^|[^a-z])(?:bili(?:uwp|app|lite|win|cast|desktop)?|bbll)(?=[^a-z]|$)", re.I)


def is_client(name):
    return bool(CLIENT_PATTERN.search(name)) and not re.search(r"biliremote|biligestureremote|手势遥控", name, re.I)


def file_version(path):
    library = ctypes.WinDLL("version", use_last_error=True)
    library.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    library.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    library.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    library.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    size = library.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return "未知"
    buffer = ctypes.create_string_buffer(size)
    if not library.GetFileVersionInfoW(str(path), 0, size, buffer):
        return "未知"
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not library.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)) or length.value < 52:
        return "未知"
    info = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
    high, low = info[2], info[3]
    return f"{high >> 16}.{high & 65535}.{low >> 16}.{low & 65535}"


def registry_value(key, name, default=""):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return default


def installed_clients():
    result = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", 0, winreg.KEY_READ | view) as registry:
                    for i in range(winreg.QueryInfoKey(registry)[0]):
                        try:
                            with winreg.OpenKey(registry, winreg.EnumKey(registry, i)) as app:
                                name = registry_value(app, "DisplayName")
                                if is_client(name):
                                    result.append({"name": name, "version": registry_value(app, "DisplayVersion") or "未知", "kind": "client", "path": registry_value(app, "InstallLocation"), "running": False, "source": "已安装"})
                        except OSError:
                            pass
            except OSError:
                pass
    # Current-user package registrations also include Store/UWP clients.
    key = r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as packages:
            for i in range(winreg.QueryInfoKey(packages)[0]):
                full_name = winreg.EnumKey(packages, i)
                if not is_client(full_name):
                    continue
                with winreg.OpenKey(packages, full_name) as app:
                    root = registry_value(app, "PackageRootFolder")
                name, version = full_name.split("_")[:2]
                result.append({"name": name, "version": version, "kind": "client", "path": root, "running": False, "source": "微软商店", "package_id": full_name})
    except OSError:
        pass
    unique = {(row["name"].lower(), row["version"], row["path"].lower()): row for row in result}
    return list(unique.values())


def running_targets():
    result = {}
    # Avoid querying/caching full executable paths for every unrelated process.
    for process in psutil.process_iter(["name"]):
        name = process.info["name"] or ""
        kind = "browser" if name.lower() in {"msedge.exe", "chrome.exe", "firefox.exe"} else "client" if is_client(name) else ""
        if not kind:
            continue
        try:
            path = process.exe() or ""
        except psutil.Error:
            path = ""
        if (kind, path or name) not in result:
            result[kind, path or name] = {"name": name, "version": file_version(path) if path else "未知", "kind": kind, "path": path, "running": True, "source": "运行中"}
    clear_cache = getattr(psutil.process_iter, "cache_clear", None)
    if clear_cache:
        clear_cache()
    return list(result.values())


def combine(installed, running, sessions, browser_connected):
    rows = [dict(row) for row in running]
    for row in installed:
        directory = row.get("path", "").rstrip("\\/").lower()
        matched = next((r for r in rows if r["kind"] == "client" and ((directory and r["path"].lower().startswith(directory + "\\")) or Path(r["name"]).stem.lower() == row["name"].lower())), None)
        if matched:
            matched["installed_name"] = row["name"]
            if row["source"] == "微软商店":
                matched["version"] = row["version"]
                matched["package_id"] = row.get("package_id", "")
        else:
            rows.append(dict(row))
    for session in sessions:
        if is_client(session["id"]) and not any(_matches(row, session["id"]) for row in rows):
            rows.append({"name": session["id"], "version": "未知", "kind": "client", "running": True, "path": "", "source": "媒体会话"})
    for row in rows:
        if row["kind"] == "browser":
            supported = row["name"].lower() in {"msedge.exe", "chrome.exe"}
            matching = [s for s in sessions if browser_name(s["id"]) and browser_name(s["id"]) == browser_name(row["name"])]
            capabilities = " / ".join(title for field, title in (("toggle", "暂停"), ("seek", "进度"), ("speed", "倍速")) if any(s.get(field) for s in matching))
            row["capabilities"] = "专用网页完整控制" if supported and browser_connected == row["name"].lower() else ("系统媒体："+capabilities if capabilities else "可打开专用网页；当前无媒体会话") if supported else "网页完整控制请使用 Edge / Chrome"
        else:
            matching = [s for s in sessions if _matches(row, s["id"])]
            row["session_ids"] = [s["id"] for s in matching]
            names = [("toggle", "暂停"), ("seek", "进度"), ("speed", "倍速")]
            row["capabilities"] = " / ".join(label for field, label in names if any(s.get(field) for s in matching)) or ("未开放控制接口" if matching else "未提供媒体会话" if row["running"] else "请先播放视频")
    return rows


def _matches(row, session_id):
    identifier = session_id.lower()
    stem = Path(row["name"]).stem.lower()
    package = row.get("package_id", "").split("_")[0].lower()
    return row["kind"] == "client" and (stem == Path(session_id).stem.lower() or (package and identifier.startswith(package + "_")) or identifier == row["name"].lower())


class ClientDetector:
    def __init__(self):
        self.installed = []
        self.last_scan = 0

    def scan(self, force=False):
        if force or time.monotonic() - self.last_scan >= 60:
            self.installed = installed_clients()
            self.last_scan = time.monotonic()
        return self.installed, running_targets()
