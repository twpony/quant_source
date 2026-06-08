"""Unified logging configuration with file rotation and microsecond precision."""

import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


class MicrosecondFormatter(logging.Formatter):
    """Custom formatter that supports ``%f`` (microseconds) in datefmt.

    Python's ``logging.Formatter`` delegates to ``time.strftime()``, which
    does **not** support ``%f``.  This subclass overrides ``formatTime()``
    to use ``datetime.strftime()`` instead, enabling microsecond precision.
    """

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat()


def setup_logger(
    name: str = "quant",
    log_dir: Path | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Create and configure a logger with console + rotating file output.

    Args:
        name: Logger name.
        log_dir: Directory for log files (defaults to ./logs).
        level: Logging level.

    Returns:
        Configured logger instance.
    """
    if log_dir is None:
        log_dir = Path.cwd() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    # Formatter with microsecond-precision timestamps
    fmt = MicrosecondFormatter(
        "%(asctime)s | %(levelname)-8s | %(module)-15s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S.%f",
    )

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # File handler with rotation (10 MB, keep 5 backups)
    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger


# Pre-configured application logger
log = setup_logger()
