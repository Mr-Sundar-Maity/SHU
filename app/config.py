"""Central, typed application configuration for SHU."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


SUPPORTED_LANGUAGE_CODES = {"bn", "hi", "en", "ta", "te", "ml"}
SUPPORTED_PROVIDERS = {"ollama", "google"}
RESPONSE_STYLE_INSTRUCTIONS = {
    "friendly": "Use a friendly, warm, natural tone while staying respectful and concise.",
    "casual": "Use relaxed, conversational wording while staying clear and respectful.",
    "formal": "Use polite, formal wording and complete sentences; avoid slang.",
    "serious": "Use direct, sober, professional wording; avoid jokes and unnecessary warmth.",
    "humorous": (
        "Use light humor sparingly when appropriate. Never joke about emergencies, "
        "harm, or sensitive personal topics."
    ),
    "supportive": (
        "Use empathetic, reassuring wording and offer practical next steps without "
        "exaggerated praise."
    ),
}


def response_style_instruction(style: str) -> str:
    """Return the trusted system instruction for one supported response style."""
    try:
        return RESPONSE_STYLE_INSTRUCTIONS[style]
    except KeyError as error:
        raise ValueError("Unsupported response style: " + str(style)) from error


def _as_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _optional_int(value: str | None, *, name: str) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer or empty") from error
    if result < 0:
        raise ValueError(f"{name} cannot be negative")
    return result


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime settings; secrets are excluded from repr output."""

    project_dir: Path
    data_dir: Path
    ai_provider: str = "ollama"
    cloud_fallback: bool = False
    local_fallback: bool = True
    cloud_ai_enabled: bool = True
    automation_enabled: bool = True
    local_ai_provider: str = "ollama"
    local_ai_base_url: str = "http://localhost:11434"
    local_ai_model: str = "qwen2.5:1.5b"
    gemini_api_key: str | None = field(default=None, repr=False)
    gemini_model: str | None = None
    default_language: str = "bn"
    response_style: str = "friendly"
    default_voice: str = "male"
    stt_model_size: str = "small"
    microphone_device: int | None = 1
    sample_rate: int = 16_000
    voice_barge_in: bool = False
    voice_barge_in_rms: float = 0.03
    allow_cloud_personal_data: bool = False
    request_timeout_seconds: float = 60.0
    tts_timeout_seconds: float = 20.0
    tts_rate_percent: int = 0
    tts_volume: float = 1.0
    ui_font_size: int = 10
    email_provider: str = "none"
    gmail_oauth_client_secrets: Path | None = None
    microsoft_oauth_client_id: str | None = None
    microsoft_oauth_tenant: str = "common"
    whatsapp_phone_number_id: str | None = None
    whatsapp_graph_api_version: str = "v27.0"
    wakeword_model_path: Path | None = None

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def database_path(self) -> Path:
        return self.memory_dir / "shu.db"

    @property
    def log_dir(self) -> Path:
        return self.memory_dir / "logs"

    def ensure_data_dirs(self) -> None:
        """Create SHU's separated user-data directories on explicit startup."""
        for name in ("backups", "exports", "logs", "attachments"):
            (self.memory_dir / name).mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        env_file: str | Path | None = None,
    ) -> "Settings":
        """Load and validate configuration from process env and the project .env."""
        project_dir = Path(__file__).resolve().parents[1]
        if env is None:
            load_dotenv(Path(env_file) if env_file else project_dir / ".env")
            values: Mapping[str, str] = os.environ
        else:
            values = env

        def get(name: str, default: str) -> str:
            return values.get(name, default).strip()

        provider = get("SHU_AI_PROVIDER", "ollama").lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"SHU_AI_PROVIDER must be one of {sorted(SUPPORTED_PROVIDERS)}"
            )

        language = get("SHU_DEFAULT_LANGUAGE", "bn").lower()
        if language not in SUPPORTED_LANGUAGE_CODES:
            raise ValueError(
                "SHU_DEFAULT_LANGUAGE must be one of "
                + ", ".join(sorted(SUPPORTED_LANGUAGE_CODES))
            )

        response_style = get("SHU_RESPONSE_STYLE", "friendly").lower()
        if response_style not in RESPONSE_STYLE_INSTRUCTIONS:
            raise ValueError(
                "SHU_RESPONSE_STYLE must be one of "
                + ", ".join(RESPONSE_STYLE_INSTRUCTIONS)
            )

        try:
            sample_rate = int(get("SHU_SAMPLE_RATE", "16000"))
            timeout = float(get("SHU_REQUEST_TIMEOUT_SECONDS", "60"))
            tts_timeout = float(get("SHU_TTS_TIMEOUT_SECONDS", "20"))
            tts_rate_percent = int(get("SHU_TTS_RATE_PERCENT", "0"))
            tts_volume = float(get("SHU_TTS_VOLUME", "1.0"))
            ui_font_size = int(get("SHU_UI_FONT_SIZE", "10"))
            voice_barge_in_rms = float(get("SHU_VOICE_BARGE_IN_RMS", "0.03"))
        except ValueError as error:
            raise ValueError(
                "Audio sample rate, timeout, and voice threshold settings must be numeric"
            ) from error
        if sample_rate < 8_000:
            raise ValueError("SHU_SAMPLE_RATE must be at least 8000 Hz")
        if not isfinite(timeout) or timeout <= 0:
            raise ValueError(
                "SHU_REQUEST_TIMEOUT_SECONDS must be a finite number greater than zero"
            )
        if not isfinite(tts_timeout) or tts_timeout <= 0:
            raise ValueError(
                "SHU_TTS_TIMEOUT_SECONDS must be a finite number greater than zero"
            )
        if not -50 <= tts_rate_percent <= 50:
            raise ValueError("SHU_TTS_RATE_PERCENT must be between -50 and 50")
        if not isfinite(tts_volume) or not 0.0 <= tts_volume <= 1.0:
            raise ValueError("SHU_TTS_VOLUME must be between 0 and 1")
        if not 8 <= ui_font_size <= 24:
            raise ValueError("SHU_UI_FONT_SIZE must be between 8 and 24 points")
        if not isfinite(voice_barge_in_rms) or not 0.0 < voice_barge_in_rms <= 1.0:
            raise ValueError(
                "SHU_VOICE_BARGE_IN_RMS must be a finite number greater than zero and at most one"
            )

        model_size = get("SHU_STT_MODEL_SIZE", "small").lower()
        if model_size not in {"tiny", "base", "small", "medium", "large-v2", "large-v3", "turbo"}:
            raise ValueError("SHU_STT_MODEL_SIZE is not a supported Whisper size")

        email_provider = get("SHU_EMAIL_PROVIDER", "none").lower()
        if email_provider not in {"none", "gmail", "outlook"}:
            raise ValueError("SHU_EMAIL_PROVIDER must be none, gmail, or outlook")
        gmail_client_secrets = get("SHU_GMAIL_OAUTH_CLIENT_SECRETS", "")
        microsoft_client_id = get("SHU_MICROSOFT_OAUTH_CLIENT_ID", "")
        microsoft_tenant = get("SHU_MICROSOFT_OAUTH_TENANT", "common")
        if not re.fullmatch(
            r"(?:common|organizations|consumers|[A-Za-z0-9.-]+)", microsoft_tenant
        ):
            raise ValueError("SHU_MICROSOFT_OAUTH_TENANT is invalid")
        if microsoft_client_id and not re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            microsoft_client_id,
        ):
            raise ValueError("SHU_MICROSOFT_OAUTH_CLIENT_ID must be an application GUID")
        whatsapp_phone_number_id = get("SHU_WHATSAPP_PHONE_NUMBER_ID", "") or None
        if whatsapp_phone_number_id and not re.fullmatch(r"\d{5,32}", whatsapp_phone_number_id):
            raise ValueError("SHU_WHATSAPP_PHONE_NUMBER_ID must contain 5-32 digits")
        whatsapp_api_version = get("SHU_WHATSAPP_GRAPH_API_VERSION", "v27.0")
        if not re.fullmatch(r"v\d+\.\d+", whatsapp_api_version):
            raise ValueError("SHU_WHATSAPP_GRAPH_API_VERSION must look like v27.0")
        wakeword_path = get("SHU_WAKEWORD_MODEL_PATH", "")

        data_dir = Path(get("SHU_DATA_DIR", r"C:\SHU_DATA")).expanduser()
        base_url = get("LOCAL_AI_BASE_URL", "http://localhost:11434").rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("LOCAL_AI_BASE_URL must be an HTTP(S) URL")

        return cls(
            project_dir=project_dir,
            data_dir=data_dir,
            ai_provider=provider,
            cloud_fallback=_as_bool(values.get("SHU_CLOUD_FALLBACK")),
            local_fallback=_as_bool(
                values.get("SHU_LOCAL_FALLBACK"), default=True
            ),
            cloud_ai_enabled=_as_bool(
                values.get("SHU_CLOUD_AI_ENABLED"), default=True
            ),
            automation_enabled=_as_bool(
                values.get("SHU_AUTOMATION_ENABLED"), default=True
            ),
            local_ai_provider=get("LOCAL_AI_PROVIDER", "ollama").lower(),
            local_ai_base_url=base_url,
            local_ai_model=get("LOCAL_AI_MODEL", "qwen2.5:1.5b"),
            gemini_api_key=values.get("GEMINI_API_KEY"),
            gemini_model=values.get("GEMINI_MODEL"),
            default_language=language,
            response_style=response_style,
            default_voice=get("SHU_DEFAULT_VOICE", "male"),
            stt_model_size=model_size,
            microphone_device=_optional_int(
                values.get("SHU_MICROPHONE_DEVICE"), name="SHU_MICROPHONE_DEVICE"
            ) if values.get("SHU_MICROPHONE_DEVICE") is not None else 1,
            sample_rate=sample_rate,
            voice_barge_in=_as_bool(values.get("SHU_VOICE_BARGE_IN")),
            voice_barge_in_rms=voice_barge_in_rms,
            allow_cloud_personal_data=_as_bool(
                values.get("SHU_ALLOW_CLOUD_PERSONAL_DATA")
            ),
            request_timeout_seconds=timeout,
            tts_timeout_seconds=tts_timeout,
            tts_rate_percent=tts_rate_percent,
            tts_volume=tts_volume,
            ui_font_size=ui_font_size,
            email_provider=email_provider,
            gmail_oauth_client_secrets=(
                Path(gmail_client_secrets).expanduser() if gmail_client_secrets else None
            ),
            microsoft_oauth_client_id=microsoft_client_id or None,
            microsoft_oauth_tenant=microsoft_tenant,
            whatsapp_phone_number_id=whatsapp_phone_number_id,
            whatsapp_graph_api_version=whatsapp_api_version,
            wakeword_model_path=Path(wakeword_path).expanduser() if wakeword_path else None,
        )


def get_settings() -> Settings:
    """Return settings for the current process."""
    return Settings.from_env()


# Backwards-compatible constants for existing imports.
_SETTINGS = get_settings()
SHU_AI_PROVIDER = _SETTINGS.ai_provider
SHU_CLOUD_FALLBACK = _SETTINGS.cloud_fallback
SHU_LOCAL_FALLBACK = _SETTINGS.local_fallback
LOCAL_AI_PROVIDER = _SETTINGS.local_ai_provider
LOCAL_AI_BASE_URL = _SETTINGS.local_ai_base_url
LOCAL_AI_MODEL = _SETTINGS.local_ai_model
GEMINI_API_KEY = _SETTINGS.gemini_api_key
GEMINI_MODEL = _SETTINGS.gemini_model
SHU_DEFAULT_LANGUAGE = _SETTINGS.default_language
SHU_DEFAULT_VOICE = _SETTINGS.default_voice
SHU_MEMORY_MODE = os.getenv("SHU_MEMORY_MODE", "local")
SHU_ALLOW_CLOUD_PERSONAL_DATA = _SETTINGS.allow_cloud_personal_data
