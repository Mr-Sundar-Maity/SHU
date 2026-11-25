"""Opt-in Gemini connectivity check; importing this module never makes a cloud call."""

import json
import time
from dataclasses import replace

from app.ai.ai_engine import SHUAIEngine
from app.config import get_settings


def main() -> int:
    settings = get_settings()
    if not settings.gemini_api_key or not settings.gemini_model:
        print("Gemini credentials/model are not configured.")
        return 2
    engine = SHUAIEngine(replace(settings, request_timeout_seconds=15.0))
    started = time.perf_counter()
    try:
        answer = engine.ask_google(
            "Reply with exactly: READY",
            system_instruction="Reply with exactly one word.",
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": SHUAIEngine._safe_error_label(error),
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                }
            )
        )
        return 1
    matches = answer.strip().casefold() == "ready"
    print(
        json.dumps(
            {
                "status": "success" if matches else "unexpected_response",
                "response_characters": len(answer),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            }
        )
    )
    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
