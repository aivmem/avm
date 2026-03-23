"""Logging configuration for the Notification Service."""

import logging
import sys
from datetime import datetime
from typing import Any

from .config import settings


def setup_logger(name: str = "notification_service") -> logging.Logger:
    """Set up and return a configured logger."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.log_level.upper()))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, settings.log_level.upper()))

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


logger = setup_logger()


def log_notification_event(
    event_type: str,
    notification_id: str,
    details: dict[str, Any] | None = None
) -> None:
    """Log a structured notification event."""
    log_data = {
        "event": event_type,
        "notification_id": notification_id,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if details:
        log_data.update(details)

    logger.info(f"[{event_type}] notification_id={notification_id} {details or ''}")


def log_error(
    message: str,
    notification_id: str | None = None,
    error: Exception | None = None
) -> None:
    """Log an error with context."""
    extra = ""
    if notification_id:
        extra += f" notification_id={notification_id}"
    if error:
        extra += f" error={type(error).__name__}: {error}"

    logger.error(f"{message}{extra}")
