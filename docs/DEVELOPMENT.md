# 开发与构建说明

[项目首页](../README.md) · [使用指南](USAGE.md) · [常见问题](FAQ.md)

本页面向维护者。当前项目版本为 **0.5.9**，安卓 `versionCode` 为 **19**。主要开发环境为 Windows、Python 3.12、JDK 17 和 Android SDK 35。

## 项目结构

```text
android/                 安卓 Activity、WebView 资源与图标
desktop/                 Windows 窗口、播放控制、发现、授权与反馈
installer/               Inno Setup 安装、升级和卸载
scripts/                 打包、自检、升级验证和文档配图生成
tests/                   Python 与 Node 测试
docs/                    使用文档及配图
dist/                    构建产物，不进入 Git
.tooling/                本地工具与临时验证文件，不进入 Git
```

## 本地运行电脑端

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe run_desktop.py
```

源码启动需要 Python；安装包用户不需要。电脑端以普通用户权限运行，无需安装 Windows 服务。依赖中的 Windows Runtime 和音频接口需要 Windows 环境。

## 两条播放控制路径

```mermaid
flowchart LR
    A[安卓 WebView 遥控界面] -->|局域网指令与独立授权| B[Windows 电脑端]
    B -->|自动管理的本机连接| C[专用 Edge / Chrome 播放窗口]
    B -->|Windows 媒体与应用音频接口| D[哔哩哔哩 Windows 客户端]
    B --> E[桌面反馈与操作记录]
