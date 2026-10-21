"""Keep the existing APK signing identity outside disposable build caches."""
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALIAS = "androiddebugkey"
PASSWORD = "android"  # Existing development key; changing identity breaks upgrades.


def certificate_digest(keystore, java_home):
    keytool = Path(java_home) / "bin" / ("keytool.exe" if os.name == "nt" else "keytool")
    result = subprocess.run([
        str(keytool), "-exportcert", "-keystore", str(keystore),
        "-storepass", PASSWORD, "-alias", ALIAS,
    ], check=True, capture_output=True)
    return hashlib.sha256(result.stdout).hexdigest()


def prepare_keystore(java_home, root=ROOT):
    folder = Path(root) / "android/signing"
    expected = (folder / "certificate.sha256").read_text(encoding="ascii").strip().lower()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise RuntimeError("安卓签名证书指纹无效，不能安全构建更新包。")
    destination = folder / "app.keystore"
    legacy = Path(root) / ".tooling/debug.keystore"
    source = destination if destination.is_file() else legacy
    if not source.is_file():
        raise RuntimeError("安卓签名密钥丢失：请从备份恢复 android/signing/app.keystore；不能生成新密钥，否则无法覆盖已安装的 APK。")
    if certificate_digest(source, java_home) != expected:
        raise RuntimeError("安卓签名与已发布版本不一致，已停止构建。请恢复原签名密钥。")
    if source != destination:
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        print("已将原安卓签名复制到 android/signing/app.keystore，请单独备份此文件。", flush=True)
    return destination
