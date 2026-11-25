import pytest
from unittest.mock import Mock
from requests.exceptions import ConnectionError as RequestsConnectionError

from app.ai.ai_engine import SHUAIEngine
from app.config import Settings


def make_settings(**overrides):
    values = {
        "SHU_AI_PROVIDER": "ollama",
        "SHU_CLOUD_FALLBACK": "false",
        "LOCAL_AI_MODEL": "qwen2.5:1.5b",
        "GEMINI_API_KEY": "test-key",
        "GEMINI_MODEL": "test-model",
    }
    values.update(overrides)
    return Settings.from_env(values)


def test_local_request_uses_selected_model_and_bounded_messages(monkeypatch):
    response = Mock()
    response.json.return_value = {"message": {"content": "  Hello  "}}
    monkeypatch.setattr("app.ai.ai_engine.requests.post", Mock(return_value=response))
    engine = SHUAIEngine(make_settings())

    result = engine.ask(
        "Hi",
        context=[{"role": "assistant", "content": "Earlier context"}],
        system_instruction="Reply in Bengali",
    )

    assert result == "Hello"
    args, kwargs = __import__("app.ai.ai_engine", fromlist=["requests"]).requests.post.call_args
    assert args[0] == "http://localhost:11434/api/chat"
    assert kwargs["json"]["model"] == "qwen2.5:1.5b"
    assert kwargs["json"]["messages"][0]["role"] == "system"
    assert kwargs["json"]["messages"][-1] == {"role": "user", "content": "Hi"}
    assert kwargs["timeout"] == 60.0


def test_local_request_can_use_deterministic_generation_temperature(monkeypatch):
    response = Mock()
    response.json.return_value = {"message": {"content": "{\"steps\":[]}"}}
    post = Mock(return_value=response)
    monkeypatch.setattr("app.ai.ai_engine.requests.post", post)
    engine = SHUAIEngine(make_settings())

    assert engine.ask("Draft a plan", temperature=0.0) == '{"steps":[]}'
    assert post.call_args.kwargs["json"]["options"] == {"temperature": 0.0}


def test_ai_rejects_invalid_generation_temperature():
    engine = SHUAIEngine(make_settings())

    with pytest.raises(ValueError, match="temperature"):
        engine.ask("Draft a plan", temperature=float("nan"))


def test_local_model_status_matches_selected_running_model(monkeypatch):
    response = Mock()
    response.json.return_value = {
        "models": [{"name": "qwen2.5:1.5b", "model": "qwen2.5:1.5b"}]
    }
    get = Mock(return_value=response)
    monkeypatch.setattr("app.ai.ai_engine.requests.get", get)
    engine = SHUAIEngine(make_settings())

    assert engine.local_model_loaded() is True
    get.assert_called_once_with(
        "http://localhost:11434/api/ps",
        timeout=2.0,
    )


def test_local_model_status_reports_unloaded_or_unavailable(monkeypatch):
    response = Mock()
    response.json.return_value = {"models": [{"name": "another-model"}]}
    monkeypatch.setattr("app.ai.ai_engine.requests.get", Mock(return_value=response))
    engine = SHUAIEngine(make_settings())
    assert engine.local_model_loaded() is False

    monkeypatch.setattr(
        "app.ai.ai_engine.requests.get",
        Mock(side_effect=RequestsConnectionError("offline")),
    )
    assert engine.local_model_loaded() is None


def test_local_error_does_not_fall_back_to_cloud_unless_enabled():
    engine = SHUAIEngine(make_settings())
    engine.ask_local = Mock(side_effect=ConnectionError("offline"))
    engine.ask_google = Mock(return_value="cloud")

    assert engine.ask("hello") == "Sorry, I could not process your request."
    engine.ask_google.assert_not_called()


def test_explicit_google_provider_uses_the_cloud_adapter():
    engine = SHUAIEngine(make_settings())
    engine.ask_google = Mock(return_value="READY")

    result = engine.ask("Reply READY", provider="google")

    assert result == "READY"
    engine.ask_google.assert_called_once_with(
        "Reply READY",
        context=(),
        system_instruction=None,
    )


