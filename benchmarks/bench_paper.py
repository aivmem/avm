#!/usr/bin/env python3
"""
AVM Paper-Quality Benchmark Suite

Complete experimental suite for academic paper:

1. Latency Distribution (CDF/histogram)
2. Throughput vs. Memory Count (scalability)
3. Cache Size Sensitivity Analysis
4. Embedding Model Comparison
5. Multi-Agent Contention Analysis
6. Cold Start Analysis
7. Memory Decay Impact
8. Token Budget vs. Recall Quality Trade-off

Each experiment outputs data suitable for plotting.

Usage:
    python benchmarks/bench_paper.py --all
    python benchmarks/bench_paper.py --exp latency_cdf
    python benchmarks/bench_paper.py --exp scalability --output results/
"""

import time
import tempfile
import os
import json
import random
import math
import statistics
import argparse
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


# ═══════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════

def generate_content(topic: str = "memory", size: int = 300) -> str:
    topic_words = {
        "market": ["NVDA", "RSI", "technical", "analysis", "price", "volume", "trend"],
        "trading": ["position", "stop-loss", "profit", "strategy", "risk"],
        "memory": ["remembered", "learned", "experience", "lesson", "insight"],
    }
    words = topic_words.get(topic, ["content", "data", "info"])
    filler = ["the", "and", "with", "for", "this"]
    return " ".join(random.choice(words) if random.random() < 0.3 else random.choice(filler) for _ in range(size // 5))


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def setup_avm(perf_config: Dict = None, embedding: bool = False):
    tmpdir = tempfile.mkdtemp()
    os.environ['XDG_DATA_HOME'] = tmpdir
    
    from avm import AVM
    from avm.config import AVMConfig, PermissionRule
    
    perf = perf_config or {"hot_cache": True, "cache_size": 100, "wal_mode": True}
    
    config = AVMConfig(
        permissions=[
            PermissionRule(pattern="/memory/*", access="rw"),
            PermissionRule(pattern="/shared/*", access="rw"),
        ],
        embedding={"enabled": embedding, "backend": "local", "model": "all-MiniLM-L6-v2", "auto_index": True} if embedding else {"enabled": False},
        performance=perf,
    )
    
    avm = AVM(config=config, agent_id="bench")
    return avm, tmpdir


def percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)


# ═══════════════════════════════════════════════════════════════
# Experiment 1: Latency Distribution (CDF)
# ═══════════════════════════════════════════════════════════════

def exp_latency_distribution(n_ops: int = 1000) -> Dict:
    """
    Measure latency distributions for read/write/search operations.
    Output: histogram bins and CDF data for plotting.
    """
    print("  Experiment: Latency Distribution...")
    
    avm, _ = setup_avm()
    
    # Populate
    for i in range(200):
        avm.write(f"/memory/item_{i}.md", generate_content(size=300))
    
    # Clear cache for cold reads
    avm._cache.clear()
    avm._cache_order.clear()
    
    results = {"read_cold": [], "read_hot": [], "write": [], "search": []}
    
    # Cold reads
    for i in range(min(n_ops, 200)):
        t0 = time.perf_counter()
        avm.read(f"/memory/item_{i}.md")
        results["read_cold"].append((time.perf_counter() - t0) * 1000)
    
    # Hot reads (same items again)
    for i in range(n_ops):
        idx = i % 200
        t0 = time.perf_counter()
        avm.read(f"/memory/item_{idx}.md")
        results["read_hot"].append((time.perf_counter() - t0) * 1000)
    
    # Writes
    for i in range(n_ops):
        content = generate_content(size=300)
        t0 = time.perf_counter()
        avm.write(f"/memory/write_{i}.md", content)
        results["write"].append((time.perf_counter() - t0) * 1000)
    
    # Search
    for i in range(min(n_ops, 100)):
        t0 = time.perf_counter()
        avm.search("memory content", limit=10)
        results["search"].append((time.perf_counter() - t0) * 1000)
    
    # Calculate statistics
    output = {}
    for op, latencies in results.items():
        if not latencies:
            continue
        
        # CDF data points (for plotting)
        sorted_lat = sorted(latencies)
        n_lat = len(sorted_lat)
        cdf_points = [(sorted_lat[min(int(n_lat * p / 100), n_lat - 1)], p) for p in range(0, 101, 5)]
        
        output[op] = {
            "n": len(latencies),
            "min": min(latencies),
            "max": max(latencies),
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "std": statistics.stdev(latencies) if len(latencies) > 1 else 0,
            "p50": percentile(latencies, 50),
            "p90": percentile(latencies, 90),
            "p95": percentile(latencies, 95),
            "p99": percentile(latencies, 99),
            "cdf": cdf_points,
            "histogram": {
                "bins": list(range(0, int(max(latencies)) + 2)),
                "counts": [sum(1 for l in latencies if b <= l < b + 1) for b in range(int(max(latencies)) + 1)],
            },
        }
    
    return output


# ═══════════════════════════════════════════════════════════════
# Experiment 2: Scalability (Throughput vs. Memory Count)
# ═══════════════════════════════════════════════════════════════

def exp_scalability(memory_counts: List[int] = None) -> Dict:
    """
    Measure how throughput scales with memory count.
    """
    print("  Experiment: Scalability...")
    
    if memory_counts is None:
        memory_counts = [10, 50, 100, 200, 500, 1000, 2000]
    
    results = []
    
    for n in memory_counts:
        print(f"    n={n}...")
        avm, _ = setup_avm()
        
        # Write
        t0 = time.perf_counter()
        for i in range(n):
            avm.write(f"/memory/item_{i}.md", generate_content(size=300))
        write_time = time.perf_counter() - t0
        write_throughput = n / write_time
        
        # Read (warm)
        n_reads = min(n * 2, 1000)
        t0 = time.perf_counter()
        for i in range(n_reads):
            avm.read(f"/memory/item_{i % n}.md")
        read_time = time.perf_counter() - t0
        read_throughput = n_reads / read_time
        
        # Search
        n_search = 50
        t0 = time.perf_counter()
        for _ in range(n_search):
            avm.search("memory content", limit=10)
        search_time = time.perf_counter() - t0
        search_throughput = n_search / search_time
        
        results.append({
            "memory_count": n,
            "write_throughput": write_throughput,
            "read_throughput": read_throughput,
            "search_throughput": search_throughput,
        })
    
    return {"data": results}


# ═══════════════════════════════════════════════════════════════
# Experiment 3: Cache Size Sensitivity
# ═══════════════════════════════════════════════════════════════

def exp_cache_sensitivity(cache_sizes: List[int] = None, n_memories: int = 500) -> Dict:
    """
    Measure hit rate and read latency for different cache sizes.
    """
    print("  Experiment: Cache Size Sensitivity...")
    
    if cache_sizes is None:
        cache_sizes = [10, 25, 50, 100, 200, 500]
    
    results = []
    
    for cache_size in cache_sizes:
        print(f"    cache_size={cache_size}...")
        
        perf = {"hot_cache": True, "cache_size": cache_size, "wal_mode": True}
        avm, _ = setup_avm(perf_config=perf)
        
        # Populate
        for i in range(n_memories):
            avm.write(f"/memory/item_{i}.md", generate_content(size=300))
        
        # Clear cache
        avm._cache.clear()
        avm._cache_order.clear()
        
        # Zipf access pattern
        hits = 0
        n_reads = 1000
        latencies = []
        
        for _ in range(n_reads):
            # Zipf distribution
            idx = min(int(random.paretovariate(1.5)) - 1, n_memories - 1)
            path = f"/memory/item_{idx}.md"
            
            was_cached = path in avm._cache
            
            t0 = time.perf_counter()
            avm.read(path)
            latencies.append((time.perf_counter() - t0) * 1000)
            
            if was_cached:
                hits += 1
        
        results.append({
            "cache_size": cache_size,
            "hit_rate": hits / n_reads,
            "avg_latency_ms": statistics.mean(latencies),
            "p99_latency_ms": percentile(latencies, 99),
        })
    
    return {"n_memories": n_memories, "n_reads": 1000, "data": results}


# ═══════════════════════════════════════════════════════════════
# Experiment 4: Multi-Agent Contention
# ═══════════════════════════════════════════════════════════════

def exp_multi_agent_contention(agent_counts: List[int] = None) -> Dict:
    """
    Measure throughput degradation with concurrent agents.
    """
    print("  Experiment: Multi-Agent Contention...")
    
    if agent_counts is None:
        agent_counts = [1, 2, 4, 8, 16]
    
    results = []
    
    for n_agents in agent_counts:
        print(f"    agents={n_agents}...")
        
        avm, _ = setup_avm()
        
        # Shared counter for completed ops
        completed = {"count": 0}
        lock = threading.Lock()
        
        def agent_workload(agent_id: int, n_ops: int = 100):
            local_latencies = []
            for i in range(n_ops):
                path = f"/shared/agent_{agent_id}/item_{i}.md"
                content = generate_content(size=200)
                
                t0 = time.perf_counter()
                avm.write(path, content)
                local_latencies.append((time.perf_counter() - t0) * 1000)
                
                with lock:
                    completed["count"] += 1
            
            return local_latencies
        
        n_ops_per_agent = 100
        all_latencies = []
        
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=n_agents) as executor:
            futures = [executor.submit(agent_workload, i, n_ops_per_agent) for i in range(n_agents)]
            for f in as_completed(futures):
                all_latencies.extend(f.result())
        total_time = time.perf_counter() - t0
        
        total_ops = n_agents * n_ops_per_agent
        throughput = total_ops / total_time
        
        results.append({
            "n_agents": n_agents,
            "total_ops": total_ops,
            "total_time_sec": total_time,
            "throughput": throughput,
            "avg_latency_ms": statistics.mean(all_latencies),
            "p99_latency_ms": percentile(all_latencies, 99),
            "throughput_per_agent": throughput / n_agents,
        })
    
    return {"data": results}


