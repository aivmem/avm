"""Tests for FAISS-based embedding store"""

import pytest
import tempfile
import os
from typing import List

from avm.store import AVMStore
from avm.node import AVMNode

# Check if FAISS is available
try:
    from avm.faiss_store import FAISSEmbeddingStore, FAISS_AVAILABLE
except ImportError:
    FAISS_AVAILABLE = False


class MockBackend:
    """Mock embedding backend for testing"""
    
    def __init__(self, dimension: int = 128):
        self._dimension = dimension
        self._cache = {}
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    def embeend(self, text: str) -> List[float]:
        """Generate deterministic pseudo-embedding"""
        import hashlib
        import random
        
        if text in self._cache:
            return self._cache[text]
        
        h = hashlib.sha256(text.encode()).digest()
        random.seed(int.from_bytes(h[:4], 'little'))
        vec = [random.gauss(0, 1) for _ in range(self._dimension)]
        # Normalize
        norm = sum(x*x for x in vec) ** 0.5
        vec = [x / norm for x in vec]
        self._cache[text] = vec
        return vec
    
    def embeend_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embeend(t) for t in texts]


@pytest.fixture
def temp_env():
    """Setup temporary environment"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield tmpdir


@pytest.fixture
def store(temp_env):
    """Create test AVMStore"""
    return AVMStore(os.path.join(temp_env, "test.db"))


@pytest.fixture
def backend():
    """Create mock embedding backend"""
    return MockBackend()


@pytest.mark.skipif(not FAISS_AVAILABLE, reason="FAISS not installed")
class TestFAISSEmbeddingStore:
    """Tests for FAISSEmbeddingStore"""
    
    def test_create_flat_index(self, store, backend, temp_env):
        """Test creating a flat index"""
        faiss_store = FAISSEmbeddingStore(
            store, backend, 
            index_type="flat",
            index_path=os.path.join(temp_env, "test.bin")
        )
        
        assert faiss_store.index_type == "flat"
        assert faiss_store.dimension == backend.dimension
        assert faiss_store.index.ntotal == 0
    
    def test_create_hnsw_index(self, store, backend, temp_env):
        """Test creating an HNSW index"""
        faiss_store = FAISSEmbeddingStore(
            store, backend,
            index_type="hnsw",
            index_path=os.path.join(temp_env, "test.bin")
        )
        
        assert faiss_store.index_type == "hnsw"
    
    def test_add_node(self, store, backend, temp_env):
        """Test adding a single node"""
        node = AVMNode(path="/memory/shared/test/doc.md", content="Test document about AI")
        store.put_node(node)
        
        faiss_store = FAISSEmbeddingStore(
            store, backend,
            index_path=os.path.join(temp_env, "test.bin")
        )
        
        added = faiss_store.add_node(node)
        assert added is True
        assert faiss_store.index.ntotal == 1
        
        # Adding same node again should skip
        added = faiss_store.add_node(node)
        assert added is False
    
    def test_add_nodes_batch(self, store, backend, temp_env):
        """Test batch adding nodes"""
        nodes = [
            AVMNode(path=f"/memory/shared/doc{i}.md", content=f"Document {i} about topic {i % 3}")
            for i in range(10)
        ]
        for n in nodes:
            store.put_node(n)
        
        faiss_store = FAISSEmbeddingStore(
            store, backend,
            index_path=os.path.join(temp_env, "test.bin")
        )
        
        count = faiss_store.add_nodes(nodes)
        assert count == 10
        assert faiss_store.index.ntotal == 10
    
    def test_search(self, store, backend, temp_env):
        """Test searching for similar nodes"""
        nodes = [
            AVMNode(path="/memory/shared/ai.md", content="Artificial intelligence and machine learning"),
            AVMNode(path="/memory/shared/market.md", content="Stock market analysis and trading"),
            AVMNode(path="/memory/shared/code.md", content="Python programming and software development"),
        ]
        for n in nodes:
            store.put_node(n)
        
        faiss_store = FAISSEmbeddingStore(
            store, backend,
            index_path=os.path.join(temp_env, "test.bin")
        )
        faiss_store.add_nodes(nodes)
        
        results = faiss_store.search("AI machine learning", k=2)
        
        assert len(results) <= 2
        assert all(isinstance(r[0], AVMNode) for r in results)
        assert all(isinstance(r[1], float) for r in results)
    
    def test_search_with_prefix(self, store, backend, temp_env):
        """Test searching with path prefix filter"""
        nodes = [
            AVMNode(path="/memory/private/agent1/doc.md", content="Agent 1 memory"),
            AVMNode(path="/memory/private/agent2/doc.md", content="Agent 2 memory"),
            AVMNode(path="/memory/shared/doc.md", content="Shared memory"),
        ]
        for n in nodes:
            store.put_node(n)
        
        faiss_store = FAISSEmbeddingStore(
            store, backend,
            index_path=os.path.join(temp_env, "test.bin")
        )
        faiss_store.add_nodes(nodes)
        
        # Search only agent1's memory
        results = faiss_store.search("memory", k=5, prefix="/memory/private/agent1")
        
        assert len(results) <= 1
        if results:
            assert results[0][0].path.startswith("/memory/private/agent1")
    
    def test_save_and_load(self, store, backend, temp_env):
        """Test saving and loading index"""
        nodes = [
            AVMNode(path=f"/memory/shared/doc{i}.md", content=f"Document {i}")
            for i in range(5)
        ]
        for n in nodes:
            store.put_node(n)
        
        index_path = os.path.join(temp_env, "test.bin")
        
        # Create and save
        faiss_store = FAISSEmbeddingStore(
            store, backend,
            index_path=index_path
        )
        faiss_store.add_nodes(nodes)
        faiss_store.save()
        
        # Load in new instance
        faiss_store2 = FAISSEmbeddingStore(
            store, backend,
            index_path=index_path
        )
        
        assert faiss_store2.index.ntotal == 5
        assert len(faiss_store2.path_to_id) == 5
    
    def test_stats(self, store, backend, temp_env):
        """Test stats output"""
        nodes = [
            AVMNode(path=f"/memory/shared/doc{i}.md", content=f"Document {i}")
            for i in range(3)
        ]
        for n in nodes:
            store.put_node(n)
        
        faiss_store = FAISSEmbeddingStore(
            store, backend,
            index_path=os.path.join(temp_env, "test.bin")
        )
        faiss_store.add_nodes(nodes)
        
        stats = faiss_store.stats()
        
        assert stats["index_type"] == "flat"
        assert stats["total_vectors"] == 3
        assert stats["indexed_paths"] == 3
        assert stats["dimension"] == backend.dimension
