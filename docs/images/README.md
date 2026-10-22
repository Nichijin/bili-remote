# 文档配图说明

[项目首页](../../README.md) · [开发说明](../DEVELOPMENT.md)

所有配图均保存在仓库内，Markdown 使用相对链接，不依赖第三方图床。图片匹配 0.5.1 当前界面，传统遥控器采用一体哑光圆环、上音量加、下音量减、左右进度及中央银白播放键的布局，右上角提供震动开关。“在电脑打开哔哩哔哩”入口位于设置的“播放器”分组。

| 图片 | 内容 | 来源 |
| --- | --- | --- |
| `overview.png` | 项目封面与两种样式 | 项目原有安卓图标、实际页面渲染与排版 |
| `remote-styles.png` | 传统遥控器 / 触摸板 | 当前 WebView 页面在独立浏览器上下文中渲染 |
| `remote-redesign.png` | 新圆环与分组设置面板 | 当前 WebView 页面实际渲染，使用示例数据 |
| `mobile-connection.png` | 设置、配对和手动 IP 历史 | 当前 WebView 页面，使用隔离的模拟连接 |
| `desktop-main.png` | 电脑端连接与播放页 | 当前 Tk 组件，使用独立预览实例 |
| `desktop-settings.png` | 电脑端设置页 | 当前 Tk 组件，固定示例设置 |
| `desktop-feedback.png` | 电脑字幕位置、字号、颜色及不透明度 | 当前 Tk 设置页滚动到字幕样式，使用独立预览实例 |
| `connection-flow.png` | 四步连接流程 | 可复现的文字与矢量形状绘制 |
| `gestures.png` | 四种手势与设置入口 | 操作教学图，箭头与触点为示意 |
| `upgrade.png` | 两端覆盖升级 | 升级步骤示意 |

界面预览中的“演示电脑”、`192.168.1.10` 和 `123456` 是固定示例，不是用户实际设备或有效授权。生成过程不使用真实手机数据、浏览器资料或配对服务，不修改正式安装配置。

手机截图反映当前页面布局，不是实体安卓手机的系统截图。电脑截图仅捕获文档预览窗口的客户区，不截取整个桌面。配图不用于证明实际网络、播放器或多机型兼容结果。

## 重新生成

需要 Windows、项目 Python 依赖、Pillow、Playwright，以及本机已有的 Edge / Chrome。无需下载额外的 Playwright 浏览器，也不使用个人浏览器配置。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install pillow playwright
.\.venv\Scripts\python.exe scripts/build_docs_images.py
```

字体使用 Windows 的微软雅黑。中间截图保存在 `.tooling/docs-captures/`，最终 10 张 PNG 写入 `docs/images/`；中间文件不进入 Git。

生成脚本位于仓库的 [scripts/build_docs_images.py](https://github.com/Nichijin/bili-remote/blob/main/scripts/build_docs_images.py)。文档事实变化时应同步修改文案、示例和绘制脚本，再检查最终图片是否溢出、裁切或包含过时入口。
