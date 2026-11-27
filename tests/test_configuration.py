from dataclasses import replace

from app.config import Settings
from app.diagnostics import (
    _email_authorization_diagnostic,
    _private_acl_diagnostic,
    _whatsapp_authorization_diagnostic,
    _whisper_model_cache_diagnostic,
)


def test_settings_use_local_privacy_first_defaults(tmp_path):
    settings = Settings.from_env(
        {
            "SHU_AI_PROVIDER": "ollama",
            "SHU_CLOUD_FALLBACK": "false",
            "LOCAL_AI_MODEL": "qwen2.5:1.5b",
            "SHU_DEFAULT_LANGUAGE": "bn",
            "SHU_DATA_DIR": str(tmp_path / "shu-data"),
            "GEMINI_API_KEY": "test-secret",
        }
    )

    assert settings.ai_provider == "ollama"
    assert settings.cloud_fallback is False
    assert settings.local_fallback is True
    assert settings.cloud_ai_enabled is True
    assert settings.automation_enabled is True
    assert settings.local_ai_model == "qwen2.5:1.5b"
    assert settings.response_style == "friendly"
    assert settings.database_path == tmp_path / "shu-data" / "memory" / "shu.db"
    assert "test-secret" not in repr(settings)


def test_tts_timeout_has_a_finite_configurable_default():
    import pytest

    assert Settings.from_env({}).tts_timeout_seconds == 20.0
    assert (
        Settings.from_env({"SHU_TTS_TIMEOUT_SECONDS": "7.5"}).tts_timeout_seconds
        == 7.5
    )
    for setting_name in ("SHU_TTS_TIMEOUT_SECONDS", "SHU_REQUEST_TIMEOUT_SECONDS"):
        for value in ("0", "-1", "nan", "inf"):
            with pytest.raises(ValueError, match=setting_name):
                Settings.from_env({setting_name: value})


def test_response_style_modes_are_supported_and_validated():
    import pytest

    from app.config import RESPONSE_STYLE_INSTRUCTIONS, response_style_instruction

    assert tuple(RESPONSE_STYLE_INSTRUCTIONS) == (
        "friendly", "casual", "formal", "serious", "humorous", "supportive"
    )
    assert Settings.from_env({}).response_style == "friendly"
    assert Settings.from_env({"SHU_RESPONSE_STYLE": "FORMAL"}).response_style == "formal"
    assert "empathetic" in response_style_instruction("supportive")
    with pytest.raises(ValueError, match="SHU_RESPONSE_STYLE"):
        Settings.from_env({"SHU_RESPONSE_STYLE": "sarcastic"})


def test_tts_rate_and_playback_volume_are_bounded_and_configurable():
    import pytest

    defaults = Settings.from_env({})
    assert defaults.tts_rate_percent == 0
    assert defaults.tts_volume == 1.0

    configured = Settings.from_env(
        {
            "SHU_TTS_RATE_PERCENT": "25",
            "SHU_TTS_VOLUME": "0.65",
        }
    )
    assert configured.tts_rate_percent == 25
    assert configured.tts_volume == 0.65

    for value in ("-51", "51", "fast"):
        with pytest.raises(ValueError):
            Settings.from_env({"SHU_TTS_RATE_PERCENT": value})
    for value in ("-0.1", "1.01", "nan", "inf"):
        with pytest.raises(ValueError, match="SHU_TTS_VOLUME"):
            Settings.from_env({"SHU_TTS_VOLUME": value})


def test_voice_barge_in_is_opt_in_and_uses_a_validated_local_threshold():
    import pytest

    default = Settings.from_env({})
    assert default.voice_barge_in is False
    assert default.voice_barge_in_rms == 0.03

    configured = Settings.from_env(
        {
            "SHU_VOICE_BARGE_IN": "true",
            "SHU_VOICE_BARGE_IN_RMS": "0.08",
        }
    )
    assert configured.voice_barge_in is True
    assert configured.voice_barge_in_rms == 0.08

    for value in ("0", "-0.1", "nan", "inf", "1.1"):
        with pytest.raises(ValueError, match="SHU_VOICE_BARGE_IN_RMS"):
            Settings.from_env({"SHU_VOICE_BARGE_IN_RMS": value})


def test_environment_template_lists_only_implemented_ai_providers():
    from pathlib import Path

    template = (Path(__file__).resolve().parents[1] / ".env.example").read_text(
        encoding="utf-8"
    )
    assert "SHU_AI_PROVIDER=ollama" in template
    assert "SHU_LOCAL_FALLBACK=true" in template
    assert "SHU_CLOUD_AI_ENABLED=true" in template
    assert "SHU_AUTOMATION_ENABLED=true" in template
    assert "GEMINI_API_KEY=" in template
    assert "SHU_TTS_TIMEOUT_SECONDS=20" in template
    assert "SHU_TTS_RATE_PERCENT=0" in template
    assert "SHU_TTS_VOLUME=1.0" in template
    assert "SHU_UI_FONT_SIZE=10" in template
    assert "SHU_RESPONSE_STYLE=friendly" in template
    assert "SHU_VOICE_BARGE_IN=false" in template
    assert "OPENROUTER" not in template
    assert "SHU_AI_MODE" not in template


