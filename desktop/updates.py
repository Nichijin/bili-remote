"""Small, bounded GitHub release checks; no download or installation side effects."""
import json
import re
import time
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .version import APP_VERSION

REPOSITORY = "Nichijin/bili-remote"
RELEASES_URL = "https://github.com/"+REPOSITORY+"/releases/latest"
API_URL = "https://api.github.com/repos/"+REPOSITORY+"/releases/latest"
MAX_RESPONSE = 128*1024
CACHE_SECONDS = 3600


def version_tuple(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(value))
    if not match:
        raise ValueError("版本号格式无效")
    return tuple(int(part) for part in match.groups())


def release_info(payload):
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        raise ValueError("未获取到正式发布版本")
    version = str(payload.get("tag_name", ""))
    version_tuple(version)
    version = version.removeprefix("v")
    page = "https://github.com/"+REPOSITORY+"/releases/tag/v"+version
    expected = "BiliRemote-Setup-"+version+".exe"
    download = ""
    for asset in payload.get("assets", []):
        if not isinstance(asset, dict) or asset.get("name") != expected or asset.get("state") != "uploaded":
            continue
        url = str(asset.get("browser_download_url", ""))
        parsed = urlsplit(url)
        if (parsed.scheme == "https" and parsed.netloc == "github.com"
                and parsed.path == "/"+REPOSITORY+"/releases/download/v"+version+"/"+expected
                and not parsed.query and not parsed.fragment):
            download = url
    if not download:
        raise ValueError("正式版电脑安装包尚不可用，请稍后重试")
    return {"version": version, "page_url": page, "download_url": download}


def web_latest(opener, now):
    """Use GitHub's public release page when the anonymous API is rate-limited."""
    headers = {"User-Agent": "BiliRemote/"+APP_VERSION}
    with opener(Request(RELEASES_URL, headers=headers), timeout=8) as response:
        location = urlsplit(response.geturl())
        prefix = "/"+REPOSITORY+"/releases/tag/"
        if location.scheme != "https" or location.netloc != "github.com" or not location.path.startswith(prefix):
            raise ValueError("发布页跳转地址无效")
        tag = location.path[len(prefix):]
        version_tuple(tag)
    version = tag.removeprefix("v")
    expected = "/"+REPOSITORY+"/releases/download/"+tag+"/BiliRemote-Setup-"+version+".exe"
    class Links(HTMLParser):
        found = False
        def handle_starttag(self, element, attributes):
            if element == "a" and dict(attributes).get("href") == expected:
                self.found = True
    url = "https://github.com/"+REPOSITORY+"/releases/expanded_assets/"+tag
    with opener(Request(url, headers=headers), timeout=8) as response:
        raw = response.read(MAX_RESPONSE+1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("版本响应过大")
    links = Links()
    links.feed(raw.decode("utf-8"))
    if not links.found:
        raise ValueError("正式版电脑安装包尚不可用，请稍后重试")
    entry = {"tag_name": tag, "assets": [{"name": "BiliRemote-Setup-"+version+".exe", "state": "uploaded",
                                         "browser_download_url": "https://github.com"+expected}]}
    return release_info(entry), {"checked_at": now, "release": entry, "source": "web"}


def check_latest(cache=None, force=False, now=None, opener=urlopen):
    now = time.time() if now is None else now
    cache = cache if isinstance(cache, dict) else {}
    info = None
    try:
        info = release_info(cache["release"])
        fresh = 0 <= now-float(cache.get("checked_at", 0)) < CACHE_SECONDS
    except (KeyError, TypeError, ValueError):
        fresh = False
    if fresh and not force:
        return {**info, "cache": cache, "cached": True}
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "BiliRemote/"+APP_VERSION}
    if info and cache.get("source") != "web" and isinstance(cache.get("etag"), str):
        headers["If-None-Match"] = cache["etag"]
    request = Request(API_URL, headers=headers)
    try:
        with opener(request, timeout=8) as response:
            raw = response.read(MAX_RESPONSE+1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError("版本响应过大")
            payload = json.loads(raw)
            info = release_info(payload)
            # Persist only the required release fields, never notes or large assets.
            entry = {"tag_name": "v"+info["version"], "assets": [{"name": "BiliRemote-Setup-"+info["version"]+".exe",
                     "state": "uploaded", "browser_download_url": info["download_url"]}]}
            cache = {"checked_at": now, "etag": response.headers.get("ETag", ""), "release": entry}
    except HTTPError as error:
        if error.code == 304 and info:
            cache = {**cache, "checked_at": now}
        elif error.code in {403, 429, 500, 502, 503, 504}:
            try:
                info, cache = web_latest(opener, now)
            except (OSError, ValueError):
                raise RuntimeError("GitHub 请求受限或网络不可用，请稍后重试") from None
        elif error.code == 404:
            raise RuntimeError("暂未找到可访问的正式发布版") from None
        else:
            raise RuntimeError("检查更新失败（HTTP "+str(error.code)+"）") from None
    except (URLError, TimeoutError, OSError):
        try:
            info, cache = web_latest(opener, now)
        except (OSError, ValueError):
            raise RuntimeError("无法连接 GitHub，请检查网络后重试") from None
    return {**info, "cache": cache, "cached": False}
