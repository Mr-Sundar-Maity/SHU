import logging

from app import logging_config
from app.config import Settings


def test_file_logging_redacts_secrets_and_rotates_with_a_fixed_backup_limit(
    tmp_path, monkeypatch
):
    logger = logging.getLogger("shu")
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate
    for handler in original_handlers:
        logger.removeHandler(handler)

    original_factory = logging_config.RotatingFileHandler
    configured = {}

    def small_rotating_handler(*args, **kwargs):
        configured["maxBytes"] = kwargs["maxBytes"]
        configured["backupCount"] = kwargs["backupCount"]
        kwargs["maxBytes"] = 180
        return original_factory(*args, **kwargs)

    monkeypatch.setattr(
        logging_config, "RotatingFileHandler", small_rotating_handler
    )
    settings = Settings.from_env({"SHU_DATA_DIR": str(tmp_path / "shu-data")})
    try:
        logging_config.setup_logging(settings)
        file_handler = next(
            handler
            for handler in logger.handlers
            if isinstance(handler, original_factory)
        )
        console_handlers = [
            handler
            for handler in logger.handlers
            if handler is not file_handler
        ]
        for handler in console_handlers:
            logger.removeHandler(handler)
            handler.close()

        for index in range(30):
            logger.info(
                "entry=%d api_key=private-token-%d %s",
                index,
                index,
                "x" * 100,
            )
        file_handler.flush()

        log_files = list(settings.log_dir.glob("shu.log*"))
        contents = b"".join(path.read_bytes() for path in log_files)
        assert configured == {"maxBytes": 2_000_000, "backupCount": 5}
        assert len(log_files) == 6
        assert not (settings.log_dir / "shu.log.6").exists()
        assert b"private-token" not in contents
        assert b"[REDACTED]" in contents
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        for handler in original_handlers:
            logger.addHandler(handler)
        logger.setLevel(original_level)
        logger.propagate = original_propagate
