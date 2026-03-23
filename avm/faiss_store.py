"""
avm/faiss_store.py - FAISS-based vector storage

High-performance vector search using Facebook's FAISS library.
Supports:
- IVF (Inverted File) index for large-scale search
- HNSW (Hierarchical Navigable Small World) for fast approximate search
- Flat index for exact search (small datasets)

Usage:
    from avm.faiss_store import FAISSEmbeddingStore
    from avm.embedding import LocalEmbedding
    
    backend = LocalEmbedding()
    store = FAISSEmbeddingStore(avm_store, backend, index_type="flat")
    store.add_node(node)
    results = store.search("query", k=5)
"""

import os
import json
import struct
import hashlib
import pickle
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
import numpy as np

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False

from .store import AVMStore
from .node import AVMNode
from .embedding import EmbeddingBackend
from .utils import utcnow


class FAISSEmbeddingStore:
    """
    FAISS-based embedding storage with multiple index types.
    
    Index types:
    - "flat": Exact search (brute force), best for <10k vectors
    - "ivf": IVF index, good for 10k-1M vectors
    - "hnsw": HNSW index, fast approximate search
    """
    
    INDEX_TYPES = ["flat", "ivf", "hnsw"]
    
    def __init__(
        self, 
        store: AVMStore, 
        backend: EmbeddingBackend,
        index_type: str = "flat",
        index_path: str = None,
        nlist: int = 100,  # For IVF: number of clusters
        m: int = 32,       # For HNSW: number of connections
    ):
        if not FAISS_AVAILABLE:
            raise ImportError("FAISS not installed. Run: pip install faiss-cpu")
        
        self.store = store
        self.backend = backend
        self.index_type = index_type
        self.dimension = backend.dimension
        self.nlist = nlist
        self.m = m
        
        # Index file path
        if index_path:
            self.index_path = Path(index_path)
        else:
            db_dir = Path(store.db_path).parent
            self.index_path = db_dir / "faiss_index.bin"
        
        # Path to ID mapping
        self.mapping_path = self.index_path.with_suffix(".map")
        
        # Initialize or load index
        self.index: Optional[faiss.Index] = None
        self.id_to_path: Dict[int, str] = {}
        self.path_to_id: Dict[str, int] = {}
        self.next_id: int = 0
        
        self._load_or_create_index()
    
    def _load_or_create_index(self):
        """Load existing index or create new one"""
        if self.index_path.exists() and self.mapping_path.exists():
            try:
                self._load_index()
                return
            except Exception as e:
                print(f"Warning: Failed to load FAISS index: {e}")
        
        self._create_index()
    
    def _create_index(self):
        """Create a new FAISS index"""
        if self.index_type == "flat":
            # Exact L2 search
            self.index = faiss.IndexFlatIP(self.dimension)  # Inner product (cosine after normalization)
        
        elif self.index_type == "ivf":
            # IVF with flat quantizer
            quantizer = faiss.IndexFlatIP(self.dimension)
            self.index = faiss.IndexIVFFlat(quantizer, self.dimension, self.nlist)
            # Need to train with some vectors first
            self.index.nprobe = 10  # Search 10 clusters
        
        elif self.index_type == "hnsw":
            # HNSW index
            self.index = faiss.IndexHNSWFlat(self.dimension, self.m)
            self.index.hnsw.efConstruction = 40
            self.index.hnsw.efSearch = 16
        
        else:
            raise ValueError(f"Unknown index type: {self.index_type}")
        
        # Use IDMap to allow custom IDs
        self.index = faiss.IndexIDMap(self.index)
        
        self.id_to_path = {}
        self.path_to_id = {}
        self.next_id = 0
    
    def _load_index(self):
        """Load index from disk"""
        self.index = faiss.read_index(str(self.index_path))
        
        with open(self.mapping_path, "rb") as f:
            mapping = pickle.load(f)
        
        self.id_to_path = mapping["id_to_path"]
        self.path_to_id = mapping["path_to_id"]
        self.next_id = mapping["next_id"]
    
    def save(self):
        """Save index to disk"""
        faiss.write_index(self.index, str(self.index_path))
        
        mapping = {
            "id_to_path": self.id_to_path,
            "path_to_id": self.path_to_id,
            "next_id": self.next_id,
        }
        with open(self.mapping_path, "wb") as f:
            pickle.dump(mapping, f)
    
    def _normalize(self, vec: np.ndarray) -> np.ndarray:
        """Normalize vector for cosine similarity"""
        norm = np.linalg.norm(vec)
        if norm > 0:
            return vec / norm
        return vec
    
    def add_node(self, node: AVMNode, force: bool = False) -> bool:
        """
        Add a node to the index.
        
        Returns True if node was added/updated.
        """
        # Check if already indexed (skip if content unchanged)
        if not force and node.path in self.path_to_id:
            # Could check content hash here for updates
            return False
        
        # Generate embedding
        text = f"{node.path}\n\n{node.content[:2000]}"
        embedding = self.backend.embeend(text)
        vec = self._normalize(np.array([embedding], dtype=np.float32))
        
        # Remove old entry if exists
        if node.path in self.path_to_id:
            old_id = self.path_to_id[node.path]
            # FAISS doesn't support removal, so we just orphan the old ID
            del self.id_to_path[old_id]
        
        # Add to index
        new_id = self.next_id
        self.next_id += 1
        
        ids = np.array([new_id], dtype=np.int64)
        self.index.add_with_ids(vec, ids)
        
        self.id_to_path[new_id] = node.path
        self.path_to_id[node.path] = new_id
        
        return True
    
    def add_nodes(self, nodes: List[AVMNode], batch_size: int = 100) -> int:
        """
        Batch add nodes to index.
        
        Returns number of nodes added.
        """
        count = 0
        
        # Filter nodes that need embedding
        to_embed = []
        for node in nodes:
            if node.path not in self.path_to_id:
                to_embed.append(node)
        
        # Batch embed
        for i in range(0, len(to_embed), batch_size):
            batch = to_embed[i:i + batch_size]
            texts = [f"{n.path}\n\n{n.content[:2000]}" for n in batch]
            
            embeddings = self.backend.embeend_batch(texts)
            vecs = np.array(embeddings, dtype=np.float32)
            
            # Normalize
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms[norms == 0] = 1
            vecs = vecs / norms
            
            # Assign IDs
            ids = np.array(range(self.next_id, self.next_id + len(batch)), dtype=np.int64)
            
            # Add to index
            self.index.add_with_ids(vecs, ids)
            
            # Update mappings
            for j, node in enumerate(batch):
                new_id = self.next_id + j
                self.id_to_path[new_id] = node.path
                self.path_to_id[node.path] = new_id
            
            self.next_id += len(batch)
            count += len(batch)
        
        return count
    
    def search(
        self, 
        query: str, 
        k: int = 5, 
        prefix: str = None
    ) -> List[Tuple[AVMNode, float]]:
        """
        Search for similar nodes.
        
        Args:
            query: Search query text
            k: Number of results
            prefix: Filter by path prefix
        
        Returns:
            List of (node, similarity) tuples
        """
        if self.index.ntotal == 0:
            return []
        
        # Generate query embedding
        query_vec = self.backend.embeend(query)
        query_vec = self._normalize(np.array([query_vec], dtype=np.float32))
        
        # Search (get more results if filtering by prefix)
        search_k = k * 5 if prefix else k
        distances, ids = self.index.search(query_vec, min(search_k, self.index.ntotal))
        
        results = []
        for i, (dist, idx) in enumerate(zip(distances[0], ids[0])):
            if idx == -1:  # FAISS returns -1 for empty slots
                continue
            
            path = self.id_to_path.get(int(idx))
            if path is None:
                continue
            
            # Filter by prefix
            if prefix and not path.startswith(prefix):
                continue
            
            # Get node
            node = self.store.get_node(path)
            if node:
                # Convert distance to similarity (for IP index, higher is better)
                similarity = float(dist)
                results.append((node, similarity))
            
            if len(results) >= k:
                break
        
        return results
    
    def index_all(self, prefix: str = "/", limit: int = 10000) -> int:
        """Index all nodes under a prefix"""
        nodes = self.store.list_nodes(prefix, limit)
        return self.add_nodes(nodes)
    
    def stats(self) -> Dict[str, Any]:
        """Get index statistics"""
        return {
            "index_type": self.index_type,
            "dimension": self.dimension,
            "total_vectors": self.index.ntotal,
            "indexed_paths": len(self.path_to_id),
            "index_path": str(self.index_path),
            "backend": type(self.backend).__name__,
        }
    
    def rebuild(self):
        """Rebuild index from scratch"""
        self._create_index()
        self.index_all()
        self.save()


def get_faiss_store(
    store: AVMStore,
    backend: EmbeddingBackend = None,
    index_type: str = "flat",
) -> FAISSEmbeddingStore:
    """
    Get or create a FAISS embedding store.
    
    If backend is None, tries to create a LocalEmbedding.
    """
    if backend is None:
        from .embedding import LocalEmbedding
        backend = LocalEmbedding()
    
    return FAISSEmbeddingStore(store, backend, index_type)