# ═══════════════════════════════════════════════════════════════
# Experiment 5: Cold Start Analysis
# ═══════════════════════════════════════════════════════════════

def exp_cold_start(history_sizes: List[int] = None) -> Dict:
    """
    Measure first-query latency with different history sizes.
    """
    print("  Experiment: Cold Start...")
    
    if history_sizes is None:
        history_sizes = [10, 50, 100, 500, 1000]
    
    results = []
    
    for n in history_sizes:
        print(f"    history_size={n}...")
        
        avm, _ = setup_avm(embedding=True)
        
        # Populate
        for i in range(n):
            avm.write(f"/memory/item_{i}.md", generate_content(size=300))
        
        # Wait for embedding
        time.sleep(0.5)
        
        # Cold search (first query)
        t0 = time.perf_counter()
        avm.search("analysis memory", limit=10)
        cold_latency = (time.perf_counter() - t0) * 1000
        
        # Warm searches
        warm_latencies = []
        for _ in range(10):
            t0 = time.perf_counter()
            avm.search("content data", limit=10)
            warm_latencies.append((time.perf_counter() - t0) * 1000)
        
        results.append({
            "history_size": n,
            "cold_latency_ms": cold_latency,
            "warm_avg_latency_ms": statistics.mean(warm_latencies),
            "warmup_factor": cold_latency / statistics.mean(warm_latencies) if warm_latencies else 0,
        })
    
    return {"data": results}


