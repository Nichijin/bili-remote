import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "BiliRemote-Desktop", "--distpath", str(ROOT / "dist"),
        "--icon", str(ROOT / "desktop/assets/bili-remote.ico"),
        "--manifest", str(ROOT / "desktop/assets/app.manifest"),
        "--workpath", str(ROOT / ".tooling/pyinstaller"), "--specpath", str(ROOT / ".tooling"),
        "--add-data", str(ROOT / "android/app/src/main/assets") + ";android/app/src/main/assets", "--add-data", str(ROOT / "README.md") + ";.",
        "--add-data", str(ROOT / "docs") + ";docs",
        "--add-data", str(ROOT / "CHANGELOG.md") + ";.",
        "--add-data", str(ROOT / "desktop/assets/bili-remote.ico") + ";desktop/assets",
        "--add-data", str(ROOT / "desktop/assets/player.js") + ";desktop/assets",
        "--hidden-import", "winrt.windows.foundation.collections", "--hidden-import", "winrt.windows.media",
        "--hidden-import", "winrt.windows.foundation", "--exclude-module", "comtypes.test", "--optimize", "2",
        str(ROOT / "run_desktop.py"),
    ], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
