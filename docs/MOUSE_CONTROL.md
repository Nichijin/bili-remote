# 鼠标模式实现说明

[图文使用方法](USAGE.md#鼠标模式) · [项目首页](../README.md)

视频触摸板同一区域两次轻点的间隔不超过 280 ms、距离不超过 28 个 CSS 像素时进入鼠标模式。为避免双击先暂停视频，视频单击等待 280 ms。鼠标模式轻点默认左键，可改为右键；原地长按 500 ms 发一次右键。鼠标双击正常使用，不再进行模式切换，退出使用顶部入口或设置。鼠标移动从首次采样起保留微小位移，累计偏移超过 3 CSS 像素后取消点击 / 长按判定。

## 移动与加速度

手机按 Pointer Event 时间戳计算速度，以 CSS 像素归一化，避免 WebView 像素比直接改变手感。加速度只调整每次位移的增益，不对光标位置做延迟插值；手指停止后不产生惯性移动。

设手指速度为 `v`（CSS 像素 / 秒），增益为 `0.65 + 2.85 × clamp(v / 900, 0, 1)`。这是连续的线性增益曲线，低速定位更细，高速最多 3.5 倍。速度使用时间常数 24 ms 的指数平滑；反向或采样间隔超过 80 ms 时重置历史，避免旧速度导致换向飞跳。小数位移累计到后续帧，不因取整丢失微调。

这些参数是本项目针对手机相对触摸板选择的初始参数，借鉴 libinput 的速度相关增益、低速减速和方向变化时丢弃旧历史思路，并非移植 libinput 或声称具有相同硬件手感。手机触摸采样、屏幕尺寸、Windows 光标更新、WiFi 延迟都会影响实际表现。

移动按 `requestAnimationFrame` 合并，最多一个请求等待电脑回应，积压时合并未发送的位移；过时的未发送动作丢弃，避免网络恢复后继续回放旧轨迹。点击与移动保持顺序。每次进入模式建立新的会话，退出 / 断线 / 后台时清理队列，电脑端拒绝旧会话的输入。空闲时每秒续期，超过 4 秒失联退出。

## Windows 输入

电脑端通过 `SendInput` 注入，读取当前光标坐标，把手机相对位移转换为整个虚拟桌面的绝对坐标（`MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK`），保留负原点多屏区域，按物理像素计算，限制在桌面边界内。这样不再经过 Windows 相对鼠标速度 / 阈值的二次加速，也不修改用户系统鼠标设置。

鼠标操作使用独立路径，不依赖哔哩哔哩窗口、媒体会话选择或媒体操作锁。高频移动、点击和续期不生成字幕或逐条操作记录，进入、退出与失败仍可反馈。

点击在同一 `SendInput` 批次中发送按下 / 松开，不使用跨网络包维持的按键状态。首次配对和保存授权沿用原来的连接流程；未经认证的连接不能进入鼠标模式。

`SendInput` 受 Windows UIPI 约束：普通权限软件无法可靠控制权限更高的窗口、UAC 安全桌面和锁屏。软件不会为此自动请求管理员权限。多显示器之间没有屏幕的空白区域由 Windows 自身处理；真实混合 DPI 多屏和实体 Android 的手感仍需实机验证。

## 资料

以下资料已在实现时查阅：

- [libinput：Pointer acceleration](https://wayland.freedesktop.org/libinput/doc/latest/pointer-acceleration.html)：速度历史、连续线性加速度、低速精细定位、方向 / 时间变化重置。
- [Microsoft：SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)：批次顺序、返回数量、结构大小和 UIPI 限制。
- [Microsoft：MOUSEINPUT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput)（亦核对[官方文档源码](https://github.com/MicrosoftDocs/sdk-api/blob/docs/sdk-api-src/content/winuser/ns-winuser-mouseinput.md)）：绝对坐标、虚拟桌面和相对移动的系统加速。
- [MDN：getCoalescedEvents](https://developer.mozilla.org/en-US/docs/Web/API/PointerEvent/getCoalescedEvents)：合并前采样获取；接口受安全上下文和浏览器支持限制，需提供普通 pointermove 回退。

## 验证

`tests/mouse.test.cjs` 检查采样率一致性、低速小数累计、连续增益、换向、每帧合并、单请求在途、点击顺序、积压丢弃和取消后的迟到响应。

`tests/test_mouse.py` 与 `tests/test_relay.py` 检查参数边界、输入结构 ABI、负原点多屏坐标、模式标识、授权、媒体锁隔离、超时与断线清理。

`scripts/smoke_mouse_input.py` 只在独立测试窗口内验证真实像素移动及左右键的按下 / 松开消息，并在结束时恢复光标位置。它不操作用户视频或正式安装。