# ═══════════════════════════════════════════════════════════════
# Experiment 6: Token Budget vs. Recall Quality
# ═══════════════════════════════════════════════════════════════

def exp_token_quality_tradeoff(budgets: List[int] = None) -> Dict:
    """
    Measure recall quality at different token budgets.
    """
    print("  Experiment: Token Budget vs. Quality...")
    
    if budgets is None:
        budgets = [100, 250, 500, 1000, 2000, 4000, 8000]
    
    avm, _ = setup_avm(embedding=True)
    
    # Create memories with known topics
    topics = ["market", "trading", "memory"]
    topic_paths = {t: [] for t in topics}
    
    for i in range(150):
        topic = topics[i % len(topics)]
        path = f"/memory/{topic}/item_{i}.md"
        avm.write(path, generate_content(topic, 400))
        topic_paths[topic].append(path)
    
    time.sleep(1)
    
    from avm.agent_memory import AgentMemory
    mem = AgentMemory(avm, "bench")
    
    results = []
    
    for budget in budgets:
        print(f"    budget={budget}...")
        
        # Query for market topic
        t0 = time.perf_counter()
        context = mem.recall("NVDA RSI technical analysis", max_tokens=budget)
        latency = (time.perf_counter() - t0) * 1000
        
        returned_tokens = estimate_tokens(context)
        
        # Check how many market paths are mentioned
        market_mentions = sum(1 for p in topic_paths["market"] if p in context or f"item_{p.split('_')[-1].replace('.md', '')}" in context)
        
        results.append({
            "budget": budget,
            "returned_tokens": returned_tokens,
            "utilization": returned_tokens / budget if budget > 0 else 0,
            "latency_ms": latency,
            "relevant_mentions": market_mentions,
            "total_relevant": len(topic_paths["market"]),
        })
    
    return {"data": results}


# ═══════════════════════════════════════════════════════════════
# Experiment 7: Write Batch Size Impact
# ═══════════════════════════════════════════════════════════════

def exp_write_batch_size(batch_sizes: List[int] = None) -> Dict:
    """
    Measure throughput for different write batch sizes.
    """
    print("  Experiment: Write Batch Size...")
    
    if batch_sizes is None:
        batch_sizes = [1, 5, 10, 25, 50, 100]
    
    results = []
    
    for batch_size in batch_sizes:
        print(f"    batch_size={batch_size}...")
        
        avm, _ = setup_avm()
        
        n_batches = 20
        latencies = []
        
        for batch_idx in range(n_batches):
            t0 = time.perf_counter()
            for i in range(batch_size):
                avm.write(f"/memory/batch_{batch_idx}/item_{i}.md", generate_content(size=300))
            latencies.append((time.perf_counter() - t0) * 1000)
        
        total_ops = n_batches * batch_size
        total_time = sum(latencies) / 1000
        throughput = total_ops / total_time
        
        results.append({
            "batch_size": batch_size,
            "total_ops": total_ops,
            "throughput": throughput,
            "avg_batch_latency_ms": statistics.mean(latencies),
            "per_op_latency_ms": statistics.mean(latencies) / batch_size,
        })
    
    return {"data": results}


