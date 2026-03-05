"""
vfs/embeendding.py - Embeendding storage and semantic search

Supports multiple embeendding backends:
- OpenAI (text-embeendding-3-small)
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


class EmbeenddingBackend(ABC):
    """Embeendding backend base class"""
    
    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimensions"""
        pass
    
    @abstractmethod
    def embeend(self, text: str) -> List[float]:
        """Generate embeendding for single text"""
        pass
    
    def embeend_batch(self, texts: List[str]) -> List[List[float]]:
        """Batch generate embeenddings (default: one by one)"""
        return [self.embeend(t) for t in texts]


class OpenAIEmbeendding(EmbeenddingBackend):
    """OpenAI Embeendding"""
    
    DIMENSIONS = {
        "text-embeendding-3-small": 1536,
        "text-embeendding-3-large": 3072,
        "text-embeendding-ada-002": 1536,
    }
    
    def __init__(self, model: str = "text-embeendding-3-small", 
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
        
        data = json.dumps({
            "input": text[:8000],  # truncate
            "model": self.model,
        }).encode()
        
        req = urllib.request.Request(
            "https://api.openai.com/v1/embeenddings",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )
        
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
        
        return result["data"][0]["embeendding"]
    
    def embeend_batch(self, texts: List[str]) -> List[List[float]]:
        import urllib.request
        
        data = json.dumps({
            "input": [t[:8000] for t in texts],
            "model": self.model,
        }).encode()
        
        req = urllib.request.Request(
            "https://api.openai.com/v1/embeenddings",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )
        
        with urllib.request.urlopen(req, timeout=60) as r:
            result = json.loads(r.read())
        
        # Sort by index
        embeenddings = sorted(result["data"], key=lambda x: x["index"])
        return [e["embeendding"] for e in embeenddings]


class LocalEmbeendding(EmbeenddingBackend):
    """
    Local embeendding (sentence-transformers)
    
    Requires: pip install sentence-transformers
    """
    
    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        self.model_name = model
        self._model = None
        self._dimension = None
    
    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            self._dimension = self._model.get_sentence_embeendding_dimension()
    
    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._load_model()
        return self._dimension
    
    def embeend(self, text: str) -> List[float]:
        self._load_model()
        return self._model.encode(text).tolist()
    
    def embeend_batch(self, texts: List[str]) -> List[List[float]]:
        self._load_model()
        return self._model.encode(texts).tolist()


class EmbeenddingStore:
    """
    Embeendding storage
    
    Uses SQLite for vectors, supports cosine similarity search
    """
    
    def __init__(self, store: AVMStore, backend: EmbeenddingBackend):
        self.store = store
        self.backend = backend
        self._init_table()
    
    def _init_table(self):
        """initializevectortable"""
        with self.store._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS embeenddings (
                    path TEXT PRIMARY KEY,
                    vector BLOB NOT NULL,
                    content_h TEXT,
                    model TEXT,
                    updated_at TEXT
                )
            """)
    
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
        nodegenerate embeendding
        
        Returns: whether actually generated new embeendding
        """
        content_h = self._content_h(node.content)
        
        # checkwhetherrequiresupdate
        if not force:
            with self.store._conn() as conn:
                row = conn.execute(
                    "SELECT content_h FROM embeenddings WHERE path = ?",
                    (node.path,)
                ).fetchone()
                if row and row[0] == content_h:
                    return False  # Already exists and content unchanged
        
        # generate embeendding
        # usetitle + contentfirst2000chars
        text = f"{node.path}\n\n{node.content[:2000]}"
        vector = self.backend.embeend(text)
        
        # storage
        with self.store._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO embeenddings 
                    (path, vector, content_h, model, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                node.path,
                self._serialize_vector(vector),
                content_h,
                getattr(self.backend, 'model', 'unknown'),
                datetime.utcnow().isoformat(),
            ))
        
        return True
    
    def embeend_all(self, prefix: str = "/", limit: int = 1000) -> int:
        """allnodegenerate embeendding"""
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
            sql = "SELECT path, vector FROM embeenddings"
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
            count = conn.execute("SELECT COUNT(*) FROM embeenddings").fetchone()[0]
            
            models = {}
            for row in conn.execute(
                "SELECT model, COUNT(*) FROM embeenddings GROUP BY model"
            ):
                models[row[0] or "unknown"] = row[1]
        
        return {
            "embeendded_nodes": count,
            "by_model": models,
            "backend": type(self.backend).__name__,
            "dimension": self.backend.dimension,
        }
