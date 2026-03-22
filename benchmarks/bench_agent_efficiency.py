#!/usr/bin/env python3
"""
AVM Agent Efficiency Benchmark

Measures metrics relevant to AI agent performance:
1. Cache hit rate
2. Recall precision/recall (semantic relevance)
3. Hop count per operation
4. Information efficiency (tokens saved)
5. Scalability curves under different loads

Usage:
    python benchmarks/bench_agent_efficiency.py
    python benchmarks/bench_agent_efficiency.py --json
    python benchmarks/bench_agent_efficiency.py --scenario cache_curve
"""

import time
import tempfile
import os
import json
import random
import math
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Tuple
import argparse


@dataclass
class CacheMetrics:
    """Cache performance metrics"""
    total_reads: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    
    @property
    def hit_rate(self) -> float:
        return self.cache_hits / self.total_reads if self.total_reads > 0 else 0.0


@dataclass
class RecallMetrics:
    """Recall quality metrics"""
    query: str
    expected_paths: List[str]
    returned_paths: List[str]
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    latency_ms: float = 0.0


@dataclass
class HopMetrics:
    """Operation hop count"""
    operation: str
    hops: int
    breakdown: Dict[str, int] = field(default_factory=dict)


@dataclass
class EfficiencyMetrics:
    """Information efficiency"""
    total_content_tokens: int
    returned_tokens: int
    tokens_saved: int
    compression_ratio: float
    relevant_ratio: float  # % of returned tokens that are relevant


@dataclass
class ScalabilityPoint:
    """Single point on scalability curve"""
    memory_count: int
    write_ops_sec: float
    read_ops_sec: float
    recall_latency_ms: float
    cache_hit_rate: float
    tokens_per_recall: float


