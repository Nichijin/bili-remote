# 电脑界面运行库声明

0.5.9 的电脑界面使用 **Qt 6.8.3、PySide6 Essentials 6.8.3 和 Shiboken 6.8.3**，版权归 The Qt Company Ltd. 及其贡献者所有，按 LGPL v3 条款使用。界面使用 Qt Core / Gui / Widgets；没有使用 Qt WebEngine 或 Qt Quick。项目原有依赖继续适用各自的许可。

- [GNU LGPL v3 原文](licenses/LGPL-3.0-only.txt)
- [GNU GPL v3 原文，LGPL 引用的基础许可](licenses/GPL-3.0-only.txt)
- [Qt GPL exception 原文](licenses/Qt-GPL-exception-1.0.txt)
- [Qt 许可说明](https://www.qt.io/licensing/open-source-lgpl-obligations)
- [Qt 6.8.3 对应源码（含各组件第三方声明）](https://download.qt.io/archive/qt/6.8/6.8.3/submodules/)
- [PySide / Shiboken 6.8.3 对应源码](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/)
- [Qt for Python 构建说明](https://doc.qt.io/qtforpython-6.8/building_from_source/index.html)

运行库未经本项目修改，以动态链接形式放在安装目录的 `_internal/PySide6/` 与 `_internal/shiboken6/` 中。可以用兼容 ABI 的自行构建版本替换相应动态库，以调试对这些库所作的修改；程序没有阻止替换的校验。升级安装会重新安装随包运行库，请自行保存修改。项目源码和打包脚本公开在[代码仓库](https://github.com/Nichijin/bili-remote)。

以上声明及许可全文随安装器的离线文档一同提供。
