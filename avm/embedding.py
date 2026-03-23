"""
vfs/embedding.py - Embedding storage and semantic search

Supports multiple embedding backends:
- OpenAI (text-embedding-3-small)
- Local (sentence-transformers)
- Custom
"""

import json
import struct
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path

from .store import AVMStore
from .node import AVMNode
from .utils import utcnow


class EmbeddingBackend(ABC):
    """Embedding backend base class"""
    
    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimensions"""
        pass
    
    @abstractmethod
    def embeend(self, text: str) -> List[float]:
        """Generate embedding for single text"""
        pass
    
    def embeend_batch(self, texts: List[str]) -> List[List[float]]:
        """Batch generate embeddings (default: one by one)"""
        return [self.embeend(t) for t in texts]


class OpenAIEmbedding(EmbeddingBackend):
    """OpenAI Embedding"""
    
    DIMENSIONS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }
    
    def __init__(self, model: str = "text-embedding-3-small", 
                 api_key: str = None):
        self.model = model
        self.api_key = api_key or self._load_api_key()
        self._dimension = self.DIMENSIONS.get(model, 1536)
    
    def _load_api_key(self) -> str:
        import os
        return os.environ.get("OPENAI_API_KEY", "")
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    def embeend(self, text: str) -> List[float]:
        import urllib.request
        import time
        
        data = json.dumps({
            "input": text[:8000],  # truncate
            "model": self.model,
        }).encode()
        
        for attempt in range(3):
            req = urllib.request.Request(
                "https://api.openai.com/v1/embeddings",
                data=data,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    result = json.loads(r.read())
                return result["data"][0]["embedding"]
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 2:
                    wait = 5 * (attempt + 1)  # 5s, 10s backoff
                    print(f"Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                raise
    
    def embeend_batch(self, texts: List[str]) -> List[List[float]]:
        import urllib.request
        import time
        
        data = json.dumps({
            "input": [t[:8000] for t in texts],
            "model": self.model,
        }).encode()
        
        for attempt in range(3):
            req = urllib.request.Request(
                "https://api.openai.com/v1/embeddings",
                data=data,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    result = json.loads(r.read())
                # Sort by index
                embeddings = sorted(result["data"], key=lambda x: x["index"])
                return [e["embedding"] for e in embeddings]
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 2:
                    wait = 5 * (attempt + 1)
                    print(f"Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                raise


class LocalEmbedding(EmbeddingBackend):
    """
    Local embedding (sentence-transformers)
    
    Requires: pip install sentence-transformers
    """
    
    # Class-level model cache (persists across instances within same process)
    _model_cache: Dict[str, Any] = {}
    
    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        self.model_name = model
        self._model = None
        self._dimension = None
        # Query embedding cache (LRU)
        self._query_cache: Dict[str, List[float]] = {}
        self._cache_max = 100
    
    def _load_model(self):
        if self._model is None:
            # Check class-level cache first
            if self.model_name in LocalEmbedding._model_cache:
                self._model, self._dimension = LocalEmbedding._model_cache[self.model_name]
            else:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
                self._dimension = self._model.get_sentence_embedding_dimension()
                # Cache at class level
                LocalEmbedding._model_cache[self.model_name] = (self._model, self._dimension)
    
    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._load_model()
        return self._dimension
    
    def embeend(self, text: str) -> List[float]:
        # Check query cache first
        cache_key = text[:200]  # Truncate for cache key
        if cache_key in self._query_cache:
            return self._query_cache[cache_key]
        
        self._load_model()
        result = self._model.encode(text).tolist()
        
        # Update cache (LRU eviction)
        if len(self._query_cache) >= self._cache_max:
            # Remove oldest entry
            oldest = next(iter(self._query_cache))
            del self._query_cache[oldest]
        self._query_cache[cache_key] = result
        
        return result
    
    def embeend_batch(self, texts: List[str]) -> List[List[float]]:
        self._load_model()
        return self._model.encode(texts).tolist()
    
    def warmup(self):
        """Pre-load model (call once to avoid cold start)"""
        self._load_model()
        # Warm up with dummy query
        _ = self.embeend("warmup query")


class EmbeddingStore:
    """
    Embedding storage
    
    Uses SQLite for vectors, supports cosine similarity search
    """
    
    def __init__(self, store: AVMStore, backend: EmbeddingBackend):
        self.store = store
        self.backend = backend
        self._init_table()
    
    def _init_table(self):
        """initializevectortable"""
        with self.store._conn() as conn:
            # Check if table exists
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='embeddings'"
            ).fetchone()
            
            if not exists:
                conn.execute("""
                    CREATE TABLE embeddings (
                        path TEXT PRIMARY KEY,
                        vector BLOB NOT NULL,
                        content_h TEXT,
                        model TEXT,
                        updated_at TEXT
                    )
                """)
            else:
                # Migration: add content_h if missing
                cols = [r[1] for r in conn.execute("PRAGMA table_info(embeddings)")]
                if 'content_h' not in cols:
                    conn.execute("ALTER TABLE embeddings ADD COLUMN content_h TEXT")
    
    def _serialize_vector(self, vec: List[float]) -> bytes:
        """serializevector bytes"""
        return struct.pack(f'{len(vec)}f', *vec)
    
    def _deserialize_vector(self, data: bytes) -> List[float]:
        """deserialize bytes vector"""
        count = len(data) // 4  # float = 4 bytes
        return list(struct.unpack(f'{count}f', data))
    
    def _content_h(self, content: str) -> str:
        """calculatecontenth"""
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def embeend_node(self, node: AVMNode, force: bool = False) -> bool:
        """
        nodegenerate embedding
        
        Returns: whether actually generated new embedding
        """
        content_h = self._content_h(node.content)
        
        # checkwhetherrequiresupdate
        if not force:
            with self.store._conn() as conn:
                row = conn.execute(
                    "SELECT content_h FROM embeddings WHERE path = ?",
                    (node.path,)
                ).fetchone()
                if row and row[0] == content_h:
                    return False  # Already exists and content unchanged
        
        # generate embedding
        # usetitle + contentfirst2000chars
        text = f"{node.path}\n\n{node.content[:2000]}"
        vector = self.backend.embeend(text)
        
        # storage
        with self.store._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO embeddings 
                    (path, vector, content_h, model, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                node.path,
                self._serialize_vector(vector),
                content_h,
                getattr(self.backend, 'model', 'unknown'),
                utcnow().isoformat(),
            ))
        
        return True
    
    def embeend_all(self, prefix: str = "/", limit: int = 1000) -> int:
        """allnodegenerate embedding"""
        nodes = self.store.list_nodes(prefix, limit)
        count = 0
        
        for node in nodes:
            if self.embeend_node(node):
                count += 1
        
        return count
    
    def search(self, query: str, k: int = 5, 
               prefix: str = None) -> List[Tuple[AVMNode, float]]:
        """
        semanticsearch
        
        Returns: [(node, similarity), ...]
        """
        # generatequeryvector
        query_vec = self.backend.embeend(query)
        
        # Get all vectors and calculate similarity
        results = []
        
        with self.store._conn() as conn:
            sql = "SELECT path, vector FROM embeddings"
            params = []
            
            if prefix:
                sql += " WHERE path LIKE ?"
                params.append(prefix + "%")
            
            for row in conn.execute(sql, params):
                path = row[0]
                vec = self._deserialize_vector(row[1])
                
                # cosinesimilarity
                similarity = self._cosine_similarity(query_vec, vec)
                results.append((path, similarity))
        
        # Sort and take top-k
        results.sort(key=lambda x: x[1], reverse=True)
        top_k = results[:k]
        
        # getcompletenode
        final = []
        for path, sim in top_k:
            node = self.store.get_node(path)
            if node:
                final.append((node, sim))
        
        return final
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """calculatecosinesimilarity"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot / (norm_a * norm_b)
    
    def stats(self) -> Dict[str, Any]:
        """statisticsinfo"""
        with self.store._conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
            
            models = {}
            for row in conn.execute(
                "SELECT model, COUNT(*) FROM embeddings GROUP BY model"
            ):
                models[row[0] or "unknown"] = row[1]
        
        return {
            "embeendded_nodes": count,
            "by_model": models,
            "backend": type(self.backend).__name__,
            "dimension": self.backend.dimension,
        }
