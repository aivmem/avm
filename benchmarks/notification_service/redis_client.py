"""Redis client for queue operations."""

import json
from typing import Optional
import redis

from .config import settings
from .models import NotificationMessage
from .logger import logger


class RedisQueue:
    """Redis-based message queue for notifications."""

    def __init__(self):
        self._client: Optional[redis.Redis] = None

    @property
    def client(self) -> redis.Redis:
        """Lazy initialization of Redis client."""
        if self._client is None:
            self._client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                password=settings.redis_password,
                decode_responses=True,
            )
        return self._client

    def is_connected(self) -> bool:
        """Check if Redis connection is healthy."""
        try:
            self.client.ping()
            return True
        except redis.ConnectionError:
            return False

    def enqueue(self, message: NotificationMessage) -> bool:
        """Add a notification message to the queue."""
        try:
            data = message.model_dump_json()
            self.client.lpush(settings.redis_queue_name, data)
            logger.info(f"Enqueued notification: {message.id}")
            return True
        except redis.RedisError as e:
            logger.error(f"Failed to enqueue message: {e}")
            return False

    def dequeue(self) -> Optional[NotificationMessage]:
        """Remove and return a notification from the queue (FIFO)."""
        try:
            data = self.client.rpop(settings.redis_queue_name)
            if data:
                return NotificationMessage.model_validate_json(data)
            return None
        except redis.RedisError as e:
            logger.error(f"Failed to dequeue message: {e}")
            return None

    def dequeue_blocking(self, timeout: int = 0) -> Optional[NotificationMessage]:
        """Blocking dequeue with optional timeout."""
        try:
            result = self.client.brpop(settings.redis_queue_name, timeout=timeout)
            if result:
                _, data = result
                return NotificationMessage.model_validate_json(data)
            return None
        except redis.RedisError as e:
            logger.error(f"Failed to dequeue message: {e}")
            return None

    def requeue(self, message: NotificationMessage) -> bool:
        """Re-add a message to the queue (for retries)."""
        message.retry_count += 1
        return self.enqueue(message)

    def queue_length(self) -> int:
        """Get current queue length."""
        try:
            return self.client.llen(settings.redis_queue_name)
        except redis.RedisError:
            return -1

    def clear(self) -> bool:
        """Clear the queue (for testing)."""
        try:
            self.client.delete(settings.redis_queue_name)
            return True
        except redis.RedisError:
            return False


# Global queue instance
queue = RedisQueue()