```

网页路径使用系统已安装的 Edge / Chrome，以独立资料目录启动浏览器，通过仅绑定本机回环地址的随机调试端口控制。无需扩展，也不捆绑浏览器内核。普通浏览器标签页不保证受控。

客户端路径使用 GSMTC 检查与调用媒体会话、使用 pycaw 控制应用音频会话。`discover` 返回暂停、进度、倍速等实际可用能力。“客户端与版本”页可见时每 15 秒更新运行状态，每 60 秒刷新安装记录，手动检测可立即刷新；后台暂停扫描。未知版本显示“未知”，未运行的便携客户端可能无法从安装记录发现。

音频排查可使用命令行服务指定进程名，例如将 `实际进程名.exe` 换成客户端真实进程：

```powershell
.\.venv\Scripts\python.exe -m desktop.server --audio-process 实际进程名.exe
```

这是命令行服务参数，不是桌面 GUI 启动参数。不要把 `run_desktop.py --audio-process ...` 当成已实现的配置入口。

## 网络与授权

| 通道 | 默认端口 | 用途 |
| --- | --- | --- |
| TCP / WebSocket | 8765 | 接收控制和认证 |
| UDP，电脑监听 | 8766 | 回复手机发现请求 |
| UDP，手机监听 | 8767 | 接收电脑每 2 秒发送的在线广播 |

手机主动扫描与被动监听并用。广播包含电脑名称、稳定标识及端口，不包含 PIN 或授权密钥。首次使用 6 位 PIN 认证，后续使用每部手机的随机密钥；PIN 每 10 分钟刷新，有错误配对限流。

当前局域网通信未实现 TLS，不提供抵御恶意网络监听或中间人攻击的加密保障。独立授权不能代替传输加密。适用于可信局域网，不应直接开放公网端口。

## 本地数据

Windows 默认目录：`%LOCALAPPDATA%\BiliGestureRemote`。

| 文件 / 目录 | 内容 |
| --- | --- |
| `trust.json` | 稳定电脑标识及已授权手机凭据 |
| `settings.json` | 电脑端偏好 |
| `remote.log`、`.1`、`.2` | 错误日志，最多 3 个文件，每个 256 KiB |
| `browser-profile/` | 专用播放窗口的资料与登录数据 |

安卓通过 `remote` SharedPreferences 保留手机标识与设置 JSON，包括授权、地址记录、样式、目标和倍速。覆盖安装保留应用数据，卸载或清除数据不会保留这些记录。

不要把授权文件、浏览器资料、真实配对码或签名私钥提交到 Git。单独备份并妥善保管原安卓签名；公开证书指纹不能恢复私钥。

## 构建 Windows 安装包

安装 PyInstaller 和 Inno Setup 6 后执行：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe scripts/build_desktop.py
.\.venv\Scripts\python.exe scripts/build_installer.py --compiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

若使用本项目本地工具缓存中的编译器，可省略 `--compiler`。脚本默认检查 `.tooling/inno/ISCC.exe`，不会自动安装 Inno Setup。编译前确认使用场景符合构建工具的许可。

构建得到 `dist/BiliRemote-Desktop.exe` 与 `dist/BiliRemote-Setup-0.5.9.exe`。普通用户分发安装器即可。

分发文件名自动读取安卓 `versionName` 和 Windows `AppVersion`，两端版本不一致时停止打包。电脑安装器、安卓 APK、整合 ZIP 和校验 JSON 均带版本号，本文以 0.5.9 为例。`BiliRemote-Desktop.exe` 是安装器使用的内部程序文件，保留固定名称以维持自启、单实例和覆盖升级路径。Android Studio / Gradle 构建的 APK 也使用带版本号的名称。

安装器固定 AppId，沿用实际旧安装路径，正常退出运行中的程序后替换文件。升级不调用旧卸载器，避免清空数据。保留实际自启和桌面快捷方式状态，原本运行的实例安装后恢复到托盘。支持同版本修复，拒绝较低版本降级。

真正卸载才清理程序、自启、登记、授权和专用资料；清理该程序的防火墙规则可能需要管理员权限，拒绝时会提示，静默卸载写日志。

## 构建安卓 APK

Android Studio 可以打开 `android/`；Windows 也可使用便携构建脚本：

```powershell
.\.venv\Scripts\python.exe scripts/build_apk.py
```

脚本把 JDK 和 Android 工具下载到 `.tooling/`，生成并验证 `dist/bili-remote-0.5.9.apk`。无需安装到全局工具路径。便携构建中的 Java / javac 使用 256 MiB 堆上限和 2 个可见处理器，降低工作站内存紧张时的构建峰值；这是构建工具限制，不是安卓 App 的运行时内存配置。

**从新克隆的仓库不能直接生成可覆盖现有用户版本的 APK。** 维护者必须先把原签名恢复到 `android/signing/app.keystore`。该私钥不在仓库中；旧项目若仍有 `.tooling/debug.keystore`，脚本会核对证书后复制原密钥。密钥缺失或不匹配时停止，不会静默生成不同身份。

Python 便携构建、Gradle debug 和 release 构建均使用同一签名，并与 `android/signing/certificate.sha256` 核对。历史密钥是开发签名，沿用它是为了覆盖兼容，不能据此声称已具备生产分发的密钥管理。细节见[仓库签名说明](https://github.com/Nichijin/bili-remote/blob/main/android/signing/README.md)。

发布新版本时保持 `applicationId` 为 `com.biliremote.app`，递增 `versionCode`，更新 `versionName` 和 Windows 安装器的 `AppVersion`。签名、包名和数据存储位置改变都需要明确的迁移设计，不能只改版本名称。

## 测试与升级验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/*.test.cjs
.\.venv\Scripts\python.exe scripts/smoke_gui.py
.\.venv\Scripts\python.exe scripts/smoke_desktop_layout.py
.\.venv\Scripts\python.exe scripts/smoke_feedback.py
.\.venv\Scripts\python.exe scripts/smoke_desktop_responsiveness.py
.\.venv\Scripts\python.exe scripts/measure_desktop_responsiveness.py --output .tooling/responsiveness.json
.\.venv\Scripts\python.exe scripts/smoke_installer.py
.\.venv\Scripts\python.exe scripts/smoke_upgrade.py --baseline .tooling/upgrade-baseline-0.5.2
.\.venv\Scripts\python.exe scripts/verify_apk_upgrade.py 旧版.apk dist/bili-remote-0.5.9.apk
```

