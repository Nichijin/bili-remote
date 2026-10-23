"""Raster widgets: Qt owns layout, clipping and one backing store per window."""
from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QBoxLayout, QFrame, QLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

BG, SURFACE, TEXT, MUTED, BLUE = "#F5F5F7", "#FFFFFF", "#20242D", "#626975", "#007AFF"

STYLE = """
QWidget { color: #20242D; }
QMainWindow, QStackedWidget, QScrollArea, QWidget#page { background: #F5F5F7; }
QWidget#sidebar { background: #EBEDF1; }
QFrame#card { background: white; border: 1px solid #E1E3E8; border-radius: 12px; }
QLabel { background: transparent; border: none; }
QLabel#muted { color: #626975; }
QLabel#title { font-size: 25px; font-weight: 700; }
QLabel#heading { font-size: 16px; font-weight: 600; }
QLabel#brand { font-size: 18px; font-weight: 700; }
QLabel#pin { font-family: Consolas; font-size: 42px; font-weight: 600; }
QPushButton { background: white; border: 1px solid #DDE1E8; border-radius: 8px; padding: 9px 14px; }
QPushButton:hover { background: #F0F4FA; }
QPushButton:pressed { background: #E5EBF4; }
QPushButton:focus { border-color: #007AFF; }
QPushButton:disabled { color: #9B9FAB; background: #F0F1F3; }
QPushButton#primary { color: white; background: #007AFF; border-color: #007AFF; }
QPushButton#primary:hover { background: #1685FF; }
QPushButton#nav { text-align: left; background: transparent; color: #535D6F; border: 1px solid transparent; padding: 14px 12px; }
QPushButton#nav:hover { background: #E3E7EE; }
QPushButton#nav:checked { color: #0065D5; background: white; border-color: #D5DBE4; font-weight: 600; }
QPushButton#nav[focusVisible="true"] { border-color: #007AFF; }
QPushButton#danger { color: #C23B45; }
QLineEdit, QSpinBox, QComboBox { background: white; border: 1px solid #DDE1E8; border-radius: 6px; padding: 6px; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #007AFF; }
QSlider::groove:horizontal { background: #E5EAF1; height: 4px; border-radius: 2px; }
QSlider::handle:horizontal { background: white; border: 1px solid #9FAEC4; width: 18px; height: 18px; margin: -7px 0; border-radius: 9px; }
QSlider::handle:horizontal:disabled { background: #F3F4F6; }
QScrollArea { border: none; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #C7CDD7; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QTableWidget, QListWidget { background: white; border: none; selection-background-color: #E1EDFF; selection-color: #0062C9; }
QHeaderView::section { background: #F5F7FA; color: #626975; border: none; padding: 12px 8px; }
"""


def label(text, kind=None, wrap=True):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if kind:
        widget.setObjectName(kind)
    return widget


def button(text, action, kind=None):
    widget = NavigationButton(text) if kind == "nav" else QPushButton(text)
    if kind:
        widget.setObjectName(kind)
    widget.clicked.connect(action)
    return widget


class NavigationButton(QPushButton):
    def __init__(self, text):
        super().__init__(text)
        self.setProperty("focusVisible", False)

    def focusInEvent(self, event):
        self.setProperty("focusVisible", event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason))
        self.style().unpolish(self)
        self.style().polish(self)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.setProperty("focusVisible", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().focusOutEvent(event)


class Card(QFrame):
    def __init__(self, title=None, description=None):
        super().__init__()
        self.setObjectName("card")
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(20, 18, 20, 18)
        self.layout_box.setSpacing(12)
        if title:
            self.layout_box.addWidget(label(title, "heading"))
        if description:
            self.layout_box.addWidget(label(description, "muted"))


class FlowLayout(QLayout):
    """Wrap actions at their natural widths; never regenerate painted assets."""
    def __init__(self, parent):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(8)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.arrange(QRect(0, 0, width, 0), False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, True)

    def arrange(self, rect, apply):
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self.items:
            size = item.sizeHint()
            width = min(size.width(), rect.width())
            if line_height and x+width > rect.right()+1:
                x, y, line_height = rect.x(), y+line_height+self.spacing(), 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), QSize(width, size.height())))
            x += width+self.spacing()
            line_height = max(line_height, size.height())
        return y+line_height-rect.y()


class ResponsiveColumns(QWidget):
    def __init__(self):
        super().__init__()
        self.columns = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.columns.setContentsMargins(0, 0, 0, 0)
        self.columns.setSpacing(24)
        self.left, self.right = QVBoxLayout(), QVBoxLayout()
        self.columns.addLayout(self.left, 1)
        self.columns.addLayout(self.right, 1)

    def resizeEvent(self, event):
        direction = QBoxLayout.Direction.LeftToRight if event.size().width() >= 490 else QBoxLayout.Direction.TopToBottom
        if self.columns.direction() != direction:
            self.columns.setDirection(direction)
        super().resizeEvent(event)


