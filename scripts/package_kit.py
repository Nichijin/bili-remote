import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    installer = ROOT / "dist/BiliRemote-Setup.exe"
    desktop = installer if installer.is_file() else ROOT / "dist/BiliRemote-Desktop.exe"
    files = [(path.name, path) for path in (desktop, ROOT / "dist/bili-remote-debug.apk", ROOT / "README.md", ROOT / "CHANGELOG.md")]
    files.extend((path.relative_to(ROOT).as_posix(), path) for path in sorted((ROOT / "docs").rglob("*")) if path.is_file())
    checksums = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files if path.is_file()}
    (ROOT / "dist/SHA256.json").write_text(json.dumps(checksums, ensure_ascii=False, indent=2), encoding="utf-8")
    destination = ROOT / "dist/bili-remote-kit.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in files:
            if not path.is_file():
                continue
            archive.write(path, name)
        archive.write(ROOT / "dist/SHA256.json", "SHA256.json")
    print(destination)


if __name__ == "__main__":
    main()
