"""
avm/gossip.py - Agent Gossip Protocol

Decentralized knowledge discovery without a central Librarian.

Each agent maintains a digest of "what I know" (topics, capabilities).
Agents periodically exchange digests to discover each other.

Architecture:
    ┌─────────┐         ┌─────────┐         ┌─────────┐
    │ Agent A │◀─────▶  │ Agent B │◀─────▶  │ Agent C │
    │ digest  │ gossip  │ digest  │ gossip  │ digest  │
    └─────────┘         └─────────┘         └─────────┘
    
    Each agent knows:
    - Its own topics (from TopicIndex)
    - Other agents' topics (from gossip)
    - How to reach other agents (tell paths)

Benefits over Librarian:
- No single point of failure
- O(1) local queries ("who knows X?")
- Eventual consistency via gossip
- Privacy: only share topics, not content

Protocol:
1. Agent A generates digest (topic bloom filter + version)
2. Agent A broadcasts digest to /gossip/{agent_id}.digest
3. Other agents read digests periodically
4. To query: check local digest cache, filter by topic overlap
"""

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from .utils import utcnow
from typing import List, Dict, Set, Optional, Tuple
from collections import defaultdict
import json

from .store import AVMStore
from .topic_index import TopicIndex


# Bloom filter parameters
BLOOM_SIZE = 1024  # bits
BLOOM_HASHES = 3


