"""Redis client for queue operations."""

import json
import time
from typing import Optional
import redis

from .config import settings
from .models import NotificationMessage
from .logger import logger


class CircuitBreaker:
    """Simple circuit breaker to prevent cascading failures."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half-open

    def record_failure(self) -> None:
        """Record a failure and potentially open the circuit."""
        self.last_failure_time = time.time()

        # In half-open state, any failure immediately re-opens the circuit
        if self.state == "half-open":
            self.state = "open"
            logger.warning("Circuit breaker re-opened after failure in half-open state")
            return

        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")

    def record_success(self) -> None:
        """Record a success and reset the circuit."""
        if self.state == "half-open":
            logger.info("Circuit breaker closed after successful probe in half-open state")
        self.failure_count = 0
        self.state = "closed"

    def can_execute(self) -> bool:
        """Check if we can attempt an operation."""
        if self.state == "closed":
            return True
        if self.state == "open":
            if self.last_failure_time and (time.time() - self.last_failure_time) > self.recovery_timeout:
                self.state = "half-open"
                return True
            return False
        return True  # half-open allows one attempt


class RedisQueue:
    """Redis-based message queue for notifications."""

    def __init__(self):
        self._client: Optional[redis.Redis] = None
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=settings.circuit_breaker_threshold,
            recovery_timeout=settings.circuit_breaker_timeout,
        )

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
                socket_connect_timeout=settings.redis_connect_timeout,
                socket_timeout=settings.redis_socket_timeout,
                retry_on_timeout=True,
            )
        return self._client

    def _reset_client(self) -> None:
        """Reset the client connection on failures."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def is_connected(self) -> bool:
        """Check if Redis connection is healthy."""
        if not self._circuit_breaker.can_execute():
            return False
        try:
            self.client.ping()
            self._circuit_breaker.record_success()
            return True
        except redis.ConnectionError:
            self._circuit_breaker.record_failure()
            self._reset_client()
            return False

    def enqueue(self, message: NotificationMessage) -> bool:
        """Add a notification message to the queue with retry logic."""
        if not self._circuit_breaker.can_execute():
            logger.warning(f"Circuit breaker open, rejecting enqueue for: {message.id}")
            return False

        for attempt in range(settings.redis_max_retries):
            try:
                data = message.model_dump_json()
                self.client.lpush(settings.redis_queue_name, data)
                logger.info(f"Enqueued notification: {message.id}")
                self._circuit_breaker.record_success()
                return True
            except redis.RedisError as e:
                logger.error(f"Failed to enqueue message (attempt {attempt + 1}): {e}")
                self._circuit_breaker.record_failure()
                self._reset_client()
                if attempt < settings.redis_max_retries - 1:
                    time.sleep(settings.redis_retry_delay * (attempt + 1))

        return False

    def dequeue(self) -> Optional[NotificationMessage]:
        """Remove and return a notification from the queue (FIFO)."""
        if not self._circuit_breaker.can_execute():
            return None

        try:
            data = self.client.rpop(settings.redis_queue_name)
            if data:
                self._circuit_breaker.record_success()
                return NotificationMessage.model_validate_json(data)
            return None
        except redis.RedisError as e:
            logger.error(f"Failed to dequeue message: {e}")
            self._circuit_breaker.record_failure()
            self._reset_client()
            return None

    def dequeue_blocking(self, timeout: int = 0) -> Optional[NotificationMessage]:
        """Blocking dequeue with optional timeout."""
        if not self._circuit_breaker.can_execute():
            return None

        try:
            result = self.client.brpop(settings.redis_queue_name, timeout=timeout)
            if result:
                _, data = result
                self._circuit_breaker.record_success()
                return NotificationMessage.model_validate_json(data)
            return None
        except redis.RedisError as e:
            logger.error(f"Failed to dequeue message: {e}")
            self._circuit_breaker.record_failure()
            self._reset_client()
            return None

    def requeue(self, message: NotificationMessage) -> bool:
        """Re-add a message to the queue (for retries)."""
        message.retry_count += 1
        return self.enqueue(message)

    def queue_length(self) -> int:
        """Get current queue length."""
        if not self._circuit_breaker.can_execute():
            return -1

        try:
            length = self.client.llen(settings.redis_queue_name)
            self._circuit_breaker.record_success()
            return length
        except redis.RedisError:
            self._circuit_breaker.record_failure()
            self._reset_client()
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
