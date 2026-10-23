"""Run the maintained Qt regression checks under the historical smoke entry point."""
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", 'tests/test_gui.py' , "-k", 'preview or color or scrolled'], cwd=ROOT))
