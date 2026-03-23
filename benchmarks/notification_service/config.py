"""Configuration for the Notification Service."""

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Service configuration from environment variables."""

    # Redis settings
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    redis_queue_name: str = "notifications"

    # Service settings
    service_name: str = "notification-service"
    service_version: str = "1.0.0"
    log_level: str = "INFO"

    # Processing settings
    poll_interval: float = 1.0  # seconds
    batch_size: int = 10
    max_retries: int = 3

    # Email settings (for future SMTP integration)
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "noreply@example.com"

    class Config:
        env_prefix = "NOTIF_"


settings = Settings()
