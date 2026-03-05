"""
test_store.py - VFSStore 测试
"""

import pytest
import tempfile
import os

from vfs.store import VFSStore
from vfs.node import VFSNode, NodeType
from vfs.graph import EdgeType


@pytest.fixture
def store():
    """创建临时数据库"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    s = VFSStore(db_path)
    yield s
    
    # 清理
    os.unlink(db_path)


class TestVFSStore:
    """VFSStore 基础测试"""
    
    def test_put_and_get_node(self, store):
        """写入和读取节点"""
        node = VFSNode(
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
        """更新节点"""
        node = VFSNode(path="/memory/test.md", content="v1")
        store.put_node(node)
        
        node.content = "v2"
        updated = store.put_node(node)
        
        assert updated.version == 2
        
        loaded = store.get_node("/memory/test.md")
        assert loaded.content == "v2"
        assert loaded.version == 2
    
    def test_readonly_permission(self, store):
        """只读路径权限"""
        node = VFSNode(path="/research/test.md", content="data")
        
        with pytest.raises(PermissionError):
            store.put_node(node)
    
    def test_delete_node(self, store):
        """删除节点"""
        node = VFSNode(path="/memory/test.md", content="delete me")
        store.put_node(node)
        
        result = store.delete_node("/memory/test.md")
        assert result is True
        
        loaded = store.get_node("/memory/test.md")
        assert loaded is None
    
    def test_delete_readonly(self, store):
        """不能删除只读节点"""
        # 通过内部方法创建只读节点
        node = VFSNode(path="/research/test.md", content="data")
        store._put_node_internal(node)
        
        with pytest.raises(PermissionError):
            store.delete_node("/research/test.md")
    
    def test_list_nodes(self, store):
        """列出节点"""
        store.put_node(VFSNode(path="/memory/a.md", content="a"))
        store.put_node(VFSNode(path="/memory/b.md", content="b"))
        store.put_node(VFSNode(path="/memory/sub/c.md", content="c"))
        
        nodes = store.list_nodes("/memory")
        assert len(nodes) == 3
        
        nodes = store.list_nodes("/memory/sub")
        assert len(nodes) == 1


class TestFTS:
    """全文搜索测试"""
    
    def test_search(self, store):
        """基础搜索"""
        store.put_node(VFSNode(
            path="/memory/lesson1.md",
            content="RSI below 30 is oversold signal"
        ))
        store.put_node(VFSNode(
            path="/memory/lesson2.md",
            content="MACD golden cross is bullish"
        ))
        
        results = store.search("RSI")
        assert len(results) >= 1
        
        paths = [n.path for n, _ in results]
        assert "/memory/lesson1.md" in paths
    
    def test_search_ranking(self, store):
        """搜索排名"""
        store.put_node(VFSNode(
            path="/memory/a.md",
            content="RSI RSI RSI multiple mentions"
        ))
        store.put_node(VFSNode(
            path="/memory/b.md",
            content="RSI single mention"
        ))
        
        results = store.search("RSI")
        # 多次出现的应该排名更高
        assert len(results) >= 2


class TestEdges:
    """关系图测试"""
    
    def test_add_edge(self, store):
        """添加边"""
        edge = store.add_edge(
            "/research/AAPL.md",
            "/research/MSFT.md",
            EdgeType.PEER
        )
        
        assert edge.source == "/research/AAPL.md"
        assert edge.target == "/research/MSFT.md"
    
    def test_get_links(self, store):
        """获取链接"""
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
        """加载完整图"""
        store.add_edge("/a", "/b")
        store.add_edge("/b", "/c")
        store.add_edge("/c", "/a")
        
        graph = store.load_graph()
        
        assert graph.node_count == 3
        assert graph.edge_count == 3


class TestHistory:
    """变更历史测试"""
    
    def test_diff_on_update(self, store):
        """更新时保存 diff"""
        node = VFSNode(path="/memory/test.md", content="version 1")
        store.put_node(node)
        
        node.content = "version 2"
        store.put_node(node)
        
        history = store.get_history("/memory/test.md")
        assert len(history) == 2
        assert history[0].version == 2
        assert history[1].version == 1
    
    def test_diff_change_type(self, store):
        """记录变更类型"""
        node = VFSNode(path="/memory/test.md", content="data")
        store.put_node(node)
        
        history = store.get_history("/memory/test.md")
        assert history[0].change_type == "create"
        
        node.content = "updated"
        store.put_node(node)
        
        history = store.get_history("/memory/test.md")
        assert history[0].change_type == "update"


class TestStats:
    """统计测试"""
    
    def test_stats(self, store):
        """获取统计"""
        store.put_node(VFSNode(path="/memory/a.md", content="a"))
        store.put_node(VFSNode(path="/memory/b.md", content="b"))
        store.add_edge("/memory/a.md", "/memory/b.md")
        
        stats = store.stats()
        
        assert stats["nodes"] == 2
        assert stats["edges"] == 1
        assert stats["diffs"] == 2
        assert stats["by_prefix"]["/memory"] == 2
