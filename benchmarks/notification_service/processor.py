"""Notification processor - consumes messages from Redis queue."""

import asyncio
from typing import Callable, Optional

from .redis_client import queue
from .handlers import get_handler
from .models import (
    NotificationMessage,
    NotificationResult,
    NotificationStatus,
)
from .config import settings
from .logger import logger, log_notification_event, log_error


class NotificationProcessor:
    """Processes notifications from the Redis queue."""

    def __init__(self):
        self._running = False
        self._processed_count = 0
        self._failed_count = 0
        self._on_result: Optional[Callable[[NotificationResult], None]] = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def stats(self) -> dict:
        return {
            "processed": self._processed_count,
            "failed": self._failed_count,
            "running": self._running,
        }

    def set_result_callback(
        self, callback: Callable[[NotificationResult], None]
    ) -> None:
        """Set a callback to be called with each processing result."""
        self._on_result = callback

    def process_one(self, message: NotificationMessage) -> NotificationResult:
        """Process a single notification message."""
        log_notification_event("PROCESSING_START", message.id, {"type": message.type})

        try:
            handler = get_handler(message.type)
            result = handler.handle(message)

            if result.status == NotificationStatus.SENT:
                self._processed_count += 1
            elif result.status == NotificationStatus.FAILED:
                self._handle_failure(message, result)

            if self._on_result:
                self._on_result(result)

            return result

        except Exception as e:
            log_error("Processing error", message.id, e)
            self._failed_count += 1
            result = NotificationResult(
                notification_id=message.id,
                status=NotificationStatus.FAILED,
                error_message=str(e),
            )
            if self._on_result:
                self._on_result(result)
            return result

    def _handle_failure(
        self, message: NotificationMessage, result: NotificationResult
    ) -> None:
        """Handle a failed notification - retry if possible."""
        self._failed_count += 1

        if message.retry_count < message.max_retries:
            log_notification_event(
                "RETRY_SCHEDULED",
                message.id,
                {"attempt": message.retry_count + 1, "max": message.max_retries},
            )
            queue.requeue(message)
        else:
            log_notification_event(
                "MAX_RETRIES_EXCEEDED",
                message.id,
                {"attempts": message.retry_count},
            )

    async def run(self) -> None:
        """Run the processor loop (async)."""
        self._running = True
        logger.info("Notification processor started")

        while self._running:
            message = queue.dequeue()
            if message:
                self.process_one(message)
            else:
                await asyncio.sleep(settings.poll_interval)

        logger.info("Notification processor stopped")

    def stop(self) -> None:
        """Signal the processor to stop."""
        self._running = False
        logger.info("Processor stop requested")


# Global processor instance
processor = NotificationProcessor()
