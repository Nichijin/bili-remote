"""Inject only into a dedicated capture window, then restore the cursor position.

No user browser, player, settings or production companion instance is touched.
"""
import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from desktop.mouse import WindowsMouse, MouseController
from desktop.version import APP_VERSION


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
    area=app.primaryScreen().availableGeometry()
    widget.move(area.center()-widget.rect().center())
    backend = WindowsMouse()
    user = backend.api
    user.GetForegroundWindow.restype = wintypes.HWND
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.SetForegroundWindow.restype = wintypes.BOOL
    user.SetWindowPos.argtypes = [wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
    user.WindowFromPoint.argtypes = [wintypes.POINT]
    user.WindowFromPoint.restype = wintypes.HWND
    original = wintypes.POINT()
    mouse = MouseController(backend)
    with backend.physical_pixels():
        assert user.GetCursorPos(ctypes.byref(original))
    try:
        widget.show()
        widget.raise_()
        widget.activateWindow()
        QTest.qWait(150)
        hwnd = int(widget.winId())
        user.SetWindowPos(hwnd,wintypes.HWND(-1),0,0,0,0,0x43)
        user.SetForegroundWindow(hwnd)
        QTest.qWait(100)
        with backend.physical_pixels():
            rect = wintypes.RECT()
            assert user.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
            target = wintypes.POINT((rect.left+rect.right)//2, (rect.top+rect.bottom)//2)
            current = wintypes.POINT()
            assert user.GetCursorPos(ctypes.byref(current))
        # Window activation can move the cursor; original is only for restoration.
        backend.move(target.x-current.x, target.y-current.y)
        QTest.qWait(40)
        actual = wintypes.POINT()
        with backend.physical_pixels():
            assert user.GetCursorPos(ctypes.byref(actual))
        assert (actual.x, actual.y) == (target.x, target.y), {
            'actual': (actual.x,actual.y), 'target': (target.x,target.y),
            'base': (current.x,current.y), 'original': (original.x,original.y)}

        def assert_fixture():
            with backend.physical_pixels():
                assert user.GetCursorPos(ctypes.byref(actual))
                hit = user.WindowFromPoint(actual)
            assert hit == hwnd, {'hit':hit,'fixture':hwnd,'point':(actual.x,actual.y),
                                 'fixture_rect':(rect.left,rect.top,rect.right,rect.bottom),
                                 'foreground':user.GetForegroundWindow()}

        assert_fixture()
        for button in ("left", "right"):
            assert_fixture()
            backend.click(button)
            QTest.qWait(30)
        assert widget.events == [("down", "LeftButton"), ("up", "LeftButton"),
                                 ("down", "RightButton"), ("up", "RightButton")], widget.events
        QTest.qWait(user.GetDoubleClickTime()+20)
        assert_fixture()
        backend.click("left")
        QTest.qWait(80)
        assert_fixture()
        backend.click("left")
        QTest.qWait(30)
        assert ("double", "LeftButton") in widget.events, widget.events
        backend.move(37, -19)
        QTest.qWait(20)
        with backend.physical_pixels():
            assert user.GetCursorPos(ctypes.byref(actual))
        assert (actual.x, actual.y) == (target.x+37, target.y-19)
        session=mouse.execute({"cmd":"mouse_start","stream":2},"fixture")["mouse_session"]
        mouse.execute({"cmd":"mouse_frame","mouse_session":session,"seq":1,"t":0,"x":12.75,"y":-8.5},"fixture")
        deadline=time.perf_counter()+.080
        while time.perf_counter()<deadline:
            app.processEvents()
            time.sleep(.004)  # Release the GIL so the Python output worker runs.
        with backend.physical_pixels():
            assert user.GetCursorPos(ctypes.byref(actual))
        assert (actual.x,actual.y)==(target.x+49,target.y-27), {'actual':(actual.x,actual.y),'expected':(target.x+49,target.y-27),'worker_error':str(mouse.worker.error),'applied':(mouse.worker.timeline.applied_x,mouse.worker.timeline.applied_y)}
        worker=mouse.worker
        mouse.release("fixture")
        assert not worker.thread.is_alive()
        result = {"source_version": APP_VERSION, "absolute_move_exact_pixels": True, "delta_move_exact_pixels": True,
                  "left_and_right_click_pairs_captured": True, "native_left_double_click_captured": True,
                  "stream_worker_endpoint_and_teardown": True,
                  "input_confined_to_fixture": True}
        path = ROOT / ".tooling/mouse-input-report.json"
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
    finally:
        mouse.release("fixture")
        with backend.physical_pixels():
            current = wintypes.POINT()
            if user.GetCursorPos(ctypes.byref(current)):
                backend.move(original.x-current.x, original.y-current.y)
        widget.close()
        app.processEvents()


if __name__ == "__main__":
    main()
