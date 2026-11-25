from unittest.mock import Mock

import pytest

from app.applications.email_auth import (
    GMAIL_SCOPES,
    MICROSOFT_GRAPH_SCOPES,
    GmailOAuth,
    MicrosoftGraphOAuth,
)
from app.config import Settings


class MemoryCredentialStore:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, secret, *, approved=False):
        if not approved:
            raise PermissionError
        self.values[name] = secret

    def delete(self, name, *, approved=False):
        if not approved:
            raise PermissionError
        self.values.pop(name, None)


def make_settings(tmp_path, **overrides):
    values = {
        "SHU_GMAIL_OAUTH_CLIENT_SECRETS": str(tmp_path / "gmail-client.json"),
        "SHU_MICROSOFT_OAUTH_CLIENT_ID": "12345678-1234-1234-1234-123456789012",
        "SHU_MICROSOFT_OAUTH_TENANT": "common",
    }
    values.update(overrides)
    return Settings.from_env(values)


def test_gmail_login_uses_desktop_oauth_and_stores_tokens(tmp_path, monkeypatch):
    client_file = tmp_path / "gmail-client.json"
    client_file.write_text("{}", encoding="utf-8")
    settings = make_settings(tmp_path)
    store = MemoryCredentialStore()
    credentials = Mock(refresh_token="refresh-token")
    credentials.to_json.return_value = '{"refresh_token":"refresh-token"}'
    flow = Mock()
    flow.run_local_server.return_value = credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    factory = Mock(return_value=flow)
    monkeypatch.setattr(InstalledAppFlow, "from_client_secrets_file", factory)

    GmailOAuth(settings, store).authorize()

    factory.assert_called_once_with(str(client_file.resolve()), GMAIL_SCOPES)
    flow.run_local_server.assert_called_once_with(
        port=0,
        access_type="offline",
        prompt="consent",
    )
    assert store.values["gmail_oauth_credentials"] == credentials.to_json.return_value


def test_gmail_access_token_refreshes_and_persists_updated_credentials(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    store = MemoryCredentialStore()
    store.values["gmail_oauth_credentials"] = '{"refresh_token":"refresh"}'
    credentials = Mock(valid=False, refresh_token="refresh", token=None)

    def refresh(_request):
        credentials.valid = True
        credentials.token = "new-access-token"

    credentials.refresh.side_effect = refresh
    credentials.to_json.return_value = '{"refresh_token":"refresh","token":"new"}'
    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.from_authorized_user_info",
        Mock(return_value=credentials),
    )

    token = GmailOAuth(settings, store).access_token()

    assert token == "new-access-token"
    credentials.refresh.assert_called_once()
    assert store.values["gmail_oauth_credentials"] == credentials.to_json.return_value


def test_gmail_live_verification_checks_profile_but_discards_account_data(
    monkeypatch, tmp_path
):
    auth = GmailOAuth(make_settings(tmp_path), MemoryCredentialStore())
    monkeypatch.setattr(auth, "access_token", lambda: "synthetic-access-token")
    response = Mock()
    request = Mock(return_value=response)
    monkeypatch.setattr("app.applications.email_auth.httpx.get", request)

    assert auth.verify_live() is None

    request.assert_called_once_with(
        "https://gmail.googleapis.com/gmail/v1/users/me/profile",
        headers={"Authorization": "Bearer synthetic-access-token"},
        timeout=15.0,
    )
    response.raise_for_status.assert_called_once_with()
    response.json.assert_not_called()


def test_gmail_client_secrets_must_stay_outside_source_tree(tmp_path):
    project_secrets = Settings.from_env({}).project_dir / ".env.example"
    settings = make_settings(tmp_path, SHU_GMAIL_OAUTH_CLIENT_SECRETS=str(project_secrets))
    with pytest.raises(ValueError, match="outside the source repository"):
        GmailOAuth(settings, MemoryCredentialStore()).authorize()


def test_microsoft_device_code_login_persists_msal_cache(monkeypatch, tmp_path, capsys):
    import msal

    settings = make_settings(tmp_path)
    store = MemoryCredentialStore()
    cache = Mock(has_state_changed=True)
    cache.serialize.return_value = "encrypted-by-windows-credential-manager"
    client = Mock()
    client.initiate_device_flow.return_value = {
        "message": "Open a Microsoft sign-in page and enter a short code.",
        "user_code": "ABCD-EFGH",
    }
    client.acquire_token_by_device_flow.return_value = {"access_token": "never-print-token"}
    monkeypatch.setattr(msal, "SerializableTokenCache", Mock(return_value=cache))
    constructor = Mock(return_value=client)
    monkeypatch.setattr(msal, "PublicClientApplication", constructor)

    MicrosoftGraphOAuth(settings, store).authorize()

    constructor.assert_called_once_with(
        settings.microsoft_oauth_client_id,
        authority="https://login.microsoftonline.com/common",
        token_cache=cache,
    )
    client.initiate_device_flow.assert_called_once_with(scopes=MICROSOFT_GRAPH_SCOPES)
    assert "never-print-token" not in capsys.readouterr().out
    assert store.values["microsoft_graph_msal_cache"] == cache.serialize.return_value


def test_microsoft_access_token_uses_msal_silent_refresh(monkeypatch, tmp_path):
    import msal

    settings = make_settings(tmp_path)
    store = MemoryCredentialStore()
    store.values["microsoft_graph_msal_cache"] = "persisted-cache"
    cache = Mock(has_state_changed=True)
    cache.serialize.return_value = "refreshed-cache"
    client = Mock()
    client.get_accounts.return_value = [{"username": "owner@example.com"}]
    client.acquire_token_silent.return_value = {"access_token": "refreshed-access-token"}
    monkeypatch.setattr(msal, "SerializableTokenCache", Mock(return_value=cache))
    constructor = Mock(return_value=client)
    monkeypatch.setattr(msal, "PublicClientApplication", constructor)

    token = MicrosoftGraphOAuth(settings, store).access_token()

    assert token == "refreshed-access-token"
    client.acquire_token_silent.assert_called_once_with(
        MICROSOFT_GRAPH_SCOPES,
        account=client.get_accounts.return_value[0],
    )
    assert store.values["microsoft_graph_msal_cache"] == "refreshed-cache"


def test_microsoft_live_verification_requests_only_the_profile_id(monkeypatch, tmp_path):
    auth = MicrosoftGraphOAuth(make_settings(tmp_path), MemoryCredentialStore())
    monkeypatch.setattr(auth, "access_token", lambda: "synthetic-access-token")
    response = Mock()
    request = Mock(return_value=response)
    monkeypatch.setattr("app.applications.email_auth.httpx.get", request)

    assert auth.verify_live() is None

    request.assert_called_once_with(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": "Bearer synthetic-access-token"},
        params={"$select": "id"},
        timeout=15.0,
    )
    response.raise_for_status.assert_called_once_with()
    response.json.assert_not_called()
