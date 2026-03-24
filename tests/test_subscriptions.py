"""Tests for subscription system"""
import pytest
import tempfile
import os
from pathlib import Path

from avm.subscriptions import (
    SubscriptionStore, SubscriptionMode, Subscription,
    get_subscription_store
)


@pytest.fixture
def temp_sub_db():
    """Create a temporary subscription database"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "subs.db")
        yield db_path


@pytest.fixture
def sub_store(temp_sub_db):
    """Create a subscription store with temp db"""
    return SubscriptionStore(temp_sub_db)


class TestSubscriptionStore:
    """Test SubscriptionStore"""
    
    def test_subscribe_batched(self, sub_store):
        """Test creating a batched subscription"""
        sub = sub_store.subscribe("agent1", "/memory/shared/*")
        assert sub.agent_id == "agent1"
        assert sub.pattern == "/memory/shared/*"
        assert sub.mode == SubscriptionMode.BATCHED
    
    def test_subscribe_throttled(self, sub_store):
        """Test creating a throttled subscription"""
        sub = sub_store.subscribe(
            "agent1", "/memory/news/*",
            mode=SubscriptionMode.THROTTLED,
            throttle_seconds=30
        )
        assert sub.mode == SubscriptionMode.THROTTLED
        assert sub.throttle_seconds == 30
    
    def test_subscribe_realtime(self, sub_store):
        """Test creating a realtime subscription"""
        sub = sub_store.subscribe("agent1", "/urgent/*", mode=SubscriptionMode.REALTIME)
        assert sub.mode == SubscriptionMode.REALTIME
    
    def test_list_subscriptions(self, sub_store):
        """Test listing subscriptions"""
        sub_store.subscribe("agent1", "/memory/*")
        sub_store.subscribe("agent2", "/shared/*")
        
        all_subs = sub_store.list_subscriptions()
        assert len(all_subs) == 2
        
        agent1_subs = sub_store.list_subscriptions(agent_id="agent1")
        assert len(agent1_subs) == 1
        assert agent1_subs[0].pattern == "/memory/*"
    
    def test_unsubscribe(self, sub_store):
        """Test removing a subscription"""
        sub_store.subscribe("agent1", "/memory/*")
        assert len(sub_store.list_subscriptions("agent1")) == 1
        
        sub_store.unsubscribe("agent1", "/memory/*")
        assert len(sub_store.list_subscriptions("agent1")) == 0
    
    def test_get_matching_subscriptions(self, sub_store):
        """Test finding subscriptions that match a path"""
        sub_store.subscribe("agent1", "/memory/shared/*")
        sub_store.subscribe("agent2", "/memory/*")
        sub_store.subscribe("agent3", "/other/*")
        
        matches = sub_store.get_matching_subscriptions("/memory/shared/file.md")
        assert len(matches) == 2
        agents = {m.agent_id for m in matches}
        assert "agent1" in agents
        assert "agent2" in agents
    
    def test_batched_stores_pending(self, sub_store):
        """Test that batched mode stores pending events"""
        sub_store.subscribe("agent1", "/memory/*", mode=SubscriptionMode.BATCHED)
        
        sub_store.on_write("/memory/test.md", author="agent2")
        
        pending = sub_store.get_pending("agent1")
        assert len(pending) == 1
        assert pending[0]["path"] == "/memory/test.md"
    
    def test_author_not_notified(self, sub_store):
        """Test that author doesn't get notified of their own writes"""
        sub_store.subscribe("agent1", "/memory/*", mode=SubscriptionMode.BATCHED)
        
        # Write by the subscriber themselves
        sub_store.on_write("/memory/test.md", author="agent1")
        
        # Should have no pending
        pending = sub_store.get_pending("agent1")
        assert len(pending) == 0
    
    def test_clear_pending(self, sub_store):
        """Test clearing pending notifications"""
        sub_store.subscribe("agent1", "/memory/*", mode=SubscriptionMode.BATCHED)
        sub_store.on_write("/memory/a.md", author="agent2")
        sub_store.on_write("/memory/b.md", author="agent2")
        
        assert len(sub_store.get_pending("agent1")) == 2
        
        # Get and mark as delivered
        sub_store.get_pending("agent1", mark_delivered=True)
        
        # Should be empty now
        assert len(sub_store.get_pending("agent1")) == 0
    
    def test_update_subscription(self, sub_store):
        """Test updating existing subscription"""
        sub_store.subscribe("agent1", "/memory/*", mode=SubscriptionMode.BATCHED)
        
        # Update to throttled
        sub = sub_store.subscribe(
            "agent1", "/memory/*",
            mode=SubscriptionMode.THROTTLED,
            throttle_seconds=120
        )
        
        assert sub.mode == SubscriptionMode.THROTTLED
        assert sub.throttle_seconds == 120
        
        # Should still be just one subscription
        assert len(sub_store.list_subscriptions("agent1")) == 1