遥控器布局另可运行 `python scripts/smoke_remote_layout.py`（需要 `pip install playwright` 和本机 Edge / Chrome）。它用隔离连接夹具验证 7 种屏幕尺寸下的圆环边界、上下左右位置、至少 44px 触控区域和按键指令；并使用真实指针事件检查两种模式的长按切挡、震动、5 挡设置、提示开关保存及连续进度，不代表安卓实机测试。`smoke_desktop_layout.py` 检查 7 组窗口与字体缩放下的真实侧栏导航、按钮换行、底部操作可达、表格滚动及新版滑块指针拖动，不等同于真实多显示器 DPI 切换测试。

升级基线目录需包含原 `BiliRemote.iss` 和 `BiliRemote-Desktop.exe`。升级冒烟脚本从旧新安装脚本读取版本，当前使用 0.5.7 → 0.5.9 的基线验证。安装与升级冒烟脚本会使用独立程序身份、目录和端口，不应测试在用户正式安装上。

| 已验证范围 | 当前证据 |
| --- | --- |
| 播放控制 | 真实无头 Edge / Chrome、本地媒体夹具，覆盖暂停、进度、音量、临时倍速及恢复 |
| 配对与连接 | PIN、保存凭据重连、广播、IP 改变和手势测试 |
| 桌面反馈 | GUI 冒烟、浮层不抢焦点及操作记录 |
| Windows 覆盖 | 独立身份的实际安装、重连、保留数据、自启、同版本修复、拒绝降级及干净卸载 |
| Android 更新包 | 旧新 APK 包名、证书和版本代码一致性检查 |
| 仍待补充 | 实体安卓 WiFi、多品牌系统、真实触摸、实体手机覆盖安装及各版哔哩哔哩客户端兼容 |

文档截图使用示例状态，不算作真实网络或实体手机测试结果。

临时倍速使用 `speed_start`、`speed_change`、`speed_keep`、`speed_end`。切挡固定路由到当前长按持有的控制器及播放器，不能重新挑选目标或覆盖最初速度；页面和电脑端的超时机制继续负责恢复。手机的震动回调仅在进入长按或挡位实际改变时触发，Android Bridge 在主线程调用短促振动，受持久化开关和窗口前台状态约束。

`config.gears` 为升序、唯一的 1–5 个允许倍速，`config.rate` 必须属于该列表；未配置时迁移为 `[0.5,2,3]`，默认起始 2 倍。`config.show_hints` 控制两种模式的操作浮层与手势说明，独立于 `config.haptics`。

连续进度通过 `status` 获取当前位置、`seek_start` / `seek_end` 和 `media_key`，再发送带小数秒的 `seek_to(position, media_key)`。横向整屏对应 120 秒，发送间隔约 80ms、最多一个未完成请求，快速移动合并为最新位置，松手补发最后位置。下一次拖动在前一次最终请求后读取基准；取消、后台或断线丢弃尚未发送的位置，不回滚已提交进度。网页使用视频元素及媒体源标识，客户端使用会话、范围和媒体属性摘要校验，避免旧拖动落到已变化的视频。客户端缺少媒体信息或时间轴时明确报错。

`desktop/gui.py` 使用 PySide6 Essentials 6.8.3 的 Qt Widgets 主窗口、QStackedWidget 和 QScrollArea；`desktop/qt_widgets.py` 提供主题、换行按钮行、宽窄双列与字幕预览；`desktop/qt_feedback.py` 提供独立、不激活的字幕窗口。`desktop/feedback.py` 只负责共用样式校验和几何计算。

主窗口使用 QWidget 默认的光栅双缓冲，子控件保持非原生控件；不要调用子控件 `winId()`、添加 `WA_NativeWindow`、分层 HWND、外部原生坐标变换、绘制锁或 OpenGL 视口。顶层主窗口和独立字幕窗口可以拥有原生句柄。此前 Tk 绘制 / 缓存实现已经删除。

