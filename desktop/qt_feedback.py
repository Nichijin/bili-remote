"""Independent passive feedback window; it never changes main-window styles."""
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QWidget
from .feedback import normalize_style, overlay_geometry, overlay_position


class OperationOverlay(QWidget):
    def __init__(self, parent, style=None, on_drag=None):
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                 Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        if on_drag is None:
            flags |= Qt.WindowType.WindowTransparentForInput
        super().__init__(parent, flags)
        self.setWindowTitle("BiliRemote operation feedback")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.on_drag, self.drag_origin = on_drag, None
        self.text = ""
        self.style = normalize_style(style)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def set_style(self, style):
        self.style = normalize_style(style)
        self.position()

    def work_area(self):
        area = self.parentWidget().screen().availableGeometry()
        return area.left(), area.top(), area.right()+1, area.bottom()+1

    def position(self):
        font = QFont("Microsoft YaHei UI", self.style["font_size"])
        self.setFont(font)
        area = self.work_area()
        metrics = QFontMetrics(font)
        box = metrics.boundingRect(0, 0, max(60, area[2]-area[0]-96), 10000,
                                   Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter, self.text)
        w, h, x, y = overlay_geometry(area, (box.width()+40, box.height()+20), self.style["x"], self.style["y"])
        self.setGeometry(x, y, w, h)
        self.setWindowOpacity(self.style["opacity"]/100)
        self.update()

    def show_text(self, text, success=True):
        self.text = text if success else "失败 · "+text
        self.position()
        self.show()
        if self.on_drag is None:
            self.timer.start(1500)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#191D2B"))
        painter.drawRoundedRect(QRectF(self.rect()), 9, 9)
        painter.setPen(QColor(self.style["color"]))
        painter.drawText(self.rect().adjusted(20, 10, -20, -10),
                         Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.text)

    def mousePressEvent(self, event):
        if self.on_drag and event.button() == Qt.MouseButton.LeftButton:
            self.drag_origin = event.globalPosition().toPoint()-self.pos()

    def mouseMoveEvent(self, event):
        if self.drag_origin is not None:
            pos = event.globalPosition().toPoint()-self.drag_origin
            self.on_drag(*overlay_position(self.work_area(), (self.width(), self.height()), pos.x(), pos.y()))

    def mouseReleaseEvent(self, event):
        self.drag_origin = None

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)
