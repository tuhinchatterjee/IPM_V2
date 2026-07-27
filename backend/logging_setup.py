"""
Application logging setup.

Call `init_logging()` once at process start (top of app.py / serve.py). Configures
the root logger with a rotating file handler (so logs never grow unbounded on the
host) plus a console handler for interactive runs. Modules obtain their own logger
with the standard `logging.getLogger(__name__)` and inherit this configuration.
"""

import logging
from logging.handlers import RotatingFileHandler

from backend.config import settings

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
_BACKUP_COUNT = 5

_initialized = False


def init_logging(level: int | None = None) -> None:
    """Idempotent: safe to call more than once (e.g. app import + serve entrypoint)."""
    global _initialized
    if _initialized:
        return

    if level is None:
        level = logging.INFO if settings.is_prod else logging.DEBUG

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = RotatingFileHandler(
        settings.log_dir / "ipm.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # Werkzeug's per-request access logs are noisy at DEBUG; keep them at WARNING.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    _initialized = True
    logging.getLogger(__name__).info(
        "Logging initialized (env=%s, level=%s, dir=%s)",
        settings.env, logging.getLevelName(level), settings.log_dir,
    )
