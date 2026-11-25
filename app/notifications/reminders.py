"""Persistent reminders with APScheduler and injectable notification sinks."""

from __future__ import annotations

import sqlite3
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from database.database import Database


Notifier = Callable[[str, str, bool], str | None]

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_CLOCK = re.compile(
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>a\.?m\.?|p\.?m\.?)?",
    re.IGNORECASE,
)
_DAYPARTS = {"morning": "am", "afternoon": "pm", "evening": "pm", "night": "pm"}
_CALENDAR_SCHEDULE_FIRST = re.compile(
    r"^(?P<schedule>(?:every\s+day|daily|every\s+week(?:\s+on\s+"
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"(?:\s+(?:morning|afternoon|evening|night))?)?|weekly|"
    r"tomorrow(?:\s+(?:morning|afternoon|evening|night))?|"
    r"today(?:\s+(?:morning|afternoon|evening|night))?|"
    r"on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"(?:\s+(?:morning|afternoon|evening|night))?|at)"
    r"\s+(?:at\s+)?(?:\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?|"
    r"noon|midday|midnight)"
    r"(?:\s+(?:in\s+the\s+)?(?:morning|afternoon|evening|night))?)"
    r"\s+(?:(?P<explicit_to>to)\s+)?(?P<text>.+)$",
    re.IGNORECASE,
)
_RELATIVE = re.compile(
    r"^(?P<text>.+?)\s+in\s+(?P<amount>\d{1,4})\s*"
    r"(?P<unit>minutes?|mins?|hours?|hrs?|days?)$",
    re.IGNORECASE,
)
_ENGLISH_SMALL_NUMBERS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
    "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
)
_ENGLISH_TENS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_ENGLISH_NUMBER_WORD = (
    rf"(?:{'|'.join(_ENGLISH_SMALL_NUMBERS)}|"
    rf"(?:{'|'.join(_ENGLISH_TENS)})(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?)"
)
_ENGLISH_RELATIVE_AMOUNT = rf"(?:\d{{1,4}}|{_ENGLISH_NUMBER_WORD}|an?|a\s+couple\s+of|half(?:\s+an?)?)"
_ENGLISH_RELATIVE_UNIT = r"(?:minutes?|mins?|hours?|hrs?|days?)"
_ENGLISH_RELATIVE_PATTERNS = (
    re.compile(
        rf"^(?P<text>.+?)\s+(?:in|after)\s+(?P<amount>{_ENGLISH_RELATIVE_AMOUNT})\s+"
        rf"(?P<unit>{_ENGLISH_RELATIVE_UNIT})$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:in|after)\s+(?P<amount>{_ENGLISH_RELATIVE_AMOUNT})\s+"
        rf"(?P<unit>{_ENGLISH_RELATIVE_UNIT})\s+(?:to\s+)?(?P<text>.+)$",
        re.IGNORECASE,
    ),
)
_LOCALIZED_REMINDER_PREFIXES = (
    (r"^(?:দয়া করে\s+)?(?:আমাকে\s+)?মনে করিয়ে দাও\s+", re.IGNORECASE),
    (r"^(?:कृपया\s+)?मुझे\s+याद दिलाओ\s+", re.IGNORECASE),
    (r"^(?:தயவு செய்து\s+)?எனக்கு\s+நினைவூட்டு\s+", re.IGNORECASE),
    (r"^(?:దయచేసి\s+)?నాకు\s+గుర్తు చేయి\s+", re.IGNORECASE),
    (r"^(?:ദയവായി\s+)?എന്നെ\s+ഓർമ്മിപ്പിക്കൂ\s+", re.IGNORECASE),
)
_LOCALIZED_REMINDER_SUFFIXES = (
    re.compile(r"(?:\u0986\u09ae\u09be\u0995\u09c7\s+)?\u09ae\u09a8\u09c7 \u0995\u09b0(?:\u09bf\u09af\u09bc\u09c7|\u09bf\u09df\u09c7) \u09a6\u09be\u0993$", re.IGNORECASE),
    re.compile(r"(?:\u092e\u0941\u091d\u0947\s+)?\u092f\u093e\u0926 \u0926\u093f\u0932(?:\u093e\u0913|\u093e\u0928\u093e)$", re.IGNORECASE),
    re.compile(r"(?:\u0b8e\u0ba9\u0b95\u0bcd\u0b95\u0bc1\s+)?\u0ba8\u0bbf\u0ba9\u0bc8\u0bb5\u0bc2\u0b9f\u0bcd\u0b9f\u0bc1(?:\u0b99\u0bcd\u0b95\u0bb3\u0bcd)?$", re.IGNORECASE),
    re.compile(r"(?:\u0c28\u0c3e\u0c15\u0c41\s+)?\u0c17\u0c41\u0c30\u0c4d\u0c24\u0c41 \u0c1a\u0c47\u0c2f(?:\u0c3f|\u0c02\u0c21\u0c3f)$", re.IGNORECASE),
    re.compile(r"(?:\u0d0e\u0d28\u0d4d\u0d28\u0d46\s+)?\u0d13\u0d7c\u0d2e\u0d4d\u0d2e\u0d3f\u0d2a\u0d4d\u0d2a\u0d3f\u0d15\u0d4d\u0d15(?:\u0d42|\u0d41\u0d15)$", re.IGNORECASE),
)

