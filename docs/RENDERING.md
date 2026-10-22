# 电脑端滚动与绘制优化 · 0.5.7

[项目首页](../README.md) · [电脑端设计](DESKTOP_DESIGN.md) · [开发说明](DEVELOPMENT.md)

0.5.7 更新菜单选中样式，并将连接 / 设置页的滚动改成独立视口内移动已有内容。保留全宽布局、菜单选中背景滑动、页面上下过渡、字幕持续预览和实际控件输入。

![当前电脑界面](images/desktop-main.png)

## 参考了什么

2026-10-22 实际读取以下官方文档及公开源码，采用其设计原则；本项目继续使用 Tk，没有迁移到 Qt，也没有引入 VS Code 的网页运行环境或复制其源码。

| 资料 | 原理与本项目对应 |
| --- | --- |
| [Qt QScrollArea 源码](https://github.com/qt/qtbase/blob/6.8/src/widgets/widgets/qscrollarea.cpp) | `updateWidgetPosition()` 在视口内移动一个内容组件；本项目以独立视口裁剪内容，不再通过 Canvas 滚动嵌套的原生子窗口 |
| [Qt QAbstractScrollArea](https://doc.qt.io/qt-6/qabstractscrollarea.html) | 滚动范围、视口大小与内容位置分开管理；本项目按内容高度限制偏移，尺寸变化后重新计算范围 |
| [Qt QWidget 绘制](https://doc.qt.io/qt-6/qwidget.html) | 缓冲绘制；多次 `update()` 合并为一次绘制，避免反复同步 `repaint()`；本项目合并布局通知，滚动帧只移动已有缓存，不逐帧全量刷新 |
| [VS Code Scrollable 源码](https://github.com/microsoft/vscode/blob/main/src/vs/base/common/scrollable.ts) | 合并连续滚动目标，复用平滑操作并在下一帧推进；本项目仅保留一个滚动计时器、按真实经过时间计算进度，反向输入立即改变方向 |
| [Windows ScrollWindowEx](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-scrollwindowex) | 官方明确说明：部分子窗口被滚动时，`SW_SCROLLCHILDREN` 可能无法正确更新屏幕；不能把像素复制与子窗口位置更新视为天然一致。本项目移除混合滚动路径，但这条说明不能证明用户机器上的残影一定由此引起 |
| [Windows 窗口与分层绘制](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features) | 系统保存分层窗口图像并进行合成；子窗口需要正确裁剪。本项目仅缓存滚动内容，其他页面缓存完整页面，避免双层重复缓存 |

## 改动

- 连接 / 设置页使用原生视口和单一内容窗口；内容宽度铺满视口。Windows 缓存内容表面，滚动以 `SetWindowPos` 改变位置；真实控件随内容移动，继续接受鼠标和键盘输入。
- 滚轮遵循 Windows 滚动行数，每行约 16 个逻辑像素。本机 125% 缩放、每格 3 行时约移动 60 像素；旧方式每格约移动视口高度的 30%，本机为 234 像素。
- 连续滚轮输入合并为最新目标，短过渡约 100 ms，目标 60 Hz；保留小增量，反向立即响应，迟到跳帧而不排队。滚动条拖动和键盘翻页直接定位；系统关闭动画时直接滚动。切页、销毁或布局变化会取消旧滚动，结束后释放精细计时。
- 菜单选中项使用白色圆角底色、细边界、蓝色图标和加粗名称。鼠标点击不显示焦点框；Tab 导航仍显示连续的蓝色圆角轮廓，Enter / 空格和 Alt+1–4 保留。
- 保持已有页面与图片复用；运行时不新增浏览器内核、截图动画、常驻渲染线程或全局强制刷新。

## 同机复测

隔离设置、停止服务与播放器检测；1040×780 窗口，系统缩放约 125%。按顺序运行旧版 0.5.6 与新版 0.5.7，分别向下和向上移动 32 次，每次相同的 24 像素。全部 64 次都发生实际位移，未把滚到边界后的空操作算入数据。

| 指标 | 0.5.6 | 0.5.7 |
| --- | ---: | ---: |
| 滚动更新中位耗时 | 16.063 ms | 1.820 ms |
| 滚动更新 95% 分位 | 58.063 ms | 4.328 ms |
| 滚动更新最大耗时 | 70.080 ms | 7.633 ms |
| 更新并等待 DwmFlush 中位耗时 | 19.485 ms | 5.720 ms |
| 真实滚轮每格移动 | 234 px | 约 60 px |
| 屏幕与强制完整重绘的抽样比较 | 10 / 10 一致 | 10 / 10 一致 |
| 滚动后真实鼠标点击设置控件 | 通过 | 通过 |

耗时包含 Tk 布局 / 绘制事件排空；`DwmFlush` 是额外的系统合成等待指标，不能当作光学显示器扫描或所有机器上的帧率保证。报告保留逐次耗时、偏移和截图差异数据，见发布附件 `Performance-0.5.7.json`。

屏幕比较先用 ImageGrab 抓取实际显示内容，再强制完整重绘同一控件树并抓取参考图。没有使用会主动修复绘制的 PrintWindow。新版抽样未见残影；本机旧版静止抽样也一致，因此不能宣称已精确复现或证明用户截图以外的每一种瞬时残影。新路径消除了 Canvas 像素滚动和原生子窗口移动混用，并明显降低实际滚动更新开销。

另外验证了 120 次连续切页、8 组窗口 / 字体缩放、菜单鼠标与键盘焦点、反向滚动与切页取消、滚动条 / 键盘定位、设置保留、字幕拖动和资源清理。菜单动画事件循环帧间隔中位约 16.7 ms；窗口全宽缩放仍需实际重排，本机中位约 617 ms、峰值约 794 ms，尚未达到流畅连续缩放的目标。不要用滚动或动画数据替代窗口缩放数据。

## 如何复测

要求 Windows 桌面已解锁，测试窗口未被其他置顶窗口遮挡。脚本短暂置顶独立测试窗口并恢复鼠标位置，不修改正式安装、设置、自启或浏览器资料。GUI、浏览器与性能测试依次运行，避免互相干扰。

```powershell
.\.venv\Scripts\python.exe scripts/measure_desktop_scrolling.py --source-root 旧版源码目录 --output .tooling/scrolling-baseline.json
.\.venv\Scripts\python.exe scripts/measure_desktop_scrolling.py --output .tooling/scrolling-current.json --captures .tooling/scroll-captures
.\.venv\Scripts\python.exe scripts/smoke_menu_motion.py
.\.venv\Scripts\python.exe scripts/smoke_desktop_layout.py
```

原生缓存不可用时回退到普通 Tk 内容定位，功能保留，但性能会受环境影响。真实跨显示器 DPI 切换、安卓实机与用户显卡 / 驱动环境仍需进一步实机验证。
