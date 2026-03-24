"""Tests for Agent Gossip Protocol"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from avm.store import AVMStore
from avm.topic_index import TopicIndex
from avm.gossip import (
    AgentDigest, GossipMessage, GossipStore, GossipProtocol,
    BLOOM_SIZE, BLOOM_HASHES
)


@pytest.fixture
def gossip_env():
    """Create a gossip environment with multiple agents"""
    import os
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Set XDG_DATA_HOME so AVMStore uses temp dir
        old_xdg = os.environ.get('XDG_DATA_HOME')
        os.environ['XDG_DATA_HOME'] = tmpdir
        
        try:
            db_path = Path(tmpdir) / "avm" / "avm.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            store = AVMStore(str(db_path))
            topic_index = TopicIndex(store)
            
            # Create some test data in topic index only
            topic_index.index_path("/memory/private/alice/btc.md", "Bitcoin trading analysis")
            topic_index.index_path("/memory/private/alice/eth.md", "Ethereum staking guide")
            topic_index.index_path("/memory/private/bob/stocks.md", "Stock market analysis")
            topic_index.index_path("/memory/private/bob/nvda.md", "NVDA technical signals")
            
            yield store, topic_index
        finally:
            if old_xdg:
                os.environ['XDG_DATA_HOME'] = old_xdg
            elif 'XDG_DATA_HOME' in os.environ:
                del os.environ['XDG_DATA_HOME']


class TestAgentDigest:
    """Test AgentDigest bloom filter"""
    
    def test_create_digest(self):
        digest = AgentDigest(
            agent_id="test",
            version=1,
            timestamp=None,
        )
        digest.timestamp = digest.timestamp or datetime.now(timezone.utc)
        assert digest.agent_id == "test"
        assert digest.version == 1
    
    def test_add_and_query_topic(self):
        from datetime import datetime, timezone
        digest = AgentDigest(
            agent_id="test",
            version=1,
            timestamp=datetime.now(timezone.utc),
        )
        
        digest.add_topic("bitcoin")
        digest.add_topic("ethereum")
        
        assert digest.might_have_topic("bitcoin")
        assert digest.might_have_topic("ethereum")
        # Unlikely to match random string
        assert not digest.might_have_topic("xyz123randomnonexistent")
    
    def test_bloom_false_positive_rate(self):
        """Test that bloom filter has acceptable FP rate"""
        from datetime import datetime, timezone
        digest = AgentDigest(
            agent_id="test",
            version=1,
            timestamp=datetime.now(timezone.utc),
        )
        
        # Add 100 topics
        for i in range(100):
            digest.add_topic(f"topic_{i}")
        
        # Check false positive rate on non-existent topics
        false_positives = 0
        test_count = 1000
        for i in range(test_count):
            if digest.might_have_topic(f"nonexistent_{i}"):
                false_positives += 1
        
        fp_rate = false_positives / test_count
        # Should be under 10% with our parameters
        assert fp_rate < 0.15, f"False positive rate too high: {fp_rate:.2%}"
    
    def test_serialization(self):
        from datetime import datetime, timezone
        digest = AgentDigest(
            agent_id="alice",
            version=5,
            timestamp=datetime.now(timezone.utc),
            memory_count=42,
            capabilities=["trading", "analysis"],
        )
        digest.add_topic("bitcoin")
        
        # Serialize and deserialize
        data = digest.to_dict()
        restored = AgentDigest.from_dict(data)
        
        assert restored.agent_id == "alice"
        assert restored.version == 5
        assert restored.memory_count == 42
        assert restored.might_have_topic("bitcoin")


class TestGossipMessage:
    """Test GossipMessage"""
    
    def test_create_message(self):
        from datetime import datetime, timezone
        digest = AgentDigest(
            agent_id="alice",
            version=1,
            timestamp=datetime.now(timezone.utc),
        )
        
        message = GossipMessage(
            from_agent="alice",
            digest=digest,
            ttl=3,
        )
        
        assert message.from_agent == "alice"
        assert message.ttl == 3
    
    def test_message_serialization(self):
        from datetime import datetime, timezone
        digest = AgentDigest(
            agent_id="alice",
            version=1,
            timestamp=datetime.now(timezone.utc),
        )
        
        message = GossipMessage(from_agent="alice", digest=digest)
        
        data = message.to_dict()
        restored = GossipMessage.from_dict(data)
        
        assert restored.from_agent == "alice"
        assert restored.digest.agent_id == "alice"


class TestGossipStore:
    """Test GossipStore"""
    
    def test_generate_digest(self, gossip_env):
        store, topic_index = gossip_env
        gossip_store = GossipStore(store, topic_index, "alice")
        
        digest = gossip_store.generate_digest()
        
        assert digest.agent_id == "alice"
        assert digest.version == 1
        assert len(digest.topics) > 0
    
    def test_publish_digest(self, gossip_env):
        store, topic_index = gossip_env
        gossip_store = GossipStore(store, topic_index, "alice")
        
        digest = gossip_store.publish_digest()
        
        # Should be stored
        node = store.get_node("/gossip/alice.digest")
        assert node is not None
        assert "alice" in node.content
    
    def test_receive_digest(self, gossip_env):
        store, topic_index = gossip_env
        
        # Alice publishes
        alice_store = GossipStore(store, topic_index, "alice")
        alice_digest = alice_store.generate_digest()
        alice_digest.add_topic("bitcoin")
        
        message = GossipMessage(from_agent="alice", digest=alice_digest)
        
        # Bob receives
        bob_store = GossipStore(store, topic_index, "bob")
        received = bob_store.receive_digest(message)
        
        assert received
        assert "alice" in bob_store.agents()
    
    def test_who_knows(self, gossip_env):
        store, topic_index = gossip_env
        
        # Alice knows about bitcoin
        alice_store = GossipStore(store, topic_index, "alice")
        alice_digest = alice_store.generate_digest()
        alice_digest.add_topic("bitcoin")
        alice_store._digest_cache["alice"] = alice_digest
        
        # Bob knows about stocks
        bob_digest = AgentDigest(
            agent_id="bob",
            version=1,
            timestamp=datetime.now(timezone.utc),
        )
        bob_digest.add_topic("stocks")
        alice_store._digest_cache["bob"] = bob_digest
        
        # Query
        bitcoin_experts = alice_store.who_knows("bitcoin")
        assert any(agent == "alice" for agent, _ in bitcoin_experts)
        
        stock_experts = alice_store.who_knows("stocks")
        assert any(agent == "bob" for agent, _ in stock_experts)
    
    def test_stats(self, gossip_env):
        store, topic_index = gossip_env
        gossip_store = GossipStore(store, topic_index, "alice")
        gossip_store.publish_digest()
        
        stats = gossip_store.stats()
        
        assert stats["known_agents"] >= 1
        assert stats["own_version"] >= 1


class TestGossipProtocol:
    """Test high-level GossipProtocol"""
    
    def test_protocol_start_stop(self, gossip_env):
        store, topic_index = gossip_env
        protocol = GossipProtocol(store, topic_index, "alice")
        
        protocol.start(interval_seconds=1)
        assert protocol._running
        
        protocol.stop()
        assert not protocol._running
    
    def test_manual_publish(self, gossip_env):
        store, topic_index = gossip_env
        protocol = GossipProtocol(store, topic_index, "alice")
        
        digest = protocol.publish()
        
        assert digest.agent_id == "alice"
        assert digest.version >= 1
    
    def test_who_knows_integration(self, gossip_env):
        store, topic_index = gossip_env
        
        # Alice and Bob both create protocols
        alice = GossipProtocol(store, topic_index, "alice")
        bob = GossipProtocol(store, topic_index, "bob")
        
        # Alice publishes (she knows about bitcoin from fixture)
        alice.publish()
        
        # Bob refreshes and queries
        bob.gossip_store.refresh()
        experts = bob.who_knows("bitcoin")
        
        # Alice should appear
        agent_ids = [a for a, _ in experts]
        assert "alice" in agent_ids
