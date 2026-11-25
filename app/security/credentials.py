"""Windows Credential Manager wrapper for OAuth tokens and long-lived secrets."""

from __future__ import annotations

import sys


class WindowsCredentialStore:
    """Store credentials without writing their values into source or log files."""

    def __init__(self, *, namespace: str = "SHU") -> None:
        self.namespace = namespace

    def get(self, name: str) -> str | None:
        wincred = self._module()
        try:
            credential = wincred.CredRead(self._target(name), wincred.CRED_TYPE_GENERIC)
        except Exception as error:
            if getattr(error, "winerror", None) == 1168:
                return None
            raise
        blob = credential.get("CredentialBlob", b"")
        # pywin32's CredRead returns CredentialBlob as the UTF-16LE byte
        # representation of the Unicode value accepted by CredWrite.
        return blob.decode("utf-16-le") if isinstance(blob, bytes) else str(blob)

    def set(self, name: str, secret: str, *, approved: bool = False) -> None:
        if not approved:
            raise PermissionError("Saving a credential requires explicit approval")
        if not name.strip() or not secret:
            raise ValueError("Credential name and value are required")
        wincred = self._module()
        wincred.CredWrite(
            {
                "Type": wincred.CRED_TYPE_GENERIC,
                "TargetName": self._target(name),
                "UserName": "SHU",
                # pywin32 converts a Python Unicode string to the wide-char
                # blob expected by CredWrite; passing bytes raises TypeError.
                "CredentialBlob": secret,
                "Persist": wincred.CRED_PERSIST_LOCAL_MACHINE,
            },
            0,
        )

    def delete(self, name: str, *, approved: bool = False) -> None:
        if not approved:
            raise PermissionError("Deleting a credential requires explicit approval")
        wincred = self._module()
        try:
            wincred.CredDelete(self._target(name), wincred.CRED_TYPE_GENERIC, 0)
        except Exception as error:
            if getattr(error, "winerror", None) != 1168:
                raise

    def _target(self, name: str) -> str:
        if not name or any(character in name for character in "\\/\r\n"):
            raise ValueError("Credential name is invalid")
        return f"{self.namespace}/{name}"

    @staticmethod
    def _module():
        if sys.platform != "win32":
            raise OSError("Windows Credential Manager is available on Windows only")
        try:
            import win32cred
        except ImportError as error:
            raise RuntimeError("Install pywin32 to use Windows Credential Manager") from error
        return win32cred
