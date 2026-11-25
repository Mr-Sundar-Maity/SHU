"""Local-first AI providers for SHU with bounded context and safe fallback."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from math import isfinite
from typing import Any

import requests

from app.config import Settings, get_settings
from app.cpu_work_queue import CPU_WORK_QUEUE
from app.security.privacy import is_sensitive_text


class SHUAIEngine:
    """Use Ollama by default; use Gemini only when explicitly permitted."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def ask_local(
        self,
        prompt: str,
        *,
        context: Sequence[Mapping[str, str]] = (),
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Send a bounded conversation to the Ollama local chat endpoint."""
        self._validate_temperature(temperature)
        messages = self._messages(
            prompt,
            context,
            system_instruction=system_instruction,
        )
        payload: dict[str, Any] = {
            "model": self.settings.local_ai_model,
            "messages": messages,
            "stream": False,
        }
        if temperature is not None:
            payload["options"] = {"temperature": temperature}
        with CPU_WORK_QUEUE.slot(timeout=self.settings.request_timeout_seconds):
            response = requests.post(
                f"{self.settings.local_ai_base_url}/api/chat",
                json=payload,
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            data: Any = response.json()
            try:
                content = data["message"]["content"]
            except (KeyError, TypeError) as error:
                raise ValueError("Ollama returned an invalid chat response") from error
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Ollama returned an empty response")
            return content.strip()

    def local_model_loaded(self) -> bool | None:
        """Best-effort check whether the selected Ollama model is resident."""
        try:
            response = requests.get(
                f"{self.settings.local_ai_base_url}/api/ps",
                timeout=min(2.0, self.settings.request_timeout_seconds),
            )
            response.raise_for_status()
            data: Any = response.json()
            models = data.get("models") if isinstance(data, Mapping) else None
            if not isinstance(models, list):
                return None
            selected = self.settings.local_ai_model.casefold()
            return any(
                isinstance(item, Mapping)
                and any(
                    isinstance(item.get(key), str)
                    and item[key].casefold() == selected
                    for key in ("name", "model")
                )
                for item in models
            )
        except (requests.RequestException, ValueError, TypeError):
            return None

    def ask_google(
        self,
        prompt: str,
        *,
        context: Sequence[Mapping[str, str]] = (),
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Send a request to Gemini; import the provider SDK only when needed."""
        self._validate_temperature(temperature)
        if not self.settings.cloud_ai_enabled:
            raise PermissionError("Cloud AI is disabled in SHU settings")
        if not self.settings.gemini_api_key:
            raise ValueError("Gemini API key is not configured")
        if not self.settings.gemini_model:
            raise ValueError("Gemini model is not configured")
        if not self.settings.allow_cloud_personal_data and self._contains_sensitive_content(
            prompt,
            context,
            system_instruction=system_instruction,
        ):
            raise PermissionError("Sensitive conversation content is blocked from cloud processing")

        try:
            from google import genai
            from google.genai import types
        except ImportError as error:
            raise RuntimeError("The google-genai package is not installed") from error

        contents = self._gemini_contents(
            prompt,
            context,
        )
        generation_options: dict[str, Any] = {}
        if system_instruction and system_instruction.strip():
            generation_options["system_instruction"] = system_instruction.strip()[:2_000]
        if temperature is not None:
            generation_options["temperature"] = temperature
        generation_config = (
            types.GenerateContentConfig(**generation_options)
            if generation_options
            else None
        )
        timeout_ms = max(1, round(self.settings.request_timeout_seconds * 1_000))
        client = genai.Client(
            api_key=self.settings.gemini_api_key,
            http_options=types.HttpOptions(
                timeout=timeout_ms,
                retry_options=types.HttpRetryOptions(
                    attempts=2,
                    initial_delay=0.5,
                    max_delay=2.0,
                    exp_base=2.0,
                    jitter=0.2,
                    http_status_codes=[408, 429, 500, 502, 503, 504],
                ),
            ),
        )
        generation_arguments = {
            "model": self.settings.gemini_model,
            "contents": contents,
        }
        if generation_config is not None:
            generation_arguments["config"] = generation_config
        response = client.models.generate_content(**generation_arguments)
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Gemini returned an empty response")
        return text.strip()

    def ask(
        self,
        prompt: str,
        provider: str | None = None,
        *,
        context: Sequence[Mapping[str, str]] = (),
        sensitive: bool = False,
        system_instruction: str | None = None,
        on_status: Callable[[str], None] | None = None,
        temperature: float | None = None,
    ) -> str:
        """Generate a response, keeping sensitive requests local by default."""
        self._validate_temperature(temperature)
        if not prompt or not prompt.strip():
            return "Please tell me something."

        selected_provider = (provider or self.settings.ai_provider).lower()
        if selected_provider not in {"ollama", "google"}:
            raise ValueError("Unknown AI provider: " + selected_provider)
        cloud_ai_disabled_route = (
            selected_provider == "google" and not self.settings.cloud_ai_enabled
        )
        if cloud_ai_disabled_route:
            selected_provider = "ollama"

        sensitive_request = sensitive or self._contains_sensitive_content(
            prompt,
            context,
            system_instruction=system_instruction,
        )
        privacy_routed_local = (
            selected_provider == "google"
            and sensitive_request
            and not self.settings.allow_cloud_personal_data
        )
        if privacy_routed_local:
            selected_provider = "ollama"

        if selected_provider == "ollama":
            try:
                if on_status:
                    self._emit_status(
                        on_status,
                        (
                            f"Sensitive request routed to local model {self.settings.local_ai_model}"
                            if privacy_routed_local
                            else (
                                f"Cloud AI is disabled; using local model {self.settings.local_ai_model}"
                                if cloud_ai_disabled_route
                                else f"Generating with local model {self.settings.local_ai_model}"
                            )
                        ),
                    )
                print(
                    "SHU: Routing sensitive request to Local AI..."
                    if privacy_routed_local
                    else (
                        "SHU: Cloud AI is disabled; using Local AI..."
                        if cloud_ai_disabled_route
                        else "SHU: Using Local AI..."
                    )
                )
                local_arguments = {
                    "context": context,
                    "system_instruction": system_instruction,
                }
                if temperature is not None:
                    local_arguments["temperature"] = temperature
                return self.ask_local(prompt, **local_arguments)
            except Exception as error:
                print("Local AI Error:", self._safe_error_label(error))
                if self.settings.cloud_ai_enabled and self.settings.cloud_fallback and not (
                    sensitive_request and not self.settings.allow_cloud_personal_data
                ):
                    if on_status:
                        self._emit_status(
                            on_status,
                            "Local AI failed; trying Google Gemini fallback",
                        )
                    print("SHU: Trying Cloud AI...")
                    try:
                        google_arguments = {
                            "context": context,
                            "system_instruction": system_instruction,
                        }
                        if temperature is not None:
                            google_arguments["temperature"] = temperature
                        return self.ask_google(prompt, **google_arguments)
                    except Exception as cloud_error:
                        print("Cloud AI Error:", self._safe_error_label(cloud_error))
                return "Sorry, I could not process your request."

        try:
            if on_status:
                self._emit_status(
                    on_status,
                    f"Generating with Google Gemini ({self.settings.gemini_model or 'configured model'})",
                )
            print("SHU: Using Google Gemini...")
            google_arguments = {
                "context": context,
                "system_instruction": system_instruction,
            }
            if temperature is not None:
                google_arguments["temperature"] = temperature
            return self.ask_google(prompt, **google_arguments)
        except Exception as error:
            print("Gemini Error:", self._safe_error_label(error))
            if self.settings.local_fallback:
                if on_status:
                    self._emit_status(
                        on_status,
                        f"Gemini unavailable; trying local model {self.settings.local_ai_model}",
                    )
                print("SHU: Trying Local AI fallback...")
                try:
                    return self.ask_local(
                        prompt,
                        context=context,
                        system_instruction=system_instruction,
                        temperature=temperature,
                    )
                except Exception as local_error:
                    print(
                        "Local AI fallback error:",
                        self._safe_error_label(local_error),
                    )
                    if on_status:
                        self._emit_status(
                            on_status,
                            "Gemini and local AI are unavailable",
                        )
                    return "Sorry, both Cloud AI and local AI are unavailable."
            return "Sorry, Cloud AI is unavailable."

    @staticmethod
    def _emit_status(callback: Callable[[str], None], message: str) -> None:
        try:
            callback(message)
        except Exception:
            # Status reporting must never interrupt or change an AI request.
            pass

    @staticmethod
    def _validate_temperature(temperature: float | None) -> None:
        if temperature is None:
            return
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not isfinite(temperature)
            or not 0.0 <= temperature <= 2.0
        ):
            raise ValueError("AI temperature must be a finite number from 0 to 2")

    @staticmethod
    def _safe_error_label(error: Exception) -> str:
        """Report the provider error class and HTTP status without its body."""
        code = getattr(error, "code", None)
        if type(code) is int:
            return f"{type(error).__name__} (HTTP {code})"
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        if type(status_code) is int:
            return f"{type(error).__name__} (HTTP {status_code})"
        return type(error).__name__

    @staticmethod
    def _messages(
        prompt: str,
        context: Sequence[Mapping[str, str]],
        *,
        system_instruction: str | None = None,
    ) -> list[dict[str, str]]:
        allowed_roles = {"user", "assistant"}
        result: list[dict[str, str]] = []
        if system_instruction and system_instruction.strip():
            result.append(
                {"role": "system", "content": system_instruction.strip()[:2_000]}
            )
        for item in context[-12:]:
            role = item.get("role", "")
            content = item.get("content", "")
            if role in allowed_roles and isinstance(content, str) and content.strip():
                result.append({"role": role, "content": content[-4_000:]})
        result.append({"role": "user", "content": prompt[-8_000:]})
        return result

    @staticmethod
    def _contains_sensitive_content(
        prompt: str,
        context: Sequence[Mapping[str, str]],
        *,
        system_instruction: str | None = None,
    ) -> bool:
        if is_sensitive_text(prompt) or is_sensitive_text(system_instruction or ""):
            return True
        return any(
            is_sensitive_text(item.get("content", ""))
            for item in context
            if isinstance(item, Mapping)
        )

    @classmethod
    def _gemini_contents(
        cls,
        prompt: str,
        context: Sequence[Mapping[str, str]],
    ) -> str:
        messages = cls._messages(prompt, context)
        return "\n".join(
            f"{message['role'].upper()}: {message['content']}"
            for message in messages
        )
