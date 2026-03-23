"""Notification Service - Redis-based message processing."""

from .main import app
from .service import notification_service, NotificationService
from .models import (
    NotificationMessage,
    NotificationType,
    NotificationPriority,
    NotificationStatus,
    NotificationResult,
    EmailPayload,
    HealthStatus,
)
from .processor import processor
from .redis_client import queue

__all__ = [
    "app",
    "notification_service",
    "NotificationService",
    "NotificationMessage",
    "NotificationType",
    "NotificationPriority",
    "NotificationStatus",
    "NotificationResult",
    "EmailPayload",
    "HealthStatus",
    "processor",
    "queue",
]
