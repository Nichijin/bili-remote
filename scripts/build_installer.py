import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", type=Path, default=ROOT / ".tooling/inno/ISCC.exe")
    arguments = parser.parse_args()
    if not arguments.compiler.is_file():
        raise SystemExit("请安装 Inno Setup 6，并通过 --compiler 指定 ISCC.exe 的路径")
    subprocess.run([str(arguments.compiler), str(ROOT / "installer/BiliRemote.iss")], check=True)


if __name__ == "__main__":
    main()
