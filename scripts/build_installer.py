import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.release_files import release_paths


def main():
    output = release_paths(ROOT)["installer"]
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", type=Path, default=ROOT / ".tooling/inno/ISCC.exe")
    arguments = parser.parse_args()
    if not arguments.compiler.is_file():
        raise SystemExit("请安装 Inno Setup 6，并通过 --compiler 指定 ISCC.exe 的路径")
    subprocess.run([str(arguments.compiler), str(ROOT / "installer/BiliRemote.iss")], check=True)
    if not output.is_file():
        raise RuntimeError(f"安装器没有生成预期的版本文件：{output.name}")
    print(output)


if __name__ == "__main__":
    main()