_LOCALIZED_UNITS = {
    # Bengali
    "মিনিট": 60, "মিনিটে": 60, "ঘণ্টা": 3600, "ঘন্টা": 3600, "দিন": 86400,
    # Hindi
    "मिनट": 60, "मिनटों": 60, "घंटा": 3600, "घंटे": 3600, "दिन": 86400,
    # Tamil
    "நிமிடம்": 60, "நிமிடங்கள்": 60, "மணி": 3600, "மணிநேரம்": 3600,
    "நாள்": 86400, "நாட்கள்": 86400,
    # Telugu
    "నిమిషం": 60, "నిమిషాలు": 60, "నిమిషాల": 60, "గంట": 3600, "గంటలు": 3600,
    "రోజు": 86400, "రోజులు": 86400,
    # Malayalam
    "മിനിറ്റ്": 60, "മിനിറ്റുകൾ": 60, "മണിക്കൂർ": 3600,
    "മണിക്കൂറുകൾ": 3600, "ദിവസം": 86400, "ദിവസങ്ങൾ": 86400,
}
_LOCALIZED_AFTER_WORDS = (
    "পরে", "পর", "बाद", "के बाद", "பிறகு", "கழித்து", "తర్వాత", "తరువాత",
    "తర్వాతలో", "കഴിഞ്ഞ്", "ശേഷം",
)
_LOCALIZED_CALENDAR_WORDS = {
    "bengali": {
        "today": ("আজ",),
        "tomorrow": ("আগামীকাল",),
        "daily": ("প্রতিদিন", "রোজ"),
        "weekly": ("প্রতি সপ্তাহে",),
        "weekdays": {
            "monday": ("সোমবার",), "tuesday": ("মঙ্গলবার",),
            "wednesday": ("বুধবার",), "thursday": ("বৃহস্পতিবার",),
            "friday": ("শুক্রবার",), "saturday": ("শনিবার",),
            "sunday": ("রবিবার",),
        },
        "periods": {
            "সকাল": "AM", "সকালে": "AM", "সকালের": "AM",
            "দুপুর": "PM", "দুপুরে": "PM", "বিকাল": "PM", "বিকেল": "PM",
            "বিকেলে": "PM", "সন্ধ্যা": "PM", "সন্ধ্যায়": "PM",
            "রাত": "PM", "রাতে": "PM",
        },
        "clock_suffixes": ("টায়", "টায়", "টা", "টার", "বাজে"),
    },
    "hindi": {
        "today": ("आज",),
        "tomorrow": ("कल",),
        "daily": ("हर दिन", "रोज़", "रोज"),
        "weekly": ("हर सप्ताह", "हर हफ़्ते", "प्रति सप्ताह"),
        "weekdays": {
            "monday": ("सोमवार",), "tuesday": ("मंगलवार",),
            "wednesday": ("बुधवार",), "thursday": ("गुरुवार", "बृहस्पतिवार"),
            "friday": ("शुक्रवार",), "saturday": ("शनिवार",),
            "sunday": ("रविवार",),
        },
        "periods": {
            "सुबह": "AM", "प्रातः": "AM", "दोपहर": "PM",
            "शाम": "PM", "रात": "PM",
        },
        "clock_suffixes": ("बजे",),
    },
    "tamil": {
        "today": ("இன்று",),
        "tomorrow": ("நாளை",),
        "daily": ("தினமும்", "ஒவ்வொரு நாளும்"),
        "weekly": ("வாரந்தோறும்", "ஒவ்வொரு வாரமும்"),
        "weekdays": {
            "monday": ("திங்கட்கிழமை", "திங்கள்"),
            "tuesday": ("செவ்வாய்க்கிழமை", "செவ்வாய்"),
            "wednesday": ("புதன்கிழமை", "புதன்"),
            "thursday": ("வியாழக்கிழமை", "வியாழன்"),
            "friday": ("வெள்ளிக்கிழமை", "வெள்ளி"),
            "saturday": ("சனிக்கிழமை", "சனி"),
            "sunday": ("ஞாயிற்றுக்கிழமை", "ஞாயிறு"),
        },
        "periods": {
            "காலை": "AM", "மதியம்": "PM", "பிற்பகல்": "PM",
            "மாலை": "PM", "இரவு": "PM",
        },
        "clock_suffixes": ("மணிக்கு", "மணி"),
    },
    "telugu": {
        "today": ("ఈరోజు", "ఈ రోజు"),
        "tomorrow": ("రేపు",),
        "daily": ("ప్రతిరోజూ", "ప్రతి రోజు"),
        "weekly": ("ప్రతి వారం", "వారానికొకసారి"),
        "weekdays": {
            "monday": ("సోమవారం",), "tuesday": ("మంగళవారం",),
            "wednesday": ("బుధవారం",), "thursday": ("గురువారం",),
            "friday": ("శుక్రవారం",), "saturday": ("శనివారం",),
            "sunday": ("ఆదివారం",),
        },
        "periods": {
            "ఉదయం": "AM", "ప్రాతఃకాలం": "AM", "మధ్యాహ్నం": "PM",
            "సాయంత్రం": "PM", "రాత్రి": "PM",
        },
        "clock_suffixes": ("గంటలకు", "గంటకి"),
    },
    "malayalam": {
        "today": ("ഇന്ന്",),
        "tomorrow": ("നാളെ",),
        "daily": ("ദിവസവും", "എല്ലാ ദിവസവും"),
        "weekly": ("എല്ലാ ആഴ്ചയും", "ആഴ്ചതോറും"),
        "weekdays": {
            "monday": ("തിങ്കളാഴ്ച",), "tuesday": ("ചൊവ്വാഴ്ച",),
            "wednesday": ("ബുധനാഴ്ച",), "thursday": ("വ്യാഴാഴ്ച",),
            "friday": ("വെള്ളിയാഴ്ച",), "saturday": ("ശനിയാഴ്ച",),
            "sunday": ("ഞായറാഴ്ച",),
        },
        "periods": {
            "രാവിലെ": "AM", "രാവിൽ": "AM", "ഉച്ചയ്ക്ക്": "PM",
            "ഉച്ച": "PM", "വൈകുന്നേരം": "PM", "രാത്രി": "PM",
        },
        "clock_suffixes": ("മണിക്ക്", "മണി"),
    },
}
_ALL_LOCALIZED_PERIODS = {
    phrase: meridiem
    for language in _LOCALIZED_CALENDAR_WORDS.values()
    for phrase, meridiem in language["periods"].items()
}
_ALL_LOCALIZED_CLOCK_SUFFIXES = tuple(
    sorted(
        {
            suffix
            for language in _LOCALIZED_CALENDAR_WORDS.values()
            for suffix in language["clock_suffixes"]
        },
        key=len,
        reverse=True,
    )
)
_LOCALIZED_WEEKDAY_AFFIXES = {
    "bengali": ("প্রতি ", ""),
    "hindi": ("हर ", ""),
    "tamil": ("ஒவ்வொரு ", "யும்"),
    "telugu": ("ప్రతి ", ""),
    "malayalam": ("എല്ലാ ", "യും"),
}
_ALL_LOCALIZED_PERIOD_PATTERN = "|".join(
    re.escape(value)
    for value in sorted(_ALL_LOCALIZED_PERIODS, key=len, reverse=True)
)
_ALL_LOCALIZED_CLOCK_SUFFIX_PATTERN = "|".join(
    re.escape(value) for value in _ALL_LOCALIZED_CLOCK_SUFFIXES
)


