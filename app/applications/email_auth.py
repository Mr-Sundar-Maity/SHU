"""User-consented OAuth helpers for Gmail and Microsoft Graph mail access."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import httpx

from app.applications.communications import ProviderNotConfigured
from app.config import Settings


GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
MICROSOFT_GRAPH_SCOPES = ["User.Read", "Mail.ReadWrite", "Mail.Send"]


class CredentialStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, secret: str, *, approved: bool = False) -> None: ...
    def delete(self, name: str, *, approved: bool = False) -> None: ...


class GmailOAuth:
    """Installed-app OAuth with refresh credentials kept in Credential Manager."""

    credential_name = "gmail_oauth_credentials"

    def __init__(self, settings: Settings, credential_store: CredentialStore) -> None:
        self.settings = settings
        self.credential_store = credential_store

    @property
    def is_authorized(self) -> bool:
        return bool(self.credential_store.get(self.credential_name))

    def authorize(self) -> None:
        client_file = self.settings.gmail_oauth_client_secrets
        if client_file is None or not client_file.is_file():
            raise ProviderNotConfigured(
                "Set SHU_GMAIL_OAUTH_CLIENT_SECRETS to a Google Desktop OAuth client JSON file"
            )
        resolved = client_file.resolve()
        project = self.settings.project_dir.resolve()
        if resolved == project or project in resolved.parents:
            raise ValueError("Keep Gmail OAuth client JSON outside the source repository")
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as error:
            raise RuntimeError("Install google-auth-oauthlib for Gmail OAuth") from error

        flow = InstalledAppFlow.from_client_secrets_file(str(resolved), GMAIL_SCOPES)
        credentials = flow.run_local_server(
            port=0,
            access_type="offline",
            prompt="consent",
        )
        if not credentials.refresh_token:
            raise RuntimeError(
                "Google did not issue a refresh token; revoke SHU consent and authorize again"
            )
        self.credential_store.set(
            self.credential_name,
            credentials.to_json(),
            approved=True,
        )

    def access_token(self) -> str:
        serialized = self.credential_store.get(self.credential_name)
        if not serialized:
            raise ProviderNotConfigured("Gmail is not authorized; run the email login command")
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials

            credentials = Credentials.from_authorized_user_info(
                json.loads(serialized), scopes=GMAIL_SCOPES
            )
        except Exception as error:
            raise ProviderNotConfigured(
                "Stored Gmail authorization is invalid; authorize Gmail again"
            ) from error
        if not credentials.valid:
            if not credentials.refresh_token:
                raise ProviderNotConfigured("Gmail authorization expired; authorize Gmail again")
            try:
                credentials.refresh(Request())
            except Exception as error:
                raise ProviderNotConfigured(
                    "Gmail authorization could not be refreshed; authorize Gmail again"
                ) from error
            self.credential_store.set(
                self.credential_name,
                credentials.to_json(),
                approved=True,
            )
        if not credentials.token:
            raise ProviderNotConfigured("Gmail did not return an access token")
        return credentials.token

    def verify_live(self, *, timeout: float = 15.0) -> None:
        """Verify Gmail access without returning account or message details."""
        token = self.access_token()
        response = httpx.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": "Bearer " + token},
            timeout=timeout,
        )
        response.raise_for_status()

    def revoke_local(self) -> None:
        """Forget SHU's local token cache; revoke app consent in Google Account separately."""
        self.credential_store.delete(self.credential_name, approved=True)


class MicrosoftGraphOAuth:
    """MSAL device-code login with its refreshable token cache in Credential Manager."""

    credential_name = "microsoft_graph_msal_cache"

    def __init__(self, settings: Settings, credential_store: CredentialStore) -> None:
        self.settings = settings
        self.credential_store = credential_store

    @property
    def is_authorized(self) -> bool:
        return bool(self.credential_store.get(self.credential_name))

    def authorize(self) -> None:
        client_id = self.settings.microsoft_oauth_client_id
        if not client_id:
            raise ProviderNotConfigured("Set SHU_MICROSOFT_OAUTH_CLIENT_ID before Outlook login")
        msal, cache = self._client_and_cache()
        client = msal.PublicClientApplication(
            client_id,
            authority=self._authority(),
            token_cache=cache,
        )
        flow = client.initiate_device_flow(scopes=MICROSOFT_GRAPH_SCOPES)
        message = flow.get("message")
        if not isinstance(message, str) or not message:
            error = str(flow.get("error", "device_flow_unavailable"))
            raise RuntimeError("Microsoft sign-in could not start: " + error)
        print(message)
        result = client.acquire_token_by_device_flow(flow)
        if not isinstance(result, dict) or not result.get("access_token"):
            error = str(result.get("error", "authorization_failed")) if isinstance(result, dict) else "authorization_failed"
            raise RuntimeError("Microsoft sign-in failed: " + error)
        self._save_cache(cache)

    def access_token(self) -> str:
        client_id = self.settings.microsoft_oauth_client_id
        if not client_id:
            raise ProviderNotConfigured("Set SHU_MICROSOFT_OAUTH_CLIENT_ID before Outlook use")
        msal, cache = self._client_and_cache()
        client = msal.PublicClientApplication(
            client_id,
            authority=self._authority(),
            token_cache=cache,
        )
        accounts = client.get_accounts()
        if not accounts:
            raise ProviderNotConfigured("Outlook is not authorized; run the email login command")
        try:
            result = client.acquire_token_silent(
                MICROSOFT_GRAPH_SCOPES,
                account=accounts[0],
            )
        except Exception as error:
            raise ProviderNotConfigured("Outlook authorization needs to be renewed") from error
        if not isinstance(result, dict) or not result.get("access_token"):
            error = str(result.get("error", "authorization_expired")) if isinstance(result, dict) else "authorization_expired"
            raise ProviderNotConfigured("Outlook authorization needs attention: " + error)
        self._save_cache(cache)
        return str(result["access_token"])

    def verify_live(self, *, timeout: float = 15.0) -> None:
        """Verify Microsoft Graph access without returning account details."""
        token = self.access_token()
        response = httpx.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": "Bearer " + token},
            params={"$select": "id"},
            timeout=timeout,
        )
        response.raise_for_status()

    def revoke_local(self) -> None:
        """Forget SHU's local token cache; revoke app consent in Microsoft Account separately."""
        self.credential_store.delete(self.credential_name, approved=True)

    def _authority(self) -> str:
        tenant = self.settings.microsoft_oauth_tenant
        return f"https://login.microsoftonline.com/{tenant}"

    def _client_and_cache(self):
        try:
            import msal
        except ImportError as error:
            raise RuntimeError("Install msal for Microsoft Graph OAuth") from error
        cache = msal.SerializableTokenCache()
        serialized = self.credential_store.get(self.credential_name)
        if serialized:
            try:
                cache.deserialize(serialized)
            except Exception as error:
                raise ProviderNotConfigured(
                    "Stored Outlook authorization is invalid; remove it and sign in again"
                ) from error
        return msal, cache

    def _save_cache(self, cache) -> None:
        if cache.has_state_changed:
            self.credential_store.set(
                self.credential_name,
                cache.serialize(),
                approved=True,
            )