class TestThrottling:
    """Test throttled notifications"""
    
    def test_throttle_aggregates(self, sub_store):
        """Test that throttle mode aggregates notifications"""
        notified = []
        sub_store.set_notify_callback(lambda agent, msg: notified.append((agent, msg)))
        
        sub_store.subscribe(
            "agent1", "/memory/*",
            mode=SubscriptionMode.THROTTLED,
            throttle_seconds=1  # Short for testing
        )
        
        # Multiple writes
        sub_store.on_write("/memory/a.md", author="agent2")
        sub_store.on_write("/memory/b.md", author="agent2")
        sub_store.on_write("/memory/c.md", author="agent2")
        
        # Wait for throttle to flush
        import time
        time.sleep(1.5)
        
        # Should have one aggregated notification
        assert len(notified) == 1
        agent, msg = notified[0]
        assert agent == "agent1"
        assert "3 updates" in msg or "a.md" in msg


class TestRealtimeNotification:
    """Test realtime notifications"""
    
    def test_realtime_immediate(self, sub_store):
        """Test that realtime mode notifies immediately"""
        notified = []
        sub_store.set_notify_callback(lambda agent, msg: notified.append((agent, msg)))
        
        sub_store.subscribe("agent1", "/urgent/*", mode=SubscriptionMode.REALTIME)
        
        sub_store.on_write("/urgent/alert.md", author="agent2")
        
        # Should be notified immediately
        assert len(notified) == 1
        assert notified[0][0] == "agent1"
        assert "/urgent/alert.md" in notified[0][1]


class TestWebhookNotification:
    """Test webhook notification"""
    
    def test_subscribe_with_webhook(self, sub_store):
        """Test creating subscription with webhook URL"""
        sub = sub_store.subscribe(
            "agent1", "/memory/shared/*",
            mode=SubscriptionMode.REALTIME,
            webhook_url="http://localhost:9999/test"
        )
        assert sub.webhook_url == "http://localhost:9999/test"
        assert sub.mode == SubscriptionMode.REALTIME
    
    def test_webhook_stored_and_retrieved(self, sub_store):
        """Test webhook URL is persisted"""
        sub_store.subscribe(
            "agent1", "/memory/shared/*",
            mode=SubscriptionMode.THROTTLED,
            throttle_seconds=60,
            webhook_url="http://example.com/webhook"
        )
        
        subs = sub_store.list_subscriptions("agent1")
        assert len(subs) == 1
        assert subs[0].webhook_url == "http://example.com/webhook"
    
    def test_update_webhook(self, sub_store):
        """Test updating webhook URL"""
        sub_store.subscribe(
            "agent1", "/memory/*",
            mode=SubscriptionMode.REALTIME,
            webhook_url="http://old.example.com"
        )
        
        # Update with new webhook
        sub_store.subscribe(
            "agent1", "/memory/*",
            mode=SubscriptionMode.REALTIME,
            webhook_url="http://new.example.com"
        )
        
        subs = sub_store.list_subscriptions("agent1")
        assert len(subs) == 1
        assert subs[0].webhook_url == "http://new.example.com"
