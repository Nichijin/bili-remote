import hashlib
import json
import zipfile

import pytest

from scripts.package_kit import main as package_kit
from scripts.release_files import release_paths, release_version


def release_project(root, android="1.2.3", windows="1.2.3"):
    (root / "android/app").mkdir(parents=True)
    (root / "installer").mkdir()
    (root / "dist").mkdir()
    (root / "android/app/build.gradle").write_text(f"versionName '{android}'\n", encoding="utf-8")
    (root / "installer/BiliRemote.iss").write_text(f'#define AppVersion "{windows}"\n', encoding="utf-8")
    for name in ("README.md", "CHANGELOG.md"):
        (root / name).write_text(name, encoding="utf-8")


def test_inconsistent_versions_stop_packaging(tmp_path):
    release_project(tmp_path, windows="1.2.2")
    with pytest.raises(RuntimeError, match="不一致"):
        package_kit(tmp_path)
    assert not list((tmp_path / "dist").iterdir())


def test_archive_uses_matching_version_and_excludes_previous_packages(tmp_path):
    release_project(tmp_path)
    paths = release_paths(tmp_path)
    paths["installer"].write_bytes(b"current installer")
    paths["apk"].write_bytes(b"current APK")
    (tmp_path / "dist/BiliRemote-Setup-1.2.2.exe").write_bytes(b"previous installer")
    (tmp_path / "dist/bili-remote-debug.apk").write_bytes(b"legacy APK")
    package_kit(tmp_path)
    assert paths["kit"].name == "bili-remote-kit-1.2.3.zip"
    with zipfile.ZipFile(paths["kit"]) as archive:
        checksums = json.loads(archive.read("SHA256-1.2.3.json"))
        assert set(checksums) == {"BiliRemote-Setup-1.2.3.exe", "bili-remote-1.2.3.apk", "README.md", "CHANGELOG.md"}
        for name, digest in checksums.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        assert set(archive.namelist()) == {*checksums, "SHA256-1.2.3.json"}


def test_missing_current_apk_cannot_fall_back_to_legacy_file(tmp_path):
    release_project(tmp_path)
    paths = release_paths(tmp_path)
    paths["installer"].write_bytes(b"current installer")
    (tmp_path / "dist/bili-remote-debug.apk").write_bytes(b"legacy APK")
    with pytest.raises(FileNotFoundError, match="bili-remote-1.2.3.apk"):
        package_kit(tmp_path)
    assert not paths["kit"].exists() and not paths["checksums"].exists()


@pytest.mark.parametrize("version", ["../1.2.3", "1.2.3/bad", "1.2"])
def test_invalid_version_cannot_become_an_output_path(tmp_path, version):
    release_project(tmp_path, version, version)
    with pytest.raises(RuntimeError, match="格式无效"):
        release_version(tmp_path)
