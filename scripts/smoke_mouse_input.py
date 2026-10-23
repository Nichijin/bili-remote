"""Inject only into a dedicated capture window, then restore the cursor position.

No user browser, player, settings or production companion instance is touched.
"""
import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from desktop.mouse import WindowsMouse


class Capture(QWidget):
    def __init__(self):
        super().__init__()
        self.events = []
        self.setWindowTitle("Bili Remote · 独立鼠标输入测试")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setFixedSize(500, 320)
        self.setMouseTracking(True)
        self.setStyleSheet("background:#e7edf3")

    def mousePressEvent(self, event):
        self.events.append(("down", event.button().name))

    def mouseReleaseEvent(self, event):
        self.events.append(("up", event.button().name))

    def mouseDoubleClickEvent(self, event):
        self.events.append(("double", event.button().name))


def main():
    app = QApplication([])
    widget = Capture()
    backend = WindowsMouse()
    user = backend.api
    user.GetForegroundWindow.restype = wintypes.HWND
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.SetForegroundWindow.restype = wintypes.BOOL
    user.WindowFromPoint.argtypes = [wintypes.POINT]
    user.WindowFromPoint.restype = wintypes.HWND
    original = wintypes.POINT()
    with backend.physical_pixels():
        assert user.GetCursorPos(ctypes.byref(original))
    try:
        widget.show()
        widget.raise_()
        widget.activateWindow()
        QTest.qWait(150)
        hwnd = int(widget.winId())
        user.SetForegroundWindow(hwnd)
        QTest.qWait(100)
        with backend.physical_pixels():
            rect = wintypes.RECT()
            assert user.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
            target = wintypes.POINT((rect.left+rect.right)//2, (rect.top+rect.bottom)//2)
        backend.move(target.x-original.x, target.y-original.y)
        QTest.qWait(40)
        actual = wintypes.POINT()
        with backend.physical_pixels():
            assert user.GetCursorPos(ctypes.byref(actual))
        assert (actual.x, actual.y) == (target.x, target.y)
        assert user.WindowFromPoint(actual) == hwnd, "鼠标下方不是测试窗口，已停止点击"
        for button in ("left", "right"):
            assert user.WindowFromPoint(actual) == hwnd
            backend.click(button)
            QTest.qWait(30)
        assert widget.events == [("down", "LeftButton"), ("up", "LeftButton"),
                                 ("down", "RightButton"), ("up", "RightButton")], widget.events
        QTest.qWait(user.GetDoubleClickTime()+20)
        backend.click("left")
        QTest.qWait(80)
        backend.click("left")
        QTest.qWait(30)
        assert ("double", "LeftButton") in widget.events, widget.events
        backend.move(37, -19)
        QTest.qWait(20)
        with backend.physical_pixels():
            assert user.GetCursorPos(ctypes.byref(actual))
        assert (actual.x, actual.y) == (target.x+37, target.y-19)
        result = {"absolute_move_exact_pixels": True, "delta_move_exact_pixels": True,
                  "left_and_right_click_pairs_captured": True, "native_left_double_click_captured": True,
                  "input_confined_to_fixture": True}
        path = ROOT / ".tooling/mouse-input-report.json"
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
    finally:
        with backend.physical_pixels():
            current = wintypes.POINT()
            if user.GetCursorPos(ctypes.byref(current)):
                backend.move(original.x-current.x, original.y-current.y)
        widget.close()
        app.processEvents()


if __name__ == "__main__":
    main()