def navigation_icon(kind):
    paths = {
        "remote": [(5, 2, 15, 2), (15, 2, 15, 18), (15, 18, 5, 18), (5, 18, 5, 2), (8, 6, 12, 6), (8, 9, 12, 9), (9, 14, 11, 14)],
        "devices": [(2, 3, 15, 3), (15, 3, 15, 13), (15, 13, 2, 13), (2, 13, 2, 3), (8, 13, 8, 17), (5, 17, 11, 17), (14, 8, 18, 8), (18, 8, 18, 18), (18, 18, 14, 18), (14, 18, 14, 8)],
        "history": [(5, 2, 15, 2), (15, 2, 15, 18), (15, 18, 5, 18), (5, 18, 5, 2), (8, 6, 12, 6), (8, 9, 12, 9), (8, 12, 12, 12)],
        "settings": [(2, 5, 18, 5), (2, 10, 18, 10), (2, 15, 18, 15), (7, 2, 7, 8), (13, 7, 13, 13), (8, 12, 8, 18)]}
    icon = QIcon()
    for state, color in ((QIcon.State.Off, "#667184"), (QIcon.State.On, "#0065D5")):
        pixmap = QPixmap(60, 60)
        pixmap.setDevicePixelRatio(3)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(color), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for x1, y1, x2, y2 in paths[kind]:
            painter.drawLine(x1, y1, x2, y2)
        painter.end()
        icon.addPixmap(pixmap, QIcon.Mode.Normal, state)
    return icon


class Switch(QPushButton):
    """Accessible checkable button; antialiased within the window backing store."""
    def __init__(self, text, checked, action):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setAccessibleName(text)
        self.setFixedSize(40, 26)
        self.clicked.connect(action)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(BLUE if self.isChecked() else "#C4CAD4"))
        painter.drawRoundedRect(QRectF(1, 2, 38, 22), 11, 11)
        painter.setBrush(QColor("white"))
        painter.drawEllipse(QRectF(20 if self.isChecked() else 4, 5, 16, 16))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(BLUE), 1))
            painter.drawRoundedRect(QRectF(.5, .5, 39, 25), 12, 12)


class SubtitlePreview(QWidget):
    moved = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("字幕位置预览，拖动或使用方向键调整")
        self.style = {"x": 50, "y": 88, "font_size": 17, "color": "#FFFFFF", "opacity": 94}
        self.drag_offset = None
        self.caption_rect = QRectF()

    def set_style(self, style, enabled=True):
        self.style = dict(style)
        self.setEnabled(enabled)
        self.update()

    def paintEvent(self, event):
        from .feedback import overlay_geometry
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#E9EDF4"))
        painter.setPen(QColor(MUTED))
        painter.drawText(self.rect().adjusted(0, 0, 0, -80), Qt.AlignmentFlag.AlignCenter, "预览工作区")
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(round(max(11, min(23, self.style["font_size"] * .75))))
        painter.setFont(font)
        size = painter.fontMetrics().size(0, "临时 2 倍速")
        w, h, x, y = overlay_geometry((8, 8, max(9, self.width()-8), max(9, self.height()-8)),
                                      (size.width()+24, size.height()+14), self.style["x"], self.style["y"])
        self.caption_rect = QRectF(x, y, w, h)
        painter.setOpacity(self.style["opacity"]/100 if self.isEnabled() else .35)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#191D2B"))
        painter.drawRoundedRect(self.caption_rect, 6, 6)
        painter.setPen(QColor(self.style["color"]))
        painter.drawText(self.caption_rect, Qt.AlignmentFlag.AlignCenter, "临时 2 倍速")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.caption_rect.contains(event.position()):
            self.setFocus()
            self.drag_offset = event.position()-self.caption_rect.topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None:
            from .feedback import overlay_position
            point = event.position()-self.drag_offset
            self.moved.emit(*overlay_position((8, 8, self.width()-8, self.height()-8),
                                              (self.caption_rect.width(), self.caption_rect.height()), point.x(), point.y()))

    def mouseReleaseEvent(self, event):
        self.drag_offset = None

    def keyPressEvent(self, event):
        shifts = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if event.key() in shifts:
            dx, dy = shifts[event.key()]
            self.moved.emit(max(0, min(100, self.style["x"]+dx)), max(0, min(100, self.style["y"]+dy)))
        else:
            super().keyPressEvent(event)