def test_disabling_cloud_routes_explicit_google_request_to_local():
    engine = SHUAIEngine(
        make_settings(
            SHU_AI_PROVIDER="google",
            SHU_CLOUD_AI_ENABLED="false",
            SHU_CLOUD_FALLBACK="true",
        )
    )
    engine.ask_google = Mock(side_effect=AssertionError("cloud adapter must not run"))
    engine.ask_local = Mock(return_value="local answer")
    statuses = []

    assert engine.ask("Reply READY", on_status=statuses.append) == "local answer"
    engine.ask_google.assert_not_called()
    engine.ask_local.assert_called_once()
    assert any("Cloud AI is disabled" in message for message in statuses)


def test_disabling_cloud_blocks_direct_adapter_and_local_cloud_fallback():
    engine = SHUAIEngine(
        make_settings(
            SHU_CLOUD_AI_ENABLED="false",
            SHU_CLOUD_FALLBACK="true",
        )
    )
    engine.ask_google = Mock(side_effect=AssertionError("cloud adapter must not run"))
    engine.ask_local = Mock(side_effect=ConnectionError("offline"))

    assert engine.ask("hello") == "Sorry, I could not process your request."
    engine.ask_google.assert_not_called()

    with pytest.raises(PermissionError, match="Cloud AI is disabled"):
        SHUAIEngine.ask_google(engine, "hello")


def test_google_failure_falls_back_to_local_with_status_and_safe_logging(capsys):
    settings = make_settings(SHU_AI_PROVIDER="google")
    engine = SHUAIEngine(settings)
    engine.ask_google = Mock(side_effect=RuntimeError("private provider response"))
    engine.ask_local = Mock(return_value="local answer")
    statuses = []

    result = engine.ask(
        "Reply READY",
        context=[{"role": "user", "content": "Earlier context"}],
        system_instruction="Reply in Bengali",
        on_status=statuses.append,
        temperature=0.0,
    )

    assert result == "local answer"
    engine.ask_google.assert_called_once()
    engine.ask_local.assert_called_once_with(
        "Reply READY",
        context=[{"role": "user", "content": "Earlier context"}],
        system_instruction="Reply in Bengali",
        temperature=0.0,
    )
    assert statuses[-1] == (
        f"Gemini unavailable; trying local model {settings.local_ai_model}"
    )
    assert "private provider response" not in capsys.readouterr().out


def test_google_failure_can_disable_local_fallback(capsys):
    engine = SHUAIEngine(
        make_settings(
            SHU_AI_PROVIDER="google",
            SHU_LOCAL_FALLBACK="false",
        )
    )
    engine.ask_google = Mock(side_effect=RuntimeError("provider unavailable"))
    engine.ask_local = Mock(return_value="must not run")

    assert engine.ask("Reply READY") == "Sorry, Cloud AI is unavailable."
    engine.ask_local.assert_not_called()
    assert "provider unavailable" not in capsys.readouterr().out


def test_google_and_local_failure_returns_clear_redacted_status(capsys):
    engine = SHUAIEngine(make_settings(SHU_AI_PROVIDER="google"))
    engine.ask_google = Mock(side_effect=RuntimeError("private cloud details"))
    engine.ask_local = Mock(side_effect=ConnectionError("private local details"))
    statuses = []

    result = engine.ask("Reply READY", on_status=statuses.append)

    assert result == "Sorry, both Cloud AI and local AI are unavailable."
    assert statuses[-1] == "Gemini and local AI are unavailable"
    output = capsys.readouterr().out
    assert "private cloud details" not in output
    assert "private local details" not in output


