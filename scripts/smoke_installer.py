"""Install/uninstall a uniquely identified build inside .tooling, never the user's app."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import winreg
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.release_files import release_paths
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVAL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"


def read_value(key, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as registry:
            return winreg.QueryValueEx(registry, name)[0]
    except FileNotFoundError:
        return None


def registry_exists(key):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            return True
    except FileNotFoundError:
        return False


def cpu_seconds(processes):
    return sum(p.cpu_times().user + p.cpu_times().system for p in processes)


def main():
    identifier = str(uuid.uuid4())
    identity = "BiliRemote-InstallTest-" + identifier[:8]
    label = "BiliRemote installation test " + identifier[:8]
    test_root = ROOT / ".tooling"
    with tempfile.TemporaryDirectory(prefix="install-smoke-", dir=test_root, delete=False) as temporary:
        folder = Path(temporary).resolve()
        assert folder.is_relative_to(test_root.resolve())
        print("Isolated installer test:", folder, flush=True)
        app_dir, data_dir, output = folder / "app with spaces", folder / "data", folder / "setup"
        output.mkdir()
        report_path = test_root / "installer-test-report.json"
        environment = {**os.environ, "BILI_REMOTE_INSTANCE_NAME": identity, "BILI_REMOTE_WINDOW_TITLE": label, "BILI_REMOTE_DATA_DIR": str(data_dir), "BILI_REMOTE_PORT": "18772", "BILI_REMOTE_DISCOVERY_PORT": "18773", "BILI_REMOTE_BIND_HOST": "127.0.0.1"}
        compiler = test_root / "inno/ISCC.exe"
        result = subprocess.run([str(compiler), "/Q", "/DAppIdentity=" + identity, "/DAppIdentifier={{" + identifier + "}", "/DAppLabel=" + label, "/DUserDataPath=" + str(data_dir), "/DOutputPath=" + str(output), str(ROOT / "installer/BiliRemote.iss")], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        setup = output / release_paths(ROOT)["installer"].name
        subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=" + str(app_dir), "/TASKS=", "/LOG=" + str(folder / "install.log")], check=True, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        exe, uninstaller = app_dir / "BiliRemote-Desktop.exe", app_dir / "unins000.exe"
        uninstall_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{" + identifier + "}_is1"
        assert exe.is_file() and uninstaller.is_file()
        assert (app_dir / "docs/USAGE.md").is_file(), "Offline usage guide is missing"
        for asset in (ROOT / "docs/images").glob("*.png"):
            assert (app_dir / "docs/images" / asset.name).read_bytes() == asset.read_bytes(), "Offline illustration is missing or changed"
        assert registry_exists(uninstall_key)
        assert read_value(RUN_KEY, identity) is None, "Autostart must default to disabled"
        # Exercise the actual application's startup integration with a unique test value,
        # enabling it AFTER installation so uninstall must also handle UI-created entries.
        code = "import sys; sys.frozen=True; sys.executable=" + repr(str(exe)) + "; from desktop.windows import set_startup; set_startup(True)"
        subprocess.run([sys.executable, "-c", code], check=True, cwd=ROOT, env=environment)
        assert read_value(RUN_KEY, identity) == '"' + str(exe) + '" --background'
        process = subprocess.Popen([str(exe), "--background"], env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Packaged desktop exited during startup")
                try:
                    with socket.create_connection(("127.0.0.1", 18772), timeout=.15):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError("Desktop service did not start")
            time.sleep(.7)
            root_process = psutil.Process(process.pid)
            processes = [root_process, *root_process.children(recursive=True)]
            before, started = cpu_seconds(processes), time.monotonic()
            time.sleep(3)
            cpu_percent = (cpu_seconds(processes) - before) / (time.monotonic() - started) * 100
            rss = sum(p.memory_info().rss for p in processes)
            duplicate = subprocess.run([str(exe), "--background"], env=environment, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            assert duplicate.returncode == 0
            assert process.poll() is None
            data_dir.mkdir(exist_ok=True)
            (data_dir / "settings.json").write_text('{"close_to_tray":true}', encoding="utf-8")
            # The isolated playback profile must be removed along with app data.
            profile = data_dir / "browser-profile/Default"
            profile.mkdir(parents=True)
            (profile / "Cookies-test").write_text("test profile data", encoding="utf-8")
            for name in ("remote.log.1", "remote.log.2"):
                (data_dir / name).write_text("test", encoding="utf-8")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, APPROVAL_KEY) as registry:
                winreg.SetValueEx(registry, identity, 0, winreg.REG_BINARY, bytes([2] + [0] * 11))
            subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=" + str(folder / "uninstall.log")], check=True, env=environment, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            process.wait(timeout=10)
            for _ in range(50):
                if not app_dir.exists():
                    break
                time.sleep(.1)
            assert not app_dir.exists(), "Installed files were left behind: " + str(list(app_dir.rglob("*")))
            assert not data_dir.exists(), "Settings, authorization or logs were left behind"
            assert read_value(RUN_KEY, identity) is None, "Startup entry was left behind"
            assert read_value(APPROVAL_KEY, identity) is None, "Windows startup approval was left behind"
            assert not registry_exists(uninstall_key), "Uninstall registration was left behind"
            shortcut = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs" / (label + ".lnk")
            assert not shortcut.exists()
            report = {"installed_and_uninstalled": True, "autostart_default_off": True, "ui_created_startup_removed": True, "data_removed": True, "registration_removed": True, "shortcut_removed": True, "single_instance": True, "idle_cpu_percent_one_core": round(cpu_percent, 3), "working_set_total_mib": round(rss / 1024 / 1024, 2), "desktop_size_mib": round(exe.stat().st_size / 1024 / 1024, 2) if exe.exists() else round((ROOT / "dist/BiliRemote-Desktop.exe").stat().st_size / 1024 / 1024, 2)}
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report))
        finally:
            if process.poll() is None:
                subprocess.run([str(exe), "--quit"], env=environment, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
                process.wait(timeout=10)
            if uninstaller.exists():
                subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], env=environment, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        if report_path.is_file():
            # This is the unique directory we created above, verified within .tooling.
            shutil.rmtree(folder)


if __name__ == "__main__":
    main()