# ═══════════════════════════════════════════════════════════════
# Experiment 8: Memory Content Size Impact
# ═══════════════════════════════════════════════════════════════

def exp_content_size_impact(sizes: List[int] = None) -> Dict:
    """
    Measure how content size affects read/write performance.
    """
    print("  Experiment: Content Size Impact...")
    
    if sizes is None:
        sizes = [100, 500, 1000, 2000, 5000, 10000]
    
    results = []
    
    for size in sizes:
        print(f"    size={size} chars...")
        
        avm, _ = setup_avm()
        
        content = generate_content(size=size)
        
        # Write latency
        write_latencies = []
        for i in range(50):
            t0 = time.perf_counter()
            avm.write(f"/memory/size_{size}/item_{i}.md", content)
            write_latencies.append((time.perf_counter() - t0) * 1000)
        
        # Read latency (warm)
        read_latencies = []
        for i in range(50):
            t0 = time.perf_counter()
            avm.read(f"/memory/size_{size}/item_{i % 50}.md")
            read_latencies.append((time.perf_counter() - t0) * 1000)
        
        results.append({
            "content_size_chars": size,
            "content_size_tokens": estimate_tokens(content),
            "write_avg_ms": statistics.mean(write_latencies),
            "write_p99_ms": percentile(write_latencies, 99),
            "read_avg_ms": statistics.mean(read_latencies),
            "read_p99_ms": percentile(read_latencies, 99),
        })
    
    return {"data": results}


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

EXPERIMENTS = {
    "latency_cdf": exp_latency_distribution,
    "scalability": exp_scalability,
    "cache_sensitivity": exp_cache_sensitivity,
    "multi_agent": exp_multi_agent_contention,
    "cold_start": exp_cold_start,
    "token_quality": exp_token_quality_tradeoff,
    "batch_size": exp_write_batch_size,
    "content_size": exp_content_size_impact,
}


def print_summary(results: Dict):
    print("\n" + "=" * 80)
    print("PAPER BENCHMARK RESULTS SUMMARY")
    print("=" * 80)
    
    for exp_name, data in results.items():
        print(f"\n### {exp_name.upper()}")
        
        if "data" in data:
            for item in data["data"][:3]:  # First 3 rows
                print(f"  {item}")
            if len(data["data"]) > 3:
                print(f"  ... ({len(data['data'])} total rows)")
        else:
            for key, val in list(data.items())[:3]:
                if isinstance(val, dict):
                    print(f"  {key}: {list(val.keys())[:3]}...")
                else:
                    print(f"  {key}: {val}")


def main():
    parser = argparse.ArgumentParser(description="AVM Paper Benchmark Suite")
    parser.add_argument("--all", action="store_true", help="Run all experiments")
    parser.add_argument("--exp", choices=list(EXPERIMENTS.keys()), help="Run specific experiment")
    parser.add_argument("--output", type=str, help="Output directory for results")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--small", action="store_true", help="Smaller dataset")
    args = parser.parse_args()
    
    print("AVM Paper Benchmark Suite")
    print()
    
    if args.exp:
        experiments_to_run = {args.exp: EXPERIMENTS[args.exp]}
    elif args.all:
        experiments_to_run = EXPERIMENTS
    else:
        # Default: run a quick subset
        experiments_to_run = {
            "latency_cdf": EXPERIMENTS["latency_cdf"],
            "scalability": EXPERIMENTS["scalability"],
            "cache_sensitivity": EXPERIMENTS["cache_sensitivity"],
        }
    
    results = {}
    
    for name, func in experiments_to_run.items():
        try:
            if args.small:
                # Reduced parameters for quick testing
                if name == "scalability":
                    results[name] = func(memory_counts=[10, 50, 100])
                elif name == "latency_cdf":
                    results[name] = func(n_ops=100)
                else:
                    results[name] = func()
            else:
                results[name] = func()
        except Exception as e:
            print(f"  ERROR in {name}: {e}")
            results[name] = {"error": str(e)}
    
    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print_summary(results)
    
    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for name, data in results.items():
            with open(output_dir / f"{name}.json", "w") as f:
                json.dump(data, f, indent=2, default=str)
        
        print(f"\nResults saved to {output_dir}/")


if __name__ == "__main__":
    main()
