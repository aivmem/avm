"""Tests for the Notification Service."""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from notification_service.main import app
from notification_service.models import (
    NotificationMessage,
    NotificationType,
    NotificationPriority,
    NotificationStatus,
    EmailPayload,
    NotificationResult,
    HealthStatus,
)
from notification_service.handlers import EmailHandler, get_handler, HANDLERS
from notification_service.processor import NotificationProcessor
from notification_service.redis_client import RedisQueue
from notification_service.config import Settings


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_redis():
    """Mock Redis queue."""
    with patch("notification_service.main.queue") as mock_queue:
        mock_queue.is_connected.return_value = True
        mock_queue.queue_length.return_value = 5
        mock_queue.enqueue.return_value = True
        yield mock_queue


@pytest.fixture
def sample_email_payload():
    """Create a sample email payload."""
    return {
        "to": "test@example.com",
        "subject": "Test Subject",
        "body": "Test body content",
    }


@pytest.fixture
def sample_notification_message():
    """Create a sample notification message."""
    return NotificationMessage(
        id="test-notification-123",
        type=NotificationType.EMAIL,
        priority=NotificationPriority.NORMAL,
        payload={
            "to": "test@example.com",
            "subject": "Test Subject",
            "body": "Test body content",
        },
    )


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check_healthy(self, client, mock_redis):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["redis_connected"] is True
        assert data["service"] == "notification-service"

    def test_health_check_degraded(self, client):
        with patch("notification_service.main.queue") as mock_queue:
            mock_queue.is_connected.return_value = False
            mock_queue.queue_length.return_value = -1
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"