`desktop/runtime.py` 管理连接、广播、配对、检测及服务生命周期，不导入 GUI。后台线程只写事件队列，不访问控件；UI 定时批量消费。扫描在客户端页可见时或手动请求时触发，WinRT 能力按需加载。`desktop/updates.py` 保留 GitHub 正式版校验、缓存与官方网页备用路径；当前版本来自 `desktop/version.py`，构建校验两端版本一致。

Qt 动态运行库、许可与对应源码入口见[第三方声明](THIRD_PARTY_NOTICES.md)。Windows 使用 PyInstaller onedir，安装器展开 EXE、`_internal` 与文档；覆盖更新前退出旧实例，替换本应用运行库，保留独立用户数据。

## 界面与性能复测

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/*.test.cjs
.\.venv\Scripts\python.exe scripts/smoke_gui.py
.\.venv\Scripts\python.exe scripts/smoke_desktop_layout.py
.\.venv\Scripts\python.exe scripts/smoke_feedback.py
.\.venv\Scripts\python.exe scripts/measure_desktop_rendering.py --assert-clean --rounds 20 --output .tooling/render-new.json
.\.venv\Scripts\python.exe scripts/measure_desktop_responsiveness.py --output .tooling/interaction-new.json
.\.venv\Scripts\python.exe scripts/measure_desktop_scrolling.py --output .tooling/scroll-new.json
.\.venv\Scripts\python.exe scripts/measure_desktop_launch.py dist/BiliRemote-Desktop.exe --output .tooling/launch-new.json
.\.venv\Scripts\python.exe scripts/measure_desktop_memory.py dist/BiliRemote-Desktop.exe --visible --output .tooling/memory-new.json
```

GUI、浏览器及性能检查顺序运行，使用独立数据、端口与实例身份。真实屏幕采样需要解锁且无遮挡，不使用 PrintWindow 修复后截图。`measure_desktop_rendering.py` 在独立线程连续抓屏，与完整真实页面参考比较，既查黑色也查空白 / 未完成的页面；跨采样动作边界和最小化系统动画单独标记。有限采样不能证明所有设备没有瞬时问题。

`tests/test_gui.py` 检查切页后立即输入、控件复用、后台焦点排除、滚动保留、字幕拖动保存、失效输入、版本查询慢网和失败重试。旧 smoke 入口调用对应 Qt 回归。布局脚本检查 8 种逻辑尺寸 × 4 个 Qt 缩放因子；跨显示器真实 DPI 仍需补测。旧版源码可用 `--source-root` 顺序比较，两个框架的滚动步长和逻辑 / 物理像素需明确区分，不能直接混比。

## 分发整合包

两端构建完成后，可生成可选整合包和校验文件：

```powershell
.\.venv\Scripts\python.exe scripts/package_kit.py
```

产物是 `dist/bili-remote-kit-0.5.9.zip` 与 `dist/SHA256-0.5.9.json`，整合包包含两端安装文件、README 和完整图文文档，校验值使用相对路径区分同名文件。普通用户只需要 Windows 安装包与 Android APK，无需下载全部构建辅助文件。安装包不纳入 Git 历史，可另行作为发布附件分发。

整合脚本只接收当前版本的两端安装包；缺少任一文件即停止，不会回退到无版本号文件或把旧版本混入新整合包。修改项目版本后会生成新的文件名，旧版带版本号的产物不会被覆盖。

电脑程序和 Windows 安装器同时打包 `docs/`，让安装后的说明可以访问本地配图。更新文档后重新构建才会更新本地安装包，GitHub 文档更新不会自动替换用户电脑中的文件。

## 图标与文档图片

图标源文件在 `desktop/assets/` 和 `android/artwork/`。图标绘制脚本为 `scripts/draw_icon.py`、`scripts/draw_android_icon.py`。0.5.9 电脑运行时改用 Qt 绘制控件与抗锯齿图标，Pillow 仍用于图标与文档生成；用户无需另行安装依赖。安卓提供自适应图标与 Android 13 单色图标，电脑使用原生托盘。

文档图片的可复现生成方式见[配图说明](images/README.md)。更新界面后同步重渲染，避免文档与软件实际入口不一致。
