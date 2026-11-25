"""Redacted, rotating file logging for SHU."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from app.config import Settings, get_settings


_SECRET_RE = re.compile(
    r"(?i)(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = "<unprintable log record>"
        record.msg = _SECRET_RE.sub(r"\1\2[REDACTED]", message)
        record.args = ()
        return True


def setup_logging(settings: Settings | None = None) -> logging.Logger:
    settings = settings or get_settings()
    settings.ensure_data_dirs()
    logger = logging.getLogger("shu")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        settings.log_dir / "shu.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(SecretRedactionFilter())
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SecretRedactionFilter())
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger
