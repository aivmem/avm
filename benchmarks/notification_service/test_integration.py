"""Integration tests for the Notification Service.

These tests require a running Redis instance.
Run with: docker-compose -f docker-compose.test.yml run test-runner
"""

import os
import time
import pytest
from fastapi.testclient import TestClient

# Skip integration tests if Redis is not available
REDIS_HOST = os.getenv("NOTIF_REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("NOTIF_REDIS_PORT", "6379"))


def redis_available():
    """Check if Redis is available."""
    try:
        import redis
        client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, socket_timeout=1)
        client.ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not redis_available(),
    reason="Redis not available"
)


@pytest.fixture(scope="module")
def integration_client():
    """Create test client with real Redis connection."""
    from notification_service.main import app
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def clear_queue():
    """Clear the notification queue before each test."""
    import redis
    client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)
    client.delete("notifications")
    yield
    client.delete("notifications")


class TestHealthIntegration:
    """Integration tests for health endpoint."""

    def test_health_with_redis(self, integration_client):
        """Health check should report healthy when Redis is connected."""
        response = integration_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["redis_connected"] is True


class TestNotificationFlow:
    """Integration tests for the full notification flow."""

    def test_submit_and_check_queue(self, integration_client):
        """Submit notification and verify it's in the queue."""
        email_data = {
            "to": "integration@example.com",
            "subject": "Integration Test",
            "body": "Testing the full notification flow",
        }

        # Submit notification
        response = integration_client.post("/notifications/email", json=email_data)
        assert response.status_code == 202
        notification_id = response.json()["notification_id"]

        # Check queue has the message
        response = integration_client.get("/health")
        assert response.json()["queue_length"] >= 1

    def test_submit_multiple_notifications(self, integration_client):
        """Submit multiple notifications and verify queue length."""
        for i in range(5):
            email_data = {
                "to": f"test{i}@example.com",
                "subject": f"Test {i}",
                "body": f"Body {i}",
            }
            response = integration_client.post("/notifications/email", json=email_data)
            assert response.status_code == 202

        # Check queue has all messages
        response = integration_client.get("/health")
        assert response.json()["queue_length"] >= 5

    def test_notification_with_priority(self, integration_client):
        """Test submitting notifications with different priorities."""
        priorities = ["low", "normal", "high", "urgent"]

        for priority in priorities:
            email_data = {
                "to": "priority@example.com",
                "subject": f"Priority: {priority}",
                "body": "Testing priority",
            }
            response = integration_client.post(
                f"/notifications/email?priority={priority}",
                json=email_data
            )
            assert response.status_code == 202

    def test_raw_notification_submission(self, integration_client):
        """Test submitting raw notification message."""
        notification = {
            "id": "integration-raw-001",
            "type": "email",
            "priority": "high",
            "payload": {
                "to": "raw@example.com",
                "subject": "Raw Notification",
                "body": "Submitted via raw endpoint",
            },
        }

        response = integration_client.post("/notifications", json=notification)
        assert response.status_code == 202
        assert response.json()["notification_id"] == "integration-raw-001"


class TestStatsIntegration:
    """Integration tests for stats endpoint."""

    def test_stats_endpoint(self, integration_client):
        """Stats endpoint should return processor stats."""
        response = integration_client.get("/stats")
        assert response.status_code == 200
        data = response.json()
        assert "processor" in data
        assert "queue_length" in data
        assert isinstance(data["processor"]["processed"], int)
        assert isinstance(data["processor"]["failed"], int)


class TestErrorHandling:
    """Integration tests for error handling."""

    def test_invalid_email_format(self, integration_client):
        """Invalid email should return validation error."""
        email_data = {
            "to": "not-an-email",
            "subject": "Test",
            "body": "Body",
        }
        response = integration_client.post("/notifications/email", json=email_data)
        assert response.status_code == 422

    def test_missing_required_fields(self, integration_client):
        """Missing required fields should return validation error."""
        email_data = {
            "to": "test@example.com",
            # missing subject and body
        }
        response = integration_client.post("/notifications/email", json=email_data)
        assert response.status_code == 422

    def test_empty_subject(self, integration_client):
        """Empty subject should return validation error."""
        email_data = {
            "to": "test@example.com",
            "subject": "",
            "body": "Body",
        }
        response = integration_client.post("/notifications/email", json=email_data)
        assert response.status_code == 422
