"""Exercise an actual old -> new Windows upgrade under a unique test identity.

--baseline contains the previously shipped BiliRemote.iss and desktop EXE.
No production installation, startup entry or data directory is used.
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.trust import TrustStore
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVAL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"


def read_value(key, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as registry:
            return winreg.QueryValueEx(registry, name)[0]
    except FileNotFoundError:
        return None


def write_value(key, name, value):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as registry:
        winreg.SetValueEx(registry, name, 0, winreg.REG_BINARY if isinstance(value, bytes) else winreg.REG_SZ, value)


def wait_service(online):
    for _ in range(150):
        try:
            with socket.create_connection(("127.0.0.1", 18774), timeout=.1):
                found = True
        except OSError:
            found = False
        if found == online:
            return
        time.sleep(.1)
    raise AssertionError("Service did not become " + ("online" if online else "offline"))


async def authenticate(token, computer_id):
    async with connect("ws://127.0.0.1:18774") as ws:
        await ws.send(json.dumps({"role": "remote", "device_id": "upgrade-test-phone", "token": token}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), 3))
        assert reply["ok"], reply
        assert reply["computer_id"] == computer_id, reply


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=ROOT / ".tooling/upgrade-baseline-0.4.0")
    arguments = parser.parse_args()
    baseline = arguments.baseline.resolve()
    assert (baseline / "BiliRemote.iss").is_file() and (baseline / "BiliRemote-Desktop.exe").is_file()
    baseline_source = (baseline / "BiliRemote.iss").read_text(encoding="utf-8")
    version_pattern = r'#define\s+AppVersion\s+"([^"]+)"'
    old_version = re.search(version_pattern, baseline_source).group(1)
    new_version = re.search(version_pattern, (ROOT / "installer/BiliRemote.iss").read_text(encoding="utf-8")).group(1)
    identifier = str(uuid.uuid4())
    identity, label = "BiliRemote-UpgradeTest-" + identifier[:8], "BiliRemote upgrade test " + identifier[:8]
    tooling = (ROOT / ".tooling").resolve()
    folder = Path(tempfile.mkdtemp(prefix="upgrade-smoke-", dir=tooling)).resolve()
    assert folder.is_relative_to(tooling)
    app_dir, data_dir = folder / "original app with spaces", folder / "data"
    environment = {**os.environ, "BILI_REMOTE_INSTANCE_NAME": identity, "BILI_REMOTE_WINDOW_TITLE": label,
                   "BILI_REMOTE_DATA_DIR": str(data_dir), "BILI_REMOTE_PORT": "18774",
                   "BILI_REMOTE_DISCOVERY_PORT": "18775", "BILI_REMOTE_BIND_HOST": "127.0.0.1"}
    uninstall_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{" + identifier + "}_is1"
    desktop = read_value(r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders", "Desktop")
    desktop_link = Path(os.path.expandvars(desktop)) / (label + ".lnk")
    exe, uninstaller = app_dir / "BiliRemote-Desktop.exe", app_dir / "unins000.exe"
    print("Isolated upgrade test:", folder, flush=True)

    def run(path, *parameters, success=True):
        result = subprocess.run([str(path), *map(str, parameters)], env=environment,
                                creationflags=subprocess.CREATE_NO_WINDOW, timeout=90)
        if success:
            result.check_returncode()
        return result

    def compile_setup(script, name, *extra):
        output = folder / name
        output.mkdir()
        command = [str(tooling / "inno/ISCC.exe"), "/Q", "/DAppIdentity=" + identity,
                   "/DAppIdentifier={{" + identifier + "}", "/DAppLabel=" + label,
                   "/DUserDataPath=" + str(data_dir), "/DOutputPath=" + str(output), *extra, str(script)]
        compiled = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if compiled.returncode:
            raise RuntimeError(compiled.stdout + compiled.stderr)
        # Baselines may use either the old fixed name or the new versioned name.
        installers = list(output.glob("BiliRemote-Setup*.exe"))
        assert len(installers) == 1, installers
        return installers[0]

    def install(setup, name, *extra, success=True):
        return run(setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                   "/LOG=" + str(folder / (name + ".log")), *extra, success=success)

    def assert_data():
        assert json.loads((data_dir / "trust.json").read_text(encoding="utf-8")) == trust_data
        assert (data_dir / "settings.json").read_bytes() == settings
        assert cookie.read_bytes() == b"saved browser login sentinel"
        assert chrome_cookie.read_bytes() == b"saved chrome login sentinel"

    complete = False
    try:
        # Compile the old install script and actual old binary with isolated identity.
        source = baseline_source
        replacements = {
            r"..\dist\{#AppExe}": str(baseline / "BiliRemote-Desktop.exe"),
            r"..\README.md": str(ROOT / "README.md"),
            r"..\CHANGELOG.md": str(ROOT / "CHANGELOG.md"),
            r"..\docs\*": str(ROOT / "docs/*"),
            r"..\desktop\assets\bili-remote.ico": str(ROOT / "desktop/assets/bili-remote.ico"),
            '"ChineseSimplified.isl"': '"' + str(ROOT / "installer/ChineseSimplified.isl") + '"',
            'Source: "firewall-cleanup.ps1"': 'Source: "' + str(ROOT / "installer/firewall-cleanup.ps1") + '"',
        }
        for old, new in replacements.items():
            source = source.replace(old, new)
        old_script = folder / "old.iss"
        old_script.write_text(source, encoding="utf-8-sig")
        old_setup = compile_setup(old_script, "old", "/DAppSourcePath=" + str(baseline))
        new_setup = compile_setup(ROOT / "installer/BiliRemote.iss", "new")
        lower_setup = compile_setup(ROOT / "installer/BiliRemote.iss", "downgrade", "/DAppVersion=0.3.99")
        install(old_setup, "initial", "/DIR=" + str(app_dir), "/TASKS=desktopicon")
        assert read_value(uninstall_key, "DisplayVersion") == old_version
        assert read_value(RUN_KEY, identity) is None
        assert desktop_link.is_file()
        # Settings changed from the app after installation must win over installer history.
        command = '"' + str(exe) + '" --background'
        write_value(RUN_KEY, identity, command)
        approved = bytes([2] + [0] * 11)
        write_value(APPROVAL_KEY, identity, approved)
        trust = TrustStore(data_dir / "trust.json")
        token = trust.allow("upgrade-test-phone", "upgrade test phone")
        trust_data = trust.data.copy()
        settings = b'{"close_to_tray":false,"show_feedback":false,"feedback_style":{"x":25,"y":60,"font_size":24,"color":"#75E1EB","opacity":70},"future_setting":"retain"}'
        (data_dir / "settings.json").write_bytes(settings)
        cookie = data_dir / "browser-profile/Default/Cookies-test"
        cookie.parent.mkdir(parents=True)
        cookie.write_bytes(b"saved browser login sentinel")
        chrome_cookie = data_dir / "browser-profile-chrome/Default/Cookies-test"
        chrome_cookie.parent.mkdir(parents=True)
        chrome_cookie.write_bytes(b"saved chrome login sentinel")
        old_process = subprocess.Popen([str(exe), "--background"], env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        wait_service(True)
        asyncio.run(authenticate(token, trust.computer_id))
        # Even /DIR must not create a second installation on upgrade.
        alternative = folder / "must not install here"
        install(new_setup, "upgrade-running", "/DIR=" + str(alternative))
        old_process.wait(timeout=15)
        wait_service(True)
        assert not alternative.exists()
        assert read_value(uninstall_key, "DisplayVersion") == new_version
        assert Path(read_value(uninstall_key, "InstallLocation")).resolve() == app_dir
        assert hashlib.sha256(exe.read_bytes()).digest() == hashlib.sha256((ROOT / "dist/BiliRemote-Desktop.exe").read_bytes()).digest()
        runtime = ROOT / "dist/_internal"
        if runtime.is_dir():
            for source_file in runtime.rglob("*"):
                if source_file.is_file():
                    installed_file = app_dir / "_internal" / source_file.relative_to(runtime)
                    assert installed_file.is_file(), installed_file
                    assert hashlib.sha256(installed_file.read_bytes()).digest() == hashlib.sha256(source_file.read_bytes()).digest(), installed_file
            for source_file in [ROOT / "README.md", ROOT / "CHANGELOG.md", *(ROOT / "docs").rglob("*")]:
                if source_file.is_file():
                    installed_file = app_dir / source_file.relative_to(ROOT)
                    assert installed_file.read_bytes() == source_file.read_bytes(), installed_file
        assert len(list(app_dir.glob("unins*.exe"))) == 1
        assert desktop_link.is_file(), "Existing desktop shortcut was not retained"
        assert read_value(RUN_KEY, identity) == command
        assert read_value(APPROVAL_KEY, identity) == approved
        assert_data()
        asyncio.run(authenticate(token, trust.computer_id))
        # A repair must preserve a Task Manager-disabled startup entry byte for byte.
        run(exe, "--quit")
        wait_service(False)
        disabled = bytes([3] + [0] * 11)
        write_value(APPROVAL_KEY, identity, disabled)
        install(new_setup, "repair-disabled")
        assert read_value(RUN_KEY, identity) == command
        assert read_value(APPROVAL_KEY, identity) == disabled
        assert_data()
        time.sleep(1)
        wait_service(False)
        # An old setup must refuse to replace the new version or alter its data.
        result = install(lower_setup, "reject-downgrade", success=False)
        assert result.returncode != 0
        assert read_value(uninstall_key, "DisplayVersion") == new_version
        assert_data()
        # Test an explicit silent task change as well as preserving existing state.
        install(new_setup, "explicit-autostart-off", "/TASKS=")
        assert read_value(RUN_KEY, identity) is None
        assert read_value(APPROVAL_KEY, identity) is None
        assert_data()
        report = {"old_to_new_upgrade": old_version + " -> " + new_version, "original_directory_retained": True,
                  "one_installation": True, "running_instance_restarted": True,
                  "settings_preserved": True, "browser_profile_preserved": True, "chrome_profile_preserved": True,
                  "computer_identity_preserved": True, "saved_phone_reconnected_without_pin": True,
                  "app_enabled_autostart_preserved": True, "task_manager_disabled_autostart_preserved": True,
                  "same_version_repair": True, "explicit_task_change": True, "downgrade_rejected": True}
        # The upgraded uninstaller must still remove the accumulated installation.
        run(uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=" + str(folder / "uninstall.log"))
        for _ in range(100):
            if not app_dir.exists():
                break
            time.sleep(.1)
        assert not app_dir.exists(), list(app_dir.rglob("*"))
        assert not data_dir.exists()
        assert read_value(uninstall_key, "DisplayVersion") is None
        assert read_value(RUN_KEY, identity) is None and read_value(APPROVAL_KEY, identity) is None
        assert not desktop_link.exists()
        report["upgraded_uninstall_clean"] = True
        (tooling / "upgrade-test-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        complete = True
    finally:
        if exe.exists():
            run(exe, "--quit", success=False)
            wait_service(False)
        if uninstaller.exists():
            run(uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", success=False)
        if complete:
            # Only remove the unique, verified folder created by this test.
            # The uninstall loader can keep its log open briefly after returning.
            for attempt in range(50):
                try:
                    shutil.rmtree(folder)
                    break
                except PermissionError:
                    if attempt == 49:
                        raise
                    time.sleep(.1)


if __name__ == "__main__":
    main()
