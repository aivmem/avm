"""Notification type handlers."""

import smtplib
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Type, Optional

from .models import (
    NotificationMessage,
    NotificationResult,
    NotificationStatus,
    NotificationType,
    EmailPayload,
)
from .config import settings
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

    def __init__(self):
        self._smtp_enabled = bool(settings.smtp_host and settings.smtp_port)

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

        try:
            self._send_email(email, message.id)
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

    def _send_email(self, email: EmailPayload, notification_id: str) -> None:
        """Send email via SMTP or log in stub mode."""
        if not self._smtp_enabled or settings.smtp_host == "localhost":
            # Stub mode: log email details without sending
            log_notification_event(
                "EMAIL_STUB",
                notification_id,
                {
                    "to": email.to,
                    "subject": email.subject,
                    "body_length": len(email.body),
                },
            )
            return

        # Build MIME message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = email.subject
        msg["From"] = settings.smtp_from
        msg["To"] = email.to

        if email.cc:
            msg["Cc"] = ", ".join(email.cc)
        if email.bcc:
            msg["Bcc"] = ", ".join(email.bcc)

        # Attach plain text body
        msg.attach(MIMEText(email.body, "plain"))

        # Attach HTML body if provided
        if email.html_body:
            msg.attach(MIMEText(email.html_body, "html"))

        # Build recipient list
        recipients = [email.to]
        if email.cc:
            recipients.extend(email.cc)
        if email.bcc:
            recipients.extend(email.bcc)

        # Send via SMTP
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            if settings.smtp_user and settings.smtp_password:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from, recipients, msg.as_string())


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
