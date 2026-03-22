"""Tests for TopicIndex"""

import pytest
import tempfile
from pathlib import Path

from avm.store import AVMStore
from avm.topic_index import TopicIndex, STOP_WORDS


@pytest.fixture
def topic_index():
    """Create a topic index with temp database"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = AVMStore(str(db_path))
        yield TopicIndex(store)


class TestTopicExtraction:
    """Test topic extraction from content"""
    
    def test_extract_hashtags(self, topic_index):
        content = "Working on #trading system with #crypto integration"
        topics = topic_index.extract_topics(content)
        assert "trading" in topics
        assert "crypto" in topics
    
    def test_extract_proper_nouns(self, topic_index):
        content = "Analysis of NVDA stock performance in March"
        topics = topic_index.extract_topics(content)
        assert "nvda" in topics
        assert "march" in topics
    
    def test_extract_from_title(self, topic_index):
        content = "Some generic content here"
        topics = topic_index.extract_topics(content, title="Bitcoin Analysis Report")
        assert "bitcoin" in topics
        assert "analysis" in topics
        assert "report" in topics
    
    def test_filters_stop_words(self, topic_index):
        content = "The quick brown fox jumps over the lazy dog"
        topics = topic_index.extract_topics(content)
        assert "the" not in topics
        # 'quick', 'brown', 'jumps', 'lazy' should be present
        assert "quick" in topics or "brown" in topics
        assert len(topics) > 0
    
    def test_max_topics_limit(self, topic_index):
        content = " ".join([f"word{i}" for i in range(100)])
        topics = topic_index.extract_topics(content)
        assert len(topics) <= 20


class TestIndexing:
    """Test path indexing"""
    
    def test_index_path(self, topic_index):
        topic_index.index_path(
            "/memory/trading/btc.md",
            "Bitcoin price analysis showing bullish patterns"
        )
        
        paths = topic_index.paths_for_topic("bitcoin")
        assert "/memory/trading/btc.md" in paths
    
    def test_index_multiple_paths(self, topic_index):
        topic_index.index_path("/memory/a.md", "Bitcoin trading strategy")
        topic_index.index_path("/memory/b.md", "Bitcoin market analysis")
        
        paths = topic_index.paths_for_topic("bitcoin")
        assert len(paths) == 2
    
    def test_remove_path(self, topic_index):
        topic_index.index_path("/memory/test.md", "Bitcoin analysis")
        assert "/memory/test.md" in topic_index.paths_for_topic("bitcoin")
        
        topic_index.remove_path("/memory/test.md")
        assert "/memory/test.md" not in topic_index.paths_for_topic("bitcoin")
    
    def test_reindex_path_updates_topics(self, topic_index):
        topic_index.index_path("/memory/note.md", "Bitcoin trading")
        assert "bitcoin" in topic_index.topics_for_path("/memory/note.md")
        
        # Re-index with different content
        topic_index.index_path("/memory/note.md", "Ethereum staking")
        topics = topic_index.topics_for_path("/memory/note.md")
        assert "ethereum" in topics
        # Bitcoin should be gone
        assert "bitcoin" not in topics


class TestQuerying:
    """Test topic-based queries"""
    
    def test_query_single_topic(self, topic_index):
        topic_index.index_path("/memory/btc.md", "Bitcoin price analysis")
        topic_index.index_path("/memory/eth.md", "Ethereum gas fees")
        
        results = topic_index.query("bitcoin")
        paths = [p for p, _ in results]
        assert "/memory/btc.md" in paths
    
    def test_query_multiple_topics(self, topic_index):
        topic_index.index_path("/memory/a.md", "Bitcoin trading strategy")
        topic_index.index_path("/memory/b.md", "Trading psychology tips")
        
        results = topic_index.query("bitcoin trading")
        # Path a should score higher (both topics match)
        assert results[0][0] == "/memory/a.md"
    
    def test_query_specificity_scoring(self, topic_index):
        # Add a common topic to many paths
        for i in range(10):
            topic_index.index_path(f"/memory/common{i}.md", "Market analysis")
        
        # Add a specific topic to one path
        topic_index.index_path("/memory/specific.md", "NVDA RSI overbought signal")
        
        results = topic_index.query("NVDA signal")
        # Specific path should score high
        paths = [p for p, _ in results]
        assert "/memory/specific.md" in paths[:3]
    
    def test_query_empty_results(self, topic_index):
        topic_index.index_path("/memory/btc.md", "Bitcoin analysis")
        
        results = topic_index.query("completely unrelated xyz123")
        assert len(results) == 0


class TestSimilarity:
    """Test topic similarity"""
    
    def test_similar_topics(self, topic_index):
        # Create co-occurring topics
        topic_index.index_path("/memory/crypto1.md", "Bitcoin trading analysis")
        topic_index.index_path("/memory/crypto2.md", "Bitcoin price trading")
        topic_index.index_path("/memory/crypto3.md", "Ethereum trading")
        
        similar = topic_index.similar_topics("trading")
        topics = [t for t, _ in similar]
        # Bitcoin appears with trading more often
        assert "bitcoin" in topics
    
    def test_similar_topics_empty(self, topic_index):
        similar = topic_index.similar_topics("nonexistent")
        assert similar == []


class TestStats:
    """Test statistics"""
    
    def test_stats_empty(self, topic_index):
        stats = topic_index.stats()
        assert stats["total_topics"] == 0
        assert stats["total_paths"] == 0
    
    def test_stats_populated(self, topic_index):
        topic_index.index_path("/memory/a.md", "Bitcoin trading")
        topic_index.index_path("/memory/b.md", "Ethereum staking")
        
        stats = topic_index.stats()
        assert stats["total_topics"] > 0
        assert stats["total_paths"] == 2
    
    def test_all_topics(self, topic_index):
        topic_index.index_path("/memory/a.md", "Bitcoin trading analysis")
        topic_index.index_path("/memory/b.md", "Bitcoin price")
        
        all_topics = topic_index.all_topics()
        assert "bitcoin" in all_topics
        assert all_topics["bitcoin"] == 2  # 2 paths


class TestPersistence:
    """Test SQLite persistence"""
    
    def test_index_persists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            
            # Create and populate index
            store1 = AVMStore(str(db_path))
            idx1 = TopicIndex(store1)
            idx1.index_path("/memory/test.md", "Bitcoin analysis")
            
            # Create new index from same DB
            store2 = AVMStore(str(db_path))
            idx2 = TopicIndex(store2)
            
            # Should load persisted data
            paths = idx2.paths_for_topic("bitcoin")
            assert "/memory/test.md" in paths
