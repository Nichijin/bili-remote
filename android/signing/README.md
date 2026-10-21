# 固定安卓签名

`app.keystore` 是已经发布 APK 使用的原密钥，不提交版本库，也不放进可清理的 `.tooling` 缓存。请单独备份到自己保管的位置；丢失后无法凭公开指纹重建同一私钥。

公开证书 SHA-256 记录在 `certificate.sha256`。便携 Python 构建和 Gradle 的 debug/release 构建都使用此处同一密钥，并在签名前检查证书。历史密钥为开发签名，沿用原 alias `androiddebugkey` 和密码 `android`；这不会把它变成生产分发的安全密钥。不要直接换新密钥，否则已安装版本无法覆盖更新。

旧项目可以运行 `python scripts/build_apk.py`，脚本核对 `.tooling/debug.keystore` 的证书后将其复制到这里；原密钥缺失或不匹配时会停止，不会另行生成密钥。Android Studio 首次打开项目前，请先完成迁移或恢复此密钥。
