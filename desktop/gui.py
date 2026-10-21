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
from tkinter import messagebox, ttk

from websockets.asyncio.server import serve

from .detection import ClientDetector, combine
from .discovery import start_discovery
from .feedback import OperationOverlay
from .layout import FlowRow, ScrollablePage, check_option, enable_dpi_awareness, fit_window, wrapped_label
from .pairing import PairingCode
from .server import Relay
from .trust import TrustStore
from .windows import NativeTray, Preferences, InstanceGuard, WINDOW_TITLE, data_directory, icon_path, installed_uninstaller, signal_existing, startup_enabled, set_startup


class Companion:
    def __init__(self, hidden=False, port=8765, discovery_port=8766, trust_path=None, background=False, preferences_path=None):
        enable_dpi_awareness()
        self.window = tk.Tk()
        if hidden or background:
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
        self.pairing = PairingCode()
        self.tray = self.overlay = None
        self.last_overlay_time = 0
        self.build_ui()
        if not hidden:
            try:
                self.tray = NativeTray(self.window, lambda kind: self.events.put((kind, None)))
                self.overlay = OperationOverlay(self.window)
            except OSError as exc:
                logging.warning("桌面提示或托盘不可用：%s", exc)
        self.window.protocol("WM_DELETE_WINDOW", self.on_close_window)
        self.window.after(200, self.poll)
        self.start()
        if background:
            self.minimize()

    def build_ui(self):
        frame = ttk.Frame(self.window, padding=round(16 * self.ui_scale))
        frame.pack(fill="both", expand=True)
        wrapped_label(frame, text="哔哩哔哩手势遥控", font=("Microsoft YaHei", 19)).pack(anchor="w", pady=(0, 12))
        tabs = ttk.Notebook(frame)
        tabs.pack(fill="both", expand=True)
        remote_page, detection, options_page, records = [ttk.Frame(tabs) for _ in range(4)]
        for widget, name in ((remote_page, "连接与播放"), (detection, "客户端与版本"), (records, "操作记录"), (options_page, "设置")):
            tabs.add(widget, text=name)
        self.tabs = tabs
        self.remote_page = ScrollablePage(remote_page, padding=round(14 * self.ui_scale))
        self.options_page = ScrollablePage(options_page, padding=round(14 * self.ui_scale))
        remote, options = self.remote_page.content, self.options_page.content
        detection.configure(padding=round(14 * self.ui_scale)); records.configure(padding=round(14 * self.ui_scale))
        wrapped_label(remote, text="手机打开即搜索。首次输入下方配对码，以后自动连接。").pack(anchor="w")
        pin_frame = FlowRow(remote)
        pin_frame.pack(fill="x", pady=12)
        self.pin_text = tk.StringVar()
        pin_frame.add(ttk.Label(pin_frame, textvariable=self.pin_text, font=("Consolas", 30, "bold")))
        pin_frame.add(ttk.Button(pin_frame, text="刷新配对码", command=self.refresh_pin))
        wrapped_label(remote, text="配对码每 10 分钟刷新，已连接手机不受影响。", foreground="#666666").pack(anchor="w")
        self.status = tk.StringVar(value="正在启动…")
        wrapped_label(remote, textvariable=self.status).pack(anchor="w", pady=(18, 8))
        self.addresses = tk.StringVar()
        wrapped_label(remote, textvariable=self.addresses, foreground="#666666").pack(anchor="w")
        player = ttk.LabelFrame(remote, text="播放视频", padding=12)
        player.pack(fill="x", pady=16)
        ttk.Button(player, text="打开哔哩哔哩 · 无需扩展", command=self.open_browser).pack(anchor="w")
        wrapped_label(player, text="使用软件打开的 Edge / Chrome 窗口播放，可完整控制进度、音量和倍速。\nWindows 客户端可直接播放；可用功能由客户端提供的接口决定。", foreground="#666666").pack(anchor="w", pady=(8, 0))
        self.last_operation = tk.StringVar(value="尚无遥控操作")
        wrapped_label(remote, textvariable=self.last_operation, font=("Microsoft YaHei", 12)).pack(anchor="w", pady=8)
        actions = FlowRow(remote)
        actions.pack(fill="x", pady=12)
        self.toggle = ttk.Button(actions, text="停止服务", command=self.toggle_service)
        actions.add(self.toggle)
        actions.add(ttk.Button(actions, text="取消手机授权", command=self.revoke))
        actions.add(ttk.Button(actions, text="最小化", command=self.minimize))
        wrapped_label(detection, text="自动读取播放器与版本，并检查实际可用的控制功能。").pack(anchor="w")
        inventory_frame = ttk.Frame(detection)
        inventory_frame.pack(fill="both", expand=True, pady=10)
        inventory_frame.rowconfigure(0, weight=1); inventory_frame.columnconfigure(0, weight=1)
        self.inventory = ttk.Treeview(inventory_frame, columns=("version", "state", "capabilities"), height=6)
        self.inventory.heading("#0", text="客户端 / 浏览器")
        self.inventory.column("#0", width=140, minwidth=90)
        for column, title, width in (("version", "版本", 105), ("state", "状态", 60), ("capabilities", "控制方式", 235)):
            self.inventory.heading(column, text=title)
            self.inventory.column(column, width=width, minwidth=55)
        self.inventory.grid(row=0, column=0, sticky="nsew")
        for orient, row, column, sticky, command in (("vertical", 0, 1, "ns", self.inventory.yview), ("horizontal", 1, 0, "ew", self.inventory.xview)):
            bar = ttk.Scrollbar(inventory_frame, orient=orient, command=command)
            bar.grid(row=row, column=column, sticky=sticky)
            self.inventory.configure(**{("y" if orient == "vertical" else "x") + "scrollcommand": bar.set})
        self.inventory_status = tk.StringVar(value="正在检测…")
        wrapped_label(detection, textvariable=self.inventory_status, foreground="#666666").pack(anchor="w", before=inventory_frame)
        ttk.Button(detection, text="重新检测", command=self.refresh_detection).pack(anchor="w", pady=10, before=inventory_frame)
        records_frame = ttk.Frame(records)
        records_frame.pack(fill="both", expand=True)
        records_frame.rowconfigure(0, weight=1); records_frame.columnconfigure(0, weight=1)
        self.records = tk.Listbox(records_frame, font=("Microsoft YaHei", 11), activestyle="none", borderwidth=0, height=4)
        self.records.grid(row=0, column=0, sticky="nsew")
        for orient, row, column, sticky, command in (("vertical", 0, 1, "ns", self.records.yview), ("horizontal", 1, 0, "ew", self.records.xview)):
            bar = ttk.Scrollbar(records_frame, orient=orient, command=command)
            bar.grid(row=row, column=column, sticky=sticky)
            self.records.configure(**{("y" if orient == "vertical" else "x") + "scrollcommand": bar.set})
        wrapped_label(records, text="保留本次运行最近 100 条操作；错误也会显示在这里。", foreground="#666666").pack(anchor="w", pady=10, before=records_frame)
        self.autostart = tk.BooleanVar(value=startup_enabled())
        check_option(options, "登录 Windows 后自动启动", self.autostart, self.change_startup)
        self.close_to_tray = tk.BooleanVar(value=self.preferences.values.get("close_to_tray", True))
        check_option(options, "关闭窗口时保留在系统托盘运行", self.close_to_tray, lambda: self.save_preference("close_to_tray", self.close_to_tray.get()))
        self.show_feedback = tk.BooleanVar(value=self.preferences.values.get("show_feedback", True))
        check_option(options, "遥控操作时显示桌面提示", self.show_feedback, lambda: self.save_preference("show_feedback", self.show_feedback.get()))
        wrapped_label(options, text="电脑在线时会广播供手机发现。配对过的手机不再需要输入配对码。\n双击托盘图标打开，右键可完全退出。", foreground="#666666").pack(anchor="w", pady=16)
        self.options_status = tk.StringVar()
        wrapped_label(options, textvariable=self.options_status).pack(anchor="w", pady=8)
        for label, action in (("打开使用说明", self.open_help), ("卸载 / 清理本机数据", self.uninstall), ("完全退出", self.close)):
            ttk.Button(options, text=label, command=action).pack(anchor="w", pady=7)
        self.refresh_pin_label()

    def refresh_pin_label(self):
        code = self.pairing.current()
        self.pin_text.set(code[:3] + " " + code[3:])

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
                self.events.put(("status", "电脑已在线，正在广播；等待手机连接。"))
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
                self.events.put(("inventory", combine(installed, running, sessions, name)))
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

    def open_browser(self):
        if not self.loop or not self.relay:
            self.status.set("请先启动电脑服务")
            return
        async def open_window():
            try:
                await self.relay.browser.open()
                self.events.put(("operation", {"ok": True, "text": "已打开遥控播放窗口，请选择视频", "cmd": "open_browser"}))
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

    def minimize(self):
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
        while not self.events.empty():
            kind, payload = self.events.get_nowait()
            if kind in {"status", "error"}:
                self.status.set(payload)
            elif kind == "addresses":
                self.addresses.set(payload)
            elif kind == "operation":
                text = payload["text"]
                self.last_operation.set(text)
                self.records.insert(0, time.strftime("%H:%M:%S") + "  " + ("" if payload["ok"] else "失败 · ") + text)
                if self.records.size() > 100:
                    self.records.delete(100, "end")
                now = time.monotonic()
                if self.overlay and self.show_feedback.get() and (payload.get("cmd") not in {"volume", "seek_to"} or now - self.last_overlay_time > .15):
                    self.overlay.show(text, payload["ok"])
                    self.last_overlay_time = now
            elif kind == "inventory":
                self.inventory.delete(*self.inventory.get_children())
                for row in payload:
                    self.inventory.insert("", "end", text=row.get("installed_name", row["name"]), values=(row["version"], "运行中" if row["running"] else "已安装", row["capabilities"]))
                self.inventory_status.set(f"检测到 {len(payload)} 个目标，每 15 秒更新" if payload else "请打开哔哩哔哩播放窗口或客户端")
            elif kind == "show":
                self.show()
            elif kind == "quit":
                self.close()
            elif kind == "stopped":
                self.toggle.config(text="启动服务")
                if not self.status.get().startswith("服务启动失败"):
                    self.status.set("服务已停止")
        if self.closing and (not self.thread or not self.thread.is_alive()):
            if self.overlay:
                self.overlay.close()
            if self.tray:
                self.tray.close()
            self.window.destroy()
            return
        self.window.after(200, self.poll)

    def close(self):
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
