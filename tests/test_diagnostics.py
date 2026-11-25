import requests

from app.config import Settings
from app.diagnostics import _ollama_diagnostic


def test_ollama_diagnostic_explains_how_to_start_an_unavailable_service(
    monkeypatch, tmp_path
):
    settings = Settings.from_env({"SHU_DATA_DIR": str(tmp_path)})

    def unavailable(*_args, **_kwargs):
        raise requests.ConnectTimeout("private endpoint details")

    monkeypatch.setattr("app.diagnostics.requests.get", unavailable)

    diagnostic = _ollama_diagnostic(settings)

    assert diagnostic.status == "WARN"
    assert diagnostic.detail == (
        "service unavailable (ConnectTimeout); start Ollama with `ollama serve`"
    )
    assert "private endpoint details" not in diagnostic.detail


def test_ollama_diagnostic_confirms_the_configured_model(monkeypatch, tmp_path):
    settings = Settings.from_env({"SHU_DATA_DIR": str(tmp_path)})

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": settings.local_ai_model}]}

    def reachable(url, *, timeout):
        assert url == settings.local_ai_base_url + "/api/tags"
        assert timeout == 2
        return Response()

    monkeypatch.setattr("app.diagnostics.requests.get", reachable)

    diagnostic = _ollama_diagnostic(settings)

    assert diagnostic.status == "PASS"
    assert diagnostic.detail == "service reachable; selected model available"
