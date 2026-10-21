"""Names for distributable files, derived from the two application versions."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def release_version(root=ROOT):
    root = Path(root)
    android = (root / "android/app/build.gradle").read_text(encoding="utf-8")
    windows = (root / "installer/BiliRemote.iss").read_text(encoding="utf-8")
    android_match = re.search(r"^\s*versionName\s+['\"]([^'\"]+)['\"]", android, re.M)
    windows_match = re.search(r'^\s*#define\s+AppVersion\s+"([^"]+)"', windows, re.M)
    if not android_match or not windows_match:
        raise RuntimeError("无法读取两端版本号，请检查 versionName 和 AppVersion。")
    version = android_match[1]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise RuntimeError("版本号格式无效，不能用于安装包文件名。")
    if version != windows_match[1]:
        raise RuntimeError("安卓与 Windows 版本号不一致，请先同步版本再打包。")
    return version


def release_paths(root=ROOT):
    version = release_version(root)
    dist = Path(root) / "dist"
    return {
        "installer": dist / f"BiliRemote-Setup-{version}.exe",
        "apk": dist / f"bili-remote-{version}.apk",
        "kit": dist / f"bili-remote-kit-{version}.zip",
        "checksums": dist / f"SHA256-{version}.json",
    }
