"""Render documentation artwork from the current UI using isolated sample data.

Windows only. Optional dependencies: pip install pillow playwright
Uses installed Edge/Chrome, never a user's browser profile, phone data or service.
"""
import ctypes
import functools
import json
import os
import sys
import tempfile
import threading
from ctypes import wintypes
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/images"
RAW = ROOT / ".tooling/docs-captures"
sys.path.insert(0, str(ROOT))
from scripts.release_files import release_paths

INK, MUTED, PINK, CYAN = "#F3F5FC", "#A3AEC3", "#FB7299", "#75E1EB"
NAVY, CARD, LINE = "#101521", "#1B2233", "#323D54"
FONT = Path("C:/Windows/Fonts/msyh.ttc")
BOLD = Path("C:/Windows/Fonts/msyhbd.ttc")


def font(size, bold=False):
    return ImageFont.truetype(str(BOLD if bold else FONT), size)


def text(draw, xy, value, size=26, color=INK, bold=False):
    draw.text(xy, value, font=font(size, bold), fill=color)


def canvas(width, height, title, subtitle):
    image = Image.new("RGB", (width, height), NAVY)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((48, 44, 56, 102), 4, fill=PINK)
    text(draw, (78, 40), title, 42, bold=True)
    text(draw, (78, 105), subtitle, 22, MUTED)
    return image, draw