def test_local_fallback_can_be_disabled_explicitly():
    assert Settings.from_env({}).local_fallback is True
    assert Settings.from_env({"SHU_LOCAL_FALLBACK": "false"}).local_fallback is False


def test_cloud_ai_and_automation_can_be_disabled_independently():
    settings = Settings.from_env(
        {
            "SHU_CLOUD_AI_ENABLED": "false",
            "SHU_AUTOMATION_ENABLED": "true",
        }
    )
    assert settings.cloud_ai_enabled is False
    assert settings.automation_enabled is True

    settings = Settings.from_env(
        {
            "SHU_CLOUD_AI_ENABLED": "true",
            "SHU_AUTOMATION_ENABLED": "false",
        }
    )
    assert settings.cloud_ai_enabled is True
    assert settings.automation_enabled is False


def test_dashboard_font_size_is_configurable_and_bounded():
    import pytest

    assert Settings.from_env({}).ui_font_size == 10
    assert Settings.from_env({"SHU_UI_FONT_SIZE": "14"}).ui_font_size == 14
    for value in ("7", "25", "large"):
        with pytest.raises(ValueError):
            Settings.from_env({"SHU_UI_FONT_SIZE": value})


def test_settings_reject_unsupported_language():
    import pytest

    with pytest.raises(ValueError, match="SHU_DEFAULT_LANGUAGE"):
        Settings.from_env({"SHU_DEFAULT_LANGUAGE": "xx"})


def test_settings_can_disable_fixed_microphone_index():
    settings = Settings.from_env({"SHU_MICROPHONE_DEVICE": ""})
    assert settings.microphone_device is None


def test_communication_settings_validate_provider_and_whatsapp_id():
    import pytest

    settings = Settings.from_env(
        {
            "SHU_EMAIL_PROVIDER": "outlook",
            "SHU_WHATSAPP_PHONE_NUMBER_ID": "123456789012345",
            "SHU_WHATSAPP_BUSINESS_ACCOUNT_ID": "987654321098765",
            "SHU_WHATSAPP_GRAPH_API_VERSION": "v27.0",
        }
    )
    assert settings.email_provider == "outlook"
    assert settings.whatsapp_phone_number_id == "123456789012345"
    assert settings.whatsapp_business_account_id == "987654321098765"
    assert settings.whatsapp_graph_api_version == "v27.0"
    with pytest.raises(ValueError, match="SHU_EMAIL_PROVIDER"):
        Settings.from_env({"SHU_EMAIL_PROVIDER": "unknown"})
    with pytest.raises(ValueError, match="PHONE_NUMBER_ID"):
        Settings.from_env({"SHU_WHATSAPP_PHONE_NUMBER_ID": "123/456"})
    with pytest.raises(ValueError, match="BUSINESS_ACCOUNT_ID"):
        Settings.from_env({"SHU_WHATSAPP_BUSINESS_ACCOUNT_ID": "123/456"})


def test_diagnostics_recognize_external_gmail_client_without_claiming_login(tmp_path):
    client = tmp_path / "gmail-client.json"
    client.write_text('{"installed":{}}', encoding="utf-8")
    settings = Settings.from_env(
        {
            "SHU_DATA_DIR": str(tmp_path / "data"),
            "SHU_GMAIL_OAUTH_CLIENT_SECRETS": str(client),
        }
    )
    email = _email_authorization_diagnostic(settings)

    assert email.status == "WARN"
    assert "set SHU_EMAIL_PROVIDER=gmail" in email.detail
    assert "user consent" in email.detail


def test_whatsapp_diagnostic_reports_missing_token_without_exposing_phone_id(
    tmp_path, monkeypatch
):
    from app import diagnostics

    phone_id = "123456789012345"
    settings = Settings.from_env(
        {
            "SHU_DATA_DIR": str(tmp_path / "data"),
            "SHU_WHATSAPP_PHONE_NUMBER_ID": phone_id,
        }
    )
    monkeypatch.setattr(diagnostics, "_credential_present", lambda _name: False)

    result = _whatsapp_authorization_diagnostic(settings)

    assert result.status == "WARN"
    assert "access token is missing" in result.detail
    assert "credentials set whatsapp_cloud_api_access_token" in result.detail
    assert phone_id not in result.detail


def test_whisper_cache_diagnostic_reports_model_files_without_loading_model(
    tmp_path, monkeypatch
):
    from app import diagnostics

    (tmp_path / "model.bin").write_bytes(b"model")
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        diagnostics,
        "_cached_whisper_model_path",
        lambda model_size: tmp_path,
    )

    result = _whisper_model_cache_diagnostic(Settings.from_env({}))

    assert result.status == "PASS"
    assert "cached locally" in result.detail
    assert "did not load" in result.detail