class TestRootEndpoint:
    """Tests for root endpoint."""

    def test_root(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "notification-service"
        assert data["status"] == "running"


class TestEmailNotificationEndpoint:
    """Tests for email notification submission."""

    def test_submit_email_notification(self, client, mock_redis):
        email_data = {
            "to": "test@example.com",
            "subject": "Test Subject",
            "body": "Test body content",
        }
        response = client.post("/notifications/email", json=email_data)
        assert response.status_code == 202
        data = response.json()
        assert "notification_id" in data
        assert data["status"] == "queued"
        assert data["type"] == "email"

    def test_submit_email_invalid(self, client, mock_redis):
        email_data = {
            "to": "invalid-email",
            "subject": "Test",
            "body": "Body",
        }
        response = client.post("/notifications/email", json=email_data)
        assert response.status_code == 422

    def test_submit_email_redis_unavailable(self, client):
        with patch("notification_service.main.queue") as mock_queue:
            mock_queue.enqueue.return_value = False
            email_data = {
                "to": "test@example.com",
                "subject": "Test",
                "body": "Body",
            }
            response = client.post("/notifications/email", json=email_data)
            assert response.status_code == 503


class TestEmailHandler:
    """Tests for email notification handler."""

    def test_validate_payload_valid(self):
        handler = EmailHandler()
        payload = {
            "to": "test@example.com",
            "subject": "Test",
            "body": "Body",
        }
        assert handler.validate_payload(payload) is True

    def test_validate_payload_invalid(self):
        handler = EmailHandler()
        payload = {"to": "invalid", "subject": "Test"}
        assert handler.validate_payload(payload) is False

    def test_handle_email(self):
        handler = EmailHandler()
        message = NotificationMessage(
            id="test-123",
            type=NotificationType.EMAIL,
            payload={
                "to": "test@example.com",
                "subject": "Test Subject",
                "body": "Test body",
            },
        )
        result = handler.handle(message)
        assert result.notification_id == "test-123"
        assert result.status == NotificationStatus.SENT


class TestGetHandler:
    """Tests for handler registry."""

    def test_get_email_handler(self):
        handler = get_handler(NotificationType.EMAIL)
        assert isinstance(handler, EmailHandler)


class TestNotificationProcessor:
    """Tests for notification processor."""

    def test_process_one(self):
        processor = NotificationProcessor()
        message = NotificationMessage(
            id="proc-test-123",
            type=NotificationType.EMAIL,
            payload={
                "to": "test@example.com",
                "subject": "Test",
                "body": "Body",
            },
        )
        result = processor.process_one(message)
        assert result.status == NotificationStatus.SENT
        assert processor.stats["processed"] == 1

    def test_stats(self):
        processor = NotificationProcessor()
        assert processor.stats["processed"] == 0
        assert processor.stats["failed"] == 0
        assert processor.stats["running"] is False

    def test_process_invalid_payload(self):
        processor = NotificationProcessor()
        message = NotificationMessage(
            id="invalid-payload-test",
            type=NotificationType.EMAIL,
            payload={"invalid": "data"},
        )
        result = processor.process_one(message)
        assert result.status == NotificationStatus.FAILED
        assert processor.stats["failed"] == 1

    def test_result_callback(self):
        processor = NotificationProcessor()
        results = []
        processor.set_result_callback(lambda r: results.append(r))

        message = NotificationMessage(
            id="callback-test",
            type=NotificationType.EMAIL,
            payload={
                "to": "test@example.com",
                "subject": "Test",
                "body": "Body",
            },
        )
        processor.process_one(message)
        assert len(results) == 1
        assert results[0].notification_id == "callback-test"


class TestModels:
    """Tests for data models."""

    def test_email_payload_valid(self):
        payload = EmailPayload(
            to="test@example.com",
            subject="Test",
            body="Body",
        )
        assert payload.to == "test@example.com"

    def test_email_payload_with_optional_fields(self):
        payload = EmailPayload(
            to="test@example.com",
            subject="Test",
            body="Body",
            html_body="<p>HTML Body</p>",
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
        )
        assert payload.html_body == "<p>HTML Body</p>"
        assert len(payload.cc) == 1
        assert len(payload.bcc) == 1

    def test_notification_message_defaults(self):
        msg = NotificationMessage(
            id="test-id",
            type=NotificationType.EMAIL,
            payload={"to": "test@example.com"},
        )
        assert msg.priority == NotificationPriority.NORMAL
        assert msg.retry_count == 0
        assert msg.max_retries == 3
        assert isinstance(msg.created_at, datetime)

    def test_notification_result(self):
        result = NotificationResult(
            notification_id="test-id",
            status=NotificationStatus.SENT,
        )
        assert result.error_message is None
        assert isinstance(result.processed_at, datetime)

    def test_health_status(self):
        health = HealthStatus(
            status="healthy",
            redis_connected=True,
            queue_length=10,
        )
        assert health.service == "notification-service"
        assert health.version == "1.0.0"


class TestNotificationSubmission:
    """Tests for notification submission endpoints."""

    def test_submit_raw_notification(self, client, mock_redis):
        notification = {
            "id": "raw-test-123",
            "type": "email",
            "payload": {
                "to": "test@example.com",
                "subject": "Test",
                "body": "Body",
            },
        }
        response = client.post("/notifications", json=notification)
        assert response.status_code == 202
        data = response.json()
        assert data["notification_id"] == "raw-test-123"

    def test_submit_email_with_priority(self, client, mock_redis):
        email_data = {
            "to": "test@example.com",
            "subject": "Urgent Test",
            "body": "Urgent body content",
        }
        response = client.post(
            "/notifications/email?priority=urgent", json=email_data
        )
        assert response.status_code == 202


class TestStatsEndpoint:
    """Tests for stats endpoint."""

    def test_get_stats(self, client, mock_redis):
        with patch("notification_service.main.processor") as mock_processor:
            mock_processor.stats = {
                "processed": 10,
                "failed": 2,
                "running": True,
            }
            response = client.get("/stats")
            assert response.status_code == 200
            data = response.json()
            assert "processor" in data
            assert "queue_length" in data


class TestRedisQueue:
    """Tests for Redis queue operations."""

    def test_queue_initialization(self):
        queue = RedisQueue()
        assert queue._client is None

    @patch("notification_service.redis_client.redis.Redis")
    def test_enqueue_message(self, mock_redis_class):
        mock_client = MagicMock()
        mock_redis_class.return_value = mock_client

        queue = RedisQueue()
        message = NotificationMessage(
            id="queue-test",
            type=NotificationType.EMAIL,
            payload={"to": "test@example.com", "subject": "Test", "body": "Body"},
        )
        result = queue.enqueue(message)
        assert mock_client.lpush.called

    @patch("notification_service.redis_client.redis.Redis")
    def test_dequeue_message(self, mock_redis_class):
        mock_client = MagicMock()
        mock_client.rpop.return_value = '{"id": "test", "type": "email", "payload": {"to": "a@b.com", "subject": "s", "body": "b"}, "priority": "normal", "retry_count": 0, "max_retries": 3}'
        mock_redis_class.return_value = mock_client

        queue = RedisQueue()
        message = queue.dequeue()
        assert message is not None
        assert message.id == "test"

    @patch("notification_service.redis_client.redis.Redis")
    def test_queue_length(self, mock_redis_class):
        mock_client = MagicMock()
        mock_client.llen.return_value = 5
        mock_redis_class.return_value = mock_client

        queue = RedisQueue()
        assert queue.queue_length() == 5

    @patch("notification_service.redis_client.redis.Redis")
    def test_requeue_increments_retry(self, mock_redis_class):
        mock_client = MagicMock()
        mock_redis_class.return_value = mock_client

        queue = RedisQueue()
        message = NotificationMessage(
            id="retry-test",
            type=NotificationType.EMAIL,
            payload={"to": "test@example.com", "subject": "Test", "body": "Body"},
            retry_count=1,
        )
        queue.requeue(message)
        assert message.retry_count == 2


class TestConfig:
    """Tests for configuration."""

    def test_default_settings(self):
        settings = Settings()
        assert settings.redis_host == "localhost"
        assert settings.redis_port == 6379
        assert settings.poll_interval == 1.0
        assert settings.max_retries == 3

    @patch.dict("os.environ", {"NOTIF_REDIS_HOST": "redis-server", "NOTIF_REDIS_PORT": "6380"})
    def test_settings_from_env(self):
        settings = Settings()
        assert settings.redis_host == "redis-server"
        assert settings.redis_port == 6380


class TestCircuitBreaker:
    """Tests for circuit breaker functionality."""

    def test_circuit_starts_closed(self):
        from notification_service.redis_client import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        assert cb.state == "closed"
        assert cb.can_execute() is True

    def test_circuit_opens_after_threshold(self):
        from notification_service.redis_client import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "open"
        assert cb.can_execute() is False

    def test_circuit_resets_on_success(self):
        from notification_service.redis_client import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == "closed"

    def test_circuit_half_open_after_timeout(self):
        from notification_service.redis_client import CircuitBreaker
        import time

        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        time.sleep(0.15)
        assert cb.can_execute() is True
        assert cb.state == "half-open"

    def test_circuit_reopens_on_failure_in_half_open(self):
        from notification_service.redis_client import CircuitBreaker
        import time

        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.can_execute()  # Transitions to half-open
        cb.record_failure()
        assert cb.state == "open"


class TestLogger:
    """Tests for logging functionality."""

    def test_setup_logger(self):
        from notification_service.logger import setup_logger
        import logging

        logger = setup_logger("test_logger")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_logger"

    def test_log_notification_event(self):
        from notification_service.logger import log_notification_event

        # Should not raise
        log_notification_event("TEST_EVENT", "test-123", {"key": "value"})
        log_notification_event("TEST_EVENT_NO_DETAILS", "test-456")

    def test_log_error(self):
        from notification_service.logger import log_error

        # Should not raise
        log_error("Test error message")
        log_error("Error with ID", notification_id="test-123")
        log_error("Error with exception", error=ValueError("test error"))


class TestHandlerRegistry:
    """Tests for notification handler registry."""

    def test_email_handler_registered(self):
        assert NotificationType.EMAIL in HANDLERS
        assert HANDLERS[NotificationType.EMAIL] == EmailHandler

    def test_get_handler_unknown_type(self):
        with pytest.raises(ValueError, match="No handler for notification type"):
            # Temporarily mock an unknown type
            get_handler("unknown")


class TestNotificationService:
    """Tests for the high-level notification service."""

    @patch("notification_service.service.queue")
    def test_submit_email(self, mock_queue):
        """Test submitting an email via service layer."""
        from notification_service.service import NotificationService

        mock_queue.enqueue.return_value = True

        service = NotificationService()
        notification_id = service.submit_email(
            to="service@example.com",
            subject="Service Test",
            body="Testing service layer",
        )

        assert notification_id is not None
        assert mock_queue.enqueue.called
        call_args = mock_queue.enqueue.call_args[0][0]
        assert call_args.type == NotificationType.EMAIL
        assert call_args.payload["to"] == "service@example.com"

    @patch("notification_service.service.queue")
    def test_submit_email_with_options(self, mock_queue):
        """Test email submission with all options."""
        from notification_service.service import NotificationService

        mock_queue.enqueue.return_value = True

        service = NotificationService()
        notification_id = service.submit_email(
            to="test@example.com",
            subject="Full Options",
            body="Plain body",
            html_body="<p>HTML body</p>",
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
            priority=NotificationPriority.HIGH,
            metadata={"source": "test"},
        )

        assert notification_id is not None
        call_args = mock_queue.enqueue.call_args[0][0]
        assert call_args.priority == NotificationPriority.HIGH
        assert call_args.payload["html_body"] == "<p>HTML body</p>"
        assert call_args.metadata == {"source": "test"}

    @patch("notification_service.service.queue")
    def test_submit_email_failure(self, mock_queue):
        """Test email submission when queue fails."""
        from notification_service.service import NotificationService

        mock_queue.enqueue.return_value = False

        service = NotificationService()
        notification_id = service.submit_email(
            to="fail@example.com",
            subject="Fail Test",
            body="Should fail",
        )

        assert notification_id is None

    @patch("notification_service.service.queue")
    def test_get_queue_status(self, mock_queue):
        """Test getting queue status."""
        from notification_service.service import NotificationService

        mock_queue.is_connected.return_value = True
        mock_queue.queue_length.return_value = 10
        mock_queue._circuit_breaker.state = "closed"

        service = NotificationService()
        status = service.get_queue_status()

        assert status["connected"] is True
        assert status["queue_length"] == 10
        assert status["circuit_breaker_state"] == "closed"

    @patch("notification_service.service.queue")
    def test_is_healthy(self, mock_queue):
        """Test health check via service."""
        from notification_service.service import NotificationService

        mock_queue.is_connected.return_value = True

        service = NotificationService()
        assert service.is_healthy() is True

        mock_queue.is_connected.return_value = False
        assert service.is_healthy() is False

    @patch("notification_service.service.processor")
    def test_process_sync(self, mock_processor):
        """Test synchronous processing."""
        from notification_service.service import NotificationService

        mock_result = NotificationResult(
            notification_id="sync-test",
            status=NotificationStatus.SENT,
        )
        mock_processor.process_one.return_value = mock_result

        service = NotificationService()
        message = NotificationMessage(
            id="sync-test",
            type=NotificationType.EMAIL,
            payload={"to": "sync@example.com", "subject": "Sync", "body": "Test"},
        )

        result = service.process_sync(message)
        assert result.status == NotificationStatus.SENT
        mock_processor.process_one.assert_called_once_with(message)
