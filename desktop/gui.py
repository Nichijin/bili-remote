"""Desktop companion: one raster backing store, no browser or GPU scene."""
import asyncio
import contextlib
import ctypes
from ctypes import wintypes
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from PySide6.QtCore import QEvent, Qt, QTimer, QSignalBlocker
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QColorDialog, QComboBox,
    QHBoxLayout, QHeaderView, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMenu, QMessageBox, QScrollArea, QSlider, QSpinBox, QStackedWidget,
    QSystemTrayIcon, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .feedback import DEFAULT_STYLE, normalize_style
from .qt_feedback import OperationOverlay
from .qt_widgets import STYLE, Card, FlowLayout, ResponsiveColumns, SubtitlePreview, Switch, button, label, navigation_icon
from .runtime import ServiceRuntime
from .version import APP_VERSION
from .windows import (Preferences, InstanceGuard, WINDOW_TITLE, WM_SHOW, WM_QUIT,
    data_directory, icon_path, installed_uninstaller, signal_existing, startup_enabled, set_startup)


def application():
    app = QApplication.instance()
    if app is None:
        # QWidget double-buffers non-native children in its window backing store.
        # Never add WA_NativeWindow, an OpenGL viewport or layered child HWNDs.
        app = QApplication([sys.argv[0]])
        app.setStyle("Fusion")
        app.setFont(QFont("Microsoft YaHei UI", 10))
        app.setQuitOnLastWindowClosed(False)
    return app


class MainWindow(QMainWindow):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowIcon(QIcon(str(icon_path())))

    def closeEvent(self, event):
        if self.owner.closing:
            event.accept()
        else:
            event.ignore()
            self.owner.on_close_window()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.owner.update_inventory_visibility()
            if self.isMinimized():
                self.owner.end_feedback_preview()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.owner.resize_navigation()

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message in (WM_SHOW, WM_QUIT):
                self.owner.events.put(("quit" if msg.message == WM_QUIT else "show", None))
                return True, 0
        return super().nativeEvent(event_type, message)


