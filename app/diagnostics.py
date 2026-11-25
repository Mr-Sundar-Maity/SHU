"""Read-only checks for the current SHU environment and integrations."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

from app.config import Settings, get_settings
from app.security.credentials import WindowsCredentialStore
from database.database import SCHEMA_VERSION

_WHISPER_CACHE_REPOSITORIES = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}
_WHISPER_CACHE_ALLOW_PATTERNS = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    name: str
    status: str
    detail: str


def collect_diagnostics(settings: Settings | None = None) -> list[Diagnostic]:
    settings = settings or get_settings()
    results: list[Diagnostic] = []

    results.append(Diagnostic(
        "Python",
        "PASS" if sys.version_info >= (3, 11) else "FAIL",
        sys.version.split()[0],
    ))
    results.append(Diagnostic(
        "Core dependency manifests",
        "PASS" if (settings.project_dir / "requirements.txt").is_file() and (settings.project_dir / "requirements-v1.txt").is_file() else "FAIL",
        "requirements.txt and requirements-v1.txt",
    ))
    results.append(Diagnostic(
        "Secrets ignored by Git",
        "PASS" if _git_ignores_env(settings.project_dir) else "WARN",
        ".env must be covered by .gitignore",
    ))
    results.append(_private_acl_diagnostic(settings))

    if settings.database_path.is_file():
        try:
            connection = sqlite3.connect(
                "file:" + settings.database_path.as_posix() + "?mode=ro", uri=True
            )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            connection.close()
            status = "PASS" if integrity == "ok" and version == SCHEMA_VERSION else "WARN"
            results.append(Diagnostic(
                "Memory database",
                status,
                f"integrity={integrity}; schema={version}; expected={SCHEMA_VERSION}",
            ))
        except sqlite3.Error as error:
            results.append(Diagnostic("Memory database", "FAIL", type(error).__name__))
    else:
        results.append(Diagnostic("Memory database", "WARN", "not initialized"))

    results.append(_ollama_diagnostic(settings))

    try:
        import sounddevice as sd
        input_devices = [
            device for device in sd.query_devices()
            if device.get("max_input_channels", 0) > 0
        ]
        selected_ok = (
            settings.microphone_device is None
            or 0 <= settings.microphone_device < len(sd.query_devices())
            and sd.query_devices()[settings.microphone_device].get("max_input_channels", 0) > 0
        )
        results.append(Diagnostic(
            "Microphone devices",
            "PASS" if input_devices and selected_ok else "WARN",
            f"{len(input_devices)} input device(s); configured index {'valid' if selected_ok else 'needs selection'}",
        ))
    except Exception as error:
        results.append(Diagnostic("Microphone devices", "WARN", type(error).__name__))

    results.append(_whisper_model_cache_diagnostic(settings))

    results.append(Diagnostic(
        "Gemini configuration",
        "PASS" if settings.gemini_api_key and settings.gemini_model else "WARN",
        "credentials configured; live API call is not part of the diagnostic",
    ))
    results.append(Diagnostic(
        "Cloud fallback",
        "PASS" if not settings.cloud_fallback else "WARN",
        "disabled" if not settings.cloud_fallback else "enabled by configuration",
    ))
    results.append(Diagnostic(
        "Local fallback",
        "PASS" if settings.local_fallback else "WARN",
        "Gemini failures fall back to Ollama"
        if settings.local_fallback
        else "disabled by configuration",
    ))

    results.append(_email_authorization_diagnostic(settings))

    results.append(_whatsapp_authorization_diagnostic(settings))

    office_executables = _office_executables()
    results.append(Diagnostic(
        "Microsoft Office",
        "PASS" if all(office_executables.values()) else "WARN",
        ", ".join(f"{name}={'present' if present else 'missing'}" for name, present in office_executables.items()),
    ))
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            has_chromium = Path(playwright.chromium.executable_path).is_file()
    except Exception:
        has_chromium = False
    results.append(Diagnostic(
        "Playwright Chromium",
        "PASS" if has_chromium else "WARN",
        "managed browser found" if has_chromium else "run python -m playwright install chromium",
    ))
    wake_path = settings.wakeword_model_path
    results.append(Diagnostic(
        "Hey SHU wake-word model",
        "PASS" if wake_path and wake_path.is_file() else "WARN",
        "custom model configured" if wake_path and wake_path.is_file() else "a trained Hey SHU model is not configured",
    ))
    results.append(Diagnostic(
        "Optional tools",
        "PASS" if all(shutil.which(name) for name in ("git", "ollama", "tesseract", "ffmpeg", "ffprobe")) else "WARN",
        "Git/Ollama/Tesseract/FFmpeg command availability",
    ))
    return results


def _email_authorization_diagnostic(settings: Settings) -> Diagnostic:
    email_credentials = {
        "gmail": ("gmail_oauth_credentials", "gmail_access_token"),
        "outlook": ("microsoft_graph_msal_cache", "microsoft_graph_access_token"),
    }.get(settings.email_provider, ())
    email_ready = bool(email_credentials) and any(
        _credential_present(name) for name in email_credentials
    )
    if email_ready:
        email_detail = "OAuth cache/access token is stored; no live email was sent"
    elif settings.email_provider == "gmail":
        email_detail = (
            "Gmail Desktop OAuth client is configured; run the consented login flow"
            if settings.gmail_oauth_client_secrets
            and settings.gmail_oauth_client_secrets.is_file()
            else "Set SHU_GMAIL_OAUTH_CLIENT_SECRETS, then run the consented Gmail login flow"
        )
    elif settings.email_provider == "outlook":
        email_detail = (
            "Microsoft app ID is configured; run the consented Outlook login flow"
            if settings.microsoft_oauth_client_id
            else "Set SHU_MICROSOFT_OAUTH_CLIENT_ID, then run the consented Outlook login flow"
        )
    elif settings.gmail_oauth_client_secrets and settings.gmail_oauth_client_secrets.is_file():
        email_detail = (
            "Gmail Desktop OAuth client is ready; set SHU_EMAIL_PROVIDER=gmail and "
            "complete user consent if mailbox access is needed"
        )
    else:
        email_detail = (
            "Mailbox is not selected; configure a provider and complete user consent "
            "if email access is needed"
        )
    return Diagnostic(
        "Email authorization configuration",
        "PASS" if email_ready else "WARN",
        email_detail,
    )


def _ollama_diagnostic(settings: Settings) -> Diagnostic:
    try:
        response = requests.get(settings.local_ai_base_url + "/api/tags", timeout=2)
        response.raise_for_status()
        models = response.json().get("models", [])
        tags = {
            model.get("name")
            for model in models
            if isinstance(model, dict) and isinstance(model.get("name"), str)
        }
        found = settings.local_ai_model in tags
        return Diagnostic(
            "Ollama service/model",
            "PASS" if found else "WARN",
            f"service reachable; selected model {'available' if found else 'not listed'}",
        )
    except requests.RequestException as error:
        return Diagnostic(
            "Ollama service/model",
            "WARN",
            f"service unavailable ({type(error).__name__}); start Ollama with `ollama serve`",
        )
    except Exception as error:
        return Diagnostic("Ollama service/model", "WARN", type(error).__name__)


def _whatsapp_authorization_diagnostic(settings: Settings) -> Diagnostic:
    phone_id_configured = bool(settings.whatsapp_phone_number_id)
    token_configured = _credential_present("whatsapp_cloud_api_access_token")
    if phone_id_configured and token_configured:
        status = "PASS"
        detail = "business phone ID and token are stored; no live message was sent"
    elif phone_id_configured:
        status = "WARN"
        detail = (
            "business phone ID is configured; access token is missing. Store it with "
            "python -m app.cli credentials set whatsapp_cloud_api_access_token"
        )
    elif token_configured:
        status = "WARN"
        detail = "access token is stored; set SHU_WHATSAPP_PHONE_NUMBER_ID"
    else:
        status = "WARN"
        detail = "business phone ID and access token are not fully configured"
    return Diagnostic("WhatsApp Cloud API configuration", status, detail)


def _whisper_model_cache_diagnostic(settings: Settings) -> Diagnostic:
    try:
        model_path = _cached_whisper_model_path(settings.stt_model_size)
        available = (model_path / "model.bin").is_file() and (
            model_path / "config.json"
        ).is_file()
    except Exception as error:
        return Diagnostic(
            "Whisper STT model cache",
            "WARN",
            f"{settings.stt_model_size} is not available offline; first use may need internet ({type(error).__name__})",
        )
    return Diagnostic(
        "Whisper STT model cache",
        "PASS" if available else "WARN",
        f"{settings.stt_model_size} model files {'cached locally' if available else 'incomplete'}; this check did not load the model",
    )


def _cached_whisper_model_path(model_size: str) -> Path:
    """Resolve a model from the Hugging Face cache without network access."""
    from huggingface_hub import snapshot_download

    repo_id = _WHISPER_CACHE_REPOSITORIES.get(model_size)
    if repo_id is None:
        raise ValueError("Unsupported Whisper cache model")
    return Path(
        snapshot_download(
            repo_id,
            local_files_only=True,
            allow_patterns=_WHISPER_CACHE_ALLOW_PATTERNS,
        )
    )


def _private_acl_diagnostic(settings: Settings) -> Diagnostic:
    private_paths = [
        path
        for path in (
            settings.project_dir / ".env",
            settings.gmail_oauth_client_secrets,
        )
        if path is not None and path.exists()
    ]
    if any(_is_reparse_point(path) for path in private_paths):
        return Diagnostic(
            "Private data ACL",
            "WARN",
            "a private SHU path is a reparse point that needs manual review",
        )
    if settings.data_dir.exists():
        if _is_reparse_point(settings.data_dir):
            return Diagnostic(
                "Private data ACL",
                "WARN",
                "the private data root is a reparse point that needs manual review",
            )
        private_paths.append(settings.data_dir)
    if not private_paths:
        return Diagnostic("Private data ACL", "WARN", "no SHU secret/data paths exist yet")

    def access_warning() -> Diagnostic:
        return Diagnostic(
            "Private data ACL",
            "WARN",
            "one or more private paths do not match the current-user/SYSTEM/Administrators allow-list; run scripts\\secure-data.ps1 from an elevated PowerShell session",
        )

    try:
        for path in private_paths:
            if _private_acl_violations(path):
                return access_warning()
    except Exception as error:
        return Diagnostic("Private data ACL", "WARN", f"could not inspect Windows ACLs ({type(error).__name__})")

    if settings.data_dir.exists():
        try:
            for path in settings.data_dir.rglob("*"):
                if _is_reparse_point(path):
                    return Diagnostic(
                        "Private data ACL",
                        "WARN",
                        "private data contains a reparse point that needs manual review",
                    )
                if _private_acl_violations(path):
                    return access_warning()
        except OSError as error:
            return Diagnostic(
                "Private data ACL",
                "WARN",
                f"could not enumerate private data ({type(error).__name__})",
            )
        except Exception as error:
            return Diagnostic("Private data ACL", "WARN", f"could not inspect Windows ACLs ({type(error).__name__})")

    return Diagnostic(
        "Private data ACL",
        "PASS",
        "private paths are restricted to the current user, SYSTEM and Administrators",
    )


def _is_reparse_point(path: Path) -> bool:
    """Detect Windows junctions/symlinks without following the target."""
    import stat

    try:
        return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except AttributeError:
        return path.is_symlink()
    except OSError:
        return True


def _private_acl_violations(path: Path) -> set[str]:
    """Return violations of the private-path allow-list using stable SIDs."""
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
    )
    try:
        user_sid = win32security.GetTokenInformation(
            token, win32security.TokenUser
        )[0]
    finally:
        win32api.CloseHandle(token)
    expected_sids = {
        win32security.ConvertSidToStringSid(user_sid),
        "S-1-5-18",  # LOCAL SYSTEM
        "S-1-5-32-544",  # BUILTIN\\Administrators
    }
    security = win32security.GetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION,
    )
    dacl = security.GetSecurityDescriptorDacl()
    if dacl is None:
        return {"unrestricted DACL"}

    allow_types = {
        win32security.ACCESS_ALLOWED_ACE_TYPE,
        getattr(win32security, "ACCESS_ALLOWED_OBJECT_ACE_TYPE", -1),
    }
    actual_sids: set[str] = set()
    violations: set[str] = set()
    for index in range(dacl.GetAceCount()):
        ace = dacl.GetAce(index)
        if ace[0][0] not in allow_types:
            violations.add("unexpected ACE type")
            continue
        sid = win32security.ConvertSidToStringSid(ace[-1])
        actual_sids.add(sid)
        if sid not in expected_sids or ace[1] != 0x1F01FF:
            violations.add("unexpected allow rule")
    if actual_sids != expected_sids:
        violations.add("missing or unexpected principal")
    return violations


def _git_ignores_env(project_dir: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_dir), "check-ignore", "-q", ".env"],
            check=False,
            capture_output=True,
            timeout=3,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _credential_present(name: str) -> bool:
    try:
        return bool(WindowsCredentialStore().get(name))
    except Exception:
        return False


def _office_executables() -> dict[str, bool]:
    roots = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft Office" / "root" / "Office16",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Office" / "root" / "Office16",
    ]
    return {
        name: any((root / filename).is_file() for root in roots)
        for name, filename in {
            "Word": "WINWORD.EXE",
            "Excel": "EXCEL.EXE",
            "PowerPoint": "POWERPNT.EXE",
        }.items()
    }
