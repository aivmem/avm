"""
test_node.py - VFSNode 测试
"""

import pytest
from datetime import datetime

from vfs.node import VFSNode, NodeDiff, NodeType, Permission


class TestVFSNode:
    """VFSNode 基础测试"""
    
    def test_create_node(self):
        """创建节点"""
        node = VFSNode(
            path="/memory/test.md",
            content="# Test\n\nContent here.",
        )
        
        assert node.path == "/memory/test.md"
        assert "Test" in node.content
        assert node.version == 1
        assert node.node_type == NodeType.FILE
    
    def test_writable_path(self):
        """可写路径检测"""
        memory_node = VFSNode(path="/memory/test.md")
        assert memory_node.is_writable is True
        
        research_node = VFSNode(path="/research/AAPL.md")
        assert research_node.is_writable is False
        
        live_node = VFSNode(path="/live/positions.md")
        assert live_node.is_writable is False
    
    def test_live_node(self):
        """Live 节点检测"""
        live_node = VFSNode(
            path="/live/positions.md",
            meta={"ttl_seconds": 60}
        )
        assert live_node.is_live is True
        assert live_node.ttl_seconds == 60
        
        static_node = VFSNode(path="/research/AAPL.md")
        assert static_node.is_live is False
        assert static_node.ttl_seconds is None
    
    def test_content_hash(self):
        """内容哈希"""
        node1 = VFSNode(path="/memory/a.md", content="Hello")
        node2 = VFSNode(path="/memory/b.md", content="Hello")
        node3 = VFSNode(path="/memory/c.md", content="World")
        
        assert node1.content_hash == node2.content_hash
        assert node1.content_hash != node3.content_hash
    
    def test_to_dict_from_dict(self):
        """序列化/反序列化"""
        node = VFSNode(
            path="/memory/test.md",
            content="Content",
            meta={"key": "value"},
            version=5,
        )
        
        data = node.to_dict()
        restored = VFSNode.from_dict(data)
        
        assert restored.path == node.path
        assert restored.content == node.content
        assert restored.meta == node.meta
        assert restored.version == node.version


class TestNodeDiff:
    """NodeDiff 测试"""
    
    def test_create_diff(self):
        """创建 diff"""
        diff = NodeDiff(
            node_path="/memory/test.md",
            version=2,
            old_hash="abc123",
            new_hash="def456",
            diff_content="- old\n+ new",
            change_type="update",
        )
        
        assert diff.node_path == "/memory/test.md"
        assert diff.version == 2
        assert diff.change_type == "update"
    
    def test_diff_to_dict(self):
        """Diff 序列化"""
        diff = NodeDiff(
            node_path="/memory/test.md",
            version=1,
            old_hash=None,
            new_hash="abc",
            diff_content="content",
            change_type="create",
        )
        
        data = diff.to_dict()
        assert data["node_path"] == "/memory/test.md"
        assert data["change_type"] == "create"