def test_sensitive_request_selected_for_google_is_routed_to_local():
    settings = make_settings(SHU_AI_PROVIDER="google")
    engine = SHUAIEngine(settings)
    engine.ask_local = Mock(return_value="local answer")
    engine.ask_google = Mock(return_value="must not be sent")
    status = Mock()

    result = engine.ask(
        "What did I save as my preference?",
        sensitive=True,
        context=[
            {
                "role": "user",
                "content": "APPROVED MEMORY DATA: prefers the blue theme",
            }
        ],
        system_instruction="Use the approved memory to answer.",
        on_status=status,
    )

    assert result == "local answer"
    engine.ask_local.assert_called_once_with(
        "What did I save as my preference?",
        context=[
            {
                "role": "user",
                "content": "APPROVED MEMORY DATA: prefers the blue theme",
            }
        ],
        system_instruction="Use the approved memory to answer.",
    )
    engine.ask_google.assert_not_called()
    status.assert_called_once_with(
        f"Sensitive request routed to local model {settings.local_ai_model}"
    )


def test_sensitive_conversation_history_selected_for_google_stays_local():
    settings = make_settings(SHU_AI_PROVIDER="google")
    engine = SHUAIEngine(settings)
    engine.ask_local = Mock(return_value="local answer")
    engine.ask_google = Mock(return_value="must not be sent")
    context = [{"role": "user", "content": "Contact me at private@example.com"}]

    result = engine.ask(
        "What did we discuss?",
        context=context,
    )

    assert result == "local answer"
    engine.ask_local.assert_called_once_with(
        "What did we discuss?",
        context=context,
        system_instruction=None,
    )
    engine.ask_google.assert_not_called()


def test_sensitive_system_instruction_selected_for_google_routes_local():
    engine = SHUAIEngine(make_settings(SHU_AI_PROVIDER="google"))
    engine.ask_local = Mock(return_value="local answer")
    engine.ask_google = Mock(return_value="must not be sent")

    result = engine.ask(
        "What should I do?",
        system_instruction="The account email is private@example.com",
    )

    assert result == "local answer"
    engine.ask_local.assert_called_once()
    engine.ask_google.assert_not_called()


def test_multilingual_sensitive_prompt_selected_for_google_routes_local():
    engine = SHUAIEngine(make_settings(SHU_AI_PROVIDER="google"))
    engine.ask_local = Mock(return_value="local answer")
    engine.ask_google = Mock(return_value="must not be sent")

    result = engine.ask("আমার পাসওয়ার্ড গোপন রাখো।", provider="google")

    assert result == "local answer"
    engine.ask_local.assert_called_once()
    engine.ask_google.assert_not_called()


@pytest.mark.parametrize(
    "prompt",
    [
        "access_token=abcdefghijklmnopqrstuvwxyz",
        "client_secret=abcdefghijklmnopqrstuvwxyz",
        "Authorization: Bearer eyJhbGciOiJub25lIn0.dGVzdC5zZWNyZXQudmFsdWU",
        "GOOGLE_API_KEY=abcdefghijklmnopqrstuvwx",
        "AWS_SECRET_ACCESS_KEY=abcdefghijklmnopqrstuvwxyz",
        "GITHUB_TOKEN=abcdefghijklmnopqrstuvwxyz",
        "Authorization: Basic YWJjZGVmZ2hpamtsbW5vcA==",
        "AKIA" + "A" * 16,
        "DATABASE_URL=postgres://shu:Q7pL2nV8@db.example.test/app",
    ],
)
def test_credential_config_formats_selected_for_google_stay_local(prompt):
    engine = SHUAIEngine(make_settings(SHU_AI_PROVIDER="google"))
    engine.ask_local = Mock(return_value="local response")
    engine.ask_google = Mock(return_value="must not be sent")

    assert engine.ask(prompt) == "local response"

    engine.ask_local.assert_called_once_with(
        prompt,
        context=(),
        system_instruction=None,
    )
    engine.ask_google.assert_not_called()


