import pytest

from scripts import android_signing


def signing_project(tmp_path):
    folder = tmp_path / "android/signing"
    folder.mkdir(parents=True)
    (folder / "certificate.sha256").write_text("a" * 64, encoding="ascii")
    return folder


def test_missing_key_never_generates_a_new_identity(tmp_path):
    folder = signing_project(tmp_path)
    with pytest.raises(RuntimeError, match="密钥丢失"):
        android_signing.prepare_keystore(tmp_path, tmp_path)
    assert not (folder / "app.keystore").exists()


def test_legacy_key_is_checked_before_migration(tmp_path, monkeypatch):
    folder = signing_project(tmp_path)
    legacy = tmp_path / ".tooling/debug.keystore"
    legacy.parent.mkdir()
    legacy.write_bytes(b"original key")
    monkeypatch.setattr(android_signing, "certificate_digest", lambda *args: "b" * 64)
    with pytest.raises(RuntimeError, match="不一致"):
        android_signing.prepare_keystore(tmp_path, tmp_path)
    assert not (folder / "app.keystore").exists()
    monkeypatch.setattr(android_signing, "certificate_digest", lambda *args: "a" * 64)
    destination = android_signing.prepare_keystore(tmp_path, tmp_path)
    assert destination.read_bytes() == legacy.read_bytes()


def test_persistent_key_cannot_be_silently_replaced_by_cached_key(tmp_path, monkeypatch):
    folder = signing_project(tmp_path)
    destination = folder / "app.keystore"
    destination.write_bytes(b"wrong key")
    monkeypatch.setattr(android_signing, "certificate_digest", lambda *args: "b" * 64)
    with pytest.raises(RuntimeError, match="不一致"):
        android_signing.prepare_keystore(tmp_path, tmp_path)
    assert destination.read_bytes() == b"wrong key"
