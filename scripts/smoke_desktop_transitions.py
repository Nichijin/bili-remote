"""Continuously sample the real screen through the current page renderer."""
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
def main():
    subprocess.run([sys.executable, str(ROOT/"scripts/measure_desktop_rendering.py"),
        "--output", str(ROOT/".tooling/desktop-transitions-smoke.json"), "--rounds", "15", "--assert-clean"], cwd=ROOT, check=True)

if __name__ == "__main__":
    main()
