#!/usr/bin/env python3
"""
TopicIndex Performance Benchmark

Compares TopicIndex vs FTS for recall operations.
"""

import os
import time
import statistics
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


def setup_env(tmpdir: str, n_memories: int = 500):
    """Set up test environment with memories"""
    os.environ['XDG_DATA_HOME'] = tmpdir
    
    from avm import AVM
    from avm.config import AVMConfig, PermissionRule
    from avm.topic_index import TopicIndex
    
    config = AVMConfig(
        permissions=[PermissionRule(pattern="/memory/*", access="rw")],
        embedding={"enabled": True, "backend": "local", "model": "all-MiniLM-L6-v2", "auto_index": True},
        performance={"hot_cache": True, "cache_size": 100, "wal_mode": True},
    )
    
    avm = AVM(config=config, agent_id="bench")
    topic_index = TopicIndex(avm.store)
    
    # Generate memories
    topics = ["trading", "crypto", "bitcoin", "ethereum", "stocks", 
              "analysis", "technical", "market", "price", "signal"]
    
    for i in range(n_memories):
        t1 = topics[i % len(topics)]
        t2 = topics[(i * 3) % len(topics)]
        content = f"Memory #{i} about {t1} and {t2}. Analysis of #{t1} patterns."
        path = f"/memory/private/bench/mem_{i}.md"
        
        avm.write(path, content, {"importance": 0.5 + (i % 5) * 0.1})
        topic_index.index_path(path, content)
    
    return avm, topic_index


def bench_index_speed(topic_index, n_docs: int = 100):
    """Benchmark indexing speed"""
    latencies = []
    
    for i in range(n_docs):
        content = f"Test document {i} about trading and crypto analysis"
        path = f"/memory/bench/speed_{i}.md"
        
        start = time.perf_counter()
        topic_index.index_path(path, content)
        latencies.append((time.perf_counter() - start) * 1000)
    
    return {
        "docs": n_docs,
        "total_ms": sum(latencies),
        "avg_ms": statistics.mean(latencies),
        "p50_ms": statistics.median(latencies),
        "p99_ms": sorted(latencies)[int(len(latencies) * 0.99)],
        "throughput_docs_per_sec": n_docs / (sum(latencies) / 1000),
    }


def bench_query_speed(topic_index, avm, queries: list, iterations: int = 50):
    """Benchmark query speed: TopicIndex vs FTS"""
    topic_latencies = []
    fts_latencies = []
    
    for _ in range(iterations):
        for query in queries:
            # TopicIndex
            start = time.perf_counter()
            topic_results = topic_index.query(query, limit=20)
            topic_latencies.append((time.perf_counter() - start) * 1000)
            
            # FTS
            start = time.perf_counter()
            fts_results = avm.search(query, limit=20)
            fts_latencies.append((time.perf_counter() - start) * 1000)
    
    return {
        "topic_index": {
            "p50_ms": statistics.median(topic_latencies),
            "p99_ms": sorted(topic_latencies)[int(len(topic_latencies) * 0.99)],
            "avg_ms": statistics.mean(topic_latencies),
        },
        "fts": {
            "p50_ms": statistics.median(fts_latencies),
            "p99_ms": sorted(fts_latencies)[int(len(fts_latencies) * 0.99)],
            "avg_ms": statistics.mean(fts_latencies),
        },
        "speedup": statistics.median(fts_latencies) / statistics.median(topic_latencies),
    }


def bench_recall_quality(topic_index, avm, test_cases: list):
    """Measure recall quality (precision/recall)"""
    results = []
    
    for query, expected_topics in test_cases:
        # Get TopicIndex results
        topic_results = topic_index.query(query, limit=20)
        topic_paths = set(p for p, _ in topic_results)
        
        # Get FTS results
        fts_results = avm.search(query, limit=20)
        fts_paths = set(n.path for n in fts_results)
        
        # Calculate overlap
        overlap = len(topic_paths & fts_paths)
        
        results.append({
            "query": query,
            "topic_count": len(topic_paths),
            "fts_count": len(fts_paths),
            "overlap": overlap,
            "jaccard": overlap / max(len(topic_paths | fts_paths), 1),
        })
    
    avg_jaccard = statistics.mean(r["jaccard"] for r in results)
    return {
        "test_cases": len(test_cases),
        "avg_jaccard_similarity": avg_jaccard,
        "details": results,
    }


def main():
    print("=" * 60)
    print("TOPICINDEX BENCHMARK")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        print("\n[1] Setting up environment (500 memories)...")
        avm, topic_index = setup_env(tmpdir, n_memories=500)
        print(f"    Topics indexed: {len(topic_index.all_topics())}")
        
        print("\n[2] Indexing Speed...")
        idx_speed = bench_index_speed(topic_index, n_docs=100)
        print(f"    Throughput: {idx_speed['throughput_docs_per_sec']:.0f} docs/sec")
        print(f"    p50: {idx_speed['p50_ms']:.3f}ms, p99: {idx_speed['p99_ms']:.3f}ms")
        
        print("\n[3] Query Speed (TopicIndex vs FTS)...")
        queries = ["trading analysis", "bitcoin price", "crypto market", "technical signal"]
        query_speed = bench_query_speed(topic_index, avm, queries)
        print(f"    TopicIndex p50: {query_speed['topic_index']['p50_ms']:.3f}ms")
        print(f"    FTS p50:        {query_speed['fts']['p50_ms']:.3f}ms")
        print(f"    Speedup:        {query_speed['speedup']:.1f}x")
        
        print("\n[4] Recall Quality...")
        test_cases = [
            ("trading", ["trading"]),
            ("bitcoin analysis", ["bitcoin", "analysis"]),
            ("crypto market", ["crypto", "market"]),
        ]
        quality = bench_recall_quality(topic_index, avm, test_cases)
        print(f"    Avg Jaccard similarity: {quality['avg_jaccard_similarity']:.2%}")
        
        # Stats
        stats = topic_index.stats()
        print("\n[5] Index Stats...")
        print(f"    Total topics: {stats['total_topics']}")
        print(f"    Total paths: {stats['total_paths']}")
        print(f"    Avg paths/topic: {stats['avg_paths_per_topic']:.1f}")
        
        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"  Index Speed:      {idx_speed['throughput_docs_per_sec']:.0f} docs/sec")
        print(f"  Query Speedup:    {query_speed['speedup']:.1f}x vs FTS")
        print(f"  Recall Quality:   {quality['avg_jaccard_similarity']:.0%} overlap with FTS")
        
        import json
        print("\n" + "=" * 60)
        print("JSON OUTPUT")
        print("=" * 60)
        print(json.dumps({
            "index_speed": idx_speed,
            "query_speed": query_speed,
            "recall_quality": {"avg_jaccard": quality["avg_jaccard_similarity"]},
            "stats": stats,
        }, indent=2))


if __name__ == "__main__":
    main()
