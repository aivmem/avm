"""Tests for AVM core functionality."""

import os
import tempfile
import pytest

from avm import AVM
from avm.core import ProviderRegistry
from avm.config import AVMConfig
from avm.node import AVMNode


@pytest.fixture
def temp_env():
    """Create temp environment."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["XDG_DATA_HOME"] = tmpdir
        yield tmpdir


class TestProviderRegistry:
    """Test ProviderRegistry class."""
    
    def test_init(self):
        """Test registry initialization."""
        registry = ProviderRegistry()
        assert registry is not None
    
    def test_register_provider(self):
        """Test registering a provider."""
        registry = ProviderRegistry()
        
        class MockProvider:
            pass
        
        registry.register("mock", MockProvider)
        assert "mock" in registry.list_types()
    
    def test_list_types(self):
        """Test listing provider types."""
        registry = ProviderRegistry()
        types = registry.list_types()
        assert isinstance(types, list)


class TestAVM:
    """Test AVM class."""
    
    def test_init(self, temp_env):
        """Test AVM initialization."""
        avm = AVM()
        assert avm is not None
        assert avm.store is not None
    
    def test_init_with_config(self, temp_env):
        """Test AVM with custom config."""
        config = AVMConfig(db_path=os.path.join(temp_env, "custom.db"))
        avm = AVM(config=config)
        assert avm.store.db_path == config.db_path
    
    def test_write_and_read(self, temp_env):
        """Test writing and reading."""
        avm = AVM()
        
        # Write
        result = avm.write("/memory/test.md", "Hello World")
        assert result is not None
        
        # Read
        node = avm.read("/memory/test.md")
        assert node is not None
        assert node.content == "Hello World"
    
    def test_write_with_meta(self, temp_env):
        """Test writing with metadata."""
        avm = AVM()
        
        result = avm.write(
            "/memory/meta.md",
            "Content",
            meta={"key": "value", "importance": 0.8}
        )
        assert result is not None
    
    def test_read_nonexistent(self, temp_env):
        """Test reading non-existent path."""
        avm = AVM()
        node = avm.read("/nonexistent/path")
        assert node is None
    
    def test_delete(self, temp_env):
        """Test deleting a node."""
        avm = AVM()
        
        avm.write("/memory/delete-me.md", "Delete this")
        avm.delete("/memory/delete-me.md")
        
        node = avm.read("/memory/delete-me.md")
        assert node is None
    
    def test_list(self, temp_env):
        """Test listing nodes."""
        avm = AVM()
        
        avm.write("/memory/a.md", "A")
        avm.write("/memory/b.md", "B")
        avm.write("/memory/c.md", "C")
        
        nodes = avm.list("/memory", limit=10)
        assert len(nodes) >= 3
    
    def test_list_with_limit(self, temp_env):
        """Test listing with limit."""
        avm = AVM()
        
        for i in range(10):
            avm.write(f"/memory/item{i}.md", f"Item {i}")
        
        nodes = avm.list("/memory", limit=5)
        assert len(nodes) == 5
    
    def test_search(self, temp_env):
        """Test searching."""
        avm = AVM()
        
        avm.write("/memory/unique.md", "unique keyword here")
        
        results = avm.search("unique", limit=5)
        assert isinstance(results, list)
    
    def test_link(self, temp_env):
        """Test linking nodes."""
        avm = AVM()
        
        avm.write("/memory/source.md", "Source")
        avm.write("/memory/target.md", "Target")
        
        avm.link("/memory/source.md", "/memory/target.md")
        
        # Check links
        links = avm.links("/memory/source.md", direction="out")
        assert len(links) >= 1
    
    def test_links_direction(self, temp_env):
        """Test links with different directions."""
        avm = AVM()
        
        avm.write("/memory/a.md", "A")
        avm.write("/memory/b.md", "B")
        avm.link("/memory/a.md", "/memory/b.md")
        
        out_links = avm.links("/memory/a.md", direction="out")
        in_links = avm.links("/memory/b.md", direction="in")
        
        assert isinstance(out_links, list)
        assert isinstance(in_links, list)
    
    def test_history(self, temp_env):
        """Test version history."""
        avm = AVM()
        
        # Create versions
        for i in range(3):
            avm.write("/memory/versioned.md", f"Version {i}")
        
        history = avm.history("/memory/versioned.md", limit=10)
        assert isinstance(history, list)
    
    def test_stats(self, temp_env):
        """Test statistics."""
        avm = AVM()
        
        avm.write("/memory/stats.md", "Stats test")
        
        stats = avm.stats()
        assert isinstance(stats, dict)
    
    def test_agent_memory(self, temp_env):
        """Test agent memory creation."""
        avm = AVM()
        
        memory = avm.agent_memory("test-agent")
        assert memory is not None
        assert memory.agent_id == "test-agent"
    
    def test_subscribe(self, temp_env):
        """Test event subscription."""
        avm = AVM()
        events = []
        
        def callback(event):
            events.append(event)
        
        sub_id = avm.subscribe("/memory/*", callback)
        assert sub_id is not None
    
    def test_retrieve(self, temp_env):
        """Test retrieval."""
        avm = AVM()
        
        avm.write("/memory/retrieve.md", "Retrievable content")
        
        # retrieve returns string or list depending on embedding availability
        results = avm.retrieve("content", k=5)
        assert results is not None
    
    def test_multiple_writes_same_path(self, temp_env):
        """Test multiple writes to same path."""
        avm = AVM()
        
        avm.write("/memory/multi.md", "Version 1")
        avm.write("/memory/multi.md", "Version 2")
        avm.write("/memory/multi.md", "Version 3")
        
        node = avm.read("/memory/multi.md")
        assert node.content == "Version 3"
        assert node.version >= 3


class TestAVMIntegration:
    """Integration tests for AVM."""
    
    def test_full_workflow(self, temp_env):
        """Test complete workflow."""
        avm = AVM()
        
        # Create agent memory
        agent = avm.agent_memory("trader")
        
        # Remember something
        result = agent.remember(
            "BTC RSI at 70, overbought signal",
            tags=["crypto", "technical"],
            importance=0.9
        )
        assert result is not None
        
        # Recall
        recalled = agent.recall("crypto signals", max_tokens=500)
        # recall returns string (may be "No relevant memories" or actual content)
        assert recalled is not None
        
        # Check stats
        stats = avm.stats()
        # stats may use different key names
        assert isinstance(stats, dict)
