"""Check Android's package, version and signing requirements against a shipped APK."""
import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def apk_identity(path):
    java = next((ROOT / ".tooling/jdk").glob("*/bin/java.exe"))
    tools = ROOT / ".tooling/build-tools-35"
    result = subprocess.run([str(tools / "aapt2.exe"), "dump", "badging", path.name], cwd=path.parent,
                            check=True, capture_output=True, text=True, encoding="utf-8")
    package = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", result.stdout)
    if not package:
        raise RuntimeError("无法读取 APK 应用身份：" + str(path))
    signed = subprocess.run([str(java), "-jar", str(tools / "lib/apksigner.jar"), "verify", "--print-certs", str(path)],
                            check=True, capture_output=True, text=True, encoding="utf-8")
    certificates = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]+)", signed.stdout)
    if len(certificates) != 1:
        raise RuntimeError("本项目要求单一固定签名证书")
    return {"package": package[1], "version_code": int(package[2]), "version": package[3], "certificate_sha256": certificates[0].lower()}


def verify(previous, candidate):
    if previous["package"] != candidate["package"]:
        raise ValueError("包名改变会安装为第二个应用，不能覆盖升级")
    if previous["certificate_sha256"] != candidate["certificate_sha256"]:
        raise ValueError("签名不一致，Android 将拒绝覆盖安装")
    if candidate["version_code"] <= previous["version_code"]:
        raise ValueError("更新版本的 versionCode 必须大于旧版")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("previous", type=Path)
    parser.add_argument("candidate", type=Path, nargs="?", default=ROOT / "dist/bili-remote-debug.apk")
    arguments = parser.parse_args()
    previous, candidate = apk_identity(arguments.previous.resolve()), apk_identity(arguments.candidate.resolve())
    verify(previous, candidate)
    report = {"upgrade_compatible": True, "previous": previous, "candidate": candidate, "device_install_tested": False}
    (ROOT / ".tooling/apk-upgrade-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
