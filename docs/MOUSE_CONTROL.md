# 鼠标模式实现与流畅度验证

[图文使用方法](USAGE.md#鼠标模式) · [项目首页](../README.md)

1000 Hz 输出档位需要两端均为 **0.5.13 或更新版本**。视频触摸板两次轻点的间隔不超过 280 ms、距离不超过 28 CSS 像素时进入。视频单击等待 280 ms 区分双击；鼠标轻点默认左键、长按 500 ms 发一次右键，正常鼠标双击保留。退出使用顶部入口或双指 / Android 返回键打开设置。

## 旧版为什么卡顿

0.5.11 把移动作为普通请求，最多一个请求在途；收到回应后才安排下一次发送。一次往返 40 ms、界面 60 Hz 时，移动发送常落到每 50 ms 一次，即约 20 次 / 秒。单看没有网络延迟的手势测试无法发现这个瓶颈。

旧加速度主要依靠相邻两个触点估算瞬时速度。坐标取整、采样间隔变化及微小抖动会改变速度和增益，连续轨迹仍可能出现快慢不均。

## 手机采样与加速度

支持时读取 `pointerrawupdate` 和 `getCoalescedEvents`，不支持时使用普通 `pointermove`。按时间戳忽略重复 / 旧样本；保留 CSS 像素归一化，不用 WebView 像素比直接放大移动。采样只更新数值，移动时不创建提示 DOM。

约 32 ms 的位置历史用于估计净移动速度，降低单点量化噪声。停顿超过 80 ms 或明显反向时重新建立速度历史，方向始终跟随当前手指位移，不对方向做延迟滤波。

设速度为 `v`（CSS 像素 / 秒），`u = clamp((v - 40) / 1000, 0, 1)`，目标增益为 `0.85 + 2.15 × u² × (3 - 2u)`。低速增益为 0.85，高速最多 3，首尾斜率连续。增益上升时间常数 32 ms、下降 12 ms，用相邻增益的平均值计算位移，避免起步突然放大及减速后仍维持高增益。小数位移累计传输。

该曲线是本项目参数选择，借鉴 libinput 的速度历史、精细定位与方向变化处理思路，没有移植其硬件算法。它平滑的是增益，不产生手指停止后的预测移动。

## 发送与拥塞处理

手机在新触摸事件处理完成后尽快发送 `mouse_frame`：模式标识、序号、模式内时间戳和累计 `x/y`；移除等待屏幕刷新帧的限制，保留帧回调作为拥塞 / 余量补发。最快按约 1 ms 间隔尝试，只有新坐标才发送，不重复旧坐标凑包频率。移动不等待回应；确认包不建立每帧 Promise 或超时计时器。手机硬件 / WebView 仍决定真实可用采样数；合并事件批次中的中间点用于估速，传输当前累计终点。停止采样后最多保留约 32 ms 的空调度窗口，不发送额外位置。

通过三层约束限制积压：浏览器 `bufferedAmount` 超过 1024 字节时暂缓发送、最多 24 个未确认包、最旧未确认包超过 180 ms 时暂缓。暂缓期间只保留当前累计终点，收到确认后合并发送，不保存旧相对移动队列。心跳失败或输入异常退出本次模式，旧模式的迟到确认不能影响新模式。

移动和点击使用同一条有序 WebSocket。点击前发送最新终点，电脑在发送按键前完成最后位置；拥塞阻止刷新时取消点击并反馈，避免点击旧位置。鼠标模式仍使用已配对连接，未认证请求、错误模式标识和无效参数不能注入输入。

## 电脑输出与延迟取舍

`MotionTimeline` 使用 4–24 ms 自适应短缓存，起始 20 ms。最近 24 个有效采样间隔的中位数，加上到包间隔偏差的 90 分位数和 1 ms 余量，作为目标缓冲；每个采样只改变不超过其间隔的 5%，避免突然跳变。稳定输入下，60 / 120 / 240 Hz 的理论缓冲约 17.7 / 9.3 / 5.2 ms，实际还受到包调度抖动影响。根据客户端时间戳在已知轨迹点之间线性插值；没有下一点时停在最后一点，不外推。客户端累计坐标在电脑端转换为整数位移，小数不会按包重复截断。重复 / 乱序包忽略；相对本次模式的最佳到达偏移落后超过 120 ms 时跳过旧轨迹并重设累计基准，避免网络恢复后回放。新一段滑动不会把移动摊到中间的抬手停顿。

`MotionWorker` 独立线程默认目标每 1 ms 输出一次（1000 Hz），也可通过手机选择 2 / 4 / 8 ms（500 / 250 / 125 Hz），使用 `QueryPerformanceCounter` 时钟与独立的高分辨率等待计时器。这个环境中 Python 3.12 的 `monotonic` 使用约 15.6 ms 分辨率的 `GetTickCount64`，不适合计算 1 ms 的鼠标插值。空闲时线程等待事件，退出释放计时器并停止线程，不修改系统全局计时精度，也不占用 Qt 绘制线程。

插值有短暂缓存及调度等待，以换取较均匀的输出；稳定高采样时自动缩短，抖动增大时逐步增加，最多 24 ms。它不能消除 WiFi 固有延迟、严重丢包、系统繁忙或手机低采样率。点击会完成最新终点，退出 / 后台 / 断线则取消尚未输出的轨迹。

Windows 仍通过 `SendInput` 的绝对坐标和 `MOUSEEVENTF_VIRTUALDESK` 覆盖整个虚拟桌面，避免叠加系统相对鼠标加速，不改系统鼠标设置。按下 / 松开在同批次注入。移动、点击和确认不逐条更新电脑字幕或日志。

高频时 `SendInput` 返回后系统可能仍报告旧位置。流式输出保存累计目标，32 ms 内已发送的位置快照不覆盖累计基准，避免丢位移；与近期轨迹不符的位置按本地鼠标 / 系统移位重新定位基准，超时清理近期历史。桌面边缘限位，退出清空缓存。这是有限时间的位置匹配，并非区分物理鼠标来源的 Raw Input；同时移动实体鼠标时仍可能有短暂干扰。

普通权限注入受 UIPI 限制，无法保证控制更高权限窗口、UAC 安全桌面或锁屏。当前提供移动、点击 / 双击与长按右键，不包含按住左键拖拽和双指滚轮。

## 验证方法与证据范围

`node scripts/measure_mouse_motion.cjs --output .tooling/mouse-motion.json` 使用确定性时钟、延迟确认和采样即发，检查 120 Hz 输入在 60 / 120 Hz 界面及 0 / 20 / 40 / 80 ms 往返延迟下的发送频率；另检查 240 / 1000 Hz 合成输入。120 / 240 Hz 输入可按各自采样率发送，1000 Hz 合成输入在 20 ms 模拟往返下也能发送约 1000 次 / 秒；这不是手机硬件支持 1000 Hz 的证据。拥塞窗口仍会限制高延迟下的吞吐。使用 `--baseline 旧版mouse.js` 可以比较 0.5.11 的逐请求等待路径。

同一量化轨迹下，旧版稳态增益范围约 0.1114，新版约 0.0311，波动范围降低约 72%。这是一条特定轨迹的对照，不代表所有手势的体验改善比例。

`python scripts/measure_mouse_output.py --all-rates --assert-smooth` 使用真实 Windows 输出线程 / 计时器及捕获后端，输入稳定和轻度抖动的 60 Hz、2400 像素 / 秒轨迹，检查四个档位，另检查 120 / 240 Hz 输入的延迟，报告输出次数、间隔分位数、精确终点及退出后零输出。0.5.13 本机捕获后端实测 1000 Hz 档约 999–1000 次 / 秒，中位间隔约 1 ms；稳定 120 / 240 Hz 合成输入的采样到输出中位延迟约 10 / 6 ms。这些是该次主机负载下的结果，**不包含实体手机、无线传输或显示器扫描延迟**。慢速轨迹可能没有每毫秒一个不同的整数坐标，有效位移次数会低于目标。CPU 采用粗粒度短时计账，读到零不代表没有 CPU 成本。

`tests/mouse.test.cjs`、`tests/test_mouse_motion.py`、`tests/test_relay.py` 覆盖采样率、量化噪声、拥塞合并、点击顺序、鉴权、模式标识、过时包、整数终点和线程清理。`scripts/smoke_mouse_touchpad.py` 在隔离浏览器验证实际指针事件、手势和偏好；`scripts/smoke_mouse_input.py` 只向独立窗口注入真实输入，退出后恢复光标。

实体 Android 的实际触摸 / WebView、真实 WiFi、混合 DPI 多屏与显示器呈现仍需实机验证，不把模拟包频率或线程调用次数等同于用户看到的帧率。

## 1000 Hz 的含义与成本

这里是 Windows 软件插值输出调度，**不是 USB HID 轮询率，也不是手机触摸采样率或显示器刷新率**。只有输入已提供的轨迹点之间可插值；没有新点就停，不以重复坐标宣称真实采样增加。1000 Hz 输出不能弥补稀疏触点的细节丢失。

`mouse_start` 携带 `output_hz`，电脑校验并返回 `mouse_output_hz`；不支持协商的旧电脑会被新版手机明确拒绝，避免显示错误档位。设置保存为 `mouse_output_hz`，默认 1000。`mouse_keep` 反馈目标频率、时间窗内实际调度频率和实际非零位移输出次数，静止时不会填充为 1000。

更高频率会增加线程唤醒和系统输入调用次数、CPU 与耗电；空闲及退出仍停止输出。Windows 不是硬实时系统，繁忙时不能承诺每 1 ms 准时；如需降低负担，可选 500 / 250 / 125 Hz。缓冲在平顺和延迟之间自动调整，不把高频率等同于更低的全部端到端延迟。

## 查阅资料

- [libinput：Pointer acceleration](https://wayland.freedesktop.org/libinput/doc/latest/pointer-acceleration.html)：速度历史、方向变化和低速定位。
- [MDN：bufferedAmount](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket/bufferedAmount)：已排入但尚未发送的字节。
- [MDN：pointerrawupdate](https://developer.mozilla.org/en-US/docs/Web/API/Element/pointerrawupdate_event) 与 [getCoalescedEvents](https://developer.mozilla.org/en-US/docs/Web/API/PointerEvent/getCoalescedEvents)：提前采样、合并事件和支持限制。
- [Microsoft：CreateWaitableTimerExW](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createwaitabletimerexw)（核对[官方源码](https://github.com/MicrosoftDocs/sdk-api/blob/docs/sdk-api-src/content/synchapi/nf-synchapi-createwaitabletimerexw.md)）：Windows 10 1803 起提供独立高分辨率等待计时器。
- [Microsoft：SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput) 与 [MOUSEINPUT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput)：批次顺序、绝对坐标、虚拟桌面及 UIPI。