def arrow(draw, start, end, color=CYAN, width=7):
    import math
    draw.line([start, end], fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    points = [end]
    for delta in (-.52, .52):
        points.append((end[0] - 21 * math.cos(angle + delta), end[1] - 21 * math.sin(angle + delta)))
    draw.polygon(points, fill=color)


def phone(image, path, x, y, width=300):
    raw = Image.open(path).convert("RGB")
    height = round(raw.height * width / raw.width)
    raw = raw.resize((width, height), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((x - 9, y - 9, x + width + 9, y + height + 9), 32, fill="#090C13", outline=LINE, width=3)
    mask = Image.new("L", raw.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width, height), 24, fill=255)
    image.paste(raw, (x, y), mask)
    return height


def capture_mobile():
    from desktop.browser import find_browser

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Handler, directory=str(ROOT / "android/app/src/main/assets"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(find_browser()), headless=True)
            try:
                for style, pairing in (("remote", False), ("touchpad", False), ("remote", True)):
                    context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
                    config = {"schema": 2, "ui_style": style, "device_id": "documentation-demo-phone", "device_name": "演示手机",
                              "host": "192.168.1.10:8765", "computer_id": "documentation-demo-computer", "target": "auto", "rate": 2,
                              "history": [{"host": "192.168.1.10:8765", "name": "演示电脑", "computer_id": "documentation-demo-computer", "manual": True}]}
                    fixture = """
                    const sample = __CONFIG__;
                    window.Android = {
                      loadSettings: () => JSON.stringify(sample), saveSettings: () => {},
                      deviceId: () => sample.device_id, deviceName: () => sample.device_name,
                      startDiscovery: () => setTimeout(() => window.onComputersDiscovered?.([
                        {name: '演示电脑', computer_id: sample.computer_id, host: sample.host}
                      ]), 200), stopDiscovery: () => {}
                    };
                    window.WebSocket = class {
                      static OPEN = 1;
                      constructor() { this.readyState = 0; setTimeout(() => { this.readyState = 1; this.onopen?.(); }, 80); }
                      send(text) {
                        const request = JSON.parse(text);
                        const reply = request.role === 'remote'
                          ? (__PAIRING__ ? {type: 'auth', ok: false, code: 'pair_required', error: '请先配对', computer_id: sample.computer_id}
                            : {type: 'auth', ok: true, computer_id: sample.computer_id, computer_name: '演示电脑', token: 'documentation-fixture-only'})
                          : {id: request.id, ok: true, result: {paused: true, volume: 0.5, rate: 1}};
                        setTimeout(() => this.onmessage?.({data: JSON.stringify(reply)}), 50);
                      }
                      close() { this.readyState = 3; }
                    };
                    """.replace("__CONFIG__", json.dumps(config, ensure_ascii=False)).replace("__PAIRING__", str(pairing).lower())
                    context.add_init_script(fixture)
                    page = context.new_page()
                    page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="networkidle")
                    if pairing:
                        page.locator("#pairing[open]").wait_for()
                        page.locator("#pairingCode").fill("123456")
                        page.screenshot(path=str(RAW / "mobile-pairing.png"))
                    else:
                        page.locator("body.connected").wait_for()
                        page.wait_for_function("!document.querySelector('#hud').classList.contains('visible') && getComputedStyle(document.querySelector('#hud')).opacity === '0'")
                        page.screenshot(path=str(RAW / ("mobile-" + style + ".png")))
                        if style == "remote":
                            page.locator("#openSettings").click()
                            page.screenshot(path=str(RAW / "mobile-settings.png"))
                            page.locator("#manualDetails summary").click()
                            page.screenshot(path=str(RAW / "mobile-history.png"))
                            page.locator("#manualDetails summary").click()
                            page.locator("#launchBrowser").scroll_into_view_if_needed()
                            page.screenshot(path=str(RAW / "mobile-player-settings.png"))
                    context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def capture_window(window, path):
    """Capture only this window's client pixels; never capture the user's screen."""
    window.update_idletasks()
    window.update()
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    user.GetParent.argtypes, user.GetParent.restype = [wintypes.HWND], wintypes.HWND
    handle = user.GetParent(window.winfo_id()) or window.winfo_id()
    rect = wintypes.RECT()
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetClientRect(handle, ctypes.byref(rect))
    width, height = rect.right, rect.bottom
    user.GetDC.argtypes, user.GetDC.restype = [wintypes.HWND], wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi.CreateCompatibleDC.argtypes, gdi.CreateCompatibleDC.restype = [wintypes.HDC], wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes, gdi.CreateCompatibleBitmap.restype = [wintypes.HDC, ctypes.c_int, ctypes.c_int], wintypes.HBITMAP
    gdi.SelectObject.argtypes, gdi.SelectObject.restype = [wintypes.HDC, wintypes.HANDLE], wintypes.HANDLE
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    source = user.GetDC(handle)
    target = gdi.CreateCompatibleDC(source)
    bitmap = gdi.CreateCompatibleBitmap(source, width, height)
    previous = gdi.SelectObject(target, bitmap)

    class BitmapHeader(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG), ("height", wintypes.LONG),
                    ("planes", wintypes.WORD), ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                    ("image_size", wintypes.DWORD), ("x", wintypes.LONG), ("y", wintypes.LONG),
                    ("colors", wintypes.DWORD), ("important", wintypes.DWORD)]

    try:
        if not user.PrintWindow(handle, target, 3):
            raise RuntimeError("无法捕获文档预览窗口")
        gdi.SelectObject(target, previous)
        header = BitmapHeader(ctypes.sizeof(BitmapHeader), width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        if not gdi.GetDIBits(target, bitmap, 0, height, pixels, ctypes.byref(header), 0):
            raise RuntimeError("无法读取窗口像素")
        image = Image.frombytes("RGB", (width, height), pixels.raw, "raw", "BGRX")
        if max(ImageStat.Stat(image).stddev) < 3:
            raise RuntimeError("窗口截图为空白")
        image.save(path)
    finally:
        gdi.SelectObject(target, previous)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(target)
        user.ReleaseDC(handle, source)


def capture_desktop():
    import tkinter.ttk as ttk
    with tempfile.TemporaryDirectory(prefix="bili-docs-") as directory:
        os.environ["BILI_REMOTE_INSTANCE_NAME"] = "BiliRemote-DocumentationPreview"
        os.environ["BILI_REMOTE_DATA_DIR"] = directory
        from desktop.gui import Companion

        class Preview(Companion):
            def start(self):
                # Render the real widgets without network, real device discovery or data.
                self.toggle.config(text="停止服务")
                self.status.set("电脑已在线，正在广播；等待手机连接。")
                self.addresses.set("演示电脑 · 192.168.1.10")

            def refresh_pin_label(self):
                self.pin_text.set("123 456")

        from unittest.mock import patch
        with patch("desktop.gui.startup_enabled", return_value=False):
            app = Preview(hidden=True)
        try:
            app.window.title("哔哩哔哩手势遥控 · 文档界面预览")
            app.window.geometry("760x730+30+30")
            app.window.deiconify()
            capture_window(app.window, RAW / "desktop-main.png")
            tabs = next(widget for frame in app.window.winfo_children() for widget in frame.winfo_children() if isinstance(widget, ttk.Notebook))
            tabs.select(3)
            capture_window(app.window, RAW / "desktop-settings.png")
        finally:
            app.window.destroy()


def build_styles():
    image, draw = canvas(1440, 1060, "两种样式，同一套播放控制", "手机界面预览 · 由当前 WebView 页面渲染；电脑名称与连接状态为示例")
    for x, name, caption, path in [(160, "传统遥控器", "按键清晰，直接点击", "mobile-remote.png"), (870, "纯黑触摸板", "整个黑色区域都能操作", "mobile-touchpad.png")]:
        text(draw, (x - 10, 185), name, 31, bold=True)
        phone(image, RAW / path, x, 254, 290)
        text(draw, (x - 25, 930), caption, 23, MUTED)
    text(draw, (551, 405), "同一手机", 26, CYAN, True)
    text(draw, (551, 454), "随时切换", 26)
    arrow(draw, (550, 535), (738, 535))
    text(draw, (490, 620), "设置 → 遥控器样式", 22, MUTED)
    image.save(OUTPUT / "remote-styles.png", optimize=True)


def build_mobile_setup():
    image, draw = canvas(1600, 1090, "第一次连接，看这三个位置", "界面预览 · 192.168.1.10 与 123456 仅为示例，请以你的电脑实际显示为准")
    for x, title, caption, path in [(100, "① 选择在线电脑", "自动扫描同一路由器下的电脑", "mobile-settings.png"),
                                   (650, "② 输入电脑配对码", "只需首次认证；以后保存授权", "mobile-pairing.png"),
                                   (1200, "③ 手动 IP 与记录", "发现失败时备用；地址自动保存", "mobile-history.png")]:
        text(draw, (x - 32, 182), title, 28, bold=True)
        phone(image, RAW / path, x, 250, 270)
        text(draw, (x - 44, 905), caption, 21, MUTED)
    text(draw, (78, 1002), "触摸板里找不到设置？双指触摸，或按 Android 返回键。", 26, CYAN)
    image.save(OUTPUT / "mobile-connection.png", optimize=True)


def build_redesign():
    image, draw = canvas(1120, 1180, "按键遥控器与设置", "0.4.5 页面渲染 · 连接数据为示例")
    for x, title, path in [(165, "一体圆环 · 按住滑动换挡", "mobile-remote.png"),
                           (665, "播放器 · 手动打开视频", "mobile-player-settings.png")]:
        text(draw, (x - 30, 184), title, 24, bold=True)
        phone(image, RAW / path, x, 242, 300)
    text(draw, (80, 1000), "上下调节音量，左右跳转进度，中央播放 / 暂停", 25, CYAN)
    text(draw, (80, 1055), "按键不会自动打开视频；主动打开入口在设置中", 23, MUTED)
    text(draw, (80, 1112), "设计参考与实现取舍见 docs/DESIGN_REFERENCES.md", 19, MUTED)
    image.save(OUTPUT / "remote-redesign.png", optimize=True)


def build_connection():
    image, draw = canvas(1600, 560, "从安装到遥控，只需四步", "电脑可接网线，手机可连 WiFi；关键是接入同一路由器且设备之间允许通信")
    steps = [("01", "安装两端", "电脑装 EXE", "手机装 APK"), ("02", "同一路由器", "打开电脑软件", "手机自动发现"),
             ("03", "首次输入配对码", "查看电脑 6 位数字", "在手机完成配对"), ("04", "之后自动重连", "保留配对记录", "打开手机即可重试连接")]
    for index, (number, title, first, second) in enumerate(steps):
        x = 60 + index * 390
        draw.rounded_rectangle((x, 190, x + 310, 465), 26, fill=CARD, outline=LINE, width=2)
        text(draw, (x + 25, 208), number, 44, PINK, True)
        text(draw, (x + 25, 289), title, 27, bold=True)
        text(draw, (x + 25, 347), first, 22, MUTED)
        text(draw, (x + 25, 391), second, 22, MUTED)
        if index < 3:
            arrow(draw, (x + 328, 328), (x + 373, 328), width=5)
    image.save(OUTPUT / "connection-flow.png", optimize=True)


def build_gestures():
    image, draw = canvas(1440, 1010, "黑色触摸板：四种手势", "以下为操作示意，图中的箭头和触点不会常驻显示在 App 中")
    cards = [("01", "轻点任意位置", "播放 / 暂停", "短按后松手", "tap"),
             ("02", "上下滑动", "调节视频音量", "上滑增大，下滑减小", "vertical"),
             ("03", "左右滑动", "快进 / 快退", "右滑快进，左滑快退；松手跳转", "horizontal"),
             ("04", "长按不放", "临时倍速播放", "按住 0.5 秒触发，松手恢复原速度", "hold")]
    for index, (number, title, main, caption, kind) in enumerate(cards):
        x, y = 52 + (index % 2) * 686, 185 + (index // 2) * 350
        draw.rounded_rectangle((x, y, x + 650, y + 320), 24, fill=CARD, outline=LINE, width=2)
        draw.rounded_rectangle((x + 30, y + 35, x + 190, y + 281), 24, fill="black", outline="#526078", width=3)
        cx, cy = x + 110, y + 158
        if kind in {"tap", "hold"}:
            draw.ellipse((cx - 27, cy - 27, cx + 27, cy + 27), outline=PINK, width=5)
            draw.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=PINK)
            if kind == "hold":
                text(draw, (cx - 22, cy + 50), "2×", 27, CYAN, True)
        elif kind == "vertical":
            arrow(draw, (cx - 15, cy + 62), (cx - 15, cy - 67))
            arrow(draw, (cx + 25, cy - 62), (cx + 25, cy + 67), color=PINK)
        else:
            arrow(draw, (cx - 55, cy - 18), (cx + 60, cy - 18))
            arrow(draw, (cx + 55, cy + 26), (cx - 60, cy + 26), color=PINK)
        text(draw, (x + 220, y + 36), number + "  " + title, 27, MUTED)
        text(draw, (x + 220, y + 105), main, 34, bold=True)
        # Split the only long captions for legible mobile rendering.
        if len(caption) > 15:
            first, second = caption.split("，", 1)
            text(draw, (x + 220, y + 180), first, 23, MUTED)
            text(draw, (x + 220, y + 222), second, 23, MUTED)
        else:
            text(draw, (x + 220, y + 180), caption, 23, MUTED)
    text(draw, (78, 920), "长按后左右滑：左滑 2× / 右滑 3×，松手恢复原速", 25, CYAN)
    text(draw, (78, 966), "开始长按、切换挡位各轻震一次；可在设置中关闭震动", 23, MUTED)
    image.save(OUTPUT / "gestures.png", optimize=True)


def build_desktop_panels():
    for stem, title, subtitle in [("desktop-main", "电脑端：配对与播放入口", "真实桌面组件渲染 · 配对码、电脑名称与地址为示例"),
                                  ("desktop-settings", "电脑端：托盘、自启与操作提示", "设置项作用于电脑端；图示使用独立预览实例，未修改你的正式配置")]:
        image, draw = canvas(1120, 1010, title, subtitle)
        raw = Image.open(RAW / (stem + ".png")).convert("RGB")
        raw.thumbnail((920, 780), Image.Resampling.LANCZOS)
        x, y = (1120 - raw.width) // 2, 190
        draw.rounded_rectangle((x - 8, y - 8, x + raw.width + 8, y + raw.height + 8), 14, fill=LINE)
        image.paste(raw, (x, y))
        image.save(OUTPUT / (stem + ".png"), optimize=True)


def build_upgrade():
    image, draw = canvas(1440, 590, "升级时，直接安装新版", "覆盖安装保留数据；先卸载再安装会清除原来的配对和设置")
    for x, label, first, second in [(60, "Windows", "运行新版 " + release_paths(ROOT)["installer"].name, "原目录覆盖；原本运行时自动恢复到托盘"),
                                   (750, "Android", "打开新版 APK，确认系统的“更新”", "同包名、同签名、递增版本代码")]:
        draw.rounded_rectangle((x, 195, x + 630, 425), 25, fill=CARD, outline=LINE, width=2)
        text(draw, (x + 30, 216), label, 31, PINK, True)
        text(draw, (x + 30, 290), first, 25)
        text(draw, (x + 30, 350), second, 23, MUTED)
    text(draw, (80, 480), "保留：电脑 / 手机标识、配对授权、IP 历史、遥控样式、电脑设置与专用浏览器资料", 26, CYAN)
    image.save(OUTPUT / "upgrade.png", optimize=True)


def build_hero():
    image = Image.new("RGB", (1600, 860), NAVY)
    draw = ImageDraw.Draw(image)
    draw.ellipse((930, -170, 1900, 800), fill="#172536")
    icon = Image.open(ROOT / "android/artwork/bili-remote-android.png").convert("RGBA")
    icon.thumbnail((110, 110))
    image.paste(icon, (82, 74), icon)
    text(draw, (215, 96), "BILI REMOTE", 31, CYAN, True)
    text(draw, (80, 240), "让播放，", 73, bold=True)
    text(draw, (80, 340), "随手掌控。", 73, bold=True)
    text(draw, (86, 475), "手机遥控电脑上的哔哩哔哩", 32, MUTED)
    text(draw, (86, 550), "传统遥控器  /  纯黑触摸板", 28)
    draw.rounded_rectangle((82, 640, 664, 705), 16, fill="#263146")
    text(draw, (106, 655), "同一局域网 · 首次配对 · 后续自动重连", 25, CYAN)
    text(draw, (85, 773), "v0.4.5  ·  Windows + Android", 24, MUTED)
    phone(image, RAW / "mobile-touchpad.png", 900, 145, 245)
    phone(image, RAW / "mobile-remote.png", 1220, 85, 265)
    text(draw, (925, 714), "纯黑手势区域", 24, MUTED)
    text(draw, (1250, 714), "传统遥控器", 24, MUTED)
    text(draw, (948, 783), "界面预览 · 连接信息为示例", 20, MUTED)
    image.save(OUTPUT / "overview.png", optimize=True)


def main():
    if os.name != "nt":
        raise SystemExit("文档桌面截图需要 Windows；已提交的 PNG 可直接用于阅读。")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    capture_mobile()
    capture_desktop()
    for renderer in (build_styles, build_mobile_setup, build_redesign, build_connection, build_gestures, build_desktop_panels, build_upgrade, build_hero):
        renderer()
    print("Documentation images:", OUTPUT)


if __name__ == "__main__":
    main()