@dataclass
class AgentDigest:
    """
    Compact representation of what an agent knows.
    
    Uses a bloom filter for space-efficient topic membership testing.
    """
    agent_id: str
    version: int  # Incremented on each update
    timestamp: datetime
    
    # Topic bloom filter (compact)
    bloom: bytes = field(default_factory=lambda: bytes(BLOOM_SIZE // 8))
    
    # Topic list (for debugging/display, optional)
    topics: List[str] = field(default_factory=list)
    
    # Metadata
    memory_count: int = 0
    capabilities: List[str] = field(default_factory=list)
    
    def add_topic(self, topic: str):
        """Add a topic to the bloom filter"""
        self.topics.append(topic)
        bloom_array = bytearray(self.bloom)
        
        for i in range(BLOOM_HASHES):
            h = hashlib.md5(f"{topic}:{i}".encode()).digest()
            bit_index = int.from_bytes(h[:4], 'big') % BLOOM_SIZE
            byte_index = bit_index // 8
            bit_offset = bit_index % 8
            bloom_array[byte_index] |= (1 << bit_offset)
        
        self.bloom = bytes(bloom_array)
    
    def might_have_topic(self, topic: str) -> bool:
        """Check if this agent might know about a topic (bloom filter query)"""
        for i in range(BLOOM_HASHES):
            h = hashlib.md5(f"{topic}:{i}".encode()).digest()
            bit_index = int.from_bytes(h[:4], 'big') % BLOOM_SIZE
            byte_index = bit_index // 8
            bit_offset = bit_index % 8
            
            if not (self.bloom[byte_index] & (1 << bit_offset)):
                return False
        
        return True  # Might have (false positives possible)
    
    def to_dict(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "version": self.version,
            "timestamp": self.timestamp.isoformat(),
            "bloom": self.bloom.hex(),
            "topics": self.topics[:20],  # Limit for size
            "memory_count": self.memory_count,
            "capabilities": self.capabilities,
        }
    
    @classmethod
    def from_dict(cls, d: Dict) -> "AgentDigest":
        return cls(
            agent_id=d["agent_id"],
            version=d["version"],
            timestamp=datetime.fromisoformat(d["timestamp"]),
            bloom=bytes.fromhex(d.get("bloom", "00" * (BLOOM_SIZE // 8))),
            topics=d.get("topics", []),
            memory_count=d.get("memory_count", 0),
            capabilities=d.get("capabilities", []),
        )


@dataclass
class GossipMessage:
    """A gossip message exchanged between agents"""
    from_agent: str
    digest: AgentDigest
    ttl: int = 3  # Hops before expiry
    
    def to_dict(self) -> Dict:
        return {
            "from_agent": self.from_agent,
            "digest": self.digest.to_dict(),
            "ttl": self.ttl,
        }
    
    @classmethod
    def from_dict(cls, d: Dict) -> "GossipMessage":
        return cls(
            from_agent=d["from_agent"],
            digest=AgentDigest.from_dict(d["digest"]),
            ttl=d.get("ttl", 3),
        )


class GossipStore:
    """
    Storage for agent digests.
    
    Stores digests in /gossip/{agent_id}.digest for sharing.
    Maintains local cache of all known agent digests.
    """
    
    GOSSIP_PREFIX = "/gossip"
    
    def __init__(self, store: AVMStore, topic_index: TopicIndex, agent_id: str):
        self.store = store
        self.topic_index = topic_index
        self.agent_id = agent_id
        
        # Local cache of agent digests
        self._digest_cache: Dict[str, AgentDigest] = {}
        self._version = 0
        
        # Load existing digests
        self._load_digests()
    
    def _load_digests(self):
        """Load all digests from storage"""
        try:
            nodes = self.store.list_nodes(self.GOSSIP_PREFIX, limit=1000)
            for node in nodes:
                if node.path.endswith(".digest"):
                    try:
                        data = json.loads(node.content or "{}")
                        digest = AgentDigest.from_dict(data)
                        self._digest_cache[digest.agent_id] = digest
                    except Exception:
                        pass
        except Exception:
            pass
    
    def generate_digest(self) -> AgentDigest:
        """Generate current agent's digest from TopicIndex"""
        self._version += 1
        
        digest = AgentDigest(
            agent_id=self.agent_id,
            version=self._version,
            timestamp=utcnow(),
        )
        
        # Add topics from TopicIndex
        all_topics = self.topic_index.all_topics()
        for topic, count in sorted(all_topics.items(), 
                                   key=lambda x: -x[1])[:100]:
            digest.add_topic(topic)
        
        # Count memories
        try:
            private_path = f"/memory/private/{self.agent_id}"
            nodes = self.store.list_nodes(private_path, limit=10000)
            digest.memory_count = len(nodes)
        except Exception:
            pass
        
        return digest
    
    def publish_digest(self):
        """Publish own digest to gossip namespace"""
        digest = self.generate_digest()
        
        from .node import AVMNode
        node = AVMNode(
            path=f"{self.GOSSIP_PREFIX}/{self.agent_id}.digest",
            content=json.dumps(digest.to_dict(), indent=2),
            meta={"type": "gossip_digest", "version": digest.version},
        )
        self.store.put_node(node)
        
        # Update local cache
        self._digest_cache[self.agent_id] = digest
        
        return digest
    
    def receive_digest(self, message: GossipMessage):
        """Receive and process a gossip message"""
        digest = message.digest
        
        # Check if newer than what we have
        existing = self._digest_cache.get(digest.agent_id)
        if existing and existing.version >= digest.version:
            return False  # Already have newer
        
        # Store in cache
        self._digest_cache[digest.agent_id] = digest
        
        # Persist to storage
        from .node import AVMNode
        node = AVMNode(
            path=f"{self.GOSSIP_PREFIX}/{digest.agent_id}.digest",
            content=json.dumps(digest.to_dict(), indent=2),
            meta={"type": "gossip_digest", "version": digest.version},
        )
        self.store.put_node(node)
        
        # Forward if TTL > 0 (epidemic spread)
        if message.ttl > 0:
            self._forward_message(message)
        
        return True
    
    def _forward_message(self, message: GossipMessage):
        """Forward gossip message to other agents (future: via tell system)"""
        # For now, just decrement TTL and store
        # In practice, this would use the tell system
        pass
    
    def who_knows(self, topic: str) -> List[Tuple[str, float]]:
        """
        Find agents who might know about a topic.
        
        Returns: List of (agent_id, confidence) tuples
        """
        results = []
        
        for agent_id, digest in self._digest_cache.items():
            if digest.might_have_topic(topic.lower()):
                # Confidence based on recency
                age_hours = (utcnow() - digest.timestamp).total_seconds() / 3600
                confidence = max(0.1, 1.0 - (age_hours / 168))  # Decay over a week
                results.append((agent_id, confidence))
        
        return sorted(results, key=lambda x: -x[1])
    
    def agents(self) -> List[str]:
        """List all known agents"""
        return list(self._digest_cache.keys())
    
    def get_digest(self, agent_id: str) -> Optional[AgentDigest]:
        """Get a specific agent's digest"""
        return self._digest_cache.get(agent_id)
    
    def refresh(self):
        """Refresh all digests from storage"""
        self._load_digests()
    
    def stats(self) -> Dict:
        """Get gossip stats"""
        return {
            "known_agents": len(self._digest_cache),
            "own_version": self._version,
            "agents": [
                {
                    "id": d.agent_id,
                    "version": d.version,
                    "topics": len(d.topics),
                    "memories": d.memory_count,
                    "age_hours": (utcnow() - d.timestamp).total_seconds() / 3600,
                }
                for d in self._digest_cache.values()
            ],
        }


class GossipProtocol:
    """
    High-level gossip protocol coordinator.
    
    Usage:
        protocol = GossipProtocol(store, topic_index, "my_agent")
        protocol.start()  # Begin periodic gossip
        
        # Query
        agents = protocol.who_knows("bitcoin")
    """
    
    def __init__(self, store: AVMStore, topic_index: TopicIndex, agent_id: str):
        self.gossip_store = GossipStore(store, topic_index, agent_id)
        self._running = False
        self._thread = None
    
    def start(self, interval_seconds: int = 60):
        """Start periodic gossip in background thread"""
        import threading
        
        self._running = True
        
        def _gossip_loop():
            while self._running:
                try:
                    # Publish own digest
                    self.gossip_store.publish_digest()
                    
                    # Refresh known digests
                    self.gossip_store.refresh()
                    
                except Exception as e:
                    print(f"[Gossip] Error: {e}")
                
                time.sleep(interval_seconds)
        
        self._thread = threading.Thread(target=_gossip_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop gossip protocol"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def who_knows(self, topic: str) -> List[Tuple[str, float]]:
        """Find agents who might know about a topic"""
        return self.gossip_store.who_knows(topic)
    
    def agents(self) -> List[str]:
        """List all known agents"""
        return self.gossip_store.agents()
    
    def publish(self):
        """Manually trigger digest publication"""
        return self.gossip_store.publish_digest()
    
    def stats(self) -> Dict:
        """Get protocol stats"""
        return self.gossip_store.stats()
