import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.release_files import release_paths


def main(root=ROOT):
    root = Path(root)
    paths = release_paths(root)
    files = [(path.name, path) for path in (paths["installer"], paths["apk"], root / "README.md", root / "CHANGELOG.md")]
    for _, path in files:
        if not path.is_file():
            raise FileNotFoundError(f"缺少当前版本文件 {path.name}，请先完成两端构建。")
    files.extend((path.relative_to(root).as_posix(), path) for path in sorted((root / "docs").rglob("*")) if path.is_file())
    checksums = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files}
    paths["checksums"].write_text(json.dumps(checksums, ensure_ascii=False, indent=2), encoding="utf-8")
    destination = paths["kit"]
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in files:
            archive.write(path, name)
        archive.write(paths["checksums"], paths["checksums"].name)
    print(destination)


if __name__ == "__main__":
    main()
