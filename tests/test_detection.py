from desktop.detection import combine, file_version, is_client
import sys


def test_detector_excludes_its_own_program_and_recognizes_third_party():
    assert is_client("BBLL.exe")
    assert is_client("哔哩哔哩")
    assert is_client("BiliBili.exe")
    assert not is_client("BiliRemote-Desktop.exe")
    assert not is_client("BiliGestureRemote")
    assert not is_client("Office Extensibility Component")
    assert not is_client("Application Compatibility Driver")


def test_detection_reports_unknown_capabilities_instead_of_guessing_from_version():
    running = [{"name": "bilibili.exe", "version": "1.2.3", "kind": "client", "path": "C:\\Bili\\bilibili.exe", "running": True}]
    rows = combine([], running, [{"id": "bilibili.exe", "toggle": True, "seek": True, "speed": False}], False)
    assert rows[0]["version"] == "1.2.3"
    assert rows[0]["capabilities"] == "暂停 / 进度"
    assert combine([], running, [], False)[0]["capabilities"] == "未提供媒体会话"


def test_installed_store_package_merges_with_running_executable():
    installed = [{"name": "Bilibili.Store", "version": "2.0.0.0", "kind": "client", "path": "C:\\Apps\\Bili", "running": False, "source": "微软商店", "package_id": "Bilibili.Store_2.0.0.0_x64__abc"}]
    running = [{"name": "Bili.exe", "version": "1.0", "kind": "client", "path": "C:\\Apps\\Bili\\Bili.exe", "running": True}]
    sessions = [{"id": "Bilibili.Store_abc!App", "toggle": True, "seek": False, "speed": True}]
    rows = combine(installed, running, sessions, False)
    assert len(rows) == 1
    assert rows[0]["version"] == "2.0.0.0"
    assert rows[0]["capabilities"] == "暂停 / 倍速"


def test_real_file_version_can_be_read_and_missing_file_is_unknown():
    assert file_version(sys.executable) != "未知"
    assert file_version("C:\\file-that-does-not-exist-bili-test.exe") == "未知"