def test_sensitive_history_is_not_sent_during_cloud_fallback():
    settings = make_settings(SHU_CLOUD_FALLBACK="true")
    engine = SHUAIEngine(settings)
    engine.ask_local = Mock(side_effect=ConnectionError("offline"))
    engine.ask_google = Mock(return_value="must not be sent")

    result = engine.ask(
        "Summarize our conversation",
        context=[{"role": "user", "content": "Contact me at private@example.com"}],
    )

    assert result == "Sorry, I could not process your request."
    engine.ask_google.assert_not_called()


def test_google_selected_sensitive_request_does_not_cloud_fallback_if_local_fails():
    settings = make_settings(
        SHU_AI_PROVIDER="google",
        SHU_CLOUD_FALLBACK="true",
    )
    engine = SHUAIEngine(settings)
    engine.ask_local = Mock(side_effect=ConnectionError("offline"))
    engine.ask_google = Mock(return_value="must not be sent")

    result = engine.ask(
        "What is my preference?",
        sensitive=True,
    )

    assert result == "Sorry, I could not process your request."
    engine.ask_local.assert_called_once()
    engine.ask_google.assert_not_called()


def test_direct_google_adapter_rejects_sensitive_history():
    engine = SHUAIEngine(make_settings())

    try:
        engine.ask_google(
            "Continue",
            context=[{"role": "user", "content": "My password is abc123"}],
        )
    except PermissionError as error:
        assert "Sensitive" in str(error)
    else:
        raise AssertionError("Sensitive history must never reach the Google adapter")


def test_direct_google_adapter_rejects_sensitive_system_instruction():
    engine = SHUAIEngine(make_settings())

    try:
        engine.ask_google(
            "Continue",
            system_instruction="The account email is private@example.com",
        )
    except PermissionError as error:
        assert "Sensitive" in str(error)
    else:
        raise AssertionError("Sensitive system instructions must not reach Google")


def test_google_adapter_applies_configured_request_timeout(monkeypatch):
    from google import genai

    client = Mock()
    client.models.generate_content.return_value.text = " READY "
    constructor = Mock(return_value=client)
    monkeypatch.setattr(genai, "Client", constructor)
    engine = SHUAIEngine(
        make_settings(
            SHU_REQUEST_TIMEOUT_SECONDS="12.5",
            GEMINI_MODEL="gemini-test",
        )
    )

    assert engine.ask_google("Reply READY") == "READY"

    constructor.assert_called_once()
    options = constructor.call_args.kwargs["http_options"]
    assert options.timeout == 12_500
    assert options.retry_options.attempts == 2
    assert options.retry_options.initial_delay == 0.5
    assert options.retry_options.max_delay == 2.0
    assert options.retry_options.http_status_codes == [408, 429, 500, 502, 503, 504]
    client.models.generate_content.assert_called_once_with(
        model="gemini-test",
        contents="USER: Reply READY",
    )


def test_google_adapter_sends_system_instruction_as_native_config(monkeypatch):
    from google import genai

    client = Mock()
    client.models.generate_content.return_value.text = "READY"
    constructor = Mock(return_value=client)
    monkeypatch.setattr(genai, "Client", constructor)
    engine = SHUAIEngine(make_settings())

    assert engine.ask_google(
        "Answer the user",
        context=[{"role": "user", "content": "Earlier question"}],
        system_instruction="Answer in Bengali",
        temperature=0.0,
    ) == "READY"

    arguments = client.models.generate_content.call_args.kwargs
    assert arguments["contents"] == (
        "USER: Earlier question\nUSER: Answer the user"
    )
    assert arguments["config"].system_instruction == "Answer in Bengali"
    assert arguments["config"].temperature == 0.0


def test_provider_error_label_reports_http_status_without_error_body():
    class ProviderError(Exception):
        code = 503

        def __str__(self):
            return "private response body"

    label = SHUAIEngine._safe_error_label(ProviderError())

    assert label == "ProviderError (HTTP 503)"
    assert "private response body" not in label


def test_empty_prompt_returns_helpful_message():
    engine = SHUAIEngine(make_settings())
    assert engine.ask("  ") == "Please tell me something."
