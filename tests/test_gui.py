"""Regression checks for input, cached-page lifetime and background results."""
import json
import threading
import time
from unittest.mock import patch

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from desktop.gui import Companion
from desktop.version import APP_VERSION


class Preview(Companion):
    def start(self):
        pass


@pytest.fixture
def companion(tmp_path, monkeypatch):
    monkeypatch.setenv("BILI_REMOTE_DATA_DIR", str(tmp_path))
    with patch("desktop.gui.startup_enabled", return_value=False):
        app = Preview(hidden=True)
    app.window.show()
    QTest.qWait(20)
    try:
        yield app
    finally:
        app.dispose()
        app.window.deleteLater()
        app.app.processEvents()


def test_first_settings_click_works_without_waiting_for_paint(companion):
    app = companion
    original = app.close_to_tray.isChecked()
    QTest.mouseClick(app.navigation[3], Qt.MouseButton.LeftButton)
    QTest.mouseClick(app.close_to_tray, Qt.MouseButton.LeftButton)
    assert app.tabs.currentIndex() == 3
    assert app.navigation[3].isChecked()
    assert app.close_to_tray.isChecked() != original
    saved = json.loads(app.preferences.path.read_text(encoding="utf-8"))
    assert saved["close_to_tray"] != original


def test_navigation_reuses_widgets_and_only_displays_current_page(companion):
    app = companion
    identities = set(map(id, app.window.findChildren(QWidget)))
    for index in (3, 1, 2, 0)*20:
        app.select_page(index)
        app.app.processEvents()
        assert app.active_navigation == index
        assert [app.tabs.widget(i).isVisible() for i in range(4)] == [i == index for i in range(4)]
    assert identities == set(map(id, app.window.findChildren(QWidget)))
    assert not any(widget.testAttribute(Qt.WidgetAttribute.WA_NativeWindow) for widget in app.window.findChildren(QWidget))


def test_scrolled_controls_accept_input_after_leaving_and_returning(companion):
    app = companion
    app.select_page(3)
    scroll = app.tabs.widget(3)
    scroll.ensureWidgetVisible(app.feedback_vars["color"])
    app.app.processEvents()
    offset = scroll.verticalScrollBar().value()
    assert offset > 0
    app.select_page(1)
    app.select_page(3)
    assert scroll.verticalScrollBar().value() == offset
    app.feedback_vars["color"].setText("#12ABEF")
    assert app.feedback_style["color"] == "#12ABEF"


def test_hidden_page_controls_are_excluded_from_keyboard_focus(companion):
    app = companion
    app.select_page(0)
    app.navigation[0].setFocus()
    for _ in range(35):
        app.window.focusNextChild()
        focus = app.app.focusWidget()
        assert focus is not None and focus.isVisible()
        for index in (1, 2, 3):
            assert not app.pages[index].isAncestorOf(focus)


def test_preview_drag_keeps_live_controls_and_saves_on_close(companion):
    app = companion
    app.select_page(3)
    scroll = app.tabs.widget(3)
    scroll.ensureWidgetVisible(app.subtitle_preview)
    QTest.qWait(20)
    preview = app.subtitle_preview
    start = preview.caption_rect.center().toPoint()
    QTest.mousePress(preview, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(preview, start+QPoint(50, -30))
    QTest.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=start+QPoint(50, -30))
    assert app.feedback_style["x"] > 50 and app.feedback_style["y"] < 88
    assert app.feedback_vars["x"].value() == app.feedback_style["x"]
    app.close()
    saved = json.loads(app.preferences.path.read_text(encoding="utf-8"))
    assert saved["feedback_style"] == app.feedback_style


def test_invalid_partial_color_does_not_overwrite_valid_preferences(companion):
    app = companion
    app.feedback_vars["color"].setText("#123456")
    app.feedback_vars["color"].setText("#12")
    assert app.feedback_style["color"] == "#123456"
    app.finish_feedback_edit()
    assert app.feedback_vars["color"].text() == "#123456"


def test_live_preview_is_closed_when_navigation_or_feedback_disabled(companion):
    app = companion
    app.select_page(3)
    app.preview_feedback()
    assert app.feedback_editor.isVisible()
    app.select_page(1)
    assert app.feedback_editor is None
    app.select_page(3)
    app.preview_feedback()
    app.show_feedback.click()
    assert app.feedback_editor is None and not app.subtitle_preview.isEnabled()
    assert not any(widget.isEnabled() for widget in app.feedback_controls)


def test_table_reuses_cells_and_keeps_selected_target_when_rows_reorder(companion):
    app = companion
    first = {"kind": "browser", "path": "C:/a.exe", "name": "a", "version": "1", "running": True, "capabilities": "test"}
    second = dict(first, name="b", path="C:/b.exe")
    app.display_inventory([first, second])
    item = app.inventory.item(0, 1)
    app.inventory.selectRow(0)
    app.display_inventory([dict(first, version="2"), second])
    assert app.inventory.item(0, 1) is item and item.text() == "2"
    app.display_inventory([second, first])
    assert app.inventory.currentRow() == 1
    app.display_inventory([])
    assert app.inventory.rowCount() == 0


def test_operation_queue_preserves_recent_failures_and_bounds_history(companion):
    app = companion
    events = [{"text": str(i), "ok": i != 104, "cmd": "toggle"} for i in range(105)]
    for event in events:
        app.events.put(("operation", event))
    for _ in range(5):
        app.poll()
    assert app.records.count() == 100
    assert app.records.item(0).text().endswith("失败 · 104")
    assert app.last_operation.text() == "104"


def test_slow_updates_do_not_block_navigation_and_duplicate_checks(companion):
    app = companion
    started, release = threading.Event(), threading.Event()
    calls = []
    def delayed(cache, force):
        calls.append(force)
        started.set()
        assert release.wait(3)
        return {"version": "9.0.0", "download_url": "https://github.com/Nichijin/bili-remote/releases/tag/v9.0.0", "cache": {}, "cached": False}
    with patch("desktop.updates.check_latest", delayed):
        app.check_updates(manual=True)
        assert started.wait(1)
        try:
            app.check_updates(manual=True)
            QTest.mouseClick(app.navigation[3], Qt.MouseButton.LeftButton)
            app.close_to_tray.click()
            assert app.tabs.currentIndex() == 3 and app.update_busy and calls == [True]
        finally:
            release.set()
        deadline = time.monotonic()+2
        while app.update_busy and time.monotonic() < deadline:
            QTest.qWait(5)
    assert app.update_download_button.isEnabled() and "9.0.0" in app.update_status.text()
    app.show_update_result({"version": APP_VERSION, "download_url": "unused", "cache": {}, "cached": False})
    assert "已是最新正式版" in app.update_status.text() and not app.update_download


def test_failed_update_reenables_retry(companion):
    app = companion
    with patch("desktop.updates.check_latest", side_effect=RuntimeError("offline")):
        app.check_updates(manual=True)
        deadline = time.monotonic()+2
        while app.update_busy and time.monotonic() < deadline:
            QTest.qWait(5)
    assert "检查更新失败" in app.update_status.text() and app.update_button.isEnabled()
