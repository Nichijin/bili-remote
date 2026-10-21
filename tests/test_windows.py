import sys
from desktop.windows import Preferences, InstanceGuard, startup_command, installed_uninstaller


def test_preferences_round_trip_in_separate_directory(tmp_path):
    path = tmp_path / "settings.json"
    preferences = Preferences(path)
    preferences.set("close_to_tray", False)
    assert Preferences(path).values["close_to_tray"] is False


def test_startup_command_quotes_an_executable_path_with_spaces(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:\\Program Files\\Bili\\BiliRemote-Desktop.exe")
    assert startup_command() == '"C:\\Program Files\\Bili\\BiliRemote-Desktop.exe" --background'


def test_instance_guard_prevents_duplicate_and_releases_mutex(tmp_path):
    name = "BiliRemoteTest-" + tmp_path.name
    first, second = InstanceGuard(name), InstanceGuard(name)
    try:
        assert not first.already_running
        assert second.already_running
    finally:
        first.close()
        second.close()
    third = InstanceGuard(name)
    assert not third.already_running
    third.close()


def test_portable_app_never_runs_another_programs_uninstaller(tmp_path, monkeypatch):
    (tmp_path / "unins000.exe").write_bytes(b"unrelated installer")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "BiliRemote-Desktop.exe"))
    assert installed_uninstaller() is None
