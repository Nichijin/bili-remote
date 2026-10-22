import io
import json
from urllib.error import HTTPError, URLError

import pytest

from desktop.updates import check_latest, release_info, version_tuple, MAX_RESPONSE, API_URL


def payload(version="0.5.9"):
    name = "BiliRemote-Setup-"+version+".exe"
    return {"tag_name": "v"+version, "draft": False, "prerelease": False,
            "assets": [{"name": name, "state": "uploaded", "browser_download_url":
                       "https://github.com/Nichijin/bili-remote/releases/download/v"+version+"/"+name}]}


class Response(io.BytesIO):
    headers = {"ETag": '"release-etag"'}


def test_numeric_versions_and_formal_release_with_matching_installer():
    assert version_tuple("v0.5.10") > version_tuple("0.5.9")
    assert release_info(payload())["version"] == "0.5.9"
    for item in ["main", "1.2", "0.5.9-beta", "v../0.5.9"]:
        with pytest.raises(ValueError):
            version_tuple(item)


@pytest.mark.parametrize("field", ["draft", "prerelease"])
def test_drafts_and_prereleases_are_never_updates(field):
    data = payload()
    data[field] = True
    with pytest.raises(ValueError):
        release_info(data)


@pytest.mark.parametrize("url", ["http://github.com/test.exe", "https://evil.example/test.exe",
                                "https://github.com/Nichijin/other/releases/download/v0.5.9/test.exe"])
def test_download_links_are_scoped_to_this_repository(url):
    data = payload()
    data["assets"][0]["browser_download_url"] = url
    with pytest.raises(ValueError):
        release_info(data)


def test_success_cache_avoids_network_and_manual_check_revalidates_etag():
    calls = []
    def opener(request, timeout):
        calls.append((request, timeout))
        return Response(json.dumps(payload()).encode())
    result = check_latest(now=1000, opener=opener)
    assert calls[0][1] == 8 and result["version"] == "0.5.9" and not result["cached"]
    cached = check_latest(result["cache"], now=1050, opener=lambda *a, **kw: pytest.fail("Fresh cache used network"))
    assert cached["cached"]
    def unchanged(request, timeout):
        assert request.get_header("If-none-match") == '"release-etag"'
        raise HTTPError(request.full_url, 304, "unchanged", {}, None)
    refreshed = check_latest(result["cache"], force=True, now=1100, opener=unchanged)
    assert refreshed["cache"]["checked_at"] == 1100 and not refreshed["cached"]


def test_offline_does_not_claim_up_to_date():
    def offline(*a, **kw):
        raise URLError("offline")
    with pytest.raises(RuntimeError, match="无法连接"):
        check_latest(opener=offline)


def test_missing_installer_or_oversize_response_rejected():
    data = payload()
    data["assets"] = []
    with pytest.raises(ValueError, match="尚不可用"):
        release_info(data)
    with pytest.raises(ValueError, match="过大"):
        check_latest(opener=lambda *a, **kw: Response(b"x"*(MAX_RESPONSE+1)))


def test_rate_limited_api_falls_back_to_official_release_web_page():
    class Page(Response):
        def geturl(self):
            return "https://github.com/Nichijin/bili-remote/releases/tag/v0.5.9"
    def opener(request, timeout):
        if request.full_url == API_URL:
            raise HTTPError(request.full_url, 403, "rate limited", {}, None)
        if "/expanded_assets/" in request.full_url:
            return Page(b'<a href="/Nichijin/bili-remote/releases/download/v0.5.9/BiliRemote-Setup-0.5.9.exe">setup</a>')
        return Page(b"")
    result = check_latest(now=1000, opener=opener)
    assert result["version"] == "0.5.9" and result["cache"]["source"] == "web"
    assert not result["cached"]
