import subprocess
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        "--contents-directory", "_internal",
        "--name", "BiliRemote-Desktop", "--distpath", str(ROOT / ".tooling/desktop-bundle"),
        "--icon", str(ROOT / "desktop/assets/bili-remote.ico"),
        "--manifest", str(ROOT / "desktop/assets/app.manifest"),
        "--workpath", str(ROOT / ".tooling/pyinstaller"), "--specpath", str(ROOT / ".tooling"),
        "--add-data", str(ROOT / "android/app/src/main/assets") + ";android/app/src/main/assets",
        "--add-data", str(ROOT / "desktop/assets/bili-remote.ico") + ";desktop/assets",
        "--add-data", str(ROOT / "desktop/assets/player.js") + ";desktop/assets",
        "--hidden-import", "winrt.windows.foundation.collections", "--hidden-import", "winrt.windows.media",
        "--hidden-import", "winrt.windows.foundation", "--exclude-module", "comtypes.test",
        "--exclude-module", "tkinter", "--exclude-module", "PySide6.QtTest",
        "--exclude-module", "PySide6.QtQml", "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtOpenGL",
        "--exclude-module", "PySide6.QtNetwork", "--optimize", "2",
        str(ROOT / "run_desktop.py"),
    ], cwd=ROOT, check=True)
    bundle = ROOT / ".tooling/desktop-bundle/BiliRemote-Desktop"
    dist = (ROOT / "dist").resolve()
    dist.mkdir(exist_ok=True)
    runtime = (dist / "_internal").resolve()
    assert runtime.parent == dist and runtime.name == "_internal" and runtime.is_relative_to(ROOT.resolve())
    print("Replacing build runtime within:", runtime, flush=True)
    if runtime.exists():
        shutil.rmtree(runtime)
    shutil.copytree(bundle / "_internal", runtime)
    shutil.copy2(bundle / "BiliRemote-Desktop.exe", dist / "BiliRemote-Desktop.exe")


if __name__ == "__main__":
    main()