def test_whisper_cache_diagnostic_warns_when_model_is_not_cached(monkeypatch):
    from app import diagnostics

    def missing_model(_model_size):
        raise FileNotFoundError

    monkeypatch.setattr(diagnostics, "_cached_whisper_model_path", missing_model)

    result = _whisper_model_cache_diagnostic(Settings.from_env({}))

    assert result.status == "WARN"
    assert "not available offline" in result.detail
    assert "FileNotFoundError" in result.detail


def test_cached_whisper_model_path_uses_local_huggingface_cache_for_supported_sizes(
    tmp_path, monkeypatch
):
    from app import diagnostics
    import huggingface_hub

    calls = []

    def snapshot_download(repo_id, **kwargs):
        calls.append((repo_id, kwargs))
        return str(tmp_path)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot_download)
    expected_repositories = {
        "tiny": "Systran/faster-whisper-tiny",
        "base": "Systran/faster-whisper-base",
        "small": "Systran/faster-whisper-small",
        "medium": "Systran/faster-whisper-medium",
        "large-v2": "Systran/faster-whisper-large-v2",
        "large-v3": "Systran/faster-whisper-large-v3",
        "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    }

    for model_size, repo_id in expected_repositories.items():
        assert diagnostics._cached_whisper_model_path(model_size) == tmp_path

    assert [repo_id for repo_id, _kwargs in calls] == list(expected_repositories.values())
    assert all(kwargs["local_files_only"] is True for _repo_id, kwargs in calls)
    assert all(
        kwargs["allow_patterns"] == diagnostics._WHISPER_CACHE_ALLOW_PATTERNS
        for _repo_id, kwargs in calls
    )


def test_private_acl_diagnostic_warns_for_access_outside_allow_list_without_listing_paths(
    tmp_path, monkeypatch
):
    from app import diagnostics

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / ".env").write_text("test-only", encoding="utf-8")
    settings = replace(
        Settings.from_env({"SHU_DATA_DIR": str(tmp_path / "private-data")}),
        project_dir=project_dir,
    )
    monkeypatch.setattr(
        diagnostics,
        "_private_acl_violations",
        lambda _path: {"S-1-5-11"},
    )

    result = _private_acl_diagnostic(settings)

    assert result.status == "WARN"
    assert "current-user/SYSTEM/Administrators" in result.detail
    assert str(project_dir) not in result.detail


def test_private_acl_diagnostic_passes_when_allow_list_is_valid(
    tmp_path, monkeypatch
):
    from app import diagnostics

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / ".env").write_text("test-only", encoding="utf-8")
    settings = replace(
        Settings.from_env({"SHU_DATA_DIR": str(tmp_path / "private-data")}),
        project_dir=project_dir,
    )
    monkeypatch.setattr(
        diagnostics,
        "_private_acl_violations",
        lambda _path: set(),
    )

    result = _private_acl_diagnostic(settings)

    assert result.status == "PASS"


def test_private_acl_diagnostic_checks_nested_data_files(tmp_path, monkeypatch):
    from app import diagnostics

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    data_dir = tmp_path / "private-data"
    nested = data_dir / "memory" / "shu.db"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"test-only")
    settings = Settings.from_env({"SHU_DATA_DIR": str(data_dir)})
    audited = []

    def unexpected_acl(path):
        audited.append(path)
        return {"unexpected allow rule"} if path == nested else set()

    monkeypatch.setattr(diagnostics, "_private_acl_violations", unexpected_acl)

    result = _private_acl_diagnostic(settings)

    assert result.status == "WARN"
    assert nested in audited


def test_private_acl_diagnostic_stops_after_known_private_path_violation(
    tmp_path, monkeypatch
):
    from app import diagnostics

    data_dir = tmp_path / "private-data"
    nested = data_dir / "memory" / "shu.db"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"test-only")
    client_file = tmp_path / "gmail-oauth-client.json"
    client_file.write_text("test-only", encoding="utf-8")
    settings = Settings.from_env(
        {
            "SHU_DATA_DIR": str(data_dir),
            "SHU_GMAIL_OAUTH_CLIENT_SECRETS": str(client_file),
        }
    )
    audited = []

    def unexpected_acl(path):
        audited.append(path)
        return {"unexpected allow rule"} if path == client_file else set()

    def unexpected_scan(_path, _pattern):
        raise AssertionError("The private tree should not be enumerated after a known violation")

    monkeypatch.setattr(diagnostics, "_private_acl_violations", unexpected_acl)
    monkeypatch.setattr(diagnostics.Path, "rglob", unexpected_scan)

    result = _private_acl_diagnostic(settings)

    assert result.status == "WARN"
    assert client_file in audited
    assert nested not in audited