def _replace_localized_token(phrase: str, token: str, replacement: str) -> tuple[str, bool]:
    pattern = rf"(?<!\w){re.escape(token)}(?!\w)"
    updated, count = re.subn(pattern, replacement, phrase, flags=re.IGNORECASE)
    return updated, count > 0


def _canonicalize_localized_schedule(phrase: str) -> str:
    result = phrase
    for language_name, words in _LOCALIZED_CALENDAR_WORDS.items():
        for weekday, variants in words["weekdays"].items():
            prefix, suffix = _LOCALIZED_WEEKDAY_AFFIXES[language_name]
            for token in sorted(variants, key=len, reverse=True):
                recurring = rf"(?<!\w){re.escape(prefix + token + suffix)}(?!\w)"
                result, recurring_count = re.subn(
                    recurring,
                    "every week on " + weekday,
                    result,
                    count=1,
                    flags=re.IGNORECASE,
                )
                if recurring_count:
                    break
            for token in sorted(variants, key=len, reverse=True):
                result, matched = _replace_localized_token(
                    result, token, "on " + weekday
                )
                if matched:
                    break
        for kind in ("today", "tomorrow", "daily", "weekly"):
            replacement = {
                "today": "today",
                "tomorrow": "tomorrow",
                "daily": "every day",
                "weekly": "every week",
            }[kind]
            for token in sorted(words[kind], key=len, reverse=True):
                result, matched = _replace_localized_token(result, token, replacement)
                if matched:
                    break

    clock_pattern = r"(?P<clock>\d{1,2}(?::\d{2})?)"
    suffix_pattern = rf"(?:{_ALL_LOCALIZED_CLOCK_SUFFIX_PATTERN})?"
    before_period = re.compile(
        rf"(?P<period>{_ALL_LOCALIZED_PERIOD_PATTERN})\s*{clock_pattern}\s*{suffix_pattern}",
        re.IGNORECASE,
    )
    after_period = re.compile(
        rf"{clock_pattern}\s*{suffix_pattern}\s*(?P<period>{_ALL_LOCALIZED_PERIOD_PATTERN})",
        re.IGNORECASE,
    )

    def period_replacement(match: re.Match[str]) -> str:
        clock = match.group("clock")
        period = match.group("period")
        meridiem = _ALL_LOCALIZED_PERIODS[period]
        return f"at {clock} {meridiem}"

    result = before_period.sub(period_replacement, result)
    result = after_period.sub(period_replacement, result)
    if _ALL_LOCALIZED_CLOCK_SUFFIX_PATTERN:
        result = re.sub(
            rf"(?P<clock>\d{{1,2}}(?::\d{{2}})?)\s*(?:{_ALL_LOCALIZED_CLOCK_SUFFIX_PATTERN})",
            r"at \g<clock>",
            result,
            flags=re.IGNORECASE,
        )
    return result

