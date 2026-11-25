"""Language names and Whisper language codes supported by SHU."""

SUPPORTED_LANGUAGES = {
    "bengali": "bn",
    "hindi": "hi",
    "english": "en",
    "tamil": "ta",
    "telugu": "te",
    "malayalam": "ml",
}

DEFAULT_LANGUAGE = "bn"


def get_language_code(language_name: str | None) -> str:
    """Normalize a supported language name/code, defaulting to Bengali."""
    if not isinstance(language_name, str):
        return DEFAULT_LANGUAGE
    normalized = language_name.strip().lower()
    return SUPPORTED_LANGUAGES.get(
        normalized,
        normalized if normalized in SUPPORTED_LANGUAGES.values() else DEFAULT_LANGUAGE,
    )
