#!/usr/bin/env python3
"""
Embedding Store Benchmark

Compares:
1. SQLite-based EmbeddingStore (brute force cosine)
2. FAISS Flat index (exact search)
3. FAISS HNSW index (approximate search)

Measures:
- Index build time
- Query latency
- Memory usage
- Recall (for approximate methods)
"""

import os
import sys
import time
import json
import random
import tempfile
import argparse
from typing import List, Dict, Tuple
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from avm.store import AVMStore
from avm.node import AVMNode


@dataclass
class EmbeddingBenchConfig:
    """Benchmark configuration"""
    num_documents: int = 1000
    embedding_dim: int = 384  # MiniLM dimension
    query_count: int = 100
    k: int = 10
    seed: int = 42


@dataclass
class EmbeddingBenchResult:
    """Benchmark results"""
    store_type: str = ""
    
    # Build
    build_time_sec: float = 0.0
    
    # Query
    avg_query_ms: float = 0.0
    p50_query_ms: float = 0.0
    p99_query_ms: float = 0.0
    
    # Accuracy (for approximate methods)
    recall_at_k: float = 1.0  # Compared to brute force
    
    # Scale
    num_documents: int = 0
    num_queries: int = 0
    
    def to_dict(self) -> Dict:
        return {
            "store_type": self.store_type,
            "build_time_sec": round(self.build_time_sec, 3),
            "latency_ms": {
                "avg": round(self.avg_query_ms, 3),
                "p50": round(self.p50_query_ms, 3),
                "p99": round(self.p99_query_ms, 3),
            },
            "recall_at_k": round(self.recall_at_k, 4),
            "scale": {
                "documents": self.num_documents,
                "queries": self.num_queries,
            }
        }


class MockEmbeddingBackend:
    """Mock embedding backend for benchmarking (no actual model)"""
    
    def __init__(self, dimension: int = 384):
        self._dimension = dimension
        self._cache: Dict[str, List[float]] = {}
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    def embeend(self, text: str) -> List[float]:
        """Generate deterministic pseudo-embedding based on text hash"""
        if text in self._cache:
            return self._cache[text]
        
        import hashlib
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


