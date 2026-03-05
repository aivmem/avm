"""
test_graph.py - KVGraph 测试
"""

import pytest

from vfs.graph import KVGraph, Edge, EdgeType


class TestEdge:
    """Edge 测试"""
    
    def test_create_edge(self):
        """创建边"""
        edge = Edge(
            source="/research/AAPL.md",
            target="/research/MSFT.md",
            edge_type=EdgeType.PEER,
            weight=0.8,
        )
        
        assert edge.source == "/research/AAPL.md"
        assert edge.target == "/research/MSFT.md"
        assert edge.edge_type == EdgeType.PEER
        assert edge.weight == 0.8
    
    def test_edge_to_tuple(self):
        """边转元组"""
        edge = Edge(
            source="/a",
            target="/b",
            edge_type=EdgeType.CITATION,
            weight=1.5,
        )
        
        t = edge.to_tuple()
        assert t == ("/a", "/b", "citation", 1.5)


class TestKVGraph:
    """KVGraph 测试"""
    
    def test_add_edge(self):
        """添加边"""
        g = KVGraph()
        
        edge = g.add_edge("/a", "/b", EdgeType.PEER)
        
        assert edge.source == "/a"
        assert edge.target == "/b"
        assert g.edge_count == 1
        assert g.node_count == 2
    
    def test_remove_edge(self):
        """删除边"""
        g = KVGraph()
        g.add_edge("/a", "/b", EdgeType.PEER)
        g.add_edge("/a", "/c", EdgeType.PARENT)
        
        removed = g.remove_edge("/a", "/b")
        
        assert removed == 1
        assert g.edge_count == 1
    
    def test_get_outgoing(self):
        """获取出边"""
        g = KVGraph()
        g.add_edge("/a", "/b", EdgeType.PEER)
        g.add_edge("/a", "/c", EdgeType.PARENT)
        g.add_edge("/b", "/d", EdgeType.PEER)
        
        edges = g.get_outgoing("/a")
        
        assert len(edges) == 2
        targets = {e.target for e in edges}
        assert targets == {"/b", "/c"}
    
    def test_get_outgoing_filtered(self):
        """按类型过滤出边"""
        g = KVGraph()
        g.add_edge("/a", "/b", EdgeType.PEER)
        g.add_edge("/a", "/c", EdgeType.PARENT)
        
        edges = g.get_outgoing("/a", EdgeType.PEER)
        
        assert len(edges) == 1
        assert edges[0].target == "/b"
    
    def test_get_incoming(self):
        """获取入边"""
        g = KVGraph()
        g.add_edge("/a", "/c", EdgeType.PEER)
        g.add_edge("/b", "/c", EdgeType.PEER)
        
        edges = g.get_incoming("/c")
        
        assert len(edges) == 2
        sources = {e.source for e in edges}
        assert sources == {"/a", "/b"}
    
    def test_get_neighbors(self):
        """获取邻居"""
        g = KVGraph()
        g.add_edge("/a", "/b")
        g.add_edge("/c", "/a")
        
        neighbors = g.get_neighbors("/a")
        
        assert neighbors == {"/b", "/c"}
    
    def test_find_path(self):
        """查找路径"""
        g = KVGraph()
        g.add_edge("/a", "/b")
        g.add_edge("/b", "/c")
        g.add_edge("/c", "/d")
        
        path = g.find_path("/a", "/d")
        
        assert path == ["/a", "/b", "/c", "/d"]
    
    def test_find_path_not_found(self):
        """路径不存在"""
        g = KVGraph()
        g.add_edge("/a", "/b")
        g.add_edge("/c", "/d")
        
        path = g.find_path("/a", "/d")
        
        assert path is None
    
    def test_get_subgraph(self):
        """获取子图"""
        g = KVGraph()
        g.add_edge("/a", "/b")
        g.add_edge("/b", "/c")
        g.add_edge("/c", "/d")
        g.add_edge("/x", "/y")  # 不连通
        
        sub = g.get_subgraph("/a", depth=2)
        
        assert sub.node_count >= 3  # a, b, c
        assert sub.edge_count >= 2
    
    def test_to_adjacency_list(self):
        """导出邻接表"""
        g = KVGraph()
        g.add_edge("/a", "/b", EdgeType.PEER)
        g.add_edge("/a", "/c", EdgeType.PARENT)
        
        adj = g.to_adjacency_list()
        
        assert "/a" in adj
        assert len(adj["/a"]) == 2
