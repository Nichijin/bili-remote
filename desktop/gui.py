"""Windows companion: first-use PIN, direct playback and visible operation feedback."""
import asyncio
import contextlib
import logging
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import colorchooser, messagebox, ttk

from websockets.asyncio.server import serve

from .appearance import BLUE, LINE, MUTED, SIDEBAR, SURFACE, TEXT, Card, Columns, apply_theme, line_icon, preference_row, tooltip
from .detection import ClientDetector, combine
from .discovery import start_discovery
from .feedback import DEFAULT_STYLE, OperationOverlay, normalize_style
from .layout import CachedPages, FlowRow, ScrollablePage, enable_dpi_awareness, fit_window, wrapped_label
from .pairing import PairingCode
from .server import Relay
from .trust import TrustStore
from .subtitle_preview import SubtitlePreview
from .windows import NativeTray, Preferences, InstanceGuard, WINDOW_TITLE, data_directory, icon_path, installed_uninstaller, signal_existing, startup_enabled, set_startup


class Companion:
    def __init__(self, hidden=False, port=8765, discovery_port=8766, trust_path=None, background=False, preferences_path=None):
        enable_dpi_awareness()
        self.window = tk.Tk()
        # Prepare real controls and geometry before exposing the main window.
        # No partially constructed page is shown during cold startup.
        self.window.withdraw()
        self.hidden, self.port, self.discovery_port, self.trust_path = hidden, port, discovery_port, trust_path
        self.window.title(WINDOW_TITLE)
        with contextlib.suppress(tk.TclError):
            self.window.iconbitmap(default=str(icon_path()))
        self.ui_scale = fit_window(self.window)
        self.events = queue.Queue()
        self.thread = self.loop = self.stop_event = self.relay = self.detection_request = None
        self.closing = self.request_stop = False
        self.preferences = Preferences(preferences_path or (Path(trust_path).with_name("settings.json") if trust_path else None))
        self.detector = ClientDetector()
        self.inventory_visible = threading.Event()
        self.inventory_signature = None
        self.feedback_save_timer = None
        self.feedback_editor = None
        self.feedback_dragging = False
        self.feedback_style = normalize_style(self.preferences.values.get("feedback_style"))
        self.pairing = PairingCode()
        self.tray = self.overlay = None
        self.last_overlay_time = 0
        self.build_ui()
        if not hidden:
            try:
                self.tray = NativeTray(self.window, lambda kind: self.events.put((kind, None)))
            except OSError as exc:
                logging.warning("桌面提示或托盘不可用：%s", exc)
        self.window.protocol("WM_DELETE_WINDOW", self.on_close_window)
        self.window.after(50, self.poll)
        self.start()
        if background:
            self.minimize()
        elif not hidden:
            self.window.update_idletasks()
            self.window.deiconify()

    def build_ui(self):
        self.font_family = apply_theme(self.window, self.ui_scale)
        self.compact_navigation = None
        self.short_navigation = None
        self.active_navigation = None
        self.shell = ttk.Frame(self.window)
        self.shell.pack(fill="both", expand=True)
        self.sidebar = ttk.Frame(self.shell, style="Sidebar.TFrame")
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        ttk.Frame(self.shell, width=1, style="Sidebar.TFrame").pack(side="left", fill="y")
        self.brand = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        self.brand.pack(fill="x", padx=self.px(18), pady=(self.px(30), self.px(34)))
        self.brand_icon = line_icon(self.window, "remote", self.px(34), BLUE)
        logo = ttk.Label(self.brand, image=self.brand_icon, style="Sidebar.TLabel")
        logo.pack(side="left")
        self.brand_text = ttk.Frame(self.brand, style="Sidebar.TFrame")
        self.brand_text.pack(side="left", padx=(self.px(9), 0))
        ttk.Label(self.brand_text, text="Bili Remote", style="Sidebar.Brand.TLabel").pack(anchor="w")
        ttk.Label(self.brand_text, text="哔哩哔哩手势遥控", style="Sidebar.Caption.TLabel").pack(anchor="w", pady=(self.px(3), 0))
        self.nav_heading = ttk.Label(self.sidebar, text="工作空间", style="Sidebar.Caption.TLabel")
        self.nav_heading.pack(anchor="w", padx=self.px(22), pady=(0, self.px(10)))
        tabs = CachedPages(self.shell)
        tabs.pack(side="left", fill="both", expand=True)
        remote_page, detection, options_page, records = [ttk.Frame(tabs) for _ in range(4)]
        for widget, name in ((remote_page, "连接与播放"), (detection, "客户端与版本"), (records, "操作记录"), (options_page, "设置")):
            tabs.add(widget, text=name)
        self.tabs = tabs
        self.detection_page = detection
        self.navigation = []
        self.nav_icons = []
        for index, (text, kind) in enumerate((("连接与播放", "remote"), ("客户端与版本", "devices"), ("操作记录", "history"), ("设置", "settings"))):
            icons = [line_icon(self.window, kind, self.px(20), color) for color in ("#667184", "#0065D5")]
            self.nav_icons.append(icons)
            button = ttk.Button(self.sidebar, text="  " + text, image=icons[0], compound="left", style="Nav.TButton",
                                command=lambda n=index: tabs.select(n), takefocus=True)
            button.pack(fill="x", padx=self.px(10), pady=self.px(3))
            tooltip(button, f"{text}  ·  Alt+{index + 1}")
            self.window.bind(f"<Alt-Key-{index + 1}>", lambda event, n=index: tabs.select(n))
            self.navigation.append((button, text))
        self.sidebar_footer = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        self.sidebar_footer.pack(side="bottom", fill="x", padx=self.px(14), pady=self.px(20))
        self.help_button = ttk.Button(self.sidebar_footer, text="使用指南  ↗", style="Nav.TButton", command=self.open_help)
        self.help_button.pack(fill="x", pady=(0, self.px(16)))
        self.service_hint = tk.StringVar(value="●  正在启动")
        self.service_label = ttk.Label(self.sidebar_footer, textvariable=self.service_hint, style="Sidebar.Caption.TLabel")
        self.service_label.pack(anchor="w", padx=self.px(8))
        tabs.bind("<<NotebookTabChanged>>", self.on_page_changed)
        self.window.bind("<Configure>", self.resize_navigation, add=True)
        self.window.bind("<Map>", self.update_inventory_visibility, add=True)
        self.window.bind("<Unmap>", self.update_inventory_visibility, add=True)
        self.window.bind("<Unmap>", lambda event: self.end_feedback_preview() if event.widget is self.window else None, add=True)
        self.window.bind("<Escape>", lambda event: self.end_feedback_preview(), add=True)
        self.remote_page = ScrollablePage(remote_page, padding=self.px(26))
        self.options_page = ScrollablePage(options_page, padding=self.px(26))
        remote, options = self.remote_page.content, self.options_page.content
        detection.configure(padding=self.px(26)); records.configure(padding=self.px(26))
        self.page_heading(remote, "连接与播放", "BILI REMOTE", "让手机成为遥控器，轻点、滑动或按住即可控制。")
        pairing_card = Card(remote, self.ui_scale)
        pairing_card.pack(fill="x", pady=(0, self.px(15)))
        pairing_columns = Columns(pairing_card.content, self.ui_scale)
        pairing_columns.pack(fill="x")
        connection, pairing = pairing_columns.left, pairing_columns.right
        ttk.Label(connection, text="连接你的手机", style="Surface.Heading.TLabel").pack(anchor="w")
        wrapped_label(connection, text="两端接入同一局域网，在手机中选择这台电脑。", style="Surface.Muted.TLabel").pack(anchor="w", pady=(self.px(6), self.px(10)))
        self.status = tk.StringVar(value="正在启动…")
        self.status_label = wrapped_label(connection, textvariable=self.status, style="Surface.TLabel", foreground=BLUE)
        self.status_label.pack(anchor="w", pady=(self.px(10), self.px(5)))
        self.addresses = tk.StringVar()
        wrapped_label(connection, textvariable=self.addresses, style="Surface.Muted.TLabel").pack(anchor="w", pady=(0, self.px(15)))
        ttk.Label(pairing, text="首次连接配对码", style="Surface.Muted.TLabel").pack(anchor="w")
        pin_frame = FlowRow(pairing, style="Surface.TFrame")
        pin_frame.pack(fill="x", pady=(0, self.px(5)))
        self.pin_text = tk.StringVar()
        pin_frame.add(ttk.Label(pin_frame, textvariable=self.pin_text, style="Surface.Pin.TLabel"))
        pin_frame.add(ttk.Button(pin_frame, text="刷新", command=self.refresh_pin))
        wrapped_label(pairing, text="配对一次，以后自动重连。配对码每 10 分钟更新。", style="Surface.Muted.TLabel").pack(anchor="w")
        player = self.card(remote, "播放视频", "打开专用播放窗口，选择你想看的视频。")
        ttk.Button(player, text="打开哔哩哔哩 · 无需扩展", command=self.open_browser, style="Primary.TButton").pack(anchor="w", pady=(self.px(17), self.px(12)))
        wrapped_label(player, text="专用 Edge / Chrome 窗口支持完整遥控。Windows 客户端请手动打开，可用功能取决于客户端接口。", style="Surface.Muted.TLabel").pack(anchor="w")
        recent = self.card(remote, "最近一次操作")
        self.last_operation = tk.StringVar(value="尚无遥控操作")
        wrapped_label(recent, textvariable=self.last_operation, style="Surface.Muted.TLabel").pack(anchor="w", pady=(self.px(7), 0))
        actions = FlowRow(remote)
        actions.pack(fill="x", pady=(self.px(4), self.px(8)))
        self.toggle = ttk.Button(actions, text="停止服务", command=self.toggle_service)
        actions.add(self.toggle)
        actions.add(ttk.Button(actions, text="取消手机授权", command=self.revoke))
        actions.add(ttk.Button(actions, text="最小化", command=self.minimize))
        self.status.trace_add("write", self.update_service_presentation)
        self.page_heading(detection, "客户端与版本", "BILI REMOTE", "查看已安装的客户端，以及当前可用的控制功能。")
        detection_actions = FlowRow(detection)
        detection_actions.pack(fill="x", pady=(0, self.px(12)))
        detection_actions.add(ttk.Button(detection_actions, text="重新检测", command=self.refresh_detection))
        self.inventory_status = tk.StringVar(value="进入本页时检测，后台保持轻量运行。")
        wrapped_label(detection, textvariable=self.inventory_status, style="Muted.TLabel").pack(anchor="w", pady=(0, self.px(14)))
        table = Card(detection, self.ui_scale, padding=12, stretch=True)
        table.pack(fill="both", expand=True)
        inventory_frame = table.content
        inventory_frame.rowconfigure(0, weight=1); inventory_frame.columnconfigure(0, weight=1)
        self.inventory = ttk.Treeview(inventory_frame, columns=("version", "state", "capabilities"), height=6)
        self.inventory.heading("#0", text="客户端 / 浏览器")
        self.inventory.column("#0", width=140, minwidth=90)
        for column, title, width in (("version", "版本", 105), ("state", "状态", 60), ("capabilities", "控制方式", 235)):
            self.inventory.heading(column, text=title)
            self.inventory.column(column, width=width, minwidth=55)
        self.inventory.grid(row=0, column=0, sticky="nsew")
        self.inventory_empty = wrapped_label(inventory_frame, text="等待检测播放器\n进入本页后自动检查已安装与正在运行的客户端。", style="Surface.Muted.TLabel", justify="center")
        self.inventory_empty.place(relx=.5, rely=.5, anchor="center")
        for orient, row, column, sticky, command in (("vertical", 0, 1, "ns", self.inventory.yview), ("horizontal", 1, 0, "ew", self.inventory.xview)):
            bar = ttk.Scrollbar(inventory_frame, orient=orient, command=command)
            bar.grid(row=row, column=column, sticky=sticky)
            self.inventory.configure(**{("y" if orient == "vertical" else "x") + "scrollcommand": bar.set})
        self.page_heading(records, "操作记录", "BILI REMOTE", "保留本次运行最近 100 条记录，失败原因也会显示在这里。")
        log_card = Card(records, self.ui_scale, padding=14, stretch=True)
        log_card.pack(fill="both", expand=True)
        records_frame = log_card.content
        records_frame.rowconfigure(0, weight=1); records_frame.columnconfigure(0, weight=1)
        self.records = tk.Listbox(records_frame, font=(self.font_family, 11), activestyle="none", borderwidth=0, height=4,
                                  background=SURFACE, foreground=TEXT, selectbackground="#E1EDFF", selectforeground="#0062C9",
                                  highlightthickness=0, relief="flat")
        self.records.grid(row=0, column=0, sticky="nsew")
        self.records_empty = wrapped_label(records_frame, text="还没有遥控操作\n连接手机后，操作与反馈会出现在这里。", style="Surface.Muted.TLabel", justify="center")
        self.records_empty.place(relx=.5, rely=.5, anchor="center")
        for orient, row, column, sticky, command in (("vertical", 0, 1, "ns", self.records.yview), ("horizontal", 1, 0, "ew", self.records.xview)):
            bar = ttk.Scrollbar(records_frame, orient=orient, command=command)
            bar.grid(row=row, column=column, sticky=sticky)
            self.records.configure(**{("y" if orient == "vertical" else "x") + "scrollcommand": bar.set})
        self.page_heading(options, "设置", "BILI REMOTE", "管理启动方式、提示字幕和本机数据。修改会自动保存。")
        general = self.card(options, "通用")
        self.autostart = tk.BooleanVar(value=startup_enabled())
        preference_row(general, "开机自启", "登录 Windows 后自动启动", self.autostart, self.change_startup, self.ui_scale)
        self.separator(general)
        self.close_to_tray = tk.BooleanVar(value=self.preferences.values.get("close_to_tray", True))
        preference_row(general, "关闭后保留在托盘", "后台继续连接，双击托盘图标可返回", self.close_to_tray,
                       lambda: self.save_preference("close_to_tray", self.close_to_tray.get()), self.ui_scale)
        feedback = self.card(options, "遥控提示字幕", "操作时在电脑屏幕短暂显示反馈，不打断播放。")
        self.show_feedback = tk.BooleanVar(value=self.preferences.values.get("show_feedback", True))
        preference_row(feedback, "开启遥控提示字幕", "关闭后仍可在操作记录中查看反馈", self.show_feedback, self.change_feedback_enabled, self.ui_scale)
        self.separator(feedback)
        self.build_feedback_settings(feedback)
        support = self.card(options, "帮助与管理", "电脑在线时会广播供手机发现，已配对的手机可自动重连。")
        self.options_status = tk.StringVar()
        wrapped_label(support, textvariable=self.options_status, style="Surface.Muted.TLabel").pack(anchor="w", pady=self.px(6))
        management = FlowRow(support, style="Surface.TFrame")
        management.pack(fill="x")
        for label, action, style in (("打开使用说明", self.open_help, "TButton"), ("卸载 / 清理本机数据", self.uninstall, "Danger.TButton"), ("完全退出", self.close, "TButton")):
            management.add(ttk.Button(management, text=label, command=action, style=style))
        tabs.prepare()
        self.refresh_pin_label()
        self.resize_navigation()
        self.on_page_changed()

    def px(self, value):
        return max(1, round(value * self.ui_scale))

    def page_heading(self, parent, title, section, subtitle):
        ttk.Label(parent, text=section.upper(), style="Eyebrow.TLabel").pack(anchor="w", pady=(self.px(3), self.px(8)))
        wrapped_label(parent, text=title, style="Title.TLabel").pack(anchor="w")
        wrapped_label(parent, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(self.px(8), self.px(25)))

    def card(self, parent, title, subtitle=None):
        card = Card(parent, self.ui_scale)
        card.pack(fill="x", pady=(0, self.px(15)))
        ttk.Label(card.content, text=title, style="Surface.Heading.TLabel").pack(anchor="w")
        if subtitle:
            wrapped_label(card.content, text=subtitle, style="Surface.Muted.TLabel").pack(anchor="w", pady=(self.px(6), 0))
        return card.content

    def separator(self, parent):
        line = tk.Frame(parent, background=LINE, height=1)
        line.pack(fill="x", pady=self.px(4))

    def resize_navigation(self, event=None):
        if event is not None and event.widget is not self.window:
            return
        compact = self.window.winfo_width() < self.px(880)
        short = self.window.winfo_height() < self.px(560)
        if (compact, short) == (self.compact_navigation, self.short_navigation):
            return
        self.compact_navigation, self.short_navigation = compact, short
        self.sidebar.configure(width=self.px(70 if compact else 208))
        self.brand.pack_configure(padx=self.px(17 if compact else 18), pady=(self.px(16 if short else 30), self.px(18 if short else 34)))
        if compact:
            self.brand_text.pack_forget()
        else:
            self.brand_text.pack(side="left", padx=(self.px(9), 0))
        if compact or short:
            self.nav_heading.pack_forget()
        else:
            self.nav_heading.pack(anchor="w", padx=self.px(22), pady=(0, self.px(10)), before=self.navigation[0][0])
        for button, name in self.navigation:
            button.configure(compound="image" if compact else "left")
        self.sidebar_footer.pack_configure(padx=self.px(8 if compact else 14), pady=self.px(12 if short else 20))
        self.help_button.configure(text="?" if compact else "使用指南  ↗")
        if short:
            self.help_button.pack_forget()
        else:
            self.help_button.pack(fill="x", pady=(0, self.px(16)), before=self.service_label)
        self.update_service_presentation()

    def on_page_changed(self, event=None):
        current = self.tabs.index(self.tabs.select())
        if current == self.active_navigation:
            return
        if current != 3:
            self.end_feedback_preview()
        for index in {self.active_navigation, current} - {None}:
            button, name = self.navigation[index]
            selected = index == current
            button.configure(style="Selected.Nav.TButton" if selected else "Nav.TButton", image=self.nav_icons[index][int(selected)])
        self.active_navigation = current
        self.update_inventory_visibility()

    def update_service_presentation(self, *args):
        value = self.status.get()
        color, hint = "#27835E", "服务在线"
        if "失败" in value:
            color, hint = "#C23B45", "服务异常"
        elif "正在启动" in value or "正在停止" in value:
            color, hint = "#9A6A18", "正在启动" if "启动" in value else "正在停止"
        elif "已停止" in value or "请先启动" in value:
            color, hint = MUTED, "服务已停止"
        elif value.startswith("手机已连接"):
            hint = "手机已连接"
        self.service_hint.set("●" if self.compact_navigation else "●  " + hint)
        self.service_label.configure(foreground=color)
        self.status_label.configure(foreground=color)

    def refresh_pin_label(self):
        code = self.pairing.current()
        formatted = code[:3] + " " + code[3:]
        if formatted != self.pin_text.get():
            self.pin_text.set(formatted)

    def build_feedback_settings(self, parent):
        frame = ttk.Frame(parent, style="Surface.TFrame")
        self.feedback_frame = frame
        frame.pack(fill="x", pady=(self.px(14), 0))
        ttk.Label(frame, text="提示字幕样式", style="Surface.Heading.TLabel").pack(anchor="w", pady=(0, self.px(12)))
        self.feedback_controls = []
        self.feedback_vars = {key: (tk.StringVar if key == "color" else tk.IntVar if key == "font_size" else tk.DoubleVar)(value=value) for key, value in self.feedback_style.items()}
        self.feedback_readouts = {}
        self.feedback_positions = {"左上": (5, 5), "上方居中": (50, 5), "右上": (95, 5),
                                   "左侧居中": (5, 50), "屏幕中央": (50, 50), "右侧居中": (95, 50),
                                   "左下": (5, 88), "下方居中": (50, 88), "右下": (95, 88)}
        self.feedback_position = tk.StringVar(value="自定义")
        self.subtitle_preview = SubtitlePreview(frame, self.ui_scale, self.drag_feedback_position)
        self.subtitle_preview.pack(fill="x", pady=(0, self.px(18)))
        preview_actions = FlowRow(frame, style="Surface.TFrame")
        preview_actions.pack(fill="x", pady=(0, self.px(14)))
        self.preview_button_text = tk.StringVar(value="在屏幕上拖动字幕")
        self.feedback_controls.append(preview_actions.add(ttk.Button(preview_actions, textvariable=self.preview_button_text, command=self.preview_feedback)))
        self.feedback_controls.append(preview_actions.add(ttk.Button(preview_actions, text="恢复默认", command=self.reset_feedback_style)))
        row = FlowRow(frame, style="Surface.TFrame"); row.pack(fill="x", pady=self.px(3))
        row.add(ttk.Label(row, text="位置预设", style="Surface.TLabel"))
        preset = row.add(ttk.Combobox(row, textvariable=self.feedback_position, values=[*self.feedback_positions, "自定义"], state="readonly", width=12))
        preset.bind("<<ComboboxSelected>>", self.choose_feedback_position)
        self.feedback_controls.append(preset)
        for key in ("x", "y", "opacity"):
            line = ttk.Frame(frame, style="Surface.TFrame"); line.pack(fill="x", pady=self.px(10))
            caption = tk.StringVar(); self.feedback_readouts[key] = caption
            ttk.Label(line, textvariable=caption, style="Surface.TLabel").pack(anchor="w")
            control = ttk.Scale(line, from_=10 if key == "opacity" else 0, to=100, variable=self.feedback_vars[key])
            control.pack(fill="x", pady=(5, 0)); self.feedback_controls.append(control)
        row = FlowRow(frame, style="Surface.TFrame"); row.pack(fill="x", pady=self.px(5))
        row.add(ttk.Label(row, text="字号（10–64 pt）", style="Surface.TLabel"))
        control = row.add(ttk.Spinbox(row, from_=10, to=64, increment=1, width=6, textvariable=self.feedback_vars["font_size"]))
        control.bind("<FocusOut>", self.finish_feedback_edit)
        control.bind("<Return>", self.finish_feedback_edit)
        self.feedback_controls.append(control)
        row = FlowRow(frame, style="Surface.TFrame"); row.pack(fill="x", pady=self.px(5))
        row.add(ttk.Label(row, text="文字颜色", style="Surface.TLabel"))
        color = row.add(ttk.Entry(row, textvariable=self.feedback_vars["color"], width=10))
        color.bind("<FocusOut>", self.finish_feedback_edit)
        color.bind("<Return>", self.finish_feedback_edit)
        chooser = row.add(ttk.Button(row, text="选择颜色", command=self.choose_feedback_color))
        self.feedback_controls.extend([color, chooser])
        wrapped_label(frame, text="上方预览持续显示样式与位置；屏幕预览展示实际字号和透明度。拖动后自动保存，按 Esc 或离开设置结束屏幕预览。", style="Surface.Muted.TLabel").pack(anchor="w", pady=self.px(12))
        for variable in self.feedback_vars.values():
            variable.trace_add("write", self.feedback_style_edited)
        self.update_feedback_labels()
        self.set_feedback_controls_state()

    def update_feedback_labels(self):
        for key, caption in self.feedback_readouts.items():
            value = self.feedback_style[key]
            text = f"{'水平位置' if key == 'x' else '垂直位置' if key == 'y' else '不透明度'}  {value}%"
            if caption.get() != text:
                caption.set(text)
        pair = self.feedback_style["x"], self.feedback_style["y"]
        position = next((name for name, position in self.feedback_positions.items() if position == pair), "自定义")
        if self.feedback_position.get() != position:
            self.feedback_position.set(position)

    def feedback_style_edited(self, *args):
        if self.feedback_dragging:
            return
        values = dict(self.feedback_style)
        for key, variable in self.feedback_vars.items():
            try:
                values[key] = variable.get()
            except tk.TclError:
                return  # A partially typed size is not a complete setting yet.
        normalized = normalize_style(values)
        if normalized["color"] != str(values["color"]).upper():
            return  # Preserve the last valid color while the hex field is typed.
        if normalized == self.feedback_style:
            return
        self.feedback_style = normalized
        self.update_feedback_labels()
        if self.overlay:
            self.overlay.set_style(self.feedback_style)
        if self.feedback_editor:
            self.feedback_editor.set_style(self.feedback_style)
        self.subtitle_preview.set_style(self.feedback_style, self.show_feedback.get())
        if self.feedback_save_timer:
            self.window.after_cancel(self.feedback_save_timer)
        self.feedback_save_timer = self.window.after(250, self.flush_feedback_style)

    def flush_feedback_style(self):
        if self.feedback_save_timer:
            self.window.after_cancel(self.feedback_save_timer)
            self.feedback_save_timer = None
        self.save_preference("feedback_style", self.feedback_style)

    def finish_feedback_edit(self, event=None):
        self.feedback_style_edited()
        for key in ("font_size", "color"):
            self.feedback_vars[key].set(self.feedback_style[key])
        self.flush_feedback_style()

    def choose_feedback_position(self, event=None):
        position = self.feedback_positions.get(self.feedback_position.get())
        if position:
            self.feedback_vars["x"].set(position[0]); self.feedback_vars["y"].set(position[1])

    def choose_feedback_color(self):
        color = colorchooser.askcolor(color=self.feedback_style["color"], title="提示字幕颜色", parent=self.window)[1]
        if color:
            self.feedback_vars["color"].set(color)

    def reset_feedback_style(self):
        for key, value in DEFAULT_STYLE.items():
            self.feedback_vars[key].set(value)
        self.flush_feedback_style()

    def set_feedback_controls_state(self):
        for widget in self.feedback_controls:
            widget.state(["!disabled"] if self.show_feedback.get() else ["disabled"])
        self.subtitle_preview.set_style(self.feedback_style, self.show_feedback.get())

    def change_feedback_enabled(self):
        self.save_preference("show_feedback", self.show_feedback.get())
        self.set_feedback_controls_state()
        if not self.show_feedback.get() and self.overlay:
            self.overlay.close(); self.overlay = None
        if not self.show_feedback.get():
            self.end_feedback_preview()

    def show_overlay(self, text, success=True):
        if not self.show_feedback.get():
            return
        try:
            if self.overlay is None:
                self.overlay = OperationOverlay(self.window, self.feedback_style)
            self.overlay.show(text, success)
        except (OSError, tk.TclError) as exc:
            logging.warning("提示字幕不可用：%s", exc)
            if self.overlay:
                with contextlib.suppress(tk.TclError):
                    self.overlay.close()
                self.overlay = None

    def preview_feedback(self):
        self.finish_feedback_edit()
        if self.feedback_editor:
            self.end_feedback_preview()
        elif self.show_feedback.get():
            try:
                self.feedback_editor = OperationOverlay(self.window, self.feedback_style, self.drag_feedback_position)
                self.feedback_editor.show("拖动调整位置 · 临时 2 倍速")
                self.preview_button_text.set("结束屏幕预览")
            except (OSError, tk.TclError) as exc:
                self.end_feedback_preview()
                self.options_status.set(f"屏幕预览不可用：{exc}")

    def drag_feedback_position(self, x, y):
        self.feedback_dragging = True
        try:
            self.feedback_vars["x"].set(x)
            self.feedback_vars["y"].set(y)
        finally:
            self.feedback_dragging = False
        self.feedback_style_edited()

    def end_feedback_preview(self):
        if self.feedback_editor:
            self.feedback_editor.close()
            self.feedback_editor = None
        if hasattr(self, "preview_button_text"):
            self.preview_button_text.set("在屏幕上拖动字幕")

    def refresh_pin(self):
        self.pairing.rotate()
        self.refresh_pin_label()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.request_stop = False
        self.toggle.config(text="停止服务")
        self.status.set("正在启动…")
        self.thread = threading.Thread(target=self.worker, daemon=True)
        self.thread.start()

    def worker(self):
        try:
            asyncio.run(self.serve())
        except Exception as exc:
            logging.exception("电脑服务失败")
            self.events.put(("error", f"服务启动失败：{exc}；请检查端口 8765 / 8766 是否被占用。"))
        finally:
            self.events.put(("stopped", None))

    async def serve(self):
        self.loop = asyncio.get_running_loop()
        self.stop_event, self.detection_request = asyncio.Event(), asyncio.Event()
        self.inventory_signature = None
        if self.inventory_visible.is_set():
            self.detection_request.set()
        if self.closing or self.request_stop:
            self.stop_event.set()
        self.relay = Relay(trust=TrustStore(self.trust_path), pairing=self.pairing, notify=lambda text: self.events.put(("status", text)), feedback=lambda event: self.events.put(("operation", event)))
        discovery = None
        watchdog = asyncio.create_task(self.relay.watchdog())
        monitor = asyncio.create_task(self.monitor_targets())
        try:
            host = os.environ.get("BILI_REMOTE_BIND_HOST", "0.0.0.0")
            async with serve(self.relay.handle, host, self.port, process_request=self.relay.http, max_size=16_384, ping_interval=10, ping_timeout=5, close_timeout=2) as server:
                discovery = await start_discovery(self.relay.trust.public_info(self.port), host=host, port=self.discovery_port)
                self.events.put(("status", "电脑已在线 · 等待手机连接"))
                addresses = sorted({r[4][0] for r in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET) if not r[4][0].startswith("127.")})
                self.events.put(("addresses", socket.gethostname() + " · " + " / ".join(addresses)))
                await self.stop_event.wait()
                await self.relay.close()
                server.close()
        finally:
            if discovery:
                discovery.close()
            for task in (watchdog, monitor):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self.loop = None

    async def monitor_targets(self):
        while True:
            if not self.inventory_visible.is_set() and not self.detection_request.is_set():
                await self.detection_request.wait()
            force = self.detection_request.is_set()
            self.detection_request.clear()
            try:
                installed, running = await asyncio.to_thread(self.detector.scan, force)
                try:
                    sessions = (await asyncio.wait_for(self.relay.native.discover(), 3))["sessions"]
                except Exception:
                    sessions = []
                browser = self.relay.browser
                name = browser.executable.name.lower() if browser.running and browser.executable else ""
                rows = combine(installed, running, sessions, name)
                if rows != self.inventory_signature:
                    self.inventory_signature = rows
                    self.events.put(("inventory", rows))
            except Exception as exc:
                logging.warning("客户端检测失败：%s", exc)
            try:
                await asyncio.wait_for(self.detection_request.wait(), 15)
            except asyncio.TimeoutError:
                pass

    def refresh_detection(self):
        self.inventory_status.set("正在检测…")
        if self.loop and self.detection_request:
            self.loop.call_soon_threadsafe(self.detection_request.set)

    def update_inventory_visibility(self, event=None):
        if event is not None and event.widget is not self.window:
            return
        visible = self.window.state() not in {"withdrawn", "iconic"} and self.tabs.select() == str(self.detection_page)
        if visible and not self.inventory_visible.is_set():
            self.inventory_visible.set()
            self.refresh_detection()
        elif not visible:
            self.inventory_visible.clear()

    def open_browser(self):
        if not self.loop or not self.relay:
            self.status.set("请先启动电脑服务")
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

    def change_startup(self):
        try:
            set_startup(self.autostart.get())
            self.options_status.set("已启用开机自启" if self.autostart.get() else "已关闭开机自启")
        except OSError as exc:
            self.autostart.set(startup_enabled())
            self.options_status.set(f"启动项设置失败：{exc}")

    def save_preference(self, name, value):
        try:
            self.preferences.set(name, value)
        except OSError as exc:
            self.options_status.set(f"设置保存失败：{exc}")

    def show(self):
        if not self.hidden:
            self.window.deiconify()
            self.window.lift()
            self.update_inventory_visibility()

    def minimize(self):
        self.inventory_visible.clear()
        if self.tray and self.tray.visible:
            self.window.withdraw()
        elif not self.hidden:
            self.window.iconify()

    def on_close_window(self):
        if self.close_to_tray.get() and self.tray and self.tray.visible:
            self.minimize()
        else:
            self.close()

    def uninstall(self):
        uninstaller = installed_uninstaller()
        if uninstaller:
            subprocess.Popen([str(uninstaller)], creationflags=subprocess.CREATE_NO_WINDOW)
            self.close()
        elif messagebox.askyesno("清理本机数据", "关闭开机自启，清除本机设置、手机授权、日志及专用播放窗口的登录记录，然后退出。程序文件可在退出后删除。是否继续？", parent=self.window):
            try:
                set_startup(False)
                self.cleanup_on_exit = True
                self.close()
            except OSError as exc:
                self.options_status.set(f"清理启动项失败：{exc}")

    def toggle_service(self):
        self.stop() if self.thread and self.thread.is_alive() else self.start()

    def stop(self):
        self.request_stop = True
        if self.loop and self.stop_event:
            self.loop.call_soon_threadsafe(self.stop_event.set)
        self.status.set("正在停止服务…")

    def revoke(self):
        if self.loop and self.relay:
            asyncio.run_coroutine_threadsafe(self.relay.revoke_all(), self.loop)
            self.status.set("手机授权已取消，下次需重新输入配对码")

    def open_help(self):
        path = Path(__file__).resolve().parents[1] / "README.md"
        if path.exists():
            os.startfile(path)

    def poll(self):
        self.refresh_pin_label()
        deadline, handled, operations = time.monotonic() + .008, 0, []
        while handled < 32 and time.monotonic() < deadline and not self.events.empty():
            kind, payload = self.events.get_nowait()
            handled += 1
            if kind in {"status", "error"}:
                self.status.set(payload)
            elif kind == "addresses":
                self.addresses.set(payload)
            elif kind == "operation":
                operations.append(payload)
            elif kind == "inventory":
                self.inventory.delete(*self.inventory.get_children())
                for row in payload:
                    self.inventory.insert("", "end", text=row.get("installed_name", row["name"]), values=(row["version"], "运行中" if row["running"] else "已安装", row["capabilities"]))
                if payload:
                    self.inventory_empty.place_forget()
                else:
                    self.inventory_empty.configure(text="暂未发现播放器\n打开哔哩哔哩播放窗口或客户端后，再次检测。")
                    self.inventory_empty.place(relx=.5, rely=.5, anchor="center")
                self.inventory_status.set(f"检测到 {len(payload)} 个目标，本页可见时每 15 秒更新" if payload else "请打开哔哩哔哩播放窗口或客户端")
            elif kind == "show":
                self.show()
            elif kind == "quit":
                self.close()
            elif kind == "stopped":
                self.toggle.config(text="启动服务")
                if not self.status.get().startswith("服务启动失败"):
                    self.status.set("服务已停止")
        if operations:
            self.display_operations(operations)
        if self.closing and (not self.thread or not self.thread.is_alive()):
            if self.overlay:
                self.overlay.close()
            if self.tray:
                self.tray.close()
            self.window.destroy()
            return
        self.window.after(16 if not self.events.empty() else 50, self.poll)

    def display_operations(self, operations):
        text = operations[-1]["text"]
        if self.last_operation.get() != text:
            self.last_operation.set(text)
        newest = list(reversed(operations))
        timestamp = time.strftime("%H:%M:%S")
        lines = [timestamp + "  " + ("" if event["ok"] else "失败 · ") + event["text"] for event in newest]
        self.records.insert(0, *lines)
        for index, event in enumerate(newest):
            if not event["ok"]:
                self.records.itemconfigure(index, foreground="#C23B45")
        if self.records.size() > 100:
            self.records.delete(100, "end")
        if self.records_empty.winfo_manager():
            self.records_empty.place_forget()
        # Keep every log entry, but paint the latest meaningful overlay once.
        # An error or discrete action takes precedence over coalesced scrubbing.
        feedback = next((event for event in newest if not event["ok"] or event.get("cmd") not in {"volume", "seek_to"}), newest[0])
        now = time.monotonic()
        if not self.hidden and self.show_feedback.get() and (feedback.get("cmd") not in {"volume", "seek_to"} or now - self.last_overlay_time > .15):
            self.show_overlay(feedback["text"], feedback["ok"])
            self.last_overlay_time = now

    def close(self):
        self.end_feedback_preview()
        if self.feedback_save_timer:
            self.flush_feedback_style()
        self.closing = True
        self.stop()

    def run(self):
        self.window.mainloop()
        if getattr(self, "cleanup_on_exit", False):
            import shutil
            logging.shutdown()
            directory = self.preferences.path.parent.resolve()
            profile = (directory / "browser-profile").resolve()
            if profile.parent == directory and profile.is_dir():
                shutil.rmtree(profile)
            for name in ("trust.json", "trust.tmp", "settings.json", "settings.tmp", "remote.log", "remote.log.1", "remote.log.2"):
                (directory / name).unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                directory.rmdir()


def main():
    enable_dpi_awareness()
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
    logging.basicConfig(level=logging.WARNING, handlers=[RotatingFileHandler(directory / "remote.log", maxBytes=256 * 1024, backupCount=2, encoding="utf-8")], format="%(asctime)s %(message)s")
    try:
        Companion(background="--background" in sys.argv, port=int(os.environ.get("BILI_REMOTE_PORT", "8765")), discovery_port=int(os.environ.get("BILI_REMOTE_DISCOVERY_PORT", "8766"))).run()
    finally:
        logging.shutdown()
        guard.close()


if __name__ == "__main__":
    main()