class EmbeddingBenchmark:
    """Benchmark harness for embedding stores"""
    
    def __init__(self, config: EmbeddingBenchConfig):
        self.config = config
        self.tmpdir = tempfile.mkdtemp()
        self.store = AVMStore(os.path.join(self.tmpdir, "bench.db"))
        self.backend = MockEmbeddingBackend(config.embedding_dim)
        
        random.seed(config.seed)
        
        # Ground truth results (from brute force)
        self.ground_truth: Dict[str, List[str]] = {}
        
        # Generate documents
        self.documents: List[AVMNode] = []
        self.queries: List[str] = []
    
    def setup(self):
        """Generate synthetic documents and queries"""
        print(f"Generating {self.config.num_documents} documents...")
        
        topics = ["ai", "market", "code", "research", "personal"]
        
        for i in range(self.config.num_documents):
            topic = random.choice(topics)
            content = f"Document {i} about {topic}. " + " ".join(
                [random.choice(["neural", "stock", "function", "paper", "note"]) 
                 for _ in range(20)]
            )
            
            node = AVMNode(
                path=f"/memory/doc_{i:05d}.md",
                content=content,
            )
            self.documents.append(node)
            self.store.put_node(node)
        
        # Generate queries
        print(f"Generating {self.config.query_count} queries...")
        for i in range(self.config.query_count):
            query = f"query {i} about " + random.choice(topics)
            self.queries.append(query)
    
    def benchmark_sqlite(self) -> EmbeddingBenchResult:
        """Benchmark SQLite-based embedding store"""
        from avm.embedding import EmbeddingStore
        
        result = EmbeddingBenchResult(
            store_type="sqlite",
            num_documents=len(self.documents),
            num_queries=len(self.queries),
        )
        
        # Build index
        store = EmbeddingStore(self.store, self.backend)
        
        start = time.perf_counter()
        for node in self.documents:
            store.embeend_node(node)
        result.build_time_sec = time.perf_counter() - start
        
        # Query benchmark
        latencies = []
        for query in self.queries:
            start = time.perf_counter()
            results = store.search(query, k=self.config.k)
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)
            
            # Store ground truth
            self.ground_truth[query] = [r[0].path for r in results]
        
        latencies.sort()
        result.avg_query_ms = sum(latencies) / len(latencies)
        result.p50_query_ms = latencies[len(latencies) // 2]
        result.p99_query_ms = latencies[int(len(latencies) * 0.99)]
        result.recall_at_k = 1.0  # Ground truth
        
        return result
    
    def benchmark_faiss(self, index_type: str = "flat") -> EmbeddingBenchResult:
        """Benchmark FAISS-based embedding store"""
        from avm.faiss_store import FAISSEmbeddingStore
        
        result = EmbeddingBenchResult(
            store_type=f"faiss-{index_type}",
            num_documents=len(self.documents),
            num_queries=len(self.queries),
        )
        
        # Build index
        index_path = os.path.join(self.tmpdir, f"faiss_{index_type}.bin")
        store = FAISSEmbeddingStore(
            self.store, self.backend, 
            index_type=index_type,
            index_path=index_path,
        )
        
        start = time.perf_counter()
        store.add_nodes(self.documents)
        result.build_time_sec = time.perf_counter() - start
        
        # Query benchmark
        latencies = []
        total_recall = 0
        
        for query in self.queries:
            start = time.perf_counter()
            results = store.search(query, k=self.config.k)
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)
            
            # Calculate recall vs ground truth
            if query in self.ground_truth:
                result_paths = set(r[0].path for r in results)
                truth_paths = set(self.ground_truth[query])
                if truth_paths:
                    recall = len(result_paths & truth_paths) / len(truth_paths)
                    total_recall += recall
        
        latencies.sort()
        result.avg_query_ms = sum(latencies) / len(latencies)
        result.p50_query_ms = latencies[len(latencies) // 2]
        result.p99_query_ms = latencies[int(len(latencies) * 0.99)]
        result.recall_at_k = total_recall / len(self.queries) if self.queries else 1.0
        
        return result
    
    def run_all(self) -> List[EmbeddingBenchResult]:
        """Run all benchmarks"""
        results = []
        
        # SQLite (baseline)
        print("\n=== SQLite (brute force) ===")
        results.append(self.benchmark_sqlite())
        print(f"  Build: {results[-1].build_time_sec:.2f}s, Query: {results[-1].avg_query_ms:.2f}ms")
        
        # FAISS Flat
        print("\n=== FAISS Flat (exact) ===")
        results.append(self.benchmark_faiss("flat"))
        print(f"  Build: {results[-1].build_time_sec:.2f}s, Query: {results[-1].avg_query_ms:.2f}ms, Recall: {results[-1].recall_at_k:.2%}")
        
        # FAISS HNSW
        print("\n=== FAISS HNSW (approximate) ===")
        results.append(self.benchmark_faiss("hnsw"))
        print(f"  Build: {results[-1].build_time_sec:.2f}s, Query: {results[-1].avg_query_ms:.2f}ms, Recall: {results[-1].recall_at_k:.2%}")
        
        return results
    
    def cleanup(self):
        """Cleanup"""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Embedding Store Benchmark")
    parser.add_argument("--documents", "-d", type=int, default=1000, help="Number of documents")
    parser.add_argument("--queries", "-q", type=int, default=100, help="Number of queries")
    parser.add_argument("--k", type=int, default=10, help="Top-k results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    config = EmbeddingBenchConfig(
        num_documents=args.documents,
        query_count=args.queries,
        k=args.k,
    )
    
    bench = EmbeddingBenchmark(config)
    bench.setup()
    results = bench.run_all()
    bench.cleanup()
    
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        print("\n" + "=" * 60)
        print("EMBEDDING STORE BENCHMARK RESULTS")
        print("=" * 60)
        print(f"Documents: {config.num_documents}, Queries: {config.query_count}, K: {config.k}")
        print()
        print(f"{'Store':<20} {'Build (s)':<12} {'Query (ms)':<12} {'Recall':<10}")
        print("-" * 54)
        for r in results:
            print(f"{r.store_type:<20} {r.build_time_sec:<12.3f} {r.avg_query_ms:<12.3f} {r.recall_at_k:<10.2%}")


if __name__ == "__main__":
    main()
