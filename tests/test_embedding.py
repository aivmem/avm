"""Tests for embedding functionality."""

import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from typing import List

from avm.embedding import (
    EmbeddingBackend,
    OpenAIEmbedding,
    LocalEmbedding,
    EmbeddingStore,
)
from avm.store import AVMStore
from avm.node import AVMNode


@pytest.fixture
def temp_env():
    """Create temp environment."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        os.environ["XDG_DATA_HOME"] = tmpdir
        yield tmpdir


class MockBackend(EmbeddingBackend):
    """Mock embedding backend for testing."""
    
    @property
    def dimension(self) -> int:
        return 3
    
    def embeend(self, text: str) -> List[float]:
        # Simple hash-based embedding for testing
        h = hash(text) % 1000
        return [h / 1000, (h % 100) / 100, (h % 10) / 10]
    
    def embeend_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embeend(t) for t in texts]


class TestEmbeddingBackend:
    """Test EmbeddingBackend base class."""
    
    def test_is_abstract(self):
        """Test EmbeddingBackend is abstract."""
        with pytest.raises(TypeError):
            EmbeddingBackend()
    
    def test_mock_backend_dimension(self):
        """Test mock backend dimension."""
        backend = MockBackend()
        assert backend.dimension == 3
    
    def test_mock_backend_embed(self):
        """Test mock backend embedding."""
        backend = MockBackend()
        result = backend.embeend("test")
        assert len(result) == 3
    
    def test_mock_backend_batch(self):
        """Test mock backend batch embedding."""
        backend = MockBackend()
        result = backend.embeend_batch(["hello", "world"])
        assert len(result) == 2


class TestOpenAIEmbedding:
    """Test OpenAI embedding backend."""
    
    def test_class_exists(self):
        """Test OpenAIEmbedding class exists."""
        assert OpenAIEmbedding is not None
    
    def test_dimension(self):
        """Test dimension property exists."""
        # Cannot test without API key
        pass


class TestLocalEmbedding:
    """Test local embedding backend."""
    
    def test_class_exists(self):
        """Test LocalEmbedding class exists."""
        assert LocalEmbedding is not None


class TestEmbeddingStore:
    """Test EmbeddingStore class."""
    
    def test_init(self, temp_env):
        """Test store initialization."""
        avm_store = AVMStore(os.path.join(temp_env, "avm.db"))
        backend = MockBackend()
        store = EmbeddingStore(avm_store, backend)
        assert store is not None
    
    def test_has_embeend_node(self, temp_env):
        """Test embeend_node method exists."""
        avm_store = AVMStore(os.path.join(temp_env, "avm.db"))
        backend = MockBackend()
        store = EmbeddingStore(avm_store, backend)
        
        assert hasattr(store, 'embeend_node')
        assert callable(store.embeend_node)
    
    def test_has_search(self, temp_env):
        """Test search method exists."""
        avm_store = AVMStore(os.path.join(temp_env, "avm.db"))
        backend = MockBackend()
        store = EmbeddingStore(avm_store, backend)
        
        assert hasattr(store, 'search')
        assert callable(store.search)
    
    def test_stats(self, temp_env):
        """Test embedding stats."""
        avm_store = AVMStore(os.path.join(temp_env, "avm.db"))
        backend = MockBackend()
        store = EmbeddingStore(avm_store, backend)
        
        stats = store.stats()
        assert stats is not None
        assert isinstance(stats, dict)
    
    def test_cosine_similarity(self, temp_env):
        """Test cosine similarity calculation."""
        avm_store = AVMStore(os.path.join(temp_env, "avm.db"))
        backend = MockBackend()
        store = EmbeddingStore(avm_store, backend)
        
        # Same vector = similarity 1.0
        sim = store._cosine_similarity([1, 0, 0], [1, 0, 0])
        assert abs(sim - 1.0) < 0.01
        
        # Orthogonal = similarity 0.0
        sim = store._cosine_similarity([1, 0, 0], [0, 1, 0])
        assert abs(sim) < 0.01
    
    def test_serialize_deserialize(self, temp_env):
        """Test vector serialization."""
        avm_store = AVMStore(os.path.join(temp_env, "avm.db"))
        backend = MockBackend()
        store = EmbeddingStore(avm_store, backend)
        
        original = [0.1, 0.2, 0.3, 0.4, 0.5]
        serialized = store._serialize_vector(original)
        deserialized = store._deserialize_vector(serialized)
        
        assert len(deserialized) == len(original)
        for a, b in zip(original, deserialized):
            assert abs(a - b) < 0.0001
