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
    redis_connect_timeout: float = 5.0
    redis_socket_timeout: float = 5.0
    redis_max_retries: int = 3
    redis_retry_delay: float = 0.5

    # Circuit breaker settings
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: float = 30.0

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
