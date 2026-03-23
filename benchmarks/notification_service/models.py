"""Data models for the Notification Service."""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, EmailStr


class NotificationType(str, Enum):
    """Supported notification types."""
    EMAIL = "email"
    # Extensible: add SMS, PUSH, WEBHOOK, etc.


class NotificationStatus(str, Enum):
    """Notification processing status."""
    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"


class NotificationPriority(str, Enum):
    """Notification priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class EmailPayload(BaseModel):
    """Email-specific notification payload."""
    to: EmailStr
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1)
    html_body: Optional[str] = None
    cc: Optional[list[EmailStr]] = None
    bcc: Optional[list[EmailStr]] = None


class NotificationMessage(BaseModel):
    """Message schema for Redis queue."""
    id: str = Field(..., description="Unique notification ID")
    type: NotificationType
    priority: NotificationPriority = NotificationPriority.NORMAL
    payload: Dict[str, Any]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    retry_count: int = 0
    max_retries: int = 3
    metadata: Optional[Dict[str, Any]] = None


class NotificationResult(BaseModel):
    """Result of processing a notification."""
    notification_id: str
    status: NotificationStatus
    processed_at: datetime = Field(default_factory=datetime.utcnow)
    error_message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class HealthStatus(BaseModel):
    """Health check response."""
    status: str
    service: str = "notification-service"
    version: str = "1.0.0"
    redis_connected: bool
    queue_length: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)
