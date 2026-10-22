"""Measure a packaged companion under isolated background instances.

Includes the one-file launcher's process; never launches a player or modifies
the installed app. Reports working set AND private bytes, without trimming.
"""
import argparse
import json
import os
import socket
import statistics
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]


def measure(executable, repeats=3):
    runs = []
    for _ in range(repeats):
        with tempfile.TemporaryDirectory(prefix="bili-memory-") as directory:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            identity = "BiliRemote-MemoryTest-" + uuid.uuid4().hex
            env = {**os.environ, "BILI_REMOTE_INSTANCE_NAME": identity, "BILI_REMOTE_WINDOW_TITLE": identity,
                   "BILI_REMOTE_DATA_DIR": directory, "BILI_REMOTE_BIND_HOST": "127.0.0.1",
                   "BILI_REMOTE_PORT": str(port), "BILI_REMOTE_DISCOVERY_PORT": "0"}
            process = subprocess.Popen([str(executable), "--background"], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Companion exited before measurement")
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=.1):
                            break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise TimeoutError("Companion service did not start")
                time.sleep(5)
                root = psutil.Process(process.pid)
                snapshots = []
                for _ in range(6):
                    processes = [root, *root.children(recursive=True)]
                    memory = [p.memory_info() for p in processes]
                    snapshots.append({"working_set_mib": sum(m.rss for m in memory) / 2**20,
                                      "private_bytes_mib": sum(m.private for m in memory) / 2**20,
                                      "processes": len(memory)})
                    time.sleep(.5)
                runs.append({key: round(statistics.median(s[key] for s in snapshots), 3) for key in snapshots[0]})
            finally:
                if process.poll() is None:
                    subprocess.run([str(executable), "--quit"], env=env, creationflags=subprocess.CREATE_NO_WINDOW, timeout=15, check=True)
                    process.wait(timeout=15)
    return {"executable": str(executable), "scenario": "background, service online, no phone or player",
            "working_set_mib": round(statistics.median(run["working_set_mib"] for run in runs), 3),
            "private_bytes_mib": round(statistics.median(run["private_bytes_mib"] for run in runs), 3), "runs": runs}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 5:
        parser.error("repeats must be between 1 and 5")
    report = measure(args.executable.resolve(), args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
