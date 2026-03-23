"""Service layer for notification operations."""

import uuid
from typing import Optional, List
from datetime import datetime

from .models import (
    NotificationMessage,
    NotificationType,
    NotificationPriority,
    NotificationStatus,
    NotificationResult,
    EmailPayload,
)
from .redis_client import queue
from .processor import processor
from .logger import logger, log_notification_event


class NotificationService:
    """High-level service for managing notifications."""

    def submit_email(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: Optional[dict] = None,
    ) -> Optional[str]:
        """Submit an email notification.

        Returns the notification ID if queued successfully, None otherwise.
        """
        notification_id = str(uuid.uuid4())

        payload = {
            "to": to,
            "subject": subject,
            "body": body,
        }
        if html_body:
            payload["html_body"] = html_body
        if cc:
            payload["cc"] = cc
        if bcc:
            payload["bcc"] = bcc

        message = NotificationMessage(
            id=notification_id,
            type=NotificationType.EMAIL,
            priority=priority,
            payload=payload,
            metadata=metadata,
        )

        if queue.enqueue(message):
            log_notification_event("NOTIFICATION_SUBMITTED", notification_id, {
                "type": "email",
                "priority": priority,
                "to": to,
            })
            return notification_id

        logger.error(f"Failed to queue notification: {notification_id}")
        return None

    def submit_notification(self, message: NotificationMessage) -> bool:
        """Submit a pre-built notification message.

        Returns True if queued successfully.
        """
        if queue.enqueue(message):
            log_notification_event("NOTIFICATION_SUBMITTED", message.id, {
                "type": message.type,
                "priority": message.priority,
            })
            return True
        return False

    def get_queue_status(self) -> dict:
        """Get current queue status."""
        connected = queue.is_connected()
        length = queue.queue_length() if connected else -1

        return {
            "connected": connected,
            "queue_length": length,
            "circuit_breaker_state": queue._circuit_breaker.state,
        }

    def get_processor_stats(self) -> dict:
        """Get processor statistics."""
        return {
            **processor.stats,
            "queue_length": queue.queue_length(),
        }

    def is_healthy(self) -> bool:
        """Check if the service is healthy."""
        return queue.is_connected()

    def process_sync(self, message: NotificationMessage) -> NotificationResult:
        """Process a notification synchronously (bypass queue).

        Useful for testing or immediate processing requirements.
        """
        return processor.process_one(message)


# Global service instance
notification_service = NotificationService()