_LOCALIZED_UNIT_PATTERN = "|".join(
    re.escape(unit) for unit in sorted(_LOCALIZED_UNITS, key=len, reverse=True)
)
_LOCALIZED_AFTER_PATTERN = "|".join(
    re.escape(word) for word in sorted(_LOCALIZED_AFTER_WORDS, key=len, reverse=True)
)
_LOCALIZED_RELATIVE_PATTERNS = (
    re.compile(
        rf"^\s*(?P<amount>\d{{1,4}})\s*(?P<unit>{_LOCALIZED_UNIT_PATTERN})\s*"
        rf"(?:{_LOCALIZED_AFTER_PATTERN})\s+(?P<text>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^\s*(?P<text>.+?)\s+(?P<amount>\d{{1,4}})\s*"
        rf"(?P<unit>{_LOCALIZED_UNIT_PATTERN})\s*(?:{_LOCALIZED_AFTER_PATTERN})\s*$",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class ParsedReminder:
    text: str
    due_at: datetime
    recurrence: str | None = None


def _strip_reminder_prefix(phrase: str) -> str:
    phrase = re.sub(r"^(?:please\s+)?remind\s+me\s+to\s+", "", phrase, flags=re.I)
    phrase = re.sub(r"^(?:please\s+)?remind\s+me\s+", "", phrase, flags=re.I)
    for prefix, flags in _LOCALIZED_REMINDER_PREFIXES:
        phrase = re.sub(prefix, "", phrase, flags=flags)
    return phrase.strip()


def _english_relative_duration(amount_text: str, unit_text: str) -> timedelta:
    amount_text = re.sub(r"\s+", " ", amount_text.casefold().replace("-", " ")).strip()
    unit = unit_text.casefold()
    if amount_text.isdecimal():
        amount = int(amount_text)
    elif amount_text in {"a", "an"}:
        amount = 1
    elif amount_text == "a couple of":
        amount = 2
    elif amount_text.startswith("half"):
        if not unit.startswith(("hour", "hr")):
            raise ValueError("Half-hour reminders must use an hour unit")
        return timedelta(minutes=30)
    else:
        words = amount_text.split()
        numbers = {word: index for index, word in enumerate(_ENGLISH_SMALL_NUMBERS)}
        numbers.update({word: (index + 2) * 10 for index, word in enumerate(_ENGLISH_TENS)})
        if len(words) == 1 and words[0] in numbers:
            amount = numbers[words[0]]
        elif (
            len(words) == 2
            and words[0] in _ENGLISH_TENS
            and words[1] in numbers
            and 1 <= numbers[words[1]] <= 9
        ):
            amount = numbers[words[0]] + numbers[words[1]]
        else:
            raise ValueError("Could not read the relative reminder amount")

    if amount < 1:
        raise ValueError("Relative reminder time must be at least one unit")
    if unit.startswith("min"):
        return timedelta(minutes=amount)
    if unit.startswith(("hour", "hr")):
        return timedelta(hours=amount)
    return timedelta(days=amount)


def parse_natural_reminder(
    request: str,
    *,
    now: datetime | None = None,
    timezone_name: str = "Asia/Kolkata",
) -> ParsedReminder:
    """Parse bounded English and localized relative-time reminder phrases."""
    if not isinstance(request, str) or not request.strip():
        raise ValueError("Enter a reminder and a time, such as 'Remind me to stretch in 20 minutes'")
    zone = ReminderService._zone(timezone_name)
    current = now or datetime.now(zone)
    if current.tzinfo is None:
        current = current.replace(tzinfo=zone)
    else:
        current = current.astimezone(zone)
    current_utc = current.astimezone(timezone.utc)

    phrase = request.strip().rstrip(".!?। ")
    phrase = re.sub(r"^(?:please\s+)?remind\s+me\s+to\s+", "", phrase, flags=re.I)
    phrase = re.sub(r"^(?:please\s+)?remind\s+me\s+", "", phrase, flags=re.I)
    for prefix, flags in _LOCALIZED_REMINDER_PREFIXES:
        phrase = re.sub(prefix, "", phrase, flags=flags)

    for localized in _LOCALIZED_RELATIVE_PATTERNS:
        localized_match = localized.fullmatch(phrase)
        if not localized_match:
            continue
        amount = int(localized_match.group("amount"))
        if amount < 1:
            raise ValueError("Relative reminder time must be at least one unit")
        unit = localized_match.group("unit").casefold()
        delta = timedelta(seconds=amount * _LOCALIZED_UNITS[unit])
        if delta > timedelta(days=365):
            raise ValueError("Reminder time cannot be more than one year away")
        text = localized_match.group("text").strip(" \t,،:؛")
        if not text:
            raise ValueError("Reminder text cannot be empty")
        return ParsedReminder(text, (current_utc + delta).astimezone(zone))

    relative = _RELATIVE.fullmatch(phrase)
    if relative:
        amount = int(relative.group("amount"))
        if amount < 1:
            raise ValueError("Relative reminder time must be at least one minute")
        unit = relative.group("unit").lower()
        delta = (
            timedelta(minutes=amount) if unit.startswith(("min",))
            else timedelta(hours=amount) if unit.startswith(("hour", "hr"))
            else timedelta(days=amount)
        )
        if delta > timedelta(days=365):
            raise ValueError("Reminder time cannot be more than one year away")
        return ParsedReminder(
            relative.group("text").strip(), (current_utc + delta).astimezone(zone)
        )

    for relative_pattern in _ENGLISH_RELATIVE_PATTERNS:
        relative = relative_pattern.fullmatch(phrase)
        if not relative:
            continue
        delta = _english_relative_duration(
            relative.group("amount"), relative.group("unit")
        )
        if delta > timedelta(days=365):
            raise ValueError("Reminder time cannot be more than one year away")
        text = _strip_reminder_prefix(relative.group("text")).strip(" \t,")
        if not text:
            raise ValueError("Reminder text cannot be empty")
        return ParsedReminder(text, (current_utc + delta).astimezone(zone))

    phrase = _canonicalize_localized_schedule(phrase)
    schedule_first = _CALENDAR_SCHEDULE_FIRST.fullmatch(phrase)
    if schedule_first:
        reminder_text = schedule_first.group("text").strip(" \t,")
        has_explicit_to = schedule_first.group("explicit_to") is not None
        if not has_explicit_to:
            for suffix in _LOCALIZED_REMINDER_SUFFIXES:
                reminder_text, suffix_count = suffix.subn(
                    "", reminder_text, count=1
                )
                if suffix_count:
                    reminder_text = reminder_text.strip(" \t,")
                    break
            else:
                schedule_first = None
        if schedule_first and not reminder_text:
            raise ValueError("Reminder text cannot be empty")
    if schedule_first:
        schedule = re.sub(r"\s+", " ", schedule_first.group("schedule")).strip()
        # An explicit English "to <task>" or a known localized reminder suffix
        # separates the schedule from its task before using the shared parser.
        phrase = f"{reminder_text} {schedule}"

    recurrence: str | None = None
    weekday: int | None = None
    schedule_match = re.search(
        r"\s+(?P<schedule>every\s+day|daily|every\s+week(?:\s+on\s+\w+(?:\s+(?:morning|afternoon|evening|night))?)?|weekly|"
        r"tomorrow(?:\s+(?:morning|afternoon|evening|night))?|"
        r"today(?:\s+(?:morning|afternoon|evening|night))?|"
        r"on\s+\w+(?:\s+(?:morning|afternoon|evening|night))?|at)"
        r"\s+(?:at\s+)?(?P<clock>\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?|noon|midday|midnight)"
        r"(?:\s+(?:in\s+the\s+)?(?P<clock_daypart>morning|afternoon|evening|night))?$",
        phrase,
        flags=re.I,
    )
    if not schedule_match:
        raise ValueError(
            "Time is unclear. Use 'in 20 minutes', 'tomorrow at 9 AM', "
            "'tomorrow morning at 9', 'today at 17:30', 'at noon', "
            "'daily at 9 AM' or 'every week on Monday at 9 AM'."
        )

    text = phrase[: schedule_match.start()].strip()
    if not text or re.fullmatch(
        r"(?:every\s+day|daily|every\s+week(?:\s+on\s+\w+)?|weekly|today|tomorrow|"
        r"on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))",
        text,
        flags=re.I,
    ):
        raise ValueError("Reminder text cannot be empty")
    schedule = re.sub(r"\s+", " ", schedule_match.group("schedule").lower()).strip()
    schedule_daypart = next(
        (part for part in _DAYPARTS if re.search(rf"\b{part}\b", schedule)),
        None,
    )
    clock_daypart = schedule_match.group("clock_daypart")
    if clock_daypart:
        clock_daypart = clock_daypart.lower()
    if schedule_daypart and clock_daypart and schedule_daypart != clock_daypart:
        raise ValueError("Reminder time has conflicting dayparts")
    daypart = schedule_daypart or clock_daypart
    schedule = re.sub(
        r"\s+(?:morning|afternoon|evening|night)$", "", schedule
    ).strip()

    clock_text = schedule_match.group("clock").strip().lower()
    if clock_text in {"noon", "midday"}:
        hour, minute, meridiem = 12, 0, "pm"
    elif clock_text == "midnight":
        hour, minute, meridiem = 12, 0, "am"
    else:
        clock_match = _CLOCK.fullmatch(clock_text)
        if not clock_match:
            raise ValueError("Could not read the reminder time")
        hour = int(clock_match.group("hour"))
        minute = int(clock_match.group("minute") or 0)
        meridiem = (clock_match.group("meridiem") or "").replace(".", "").lower()
    if minute > 59 or (meridiem and not 1 <= hour <= 12) or (not meridiem and hour > 23):
        raise ValueError("Reminder clock time is out of range")
    if daypart:
        expected_meridiem = _DAYPARTS[daypart]
        if meridiem and meridiem != expected_meridiem:
            raise ValueError("Reminder clock conflicts with its daypart")
        if not meridiem:
            if hour == 0 and expected_meridiem == "pm":
                raise ValueError("Daypart requires a valid 12-hour clock")
            if hour <= 12:
                hour = hour % 12 + (12 if expected_meridiem == "pm" else 0)
            elif (hour >= 12) != (expected_meridiem == "pm"):
                raise ValueError("Reminder clock conflicts with its daypart")
        meridiem = expected_meridiem
    if meridiem:
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    due_time = time(hour, minute, tzinfo=zone)

    if schedule in {"every day", "daily"}:
        recurrence = "daily"
        due = datetime.combine(current.date(), due_time)
        if due.astimezone(timezone.utc) <= current_utc:
            due += timedelta(days=1)
    elif schedule.startswith("every week") or schedule == "weekly":
        recurrence = "weekly"
        weekday_match = re.search(r"\bon\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", schedule)
        weekday = _WEEKDAYS[weekday_match.group(1)] if weekday_match else current.weekday()
        due = _next_weekday(current, weekday, due_time)
    elif schedule.startswith("on "):
        weekday_name = schedule.split(maxsplit=1)[1]
        if weekday_name not in _WEEKDAYS:
            raise ValueError("Use a weekday name after 'on'")
        recurrence = "weekly"
        due = _next_weekday(current, _WEEKDAYS[weekday_name], due_time)
    elif schedule == "tomorrow":
        due = datetime.combine(current.date() + timedelta(days=1), due_time)
    elif schedule == "today":
        due = datetime.combine(current.date(), due_time)
        if due.astimezone(timezone.utc) <= current_utc:
            raise ValueError("That time has already passed today")
    else:  # at <clock>: choose the next occurrence, never silently schedule in the past.
        due = datetime.combine(current.date(), due_time)
        if due.astimezone(timezone.utc) <= current_utc:
            due += timedelta(days=1)

    _validate_local_time(due)
    return ParsedReminder(text, due, recurrence)


def _validate_local_time(value: datetime) -> None:
    # A wall time in a daylight-saving gap changes when round-tripped via UTC.
    round_tripped = value.astimezone(timezone.utc).astimezone(value.tzinfo)
    if round_tripped.replace(tzinfo=None) != value.replace(tzinfo=None):
        raise ValueError("That local time does not exist because the clock changes. Choose a different time.")


def _next_weekday(current: datetime, weekday: int, due_time: time) -> datetime:
    days_ahead = (weekday - current.weekday()) % 7
    due = datetime.combine(current.date() + timedelta(days=days_ahead), due_time)
    if due.astimezone(timezone.utc) <= current.astimezone(timezone.utc):
        due += timedelta(days=7)
    return due


class ReminderService:
    """Schedule reminders while SHU is running and record each delivery."""

    def __init__(
        self,
        database: Database,
        *,
        notifier: Notifier | None = None,
        quiet_mode: Callable[[], bool] | None = None,
    ) -> None:
        self.database = database
        self.notifier = notifier or self._console_notice
        self.quiet_mode = quiet_mode or (lambda: False)
        self.scheduler = BackgroundScheduler(timezone="UTC")

    @staticmethod
    def _console_notice(reminder_id: str, text: str, allow_speech: bool) -> str:
        print(f"SHU REMINDER [{reminder_id}]: {text}")
        if not allow_speech:
            print("SHU: quiet mode is on; reminder was not spoken.")
        return "displayed"

    def create(
        self,
        text: str,
        due_at: str | datetime,
        *,
        timezone_name: str = "Asia/Kolkata",
        recurrence: str | None = None,
        source: str = "user",
    ) -> str:
        if not text or not text.strip():
            raise ValueError("Reminder text cannot be empty")
        zone = self._zone(timezone_name)
        due = self._parse_due(due_at, zone)
        recurrence_value = recurrence.lower() if recurrence else None
        if recurrence_value not in {None, "daily", "weekly"}:
            raise ValueError("recurrence must be daily, weekly or None")
        reminder_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.database.connect() as connection:
            with connection:
                connection.execute(
                    """INSERT INTO reminders
                    (reminder_id,text,due_at,timezone,recurrence,status,created_at,source)
                    VALUES(?,?,?,?,?,'pending',?,?)""",
                    (
                        reminder_id,
                        text.strip(),
                        due.astimezone(timezone.utc).isoformat(timespec="seconds"),
                        timezone_name,
                        recurrence_value,
                        now,
                        source,
                    ),
                )
        if self.scheduler.running:
            self._schedule(reminder_id)
        return reminder_id

    def create_from_text(
        self,
        request: str,
        *,
        timezone_name: str = "Asia/Kolkata",
        now: datetime | None = None,
    ) -> tuple[str, ParsedReminder]:
        """Parse a supported phrase, persist it, and return its preview details."""
        parsed = parse_natural_reminder(
            request,
            now=now,
            timezone_name=timezone_name,
        )
        reminder_id = self.create(
            parsed.text,
            parsed.due_at,
            timezone_name=timezone_name,
            recurrence=parsed.recurrence,
            source="natural_language",
        )
        return reminder_id, parsed

    def start(self) -> list[sqlite3.Row]:
        if not self.scheduler.running:
            self.scheduler.start()
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reminders WHERE status='pending' ORDER BY due_at"
            ).fetchall()
        now = datetime.now(timezone.utc)
        overdue = []
        for row in rows:
            due = datetime.fromisoformat(row["due_at"])
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if row["recurrence"] in {"daily", "weekly"}:
                # The stored due_at is the first occurrence. After a restart
                # it will usually be in the past; the cron trigger still knows
                # how to schedule the next future occurrence from its time.
                self._schedule(row["reminder_id"])
            elif due <= now:
                overdue.append(row)
            else:
                self._schedule(row["reminder_id"])
        return overdue

    def confirm_overdue(self, reminder_id: str, *, still_relevant: bool) -> None:
        """Resume or dismiss an overdue item after an explicit user decision."""
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT status, recurrence FROM reminders WHERE reminder_id=?",
                (reminder_id,),
            ).fetchone()
            if row is None:
                raise KeyError("Reminder not found")
            if row["status"] != "pending":
                raise ValueError("Only pending reminders can be recovered")
            if still_relevant:
                self._schedule(
                    reminder_id,
                    run_now=row["recurrence"] not in {"daily", "weekly"},
                )
            else:
                with connection:
                    connection.execute(
                        "UPDATE reminders SET status='dismissed', result='overdue_dismissed' WHERE reminder_id=?",
                        (reminder_id,),
                    )

    def snooze(self, reminder_id: str, minutes: int = 10) -> None:
        if not 1 <= minutes <= 24 * 60:
            raise ValueError("Snooze must be between 1 minute and 24 hours")
        due = datetime.now(timezone.utc).timestamp() + minutes * 60
        due_at = datetime.fromtimestamp(due, timezone.utc).isoformat(timespec="seconds")
        with self.database.connect() as connection:
            with connection:
                cursor = connection.execute(
                    "UPDATE reminders SET due_at=?, status='pending', result=NULL WHERE reminder_id=?",
                    (due_at, reminder_id),
                )
                if cursor.rowcount == 0:
                    raise KeyError("Reminder not found")
        if self.scheduler.running:
            self._schedule(reminder_id)

    def complete(self, reminder_id: str) -> None:
        self._set_status(reminder_id, "completed")

    def cancel(self, reminder_id: str) -> None:
        self._set_status(reminder_id, "cancelled")

    def list_pending(self) -> list[sqlite3.Row]:
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT * FROM reminders WHERE status='pending' ORDER BY due_at"
            ).fetchall()

    def shutdown(self, *, wait: bool = True) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)

    def _set_status(self, reminder_id: str, status: str) -> None:
        with self.database.connect() as connection:
            with connection:
                cursor = connection.execute(
                    "UPDATE reminders SET status=? WHERE reminder_id=?",
                    (status, reminder_id),
                )
                if cursor.rowcount == 0:
                    raise KeyError("Reminder not found")
        try:
            self.scheduler.remove_job(reminder_id)
        except Exception:
            pass

    def _schedule(self, reminder_id: str, *, run_now: bool = False) -> None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM reminders WHERE reminder_id=? AND status='pending'",
                (reminder_id,),
            ).fetchone()
        if row is None:
            raise KeyError("Pending reminder not found")

        if run_now:
            trigger = DateTrigger(run_date=datetime.now(timezone.utc))
        elif row["recurrence"] in {"daily", "weekly"}:
            zone = self._zone(row["timezone"])
            local_due = datetime.fromisoformat(row["due_at"]).astimezone(zone)
            options = {
                "start_date": local_due,
                "hour": local_due.hour,
                "minute": local_due.minute,
                "second": local_due.second,
                "timezone": zone,
            }
            if row["recurrence"] == "weekly":
                options["day_of_week"] = local_due.weekday()
            trigger = CronTrigger(**options)
        else:
            trigger = DateTrigger(run_date=datetime.fromisoformat(row["due_at"]))

        self.scheduler.add_job(
            self._deliver,
            trigger=trigger,
            args=[reminder_id, row["due_at"]],
            id=reminder_id,
            replace_existing=True,
            misfire_grace_time=24 * 60 * 60,
        )

    def _deliver(self, reminder_id: str, scheduled_due_at: str) -> None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM reminders WHERE reminder_id=? AND status='pending' AND due_at=?",
                (reminder_id, scheduled_due_at),
            ).fetchone()
        if row is None:
            return

        quiet = bool(self.quiet_mode())
        try:
            result = self.notifier(reminder_id, row["text"], not quiet) or "delivered"
            status = "pending" if row["recurrence"] else "delivered"
        except Exception as error:
            result = type(error).__name__
            status = "failed" if not row["recurrence"] else "pending"

        with self.database.connect() as connection:
            with connection:
                connection.execute(
                    """UPDATE reminders SET status=?,last_notified_at=?,result=?
                    WHERE reminder_id=? AND status='pending' AND due_at=?""",
                    (
                        status,
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        result[:200],
                        reminder_id,
                        scheduled_due_at,
                    ),
                )

    @staticmethod
    def _zone(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Unknown timezone: " + name) from error

    @staticmethod
    def _parse_due(value: str | datetime, zone: ZoneInfo) -> datetime:
        try:
            due = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("due_at must be an ISO-8601 date/time") from error
        if due.tzinfo is None:
            due = due.replace(tzinfo=zone)
        _validate_local_time(due)
        return due
