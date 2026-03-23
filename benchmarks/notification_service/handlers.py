"""Notification type handlers."""

from abc import ABC, abstractmethod
from typing import Dict, Type

from .models import (
    NotificationMessage,
    NotificationResult,
    NotificationStatus,
    NotificationType,
    EmailPayload,
)
from .logger import log_notification_event, log_error


class NotificationHandler(ABC):
    """Base class for notification handlers."""

    @abstractmethod
    def handle(self, message: NotificationMessage) -> NotificationResult:
        """Process a notification message."""
        pass

    @abstractmethod
    def validate_payload(self, payload: dict) -> bool:
        """Validate the notification payload."""
        pass


class EmailHandler(NotificationHandler):
    """Handler for email notifications."""

    def validate_payload(self, payload: dict) -> bool:
        """Validate email payload structure."""
        try:
            EmailPayload.model_validate(payload)
            return True
        except Exception:
            return False

    def handle(self, message: NotificationMessage) -> NotificationResult:
        """Process an email notification."""
        log_notification_event("EMAIL_PROCESSING", message.id, {"type": "email"})

        if not self.validate_payload(message.payload):
            log_error("Invalid email payload", message.id)
            return NotificationResult(
                notification_id=message.id,
                status=NotificationStatus.FAILED,
                error_message="Invalid email payload",
            )

        email = EmailPayload.model_validate(message.payload)

        # Simulate email sending (replace with actual SMTP logic)
        try:
            self._send_email(email)
            log_notification_event(
                "EMAIL_SENT",
                message.id,
                {"to": email.to, "subject": email.subject},
            )
            return NotificationResult(
                notification_id=message.id,
                status=NotificationStatus.SENT,
                details={"to": email.to, "subject": email.subject},
            )
        except Exception as e:
            log_error("Email send failed", message.id, e)
            return NotificationResult(
                notification_id=message.id,
                status=NotificationStatus.FAILED,
                error_message=str(e),
            )

    def _send_email(self, email: EmailPayload) -> None:
        """Send email via SMTP. Currently a stub for extensibility."""
        # TODO: Implement actual SMTP sending
        # For now, log the email details
        log_notification_event(
            "EMAIL_STUB",
            "stub",
            {
                "to": email.to,
                "subject": email.subject,
                "body_length": len(email.body),
            },
        )


# Handler registry for extensibility
HANDLERS: Dict[NotificationType, Type[NotificationHandler]] = {
    NotificationType.EMAIL: EmailHandler,
}


def get_handler(notification_type: NotificationType) -> NotificationHandler:
    """Get the appropriate handler for a notification type."""
    handler_class = HANDLERS.get(notification_type)
    if not handler_class:
        raise ValueError(f"No handler for notification type: {notification_type}")
    return handler_class()
