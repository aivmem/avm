"""
test_store.py - AVMStore test
"""

import pytest
import tempfile
import os

from avm.store import AVMStore
from avm.node import AVMNode, NodeType
from avm.graph import EdgeType


@pytest.fixture
def store():
    """Create temporary database"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    s = AVMStore(db_path)
    yield s
    
    # Cleanup
    os.unlink(db_path)


class TestAVMStore:
    """AVMStore basic tests"""
    
    def test_put_and_get_node(self, store):
        """Write and read node"""
        node = AVMNode(
            path="/memory/test.md",
            content="# Test\n\nHello world.",
        )
        
        saved = store.put_node(node)
        assert saved.version == 1
        
        loaded = store.get_node("/memory/test.md")
        assert loaded is not None
        assert loaded.content == node.content
        assert loaded.version == 1
    
    def test_update_node(self, store):
        """updatenode"""
        node = AVMNode(path="/memory/test.md", content="v1")
        store.put_node(node)
        
        node.content = "v2"
        updated = store.put_node(node)
        
        assert updated.version == 2
        
        loaded = store.get_node("/memory/test.md")
        assert loaded.content == "v2"
        assert loaded.version == 2
    
    def test_readonly_permission(self, store):
        """Read-only path permission"""
        node = AVMNode(path="/research/test.md", content="data")
        
        with pytest.raises(PermissionError):
            store.put_node(node)
    
    def test_delete_node(self, store):
        """deletenode"""
        node = AVMNode(path="/memory/test.md", content="delete me")
        store.put_node(node)
        
        result = store.delete_node("/memory/test.md")
        assert result is True
        
        loaded = store.get_node("/memory/test.md")
        assert loaded is None
    
    def test_delete_readonly(self, store):
        """Cannot delete read-only node"""
        # Create read-only node via internal method
        node = AVMNode(path="/research/test.md", content="data")
        store._put_node_internal(node)
        
        with pytest.raises(PermissionError):
            store.delete_node("/research/test.md")
    
    def test_list_nodes(self, store):
        """List nodes"""
        store.put_node(AVMNode(path="/memory/a.md", content="a"))
        store.put_node(AVMNode(path="/memory/b.md", content="b"))
        store.put_node(AVMNode(path="/memory/sub/c.md", content="c"))
        
        nodes = store.list_nodes("/memory")
        assert len(nodes) == 3
        
        nodes = store.list_nodes("/memory/sub")
        assert len(nodes) == 1


class TestFTS:
    """Full-text search tests"""
    
    def test_search(self, store):
        """Basic search"""
        store.put_node(AVMNode(
            path="/memory/lesson1.md",
            content="RSI below 30 is oversold signal"
        ))
        store.put_node(AVMNode(
            path="/memory/lesson2.md",
            content="MACD golden cross is bullish"
        ))
        
        results = store.search("RSI")
        assert len(results) >= 1
        
        paths = [n.path for n, _ in results]
        assert "/memory/lesson1.md" in paths
    
    def test_search_ranking(self, store):
        """Search ranking"""
        store.put_node(AVMNode(
            path="/memory/a.md",
            content="RSI RSI RSI multiple mentions"
        ))
        store.put_node(AVMNode(
            path="/memory/b.md",
            content="RSI single mention"
        ))
        
        results = store.search("RSI")
        # Multiple occurrences should rank higher
        assert len(results) >= 2


class TestEdges:
    """Graph tests"""
    
    def test_add_edge(self, store):
        """addedge"""
        edge = store.add_edge(
            "/research/AAPL.md",
            "/research/MSFT.md",
            EdgeType.PEER
        )
        
        assert edge.source == "/research/AAPL.md"
        assert edge.target == "/research/MSFT.md"
    
    def test_get_links(self, store):
        """Get links"""
        store.add_edge("/a", "/b", EdgeType.PEER)
        store.add_edge("/a", "/c", EdgeType.PARENT)
        store.add_edge("/d", "/a", EdgeType.CITATION)
        
        links = store.get_links("/a")
        assert len(links) == 3
        
        out_links = store.get_links("/a", direction="out")
        assert len(out_links) == 2
        
        in_links = store.get_links("/a", direction="in")
        assert len(in_links) == 1
    
    def test_load_graph(self, store):
        """Load complete graph"""
        store.add_edge("/a", "/b")
        store.add_edge("/b", "/c")
        store.add_edge("/c", "/a")
        
        graph = store.load_graph()
        
        assert graph.node_count == 3
        assert graph.edge_count == 3


class TestHistory:
    """Change history tests"""
    
    def test_diff_on_update(self, store):
        """Save diff on update"""
        node = AVMNode(path="/memory/test.md", content="version 1")
        store.put_node(node)
        
        node.content = "version 2"
        store.put_node(node)
        
        history = store.get_history("/memory/test.md")
        assert len(history) == 2
        assert history[0].version == 2
        assert history[1].version == 1
    
    def test_diff_change_type(self, store):
        """Record change type"""
        node = AVMNode(path="/memory/test.md", content="data")
        store.put_node(node)
        
        history = store.get_history("/memory/test.md")
        assert history[0].change_type == "create"
        
        node.content = "updated"
        store.put_node(node)
        
        history = store.get_history("/memory/test.md")
        assert history[0].change_type == "update"


class TestStats:
    """statisticstest"""
    
    def test_stats(self, store):
        """getstatistics"""
        store.put_node(AVMNode(path="/memory/a.md", content="a"))
        store.put_node(AVMNode(path="/memory/b.md", content="b"))
        store.add_edge("/memory/a.md", "/memory/b.md")
        
        stats = store.stats()
        
        assert stats["nodes"] == 2
        assert stats["edges"] == 1
        assert stats["diffs"] == 2
        assert stats["by_prefix"]["/memory"] == 2
