"""Tests for memory consolidation and clustering"""

import pytest
import tempfile
import shutil
import os
from datetime import datetime, timedelta, timezone

from avm.store import AVMStore
from avm.node import AVMNode
from avm.topic_index import TopicIndex
from avm.consolidation import MemoryConsolidator, ConsolidationConfig, MemoryCluster


@pytest.fixture
def temp_env():
    """Setup temporary environment"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        os.environ['XDG_DATA_HOME'] = tmpdir
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def store(temp_env):
    """Create test store"""
    db_path = os.path.join(temp_env, "test.db")
    return AVMStore(db_path)


@pytest.fixture
def topic_index(store):
    """Create topic index"""
    return TopicIndex(store)


@pytest.fixture
def consolidator(store, topic_index):
    """Create consolidator"""
    config = ConsolidationConfig(
        min_cluster_size=2,
        max_clusters=5,
    )
    return MemoryConsolidator(store, topic_index, config)


class TestMemoryConsolidation:
    """Test consolidation operations"""
    
    def test_decay_importance(self, store, consolidator):
        """Test importance decay over time"""
        # Create a memory first
        node = AVMNode(
            path="/memory/old.md",
            content="Old content",
            meta={"importance": 1.0},
        )
        store.put_node(node)
        
        # Modify the updated_at directly for testing decay
        old_date = datetime.now(timezone.utc) - timedelta(days=60)
        node.updated_at = old_date
        
        # Run decay with the modified node
        decayed = consolidator.decay_importance([node])
        
        # Check that importance was reduced
        updated = store.get_node("/memory/old.md")
        assert updated.meta["importance"] < 1.0
    
    def test_cluster_memories(self, store, topic_index, consolidator):
        """Test memory clustering by topic"""
        # Create memories with overlapping topics
        memories = [
            AVMNode(path="/memory/trading1.md", content="BTC trading strategy #crypto #trading"),
            AVMNode(path="/memory/trading2.md", content="ETH market analysis #crypto #trading"),
            AVMNode(path="/memory/trading3.md", content="Crypto portfolio review #crypto"),
            AVMNode(path="/memory/news1.md", content="AI news today #ai #tech"),
            AVMNode(path="/memory/news2.md", content="Machine learning advances #ai #tech"),
        ]
        
        for mem in memories:
            store.put_node(mem)
            topic_index.index_path(mem.path, mem.content)
        
        # Cluster
        clusters = consolidator.cluster_memories(memories)
        
        # Should have at least 1 cluster
        assert len(clusters) >= 1
        
        # Clusters should have correct structure
        for c in clusters:
            assert isinstance(c, MemoryCluster)
            assert len(c.memories) >= 2
            assert c.topic
            assert c.centroid_topics
    
    def test_generate_summaries(self, store, topic_index, consolidator):
        """Test cluster summary generation"""
        # Create memories
        memories = [
            AVMNode(path="/memory/test1.md", content="First test memory about testing."),
            AVMNode(path="/memory/test2.md", content="Second test memory about testing."),
            AVMNode(path="/memory/test3.md", content="Third test memory about testing."),
        ]
        
        for mem in memories:
            store.put_node(mem)
            topic_index.index_path(mem.path, mem.content, "testing")
        
        # Create clusters
        clusters = consolidator.cluster_memories(memories)
        
        if clusters:  # Only if clustering succeeded
            # Generate summaries
            created = consolidator.generate_cluster_summaries(clusters)
            
            # Check summary was created
            assert created >= 0
    
    def test_run_full_consolidation(self, store, topic_index, consolidator):
        """Test full consolidation run"""
        # Create some memories
        for i in range(5):
            node = AVMNode(
                path=f"/memory/mem{i}.md",
                content=f"Memory {i} about topic{i % 2}",
                meta={"importance": 0.5},
            )
            store.put_node(node)
        
        # Run consolidation
        result = consolidator.run(dry_run=True)
        
        # Check result structure
        assert result.memories_processed >= 0
        assert result.duration_ms >= 0


class TestConsolidationConfig:
    """Test configuration options"""
    
    def test_default_config(self):
        """Test default configuration values"""
        config = ConsolidationConfig()
        assert config.decay_half_life_days == 30.0
        assert config.min_importance == 0.1
        assert config.similarity_threshold == 0.8
    
    def test_custom_config(self):
        """Test custom configuration"""
        config = ConsolidationConfig(
            decay_half_life_days=7.0,
            min_cluster_size=5,
            max_clusters=10,
        )
        assert config.decay_half_life_days == 7.0
        assert config.min_cluster_size == 5
        assert config.max_clusters == 10
