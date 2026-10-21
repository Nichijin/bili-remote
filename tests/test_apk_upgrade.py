import pytest

from scripts.verify_apk_upgrade import verify


def identity(**changes):
    return {"package": "com.biliremote.app", "certificate_sha256": "original-certificate", "version_code": 4, **changes}


def test_same_identity_with_new_version_can_upgrade():
    verify(identity(), identity(version_code=5))


@pytest.mark.parametrize("change, reason", [
    ({"package": "com.biliremote.other", "version_code": 5}, "包名"),
    ({"certificate_sha256": "different-certificate", "version_code": 5}, "签名"),
    ({"version_code": 4}, "versionCode"),
    ({"version_code": 3}, "versionCode"),
])
def test_incompatible_update_is_rejected(change, reason):
    with pytest.raises(ValueError, match=reason):
        verify(identity(), identity(**change))
