from types import SimpleNamespace

import pytest

from app.security.credentials import WindowsCredentialStore


def test_credential_store_requires_user_approval():
    store = WindowsCredentialStore()
    with pytest.raises(PermissionError):
        store.set("gmail-token", "secret")
    with pytest.raises(ValueError):
        store._target("bad/name")


def test_credential_store_writes_unicode_blob(monkeypatch):
    store = WindowsCredentialStore()
    saved = []
    wincred = SimpleNamespace(
        CRED_TYPE_GENERIC=1,
        CRED_PERSIST_LOCAL_MACHINE=2,
        CredWrite=lambda credential, flags: saved.append((credential, flags)),
    )
    monkeypatch.setattr(store, "_module", lambda: wincred)

    value = "synthetic-token-\u2713"
    store.set("whatsapp_cloud_api_access_token", value, approved=True)

    credential, flags = saved[0]
    assert credential["CredentialBlob"] == value
    assert isinstance(credential["CredentialBlob"], str)
    assert credential["TargetName"] == "SHU/whatsapp_cloud_api_access_token"
    assert flags == 0


def test_credential_store_reads_unicode_blob(monkeypatch):
    store = WindowsCredentialStore()
    value = "synthetic-token-\u2713"
    wincred = SimpleNamespace(
        CRED_TYPE_GENERIC=1,
        CredRead=lambda target, credential_type: {
            "CredentialBlob": value.encode("utf-16-le")
        },
    )
    monkeypatch.setattr(store, "_module", lambda: wincred)

    assert store.get("whatsapp_cloud_api_access_token") == value
