# 电脑端性能、绘制与更新检查 · 0.5.8

[项目首页](../README.md) · [电脑端设计](DESKTOP_DESIGN.md) · [开发说明](DEVELOPMENT.md)

0.5.8 取消页面和菜单切换动画，调整启动打包方式和滚动缓存建立时机，并加入遥控器自身的当前版本及新版检查。

![版本与更新入口](images/desktop-players.png)

## 参考依据与实现

本轮实际阅读 Python / Tkinter、PyInstaller、Windows 绘制和 GitHub 官方文档，并结合上轮读取的 Qt / VS Code 滚动实现。继续使用 Tk 和系统控件，没有引入额外网页内核。

| 官方资料 | 本项目的处理 |
| --- | --- |
| [PyInstaller 运行模式](https://pyinstaller.org/en/latest/operating-mode.html) | 官方说明单文件模式需在临时目录解压且启动略慢；本版改为安装器展开 onedir 运行文件，启动直接加载，不重复解压 |
| [Tkinter 线程模型](https://docs.python.org/3/library/tkinter.html#threading-model) | 事件处理需尽快返回，长任务分段或放在线程中；版本检查与进程 / 注册信息扫描在后台执行，结果经队列更新 UI |
| [Windows 分层窗口与绘制](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features) | 分层窗口有独立图像并由系统合成；移除整页分层纹理，仅在实际滚动时按需缓存已经显示的内容，立即完成缓存首轮绘制 |
| [GitHub 最新正式发布版 API](https://docs.github.com/en/rest/releases/releases#get-the-latest-release) | 检查公开正式版，跳过草稿 / 预发布，校验本仓库对应版本的电脑安装包已存在 |
| [GitHub REST API 使用建议](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api) | 一小时缓存、ETag 条件请求，避免每次切页联网；匿名 API 受限时通过同一仓库的官方最新发布页及附件列表检查 |
| [Qt QScrollArea 源码](https://github.com/qt/qtbase/blob/6.8/src/widgets/widgets/qscrollarea.cpp) / [VS Code Scrollable](https://github.com/microsoft/vscode/blob/main/src/vs/base/common/scrollable.ts) | 保留独立裁剪视口、移动内容、合并输入、反向响应与按时间推进；没有复制这些项目的源码 |

## 启动和黑屏处理

旧版在启动 / 切页时使用尚未完成首轮绘制的分层页面及内容表面。本机旧版打包程序启动抽样曾出现内容区大面积黑色；取消隐藏阶段的缓存创建后，新版最终 EXE 的三次启动抽样未见大面积黑屏。

本版页面和菜单立即切换，不移动页面、不抬高中间遮盖层、不分配整页缓存。页面控件在启动阶段构造并保留；进入“客户端与版本”时不重建页面或表格。表格按稳定行身份更新变化内容，相同检测结果也会结束“正在检测”，选中项和滚动位置保留。

滚动缓存推迟到首次实际滚动：此时真实内容已经映射，同步填充缓存后再移动；后续滚动复用它。这样避免冷启动时提前分配多个空白纹理，也避免完全关闭缓存导致的持续滚动退化。首次滚动有一次准备成本，不能用后续低耗时替代该成本。点击菜单后的滚轮按鼠标所在位置路由，避免事件被仍有焦点的菜单接收后丢弃。

只运行浏览器且没有已安装客户端 / 既有媒体管理器时，列表检测不加载 WinRT 媒体 DLL。已安装客户端和实际控制所需的媒体能力仍按需检测。

## 当前版本和新版检查

- 当前版本直接读取构建内的 `APP_VERSION`，不依赖网络；构建时校验与安装器及安卓版本一致。
- 首次进入“客户端与版本”时后台检查，正常启动不检查；“检查更新”按钮可强制刷新。下载按钮只在存在较新正式版时启用。
- 自动检查优先使用约一小时内的缓存，并支持 ETag；API 限流 / 暂时不可用时读取官方最新发布页和附件链接。所有链接限定到本项目仓库和对应版本安装器，不嵌入 GitHub 令牌。
- 网络等待不会占用 Tk 主线程；同一时间只保留一个检查任务。单次 HTTP 请求超时 8 秒，读取内容不超过 128 KiB。备用路径可能需要多次请求，总耗时会增加，但页面仍可操作。
- 离线、限流及异常响应明确显示失败并允许重试，不将失败显示为“已是最新”。点击下载在默认浏览器打开安装包链接，由用户运行覆盖安装；不会自动安装或重启。

## 同机测量与边界

| 指标 | 0.5.7 | 0.5.8 |
| --- | ---: | ---: |
| 主窗口显示、服务在线时的总工作集中位值 | 58.152 MiB | 50.852 MiB |
| 相同条件下私有内存中位值 | 32.199 MiB | 30.684 MiB |
| 运行进程数 | 2 | 1 |
| 启动到可见窗口的中位耗时 | 1346.740 ms | 645.493 ms |
| 切页过渡时间 | 约 200 ms | 已移除 |

内存各启动 3 次，服务在线、未连接手机 / 播放器，等待 5 秒后采样 6 次，包含旧版单文件启动器进程，不裁剪工作集。工作集与私有内存都报告；该结果不是所有视频或使用时长下的内存上限。

新版源码 64 次相同 24 px 滚动的更新中位耗时为 2.375 ms、95% 分位 12.171 ms、最大 135.661 ms；最大值包含第一次缓存准备。10 组实际屏幕截图与强制完整重绘参考图一致，真实滚轮及滚动后控件点击通过。截图使用 ImageGrab，先采集再完整重绘对照，没有用会主动修复绘制的 PrintWindow。

无动画切页需要重新显示真实控件，本次源码切页更新中位约 34.6 ms；移除 200 ms 过渡不等于绘制开销为零。全宽窗口尺寸变化仍需实际重排，本机中位约 1091 ms、峰值约 1314 ms，连续缩放仍有优化空间。

实际打包启动脚本测量程序启动至可见完整窗口及原生消息响应，包含旧版解压时间；文件缓存冷热不受控，不能当作严格冷启动基准。旧版启动解锁屏幕抽样复现过黑屏。最终 EXE 已在解锁桌面补测三次启动、28 次切页画面抽样、真实鼠标设置、更新检查期间输入、滚动后命中与重绘对照，均通过。测试脚本等待程序自行显示和控件实际命中，不在服务上线时提前强制显示未映射窗口。有限抽样不能证明所有显卡和负载下完全没有瞬时闪烁。详细原始数据及限制随 `Performance-0.5.8.json` 发布。

## 安装与复测

普通用户仍只需下载 `BiliRemote-Setup-0.5.8.exe` 覆盖安装。安装器将 EXE、`_internal` 依赖和图文说明放在原应用目录。EXE 不再是可单独移动的便携文件；不要只复制 EXE。手机无需强制更新，原配对和设置保留。

```powershell
.\.venv\Scripts\python.exe scripts/measure_desktop_launch.py 旧版程序.exe --output .tooling/launch-old.json
.\.venv\Scripts\python.exe scripts/measure_desktop_launch.py dist/BiliRemote-Desktop.exe --output .tooling/launch-new.json
.\.venv\Scripts\python.exe scripts/measure_desktop_memory.py dist/BiliRemote-Desktop.exe --visible --output .tooling/memory-new.json
.\.venv\Scripts\python.exe scripts/measure_desktop_scrolling.py --output .tooling/scrolling-new.json
.\.venv\Scripts\python.exe scripts/smoke_desktop_transitions.py
.\.venv\Scripts\python.exe scripts/smoke_desktop_updates.py
```

GUI、浏览器和性能测试按顺序执行。实际屏幕及真实鼠标测量需要解锁且无遮挡的测试桌面；不触碰正式安装、用户设置、浏览器资料或自启配置。跨显示器 DPI、安卓实机以及其他显卡 / 驱动环境仍需补充实机验证。