class Companion(ServiceRuntime):
    def __init__(self, hidden=False, port=8765, discovery_port=8766, trust_path=None,
                 background=False, preferences_path=None):
        self.app = application()
        super().__init__(queue.Queue(), port, discovery_port, trust_path)
        self.hidden = hidden
        self.preferences = Preferences(preferences_path or (Path(trust_path).with_name("settings.json") if trust_path else None))
        self.feedback_style = normalize_style(self.preferences.values.get("feedback_style"))
        self.overlay = self.feedback_editor = self.tray = None
        self.last_overlay_time = 0
        self.update_busy = self.update_started = False
        self.update_download = ""
        self.active_navigation = self.compact_navigation = None
        self.window = MainWindow(self)
        self.window.setStyleSheet(STYLE)
        self.build_ui()
        area = self.window.screen().availableGeometry()
        self.window.resize(min(1040, area.width()-32), min(780, area.height()-48))
        self.window.setMinimumSize(min(440, area.width()), min(300, area.height()))
        self.window.move(area.center()-self.window.rect().center())
        self.feedback_save_timer = QTimer(self.window)
        self.feedback_save_timer.setSingleShot(True)
        self.feedback_save_timer.timeout.connect(self.flush_feedback_style)
        self.poll_timer = QTimer(self.window)
        self.poll_timer.setInterval(50)
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start()
        if not hidden and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.window.windowIcon(), self.window)
            self.tray.setToolTip("哔哩哔哩手势遥控 · 双击打开")
            menu = QMenu(self.window)
            menu.addAction("打开电脑端", self.show)
            menu.addAction("退出", self.close)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.show() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
            self.tray.show()
        self.start()
        if not hidden and not background:
            self.show()
        # Keep one HWND even in tray-only mode for the established installer IPC.
        self.window.winId()

    def build_ui(self):
        shell = QWidget()
        self.window.setCentralWidget(shell)
        layout = QHBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(208)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(10, 26, 10, 18)
        side.setSpacing(6)
        self.brand = label("Bili Remote", "brand")
        self.brand.setContentsMargins(12, 0, 0, 18)
        side.addWidget(self.brand)
        self.nav_heading = label("工作空间", "muted")
        self.nav_heading.setContentsMargins(12, 0, 0, 10)
        side.addWidget(self.nav_heading)
        self.tabs = QStackedWidget()
        self.navigation, self.pages = [], []
        self.navigation_group = QButtonGroup(self.window)
        names = ("连接与播放", "客户端与版本", "操作记录", "设置")
        descriptions = ("让手机成为遥控器，轻点、滑动或按住即可控制。", "查看遥控器版本，以及当前可用的播放控制功能。",
                        "保留本次运行最近 100 条操作与失败原因。", "管理启动方式、提示字幕和本机数据。修改会自动保存。")
        for index, text in enumerate(names):
            nav = button(text, lambda checked=False, index=index: self.select_page(index), "nav")
            nav.setCheckable(True)
            nav.setIcon(navigation_icon(("remote", "devices", "history", "settings")[index]))
            nav.setToolTip(text+f"  ·  Alt+{index+1}")
            self.navigation_group.addButton(nav, index)
            self.navigation.append(nav)
            side.addWidget(nav)
            shortcut = QShortcut(QKeySequence(f"Alt+{index+1}"), self.window)
            shortcut.activated.connect(lambda index=index: self.select_page(index))
            page = QWidget()
            page.setObjectName("page")
            content = QVBoxLayout(page)
            content.setContentsMargins(16, 24, 16, 24)
            content.setSpacing(16)
            content.addWidget(label("BILI REMOTE", "muted"))
            content.addWidget(label(text, "title"))
            content.addWidget(label(descriptions[index], "muted"))
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.tabs.addWidget(scroll)
            self.pages.append(page)
        side.addStretch()
        self.help_button = button("使用指南  ↗", self.open_help)
        side.addWidget(self.help_button)
        self.service_hint = label("●  正在启动", "muted")
        self.service_hint.setContentsMargins(10, 8, 0, 0)
        side.addWidget(self.service_hint)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.tabs, 1)
        self.build_connection()
        self.build_clients()
        self.build_records()
        self.build_settings()
        self.tabs.currentChanged.connect(self.on_page_changed)
        self.select_page(0)
        self.refresh_pin_label()
        self.resize_navigation()
        escape = QShortcut(QKeySequence("Escape"), self.window)
        escape.activated.connect(self.end_feedback_preview)

    def add_card(self, index, title=None, description=None):
        card = Card(title, description)
        self.pages[index].layout().addWidget(card)
        return card.layout_box

    def add_action(self, layout, text, action, kind=None):
        control = button(text, action, kind)
        if isinstance(layout, FlowLayout):
            layout.addWidget(control)
        else:
            layout.addWidget(control, alignment=Qt.AlignmentFlag.AlignLeft)
        return control

    def build_connection(self):
        connection_card = self.add_card(0)
        columns = ResponsiveColumns()
        connection_card.addWidget(columns)
        connection, pairing = columns.left, columns.right
        connection.addWidget(label("连接你的手机", "heading"))
        connection.addWidget(label("两端接入同一局域网，在手机中选择这台电脑。", "muted"))
        self.status = label("正在启动…")
        self.addresses = label("", "muted")
        connection.addWidget(self.status)
        connection.addWidget(self.addresses)
        pairing.addWidget(label("首次连接配对码", "muted"))
        self.pin_text = label("", "pin", False)
        pairing.addWidget(self.pin_text)
        self.add_action(pairing, "刷新配对码", self.refresh_pin)
        pairing.addWidget(label("配对一次，以后自动重连。配对码每 10 分钟更新。", "muted"))
        connection.addStretch()
        pairing.addStretch()
        player = self.add_card(0, "播放视频", "打开专用播放窗口，选择你想看的视频。")
        self.add_action(player, "打开哔哩哔哩 · 无需扩展", self.open_browser, "primary")
        player.addWidget(label("专用 Edge / Chrome 窗口支持完整遥控。Windows 客户端请手动打开，可用功能取决于客户端接口。", "muted"))
        recent = self.add_card(0, "最近一次操作")
        self.last_operation = label("尚无遥控操作", "muted")
        recent.addWidget(self.last_operation)
        actions = self.action_row(self.pages[0].layout())
        self.toggle = self.add_action(actions, "停止服务", self.toggle_service)
        self.add_action(actions, "取消手机授权", self.revoke)
        self.add_action(actions, "最小化", self.minimize)
        self.pages[0].layout().addStretch()

    def build_clients(self):
        about = self.add_card(1, "Bili Remote  ·  当前版本 "+APP_VERSION)
        actions = self.action_row(about)
        self.update_button = self.add_action(actions, "检查更新", lambda: self.check_updates(manual=True))
        self.update_download_button = self.add_action(actions, "下载新版", self.download_update)
        self.update_download_button.setEnabled(False)
        self.update_status = label("进入本页后在后台检查遥控器新版本。", "muted")
        about.addWidget(self.update_status)
        clients = self.add_card(1)
        self.add_action(clients, "重新检测", self.refresh_detection)
        self.inventory_status = label("进入本页时检测，后台保持轻量运行。", "muted")
        clients.addWidget(self.inventory_status)
        self.inventory = QTableWidget(0, 4)
        self.inventory.setHorizontalHeaderLabels(("客户端 / 浏览器", "版本", "状态", "控制方式"))
        self.inventory.verticalHeader().hide()
        self.inventory.setShowGrid(False)
        self.inventory.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.inventory.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.inventory.setMinimumHeight(240)
        self.inventory.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.inventory.horizontalHeader().setStretchLastSection(True)
        for index, width in enumerate((165, 110, 75, 230)):
            self.inventory.setColumnWidth(index, width)
        clients.addWidget(self.inventory)
        self.pages[1].layout().addStretch()

    def build_records(self):
        records = self.add_card(2)
        self.records = QListWidget()
        self.records.setMinimumHeight(280)
        self.records.setWordWrap(True)
        records.addWidget(self.records)

    def preference_row(self, layout, text, description, checked, action):
        row = QHBoxLayout()
        words = QVBoxLayout()
        words.addWidget(label(text))
        words.addWidget(label(description, "muted"))
        row.addLayout(words, 1)
        switch = Switch(text, checked, action)
        row.addWidget(switch)
        layout.addLayout(row)
        return switch

    def build_settings(self):
        general = self.add_card(3, "通用")
        self.autostart = self.preference_row(general, "开机自启", "登录 Windows 后自动启动", startup_enabled(), self.change_startup)
        self.close_to_tray = self.preference_row(general, "关闭后保留在托盘", "后台继续连接，双击托盘图标可返回",
            self.preferences.values.get("close_to_tray", True), lambda value: self.save_preference("close_to_tray", value))
        feedback = self.add_card(3, "遥控提示字幕", "操作时在电脑屏幕短暂显示反馈，不打断播放。")
        self.show_feedback = self.preference_row(feedback, "开启遥控提示字幕", "关闭后仍可在操作记录中查看反馈",
            self.preferences.values.get("show_feedback", True), self.change_feedback_enabled)
        self.subtitle_preview = SubtitlePreview()
        self.subtitle_preview.moved.connect(self.drag_feedback_position)
        feedback.addWidget(self.subtitle_preview)
        feedback.addWidget(label("拖动字幕调整位置 · 方向键微调 · 自动保存", "muted"))
        preview_actions = self.action_row(feedback)
        self.preview_button = self.add_action(preview_actions, "在屏幕上拖动字幕", self.preview_feedback)
        reset = self.add_action(preview_actions, "恢复默认", self.reset_feedback_style)
        self.feedback_positions = {"左上": (5, 5), "上方居中": (50, 5), "右上": (95, 5), "左侧居中": (5, 50),
            "屏幕中央": (50, 50), "右侧居中": (95, 50), "左下": (5, 88), "下方居中": (50, 88), "右下": (95, 88)}
        self.feedback_position = QComboBox()
        self.feedback_position.addItems([*self.feedback_positions, "自定义"])
        self.feedback_position.activated.connect(self.choose_feedback_position)
        feedback.addWidget(label("位置预设"))
        feedback.addWidget(self.feedback_position)
        self.feedback_controls = [self.preview_button, reset, self.feedback_position]
        self.feedback_vars, self.feedback_readouts = {}, {}
        for key, title in (("x", "水平位置"), ("y", "垂直位置"), ("opacity", "不透明度")):
            caption = label(title)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(10 if key == "opacity" else 0, 100)
            slider.setAccessibleName(title)
            slider.valueChanged.connect(self.feedback_style_edited)
            feedback.addWidget(caption)
            feedback.addWidget(slider)
            self.feedback_vars[key], self.feedback_readouts[key] = slider, (caption, title)
            self.feedback_controls.append(slider)
        feedback.addWidget(label("字号（10–64 pt）"))
        size = QSpinBox()
        size.setRange(10, 64)
        size.setAccessibleName("字幕字号")
        size.valueChanged.connect(self.feedback_style_edited)
        feedback.addWidget(size)
        feedback.addWidget(label("文字颜色"))
        color = QLineEdit()
        color.setMaxLength(7)
        color.setAccessibleName("字幕颜色，十六进制 RGB")
        color.textChanged.connect(self.feedback_style_edited)
        color.editingFinished.connect(self.finish_feedback_edit)
        feedback.addWidget(color)
        chooser = self.add_action(feedback, "选择颜色", self.choose_feedback_color)
        self.feedback_vars.update(font_size=size, color=color)
        self.feedback_controls.extend((size, color, chooser))
        feedback.addWidget(label("预览持续显示样式与位置；屏幕预览展示实际字号和透明度。按 Esc 或离开设置结束屏幕预览。", "muted"))
        support = self.add_card(3, "帮助与管理", "电脑在线时会广播供手机发现，已配对的手机可自动重连。")
        self.options_status = label("", "muted")
        support.addWidget(self.options_status)
        management = self.action_row(support)
        for text, action, kind in (("打开使用说明", self.open_help, None), ("卸载 / 清理本机数据", self.uninstall, "danger"), ("完全退出", self.close, None)):
            self.add_action(management, text, action, kind)
        self.sync_feedback_controls()

    def select_page(self, index):
        self.tabs.setCurrentIndex(index)
        self.on_page_changed(index)

    def on_page_changed(self, index):
        if index == self.active_navigation:
            return
        if index != 3:
            self.end_feedback_preview()
        self.active_navigation = index
        self.navigation[index].setChecked(True)
        self.update_inventory_visibility()

    def resize_navigation(self):
        if not hasattr(self, "help_button"):
            return
        compact = self.window.width() < 880
        short = self.window.height() < 560
        if compact != self.compact_navigation:
            self.compact_navigation = compact
            self.sidebar.setFixedWidth(70 if compact else 208)
            self.brand.setText("BR" if compact else "Bili Remote")
            for nav, text in zip(self.navigation, ("连接与播放", "客户端与版本", "操作记录", "设置")):
                nav.setText("" if compact else text)
            self.help_button.setText("?" if compact else "使用指南  ↗")
        self.nav_heading.setVisible(not compact and not short)
        self.brand.setVisible(not short)
        self.help_button.setVisible(not short)

    def action_row(self, layout):
        row = QWidget()
        flow = FlowLayout(row)
        layout.addWidget(row)
        return flow

    def update_inventory_visibility(self):
        visible = self.window.isVisible() and not self.window.isMinimized() and self.tabs.currentIndex() == 1
        if visible and not self.inventory_visible.is_set():
            self.inventory_visible.set()
            self.refresh_detection(False)
            if not self.update_started and not self.hidden:
                self.check_updates()
        elif not visible:
            self.inventory_visible.clear()

    def refresh_pin_label(self):
        code = self.pairing.current()
        self.pin_text.setText(code[:3]+" "+code[3:])

    def refresh_pin(self):
        self.pairing.rotate()
        self.refresh_pin_label()

    def start(self):
        self.toggle.setText("停止服务")
        self.set_status("正在启动…")
        self.start_service()

    def stop(self):
        self.stop_service()
        self.set_status("正在停止服务…")

    def toggle_service(self):
        self.stop() if self.thread and self.thread.is_alive() else self.start()

    def set_status(self, text):
        self.status.setText(text)
        self.service_hint.setText("●  "+("服务已停止" if text == "服务已停止" else "服务异常" if "失败" in text else "正在启动" if "正在启动" in text else "服务在线"))

    def refresh_detection(self, manual=True):
        self.inventory_status.setText("正在检测…")
        if manual:
            self.inventory_force.set()
        if self.loop and self.detection_request:
            self.loop.call_soon_threadsafe(self.detection_request.set)

    def check_updates(self, manual=False):
        if self.update_busy or self.closing:
            return
        self.update_busy = self.update_started = True
        self.update_button.setEnabled(False)
        self.update_status.setText("正在检查遥控器新版本…")
        cache = self.preferences.values.get("update_cache")
        def work():
            try:
                from .updates import check_latest
                self.events.put(("update_result", check_latest(cache, force=manual)))
            except Exception as exc:
                self.events.put(("update_error", str(exc)))
        threading.Thread(target=work, name="release-check", daemon=True).start()

    def show_update_result(self, result):
        from .updates import version_tuple
        self.update_busy = False
        self.update_button.setEnabled(True)
        latest = result["version"]
        newer = version_tuple(latest) > version_tuple(APP_VERSION)
        self.update_download = result["download_url"] if newer else ""
        self.update_download_button.setEnabled(newer)
        text = "发现新版本 "+latest+" · 当前 "+APP_VERSION if newer else (
            "已是最新正式版 · "+APP_VERSION if version_tuple(latest) == version_tuple(APP_VERSION) else "当前版本 "+APP_VERSION+" · 最新正式版 "+latest)
        self.update_status.setText(text+("（缓存结果）" if result["cached"] else ""))
        with contextlib.suppress(OSError):
            self.preferences.set("update_cache", result["cache"])

    def download_update(self):
        if self.update_download:
            import webbrowser
            webbrowser.open(self.update_download)

    def display_inventory(self, rows):
        selected = self.inventory.currentRow()
        selected_key = self.inventory.item(selected, 0).data(Qt.ItemDataRole.UserRole) if selected >= 0 else None
        wanted = []
        self.inventory.setUpdatesEnabled(False)
        try:
            self.inventory.setRowCount(len(rows))
            for index, row in enumerate(rows):
                key = (row["kind"], row.get("path", ""), row["name"])
                wanted.append(key)
                values = (row.get("installed_name", row["name"]), row["version"], "运行中" if row["running"] else "已安装", row["capabilities"])
                for column, value in enumerate(values):
                    item = self.inventory.item(index, column)
                    if item is None:
                        item = QTableWidgetItem()
                        self.inventory.setItem(index, column, item)
                    if item.text() != value:
                        item.setText(value)
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, key)
            if selected_key in wanted:
                self.inventory.selectRow(wanted.index(selected_key))
        finally:
            self.inventory.setUpdatesEnabled(True)

    def open_browser(self):
        if not self.loop or not self.relay:
            self.set_status("请先启动电脑服务")
            return
        async def open_window():
            try:
                await self.relay.browser.open()
                self.events.put(("operation", {"ok": True, "text": "已打开遥控播放窗口，请选择视频", "cmd": "open_browser"}))
                if self.inventory_visible.is_set():
                    self.detection_request.set()
            except Exception as exc:
                self.events.put(("operation", {"ok": False, "text": str(exc), "cmd": "open_browser"}))
        asyncio.run_coroutine_threadsafe(open_window(), self.loop)

    def revoke(self):
        if self.loop and self.relay:
            asyncio.run_coroutine_threadsafe(self.relay.revoke_all(), self.loop)
            self.set_status("手机授权已取消，下次需重新输入配对码")

    def save_preference(self, name, value):
        try:
            self.preferences.set(name, value)
        except OSError as exc:
            self.options_status.setText(f"设置保存失败：{exc}")

    def change_startup(self, checked):
        try:
            set_startup(checked)
            self.options_status.setText("已启用开机自启" if checked else "已关闭开机自启")
        except OSError as exc:
            self.autostart.setChecked(startup_enabled())
            self.options_status.setText(f"启动项设置失败：{exc}")

    def sync_feedback_controls(self):
        for key, widget in self.feedback_vars.items():
            with QSignalBlocker(widget):
                widget.setText(self.feedback_style[key]) if key == "color" else widget.setValue(self.feedback_style[key])
        for key, (caption, text) in self.feedback_readouts.items():
            caption.setText(f"{text}  {self.feedback_style[key]}%")
        pair = self.feedback_style["x"], self.feedback_style["y"]
        self.feedback_position.setCurrentText(next((name for name, value in self.feedback_positions.items() if value == pair), "自定义"))
        enabled = self.show_feedback.isChecked()
        for widget in self.feedback_controls:
            widget.setEnabled(enabled)
        self.subtitle_preview.set_style(self.feedback_style, enabled)

    def feedback_style_edited(self, *args):
        values = {key: widget.text() if key == "color" else widget.value() for key, widget in self.feedback_vars.items()}
        if len(values) != len(DEFAULT_STYLE):
            return
        normalized = normalize_style(values)
        if normalized["color"] != values["color"].upper() or normalized == self.feedback_style:
            return
        self.feedback_style = normalized
        for key, (caption, text) in self.feedback_readouts.items():
            caption.setText(f"{text}  {normalized[key]}%")
        pair = normalized["x"], normalized["y"]
        self.feedback_position.setCurrentText(next((name for name, value in self.feedback_positions.items() if value == pair), "自定义"))
        self.subtitle_preview.set_style(normalized, self.show_feedback.isChecked())
        for overlay in (self.overlay, self.feedback_editor):
            if overlay:
                overlay.set_style(normalized)
        self.feedback_save_timer.start(250)

    def flush_feedback_style(self):
        self.feedback_save_timer.stop()
        self.save_preference("feedback_style", self.feedback_style)

    def finish_feedback_edit(self):
        self.feedback_style_edited()
        self.sync_feedback_controls()
        self.flush_feedback_style()

    def drag_feedback_position(self, x, y):
        for key, value in (("x", x), ("y", y)):
            with QSignalBlocker(self.feedback_vars[key]):
                self.feedback_vars[key].setValue(value)
        self.feedback_style_edited()

    def choose_feedback_position(self, *args):
        pair = self.feedback_positions.get(self.feedback_position.currentText())
        if pair:
            self.drag_feedback_position(*pair)

    def choose_feedback_color(self):
        color = QColorDialog.getColor(QColor(self.feedback_style["color"]), self.window, "提示字幕颜色")
        if color.isValid():
            self.feedback_vars["color"].setText(color.name().upper())

    def reset_feedback_style(self):
        self.feedback_style = dict(DEFAULT_STYLE)
        self.sync_feedback_controls()
        for overlay in (self.overlay, self.feedback_editor):
            if overlay:
                overlay.set_style(self.feedback_style)
        self.flush_feedback_style()

    def change_feedback_enabled(self, checked):
        self.save_preference("show_feedback", checked)
        self.sync_feedback_controls()
        if not checked:
            if self.overlay:
                self.overlay.close()
                self.overlay.deleteLater()
                self.overlay = None
            self.end_feedback_preview()

    def preview_feedback(self):
        self.finish_feedback_edit()
        if self.feedback_editor:
            self.end_feedback_preview()
        elif self.show_feedback.isChecked():
            self.feedback_editor = OperationOverlay(self.window, self.feedback_style, self.drag_feedback_position)
            self.feedback_editor.show_text("拖动调整位置 · 临时 2 倍速")
            self.preview_button.setText("结束屏幕预览")

    def end_feedback_preview(self):
        if self.feedback_editor:
            self.feedback_editor.close()
            self.feedback_editor.deleteLater()
            self.feedback_editor = None
        if hasattr(self, "preview_button"):
            self.preview_button.setText("在屏幕上拖动字幕")

    def show_overlay(self, text, success=True):
        if not self.show_feedback.isChecked():
            return
        if self.overlay is None:
            self.overlay = OperationOverlay(self.window, self.feedback_style)
        self.overlay.show_text(text, success)

    def display_operations(self, operations):
        self.last_operation.setText(operations[-1]["text"])
        timestamp = time.strftime("%H:%M:%S")
        for event in operations:
            item = QListWidgetItem(timestamp+"  "+("" if event["ok"] else "失败 · ")+event["text"])
            if not event["ok"]:
                item.setForeground(QColor("#C23B45"))
            self.records.insertItem(0, item)
        while self.records.count() > 100:
            self.records.takeItem(100)
        newest = list(reversed(operations))
        feedback = next((event for event in newest if not event["ok"] or event.get("cmd") not in {"volume", "seek_to"}), newest[0])
        now = time.monotonic()
        if not self.hidden and self.show_feedback.isChecked() and (feedback.get("cmd") not in {"volume", "seek_to"} or now-self.last_overlay_time > .15):
            self.show_overlay(feedback["text"], feedback["ok"])
            self.last_overlay_time = now

    def poll(self):
        self.refresh_pin_label()
        deadline, handled, operations = time.monotonic()+.008, 0, []
        while handled < 32 and time.monotonic() < deadline:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            handled += 1
            if kind in {"status", "error"}:
                self.set_status(payload)
            elif kind == "addresses":
                self.addresses.setText(payload)
            elif kind == "operation":
                operations.append(payload)
            elif kind == "inventory":
                self.display_inventory(payload)
            elif kind == "inventory_done":
                self.inventory_status.setText(f"检测到 {payload} 个目标，本页可见时每 15 秒更新" if payload else "请打开哔哩哔哩播放窗口或客户端")
            elif kind == "inventory_error":
                self.inventory_status.setText(payload)
            elif kind == "update_result":
                self.show_update_result(payload)
            elif kind == "update_error":
                self.update_busy = False
                self.update_button.setEnabled(True)
                self.update_status.setText("检查更新失败："+payload)
            elif kind == "show":
                self.show()
            elif kind == "quit":
                self.close()
            elif kind == "stopped":
                self.toggle.setText("启动服务")
                if not self.status.text().startswith("服务启动失败"):
                    self.set_status("服务已停止")
        if operations:
            self.display_operations(operations)
        self.poll_timer.setInterval(16 if not self.events.empty() else 50)
        if self.closing and (not self.thread or not self.thread.is_alive()):
            self.dispose()
            self.app.quit()

    def show(self):
        if not self.hidden:
            self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()
            self.update_inventory_visibility()

    def minimize(self):
        self.inventory_visible.clear()
        self.end_feedback_preview()
        if self.tray and self.tray.isVisible():
            self.window.hide()
        elif not self.hidden:
            self.window.showMinimized()

    def on_close_window(self):
        self.minimize() if self.close_to_tray.isChecked() and self.tray and self.tray.isVisible() else self.close()

    def open_help(self):
        path = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1])/"README.md"
        if path.exists():
            os.startfile(path)

    def uninstall(self):
        uninstaller = installed_uninstaller()
        if uninstaller:
            subprocess.Popen([str(uninstaller)], creationflags=subprocess.CREATE_NO_WINDOW)
            self.close()
        elif QMessageBox.question(self.window, "清理本机数据", "关闭开机自启，清除本机设置、手机授权、日志及专用播放窗口的登录记录，然后退出。程序文件可在退出后删除。是否继续？") == QMessageBox.StandardButton.Yes:
            try:
                set_startup(False)
                self.cleanup_on_exit = True
                self.close()
            except OSError as exc:
                self.options_status.setText(f"清理启动项失败：{exc}")

    def close(self):
        self.end_feedback_preview()
        if self.feedback_save_timer.isActive():
            self.flush_feedback_style()
        self.closing = True
        self.stop()

    def dispose(self):
        self.closing = True
        self.poll_timer.stop()
        self.feedback_save_timer.stop()
        self.end_feedback_preview()
        if self.overlay:
            self.overlay.close()
            self.overlay.deleteLater()
            self.overlay = None
        if self.tray:
            self.tray.hide()
        self.window.close()

    def run(self):
        self.app.exec()
        if getattr(self, "cleanup_on_exit", False):
            import shutil
            logging.shutdown()
            directory = self.preferences.path.parent.resolve()
            profile = (directory/"browser-profile").resolve()
            if profile.parent == directory and profile.is_dir():
                shutil.rmtree(profile)
            for name in ("trust.json", "trust.tmp", "settings.json", "settings.tmp", "remote.log", "remote.log.1", "remote.log.2"):
                (directory/name).unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                directory.rmdir()


def main():
    if "--quit" in sys.argv:
        signal_existing(quit=True)
        return
    guard = InstanceGuard()
    if guard.already_running:
        if "--background" not in sys.argv:
            signal_existing()
        guard.close()
        return
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.WARNING, handlers=[RotatingFileHandler(directory/"remote.log", maxBytes=256*1024, backupCount=2, encoding="utf-8")], format="%(asctime)s %(message)s")
    sys.excepthook = lambda kind, value, traceback: logging.error("界面回调失败", exc_info=(kind, value, traceback))
    try:
        Companion(background="--background" in sys.argv, port=int(os.environ.get("BILI_REMOTE_PORT", "8765")),
                  discovery_port=int(os.environ.get("BILI_REMOTE_DISCOVERY_PORT", "8766"))).run()
    finally:
        logging.shutdown()
        guard.close()


if __name__ == "__main__":
    main()
