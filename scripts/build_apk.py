"""Build a debug APK on Windows without installing a global Android toolchain.

Downloads are kept in .tooling. Android Studio/Gradle can also build android/.
"""
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from android_signing import ALIAS, PASSWORD, prepare_keystore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.release_files import release_paths
TOOLS = ROOT / ".tooling"
BUILD = TOOLS / "apk-build"
DIST = ROOT / "dist"


def fetch(url, destination, checksum=None, algorithm="sha256"):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and checksum:
        if hashlib.file_digest(destination.open("rb"), algorithm).hexdigest() == checksum:
            return destination
    print(f"下载 {destination.name}", flush=True)
    with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output, 1024 * 1024)
    if checksum and hashlib.file_digest(destination.open("rb"), algorithm).hexdigest() != checksum:
        raise RuntimeError(f"{destination.name} 校验失败")
    return destination


def google_package(path, destination):
    if destination.exists():
        return
    with urllib.request.urlopen("https://dl.google.com/android/repository/repository2-1.xml", timeout=30) as response:
        tree = ET.fromstring(response.read())
    package = next(p for p in tree.findall("remotePackage") if p.attrib["path"] == path)
    archives = package.find("archives")
    archive = next(a for a in archives if a.findtext("host-os") in (None, "windows"))
    complete = archive.find("complete")
    url = "https://dl.google.com/android/repository/" + complete.findtext("url")
    checksum = complete.findtext("checksum")
    archive_path = fetch(url, TOOLS / Path(url).name, checksum, "sha1")
    temporary = destination.parent / (destination.name + "-extract")
    temporary.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as zipped:
        zipped.extractall(temporary)
    directories = [p for p in temporary.iterdir() if p.is_dir()]
    shutil.move(str(directories[0]), str(destination))


def jdk():
    existing = list(TOOLS.glob("jdk/*/bin/javac.exe"))
    if existing:
        return existing[0].parents[1]
    url = "https://api.azul.com/metadata/v1/zulu/packages/?java_version=17&os=windows&arch=x86&hw_bitness=64&archive_type=zip&java_package_type=jdk&release_status=ga&availability_types=CA&latest=true"
    with urllib.request.urlopen(url, timeout=30) as response:
        packages = json.load(response)
    package = next(p for p in packages if "-ca-jdk" in p["name"] and "win_x64" in p["name"])
    archive = TOOLS / package["name"]
    if not archive.exists():
        fetch(package["download_url"], archive)
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(TOOLS / "jdk")
    return next(TOOLS.glob("jdk/*/bin/javac.exe")).parents[1]


def command(arguments, environment=None, cwd=None):
    subprocess.run([str(a) for a in arguments], check=True, env=environment, cwd=cwd)


def main():
    output = release_paths(ROOT)["apk"]
    if os.name != "nt":
        raise RuntimeError("此便携构建脚本针对 Windows；其他系统请用 Android Studio")
    TOOLS.mkdir(exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        work = [executor.submit(google_package, "platforms;android-35", TOOLS / "platform-35"), executor.submit(google_package, "build-tools;35.0.0", TOOLS / "build-tools-35"), executor.submit(jdk)]
        results = [future.result() for future in work]
    java_home = results[2]
    keystore = prepare_keystore(java_home)
    environment = {**os.environ, "JAVA_HOME": str(java_home), "PATH": str(java_home / "bin") + os.pathsep + os.environ["PATH"]}
    platform = TOOLS / "platform-35" / "android.jar"
    build_tools = TOOLS / "build-tools-35"
    classes, dex = BUILD / "classes", BUILD / "dex"
    classes.mkdir(parents=True, exist_ok=True)
    dex.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(exist_ok=True)
    manifest = ET.parse(ROOT / "android/app/src/main/AndroidManifest.xml")
    manifest.getroot().set("package", "com.biliremote.app")
    ET.register_namespace("android", "http://schemas.android.com/apk/res/android")
    manifest_path = BUILD / "AndroidManifest.xml"
    manifest.write(manifest_path, encoding="utf-8", xml_declaration=True)
    sources = list((ROOT / "android/app/src/main/java").rglob("*.java"))
    command([java_home / "bin/javac.exe", "-encoding", "UTF-8", "-source", "8", "-target", "8", "-bootclasspath", platform, "-d", classes, *sources])
    command([java_home / "bin/java.exe", "-cp", build_tools / "lib/d8.jar", "com.android.tools.r8.D8", "--lib", platform, "--min-api", "26", "--output", dex, *classes.rglob("*.class")])
    base, aligned = BUILD / "unaligned.apk", BUILD / "aligned.apk"
    # aapt2/zipalign on Windows may not handle non-ASCII argument paths.
    # Relative arguments also work when this project lives in a Chinese directory.
    shutil.copytree(ROOT / "android/app/src/main/assets", BUILD / "assets", dirs_exist_ok=True)
    shutil.copytree(ROOT / "android/app/src/main/res", BUILD / "res", dirs_exist_ok=True)
    command([build_tools / "aapt2.exe", "compile", "--dir", "res", "-o", "compiled-resources.zip"], cwd=BUILD)
    gradle = (ROOT / "android/app/build.gradle").read_text(encoding="utf-8")
    version_code = re.search(r"versionCode\s+(\d+)", gradle).group(1)
    version_name = re.search(r"versionName\s+'([^']+)'", gradle).group(1)
    command([build_tools / "aapt2.exe", "link", "-o", "unaligned.apk", "--manifest", "AndroidManifest.xml", "-I", "../platform-35/android.jar", "-A", "assets", "compiled-resources.zip", "--min-sdk-version", "26", "--target-sdk-version", "35", "--version-code", version_code, "--version-name", version_name], cwd=BUILD)
    with zipfile.ZipFile(base, "a", compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in dex.glob("*.dex"):
            zipped.write(path, path.name)
    command([build_tools / "zipalign.exe", "-f", "4", "unaligned.apk", "aligned.apk"], cwd=BUILD)
    signer = [java_home / "bin/java.exe", "-jar", build_tools / "lib/apksigner.jar"]
    command([*signer, "sign", "--ks", keystore, "--ks-key-alias", ALIAS, "--ks-pass", "pass:" + PASSWORD, "--key-pass", "pass:" + PASSWORD, "--out", output, aligned], environment)
    command([*signer, "verify", "--verbose", output], environment)
    print(f"APK：{output}")


if __name__ == "__main__":
    main()