def generate_topic_content(topic: str, size: int = 300) -> str:
    """Generate content with specific topic keywords"""
    topic_words = {
        "market": ["NVDA", "RSI", "overbought", "technical", "analysis", "price", "volume"],
        "trading": ["position", "stop-loss", "profit", "strategy", "risk", "entry", "exit"],
        "news": ["announced", "reported", "update", "breaking", "market", "impact"],
        "research": ["study", "analysis", "findings", "data", "conclusion", "evidence"],
        "memory": ["remembered", "learned", "experience", "lesson", "insight"],
    }
    
    words = topic_words.get(topic, ["general", "content", "data"])
    filler = ["the", "and", "with", "for", "this", "that", "about"]
    
    content = []
    for _ in range(size // 8):
        if random.random() < 0.4:
            content.append(random.choice(words))
        else:
            content.append(random.choice(filler))
    
    return " ".join(content)


def estimate_tokens(text: str) -> int:
    """Estimate token count (chars / 4)"""
    return len(text) // 4


def setup_avm_with_tracking():
    """Setup AVM with hop tracking"""
    tmpdir = tempfile.mkdtemp()
    os.environ['XDG_DATA_HOME'] = tmpdir
    
    from avm import AVM
    from avm.config import AVMConfig, PermissionRule
    
    config = AVMConfig(
        permissions=[
            PermissionRule(pattern="/memory/*", access="rw"),
        ],
        embedding={"enabled": True, "backend": "local", "model": "all-MiniLM-L6-v2", "auto_index": True},
        performance={"hot_cache": True, "cache_size": 100, "wal_mode": True},
    )
    
    avm = AVM(config=config, agent_id="bench")
    return avm, tmpdir


def setup_avm_minimal():
    """Setup AVM without embedding for faster tests"""
    tmpdir = tempfile.mkdtemp()
    os.environ['XDG_DATA_HOME'] = tmpdir
    
    from avm import AVM
    from avm.config import AVMConfig, PermissionRule
    
    config = AVMConfig(
        permissions=[
            PermissionRule(pattern="/memory/*", access="rw"),
        ],
        embedding={"enabled": False},
        performance={"hot_cache": True, "cache_size": 100, "wal_mode": True},
    )
    
    avm = AVM(config=config, agent_id="bench")
    return avm, tmpdir


# ═══════════════════════════════════════════════════════════════
# 1. Cache Hit Rate Analysis
# ═══════════════════════════════════════════════════════════════

def bench_cache_hit_rate(n_memories: int = 200, n_reads: int = 500,
                         access_pattern: str = "zipf") -> Dict[str, Any]:
    """
    Measure cache hit rate under different access patterns
    
    Patterns:
    - uniform: equal probability for all items
    - zipf: power-law (some items accessed much more)
    - temporal: recent items accessed more
    - working_set: hot set + occasional cold
    """
    print(f"  Cache hit rate ({access_pattern} pattern)...")
    
    avm, tmpdir = setup_avm_minimal()
    
    # Populate memories
    for i in range(n_memories):
        avm.write(f"/memory/item_{i}.md", generate_topic_content("memory", 200))
    
    # Clear cache stats
    avm._cache.clear()
    avm._cache_order.clear()
    
    # Access pattern generators
    def uniform_access():
        return random.randint(0, n_memories - 1)
    
    def zipf_access(alpha=1.5):
        # Zipf distribution: P(k) ∝ 1/k^alpha
        rank = int(random.paretovariate(alpha))
        return min(rank - 1, n_memories - 1)
    
    def temporal_access():
        # Prefer recent items (higher indices)
        return int(random.triangular(0, n_memories, n_memories * 0.9))
    
    def working_set_access(hot_size=20, hot_prob=0.8):
        if random.random() < hot_prob:
            return random.randint(0, hot_size - 1)
        else:
            return random.randint(hot_size, n_memories - 1)
    
    access_fn = {
        "uniform": uniform_access,
        "zipf": zipf_access,
        "temporal": temporal_access,
        "working_set": working_set_access,
    }[access_pattern]
    
    # Track hits/misses
    hits = 0
    misses = 0
    hit_rate_over_time = []
    
    for i in range(n_reads):
        idx = access_fn()
        path = f"/memory/item_{idx}.md"
        
        # Check if in cache before read
        was_cached = path in avm._cache
        
        avm.read(path)
        
        if was_cached:
            hits += 1
        else:
            misses += 1
        
        # Record hit rate every 50 reads
        if (i + 1) % 50 == 0:
            hit_rate_over_time.append({
                "reads": i + 1,
                "hit_rate": hits / (i + 1),
            })
    
    return {
        "pattern": access_pattern,
        "n_memories": n_memories,
        "n_reads": n_reads,
        "cache_size": avm._cache_max_size,
        "total_hits": hits,
        "total_misses": misses,
        "final_hit_rate": hits / n_reads,
        "hit_rate_curve": hit_rate_over_time,
    }


# ═══════════════════════════════════════════════════════════════
# 2. Recall Quality (Precision/Recall)
# ═══════════════════════════════════════════════════════════════

def bench_recall_quality(n_memories: int = 100) -> Dict[str, Any]:
    """Measure recall precision and recall for semantic search"""
    print("  Recall quality (precision/recall)...")
    
    avm, tmpdir = setup_avm_with_tracking()
    
    # Create memories with known topics
    topics = ["market", "trading", "news", "research", "memory"]
    topic_paths = {t: [] for t in topics}
    
    for i in range(n_memories):
        topic = topics[i % len(topics)]
        path = f"/memory/{topic}/item_{i}.md"
        content = generate_topic_content(topic, 300)
        avm.write(path, content, meta={"topic": topic})
        topic_paths[topic].append(path)
    
    # Wait for embedding to complete
    time.sleep(2)
    
    # Test queries
    test_queries = [
        ("NVDA RSI technical analysis", "market"),
        ("stop-loss trading strategy", "trading"),
        ("breaking news announcement", "news"),
        ("research study findings", "research"),
    ]
    
    results = []
    
    for query, expected_topic in test_queries:
        expected = set(topic_paths[expected_topic])
        
        t0 = time.perf_counter()
        search_results = avm.search(query, limit=20)
        latency = (time.perf_counter() - t0) * 1000
        
        returned = set(node.path for node, _ in search_results)
        
        # Calculate precision/recall
        true_positives = len(returned & expected)
        precision = true_positives / len(returned) if returned else 0
        recall = true_positives / len(expected) if expected else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        
        results.append({
            "query": query,
            "expected_topic": expected_topic,
            "expected_count": len(expected),
            "returned_count": len(returned),
            "true_positives": true_positives,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "latency_ms": latency,
        })
    
    # Aggregate
    avg_precision = sum(r["precision"] for r in results) / len(results)
    avg_recall = sum(r["recall"] for r in results) / len(results)
    avg_f1 = sum(r["f1"] for r in results) / len(results)
    avg_latency = sum(r["latency_ms"] for r in results) / len(results)
    
    return {
        "n_memories": n_memories,
        "n_queries": len(test_queries),
        "avg_precision": avg_precision,
        "avg_recall": avg_recall,
        "avg_f1": avg_f1,
        "avg_latency_ms": avg_latency,
        "per_query": results,
    }


# ═══════════════════════════════════════════════════════════════
# 3. Hop Count Analysis
# ═══════════════════════════════════════════════════════════════

def bench_hop_count() -> Dict[str, Any]:
    """Analyze hop count for different operations"""
    print("  Hop count analysis...")
    
    # Theoretical hop counts
    operations = {
        "read_cold": {
            "description": "Read uncached node",
            "hops": 2,
            "breakdown": {"cache_check": 1, "sqlite_read": 1},
        },
        "read_hot": {
            "description": "Read cached node",
            "hops": 1,
            "breakdown": {"cache_check": 1},
        },
        "write": {
            "description": "Write with async embedding",
            "hops": 1,  # SQLite only, embedding is async
            "breakdown": {"sqlite_write": 1, "cache_update": 0, "embedding_async": 0},
        },
        "search_embedding": {
            "description": "Semantic search",
            "hops": 2,
            "breakdown": {"embedding_search": 1, "batch_read": 1},
        },
        "search_fts": {
            "description": "Full-text search",
            "hops": 2,
            "breakdown": {"fts_search": 1, "batch_read": 1},
        },
        "recall_hot": {
            "description": "Recall with topic hit",
            "hops": 1,
            "breakdown": {"topic_index": 1},
            "note": "Future optimization",
        },
        "recall_cold": {
            "description": "Recall full search",
            "hops": 4,
            "breakdown": {"embedding": 1, "fts": 1, "graph_expand": 1, "batch_read": 1},
        },
    }
    
    return {
        "operations": operations,
        "summary": {
            "best_case": 1,
            "worst_case": 4,
            "optimization_target": 2,
        },
    }


# ═══════════════════════════════════════════════════════════════
# 4. Information Efficiency (Token Savings)
# ═══════════════════════════════════════════════════════════════

def bench_information_efficiency(n_memories: int = 100) -> Dict[str, Any]:
    """Measure token savings from recall vs full read"""
    print("  Information efficiency...")
    
    avm, tmpdir = setup_avm_minimal()
    
    # Create memories of varying sizes
    total_content_tokens = 0
    for i in range(n_memories):
        size = random.randint(200, 1000)
        content = generate_topic_content("memory", size)
        total_content_tokens += estimate_tokens(content)
        avm.write(f"/memory/item_{i}.md", content)
    
    # Simulate recall with different token budgets
    budgets = [500, 1000, 2000, 4000, 8000]
    results = []
    
    from avm.agent_memory import AgentMemory
    mem = AgentMemory(avm, "bench")
    
    for budget in budgets:
        # Recall returns token-limited context
        t0 = time.perf_counter()
        context = mem.recall("general content data", max_tokens=budget)
        latency = (time.perf_counter() - t0) * 1000
        
        returned_tokens = estimate_tokens(context)
        
        results.append({
            "budget": budget,
            "returned_tokens": returned_tokens,
            "total_available": total_content_tokens,
            "compression_ratio": returned_tokens / total_content_tokens if total_content_tokens > 0 else 0,
            "tokens_saved": total_content_tokens - returned_tokens,
            "savings_pct": (1 - returned_tokens / total_content_tokens) * 100 if total_content_tokens > 0 else 0,
            "latency_ms": latency,
        })
    
    return {
        "n_memories": n_memories,
        "total_content_tokens": total_content_tokens,
        "budget_results": results,
    }


# ═══════════════════════════════════════════════════════════════
# 5. Scalability Curves
# ═══════════════════════════════════════════════════════════════

def bench_scalability_curve(memory_counts: List[int] = None) -> Dict[str, Any]:
    """Generate scalability curves for different memory counts"""
    print("  Scalability curves...")
    
    if memory_counts is None:
        memory_counts = [50, 100, 200, 500, 1000]
    
    curves = {
        "write": [],
        "read": [],
        "search": [],
        "cache_hit_rate": [],
    }
    
    for n in memory_counts:
        print(f"    Testing with {n} memories...")
        
        avm, tmpdir = setup_avm_minimal()
        
        # Write benchmark
        write_latencies = []
        t0 = time.perf_counter()
        for i in range(n):
            tw = time.perf_counter()
            avm.write(f"/memory/item_{i}.md", generate_topic_content("memory", 300))
            write_latencies.append((time.perf_counter() - tw) * 1000)
        write_total = time.perf_counter() - t0
        write_ops_sec = n / write_total
        
        curves["write"].append({"memory_count": n, "ops_sec": write_ops_sec, "avg_latency_ms": sum(write_latencies) / len(write_latencies)})
        
        # Clear cache
        avm._cache.clear()
        avm._cache_order.clear()
        
        # Read benchmark (with cache warming)
        n_reads = min(n * 2, 500)
        hits = 0
        read_latencies = []
        t0 = time.perf_counter()
        for i in range(n_reads):
            idx = random.randint(0, n - 1)
            path = f"/memory/item_{idx}.md"
            was_cached = path in avm._cache
            
            tr = time.perf_counter()
            avm.read(path)
            read_latencies.append((time.perf_counter() - tr) * 1000)
            
            if was_cached:
                hits += 1
        read_total = time.perf_counter() - t0
        read_ops_sec = n_reads / read_total
        
        curves["read"].append({"memory_count": n, "ops_sec": read_ops_sec, "avg_latency_ms": sum(read_latencies) / len(read_latencies)})
        curves["cache_hit_rate"].append({"memory_count": n, "hit_rate": hits / n_reads})
        
        # Search benchmark
        n_searches = 20
        search_latencies = []
        t0 = time.perf_counter()
        for i in range(n_searches):
            ts = time.perf_counter()
            avm.search("memory content", limit=10)
            search_latencies.append((time.perf_counter() - ts) * 1000)
        search_total = time.perf_counter() - t0
        search_ops_sec = n_searches / search_total
        
        curves["search"].append({"memory_count": n, "ops_sec": search_ops_sec, "avg_latency_ms": sum(search_latencies) / len(search_latencies)})
    
    return {
        "memory_counts": memory_counts,
        "curves": curves,
    }


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def print_results(results: Dict[str, Any], as_json: bool = False):
    if as_json:
        print(json.dumps(results, indent=2, default=str))
        return
    
    print("\n" + "=" * 80)
    print("AGENT EFFICIENCY BENCHMARK RESULTS")
    print("=" * 80)
    
    # Cache hit rate
    if "cache" in results:
        cache = results["cache"]
        print(f"\n### CACHE HIT RATE")
        for pattern, data in cache.items():
            print(f"  {pattern}: {data['final_hit_rate']:.1%} hit rate")
    
    # Recall quality
    if "recall_quality" in results:
        rq = results["recall_quality"]
        print(f"\n### RECALL QUALITY")
        print(f"  Avg Precision: {rq['avg_precision']:.2%}")
        print(f"  Avg Recall: {rq['avg_recall']:.2%}")
        print(f"  Avg F1: {rq['avg_f1']:.2%}")
        print(f"  Avg Latency: {rq['avg_latency_ms']:.1f}ms")
    
    # Hop count
    if "hop_count" in results:
        hc = results["hop_count"]
        print(f"\n### HOP COUNT")
        for op, data in hc["operations"].items():
            print(f"  {op}: {data['hops']} hops - {data['description']}")
    
    # Information efficiency
    if "efficiency" in results:
        eff = results["efficiency"]
        print(f"\n### INFORMATION EFFICIENCY")
        print(f"  Total content: {eff['total_content_tokens']:,} tokens")
        for r in eff["budget_results"]:
            print(f"  Budget {r['budget']:,}: {r['savings_pct']:.1f}% saved ({r['returned_tokens']:,} returned)")
    
    # Scalability
    if "scalability" in results:
        sc = results["scalability"]
        print(f"\n### SCALABILITY CURVES")
        print(f"  Memory counts tested: {sc['memory_counts']}")
        print(f"\n  Write ops/sec:")
        for p in sc["curves"]["write"]:
            print(f"    {p['memory_count']:4d} memories: {p['ops_sec']:.1f} ops/s")
        print(f"\n  Cache hit rate:")
        for p in sc["curves"]["cache_hit_rate"]:
            print(f"    {p['memory_count']:4d} memories: {p['hit_rate']:.1%}")


def main():
    parser = argparse.ArgumentParser(description="AVM Agent Efficiency Benchmark")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--scenario", choices=["cache", "recall", "hops", "efficiency", "scale", "all"], 
                        default="all", help="Specific scenario to run")
    parser.add_argument("--small", action="store_true", help="Smaller dataset")
    args = parser.parse_args()
    
    scale = 0.5 if args.small else 1.0
    
    results = {}
    
    print("AVM Agent Efficiency Benchmark")
    print()
    
    if args.scenario in ("cache", "all"):
        results["cache"] = {}
        for pattern in ["uniform", "zipf", "temporal", "working_set"]:
            results["cache"][pattern] = bench_cache_hit_rate(
                n_memories=int(200 * scale),
                n_reads=int(500 * scale),
                access_pattern=pattern
            )
    
    if args.scenario in ("recall", "all"):
        results["recall_quality"] = bench_recall_quality(n_memories=int(100 * scale))
    
    if args.scenario in ("hops", "all"):
        results["hop_count"] = bench_hop_count()
    
    if args.scenario in ("efficiency", "all"):
        results["efficiency"] = bench_information_efficiency(n_memories=int(100 * scale))
    
    if args.scenario in ("scale", "all"):
        counts = [50, 100, 200] if args.small else [50, 100, 200, 500, 1000]
        results["scalability"] = bench_scalability_curve(counts)
    
    print_results(results, as_json=args.json)


if __name__ == "__main__":
    main()
