"""Conservative local/cloud data sensitivity classification."""

from __future__ import annotations

import re
import unicodedata


_AUTHENTICATION_TERMS = (
    r"password|passcode|otp|"
    r"recovery[\s_-]+code|verification[\s_-]+code|security[\s_-]+code|"
    r"one[\s_-]+time[\s_-]+(?:password|code)|"
    r"api[\s_-]*key|api[\s_-]*token|github[\s_-]*token|"
    r"access[\s_-]*key|secret[\s_-]*access[\s_-]*key|"
    r"access[\s_-]*token|refresh[\s_-]*token|"
    r"client[\s_-]*secret|private[\s_-]*key|secret[\s_-]*key"
)
_AUTHENTICATION_ASSIGNMENT = re.compile(
    rf"\b(?:{_AUTHENTICATION_TERMS}|passwd|token|secret|credential)\b"
    r"['\"]?\s*(?:[:=]|\bis\b)"
)
_AUTHENTICATION_FORMATS = (
    re.compile(r"(?i)(?<![a-z0-9])bearer\s+[a-z0-9._~+/-]{16,}={0,2}"),
    re.compile(r"(?i)(?<![a-z0-9])basic\s+[a-z0-9+/]{16,}={0,2}"),
    re.compile(
        r"(?i)(?<![a-z0-9])(?:AKIA[0-9A-Z]{16}|AIza[0-9a-z_-]{30,}|"
        r"sk-(?:proj-)?[a-z0-9_-]{20,}|"
        r"gh[pousr]_[a-z0-9_]{20,}|github_pat_[a-z0-9_]{20,}|"
        r"xox[baprs]-[a-z0-9-]{16,})(?![a-z0-9])"
    ),
    re.compile(r"(?i)-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    re.compile(
        r"(?i)(?<![a-z0-9])(?:https?|ftp|ssh|postgres(?:ql)?|mysql|mariadb|"
        r"mongodb(?:\+srv)?|redis(?:s)?|amqp(?:s)?)://[^/\s:@]+:[^@\s/]+@"
    ),
)

_MULTILINGUAL_AUTHENTICATION_TERMS = (
    # Bengali
    "পাসওয়ার্ড", "পাসওয়ার্ড", "সংকেত শব্দ", "ওটিপি", "পিন নম্বর",
    # Hindi
    "पासवर्ड", "संकेत शब्द", "ओटीपी", "पिन नंबर",
    # Tamil
    "கடவுச்சொல்", "இரகசிய மொழி", "மறைபொருள் சொல்", "ஓடிபி", "ஒடிபி", "பின் எண்",
    # Telugu
    "పాస్‌వర్డ్", "పాస్వర్డ్", "సంకేత వచనం", "ఓటీపీ", "ఒటిపి", "పిన్ నంబర్",
    # Malayalam
    "പാസ്‌വേഡ്", "പാസ്വേഡ്", "രഹസ്യവാക്ക്", "ഒടിപി", "ഒറ്റത്തവണ പാസ്‌വേഡ്", "പിൻ നമ്പർ",
)

_SENSITIVE_PATTERNS = (
    re.compile(rf"(?i)(?<![a-z0-9])(?:{_AUTHENTICATION_TERMS})(?![a-z0-9])"),
    re.compile(
        r"(?i)(?<![a-z0-9])(?:bank|credit[\s_-]+card|debit[\s_-]+card|"
        r"medical|diagnosis|salary|account[\s_-]+number|routing[\s_-]+number|"
        r"social[\s_-]+security[\s_-]+number|ssn|national[\s_-]+id|"
        r"passport|aadhaar)(?![a-z0-9])"
    ),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?<!\d)(?:\+?\d[\d ()-]{8,}\d)(?!\d)"),
    *_AUTHENTICATION_FORMATS,
)

_MULTILINGUAL_SENSITIVE_TERMS = (
    *_MULTILINGUAL_AUTHENTICATION_TERMS,
    # Bengali
    "ব্যাংক",
    "ব্যাঙ্ক", "ক্রেডিট কার্ড", "ডেবিট কার্ড", "চিকিৎসা", "রোগ নির্ণয়",
    "বেতন", "জাতীয় পরিচয়পত্র", "আধার", "পাসপোর্ট",
    # Hindi
    "बैंक", "क्रेडिट कार्ड",
    "डेबिट कार्ड", "चिकित्सा", "निदान", "वेतन", "आधार", "पहचान पत्र",
    "पासपोर्ट",
    # Tamil
    "வங்கி", "கிரெடிட் கார்டு", "கடன் அட்டை", "டெபிட் கார்டு",
    "மருத்துவம்", "நோயறிதல்", "சம்பளம்", "ஆதார்", "கடவுச்சீட்டு",
    # Telugu
    "బ్యాంకు", "బ్యాంక్", "క్రెడిట్ కార్డు", "డెబిట్ కార్డు", "వైద్యం",
    "వ్యాధి", "జీతం", "ఆధార్", "పాస్‌పోర్ట్",
    # Malayalam
    "ബാങ്ക്", "ക്രെഡിറ്റ് കാർഡ്", "ഡെബിറ്റ് കാർഡ്", "ചികിത്സ",
    "രോഗനിർണയം", "ശമ്പളം", "വേതനം", "ആധാർ", "പാസ്പോർട്ട്",
)


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Cf"
    )


def _term_alternatives(terms: tuple[str, ...]) -> str:
    return "|".join(
        re.escape(_normalize_text(term))
        for term in sorted(terms, key=len, reverse=True)
    )


_MULTILINGUAL_TERM_PATTERN = re.compile(_term_alternatives(_MULTILINGUAL_SENSITIVE_TERMS))
_MULTILINGUAL_AUTHENTICATION_ASSIGNMENT = re.compile(
    rf"(?:{_term_alternatives(_MULTILINGUAL_AUTHENTICATION_TERMS)})"
    r"['\"]?\s*(?:[:=]|(?:হলো|হল|হচ্ছে|হয়|হয়|है|என்பது|అనేది|ആണ്)(?!\w))"
)


def contains_authentication_secret(text: str) -> bool:
    """Detect likely assigned credentials or structured authentication values."""
    normalized = _normalize_text(text)
    return bool(
        _AUTHENTICATION_ASSIGNMENT.search(normalized.replace("_", " "))
        or _MULTILINGUAL_AUTHENTICATION_ASSIGNMENT.search(normalized)
        or any(pattern.search(normalized) for pattern in _AUTHENTICATION_FORMATS)
    )


def is_sensitive_text(text: str) -> bool:
    """Flag likely credential, finance, health or contact data in six languages."""
    if not isinstance(text, str) or not text:
        return False
    normalized = _normalize_text(text)
    return bool(
        _MULTILINGUAL_TERM_PATTERN.search(normalized)
        or any(pattern.search(normalized) for pattern in _SENSITIVE_PATTERNS)
    )
