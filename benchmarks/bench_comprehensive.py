#!/usr/bin/env python3
"""
AVM Comprehensive Benchmark

Compares AVM vs raw file I/O across different scenarios:
1. Single agent continuous work
2. Multi-agent collaboration
3. Cold start with large history
4. Subscription notification latency

Usage:
    python benchmarks/bench_comprehensive.py
    python benchmarks/bench_comprehensive.py --scenario single
    python benchmarks/bench_comprehensive.py --json
"""

import time
import tempfile
import os
import json
import random
import string
import threading
import concurrent.futures
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any
import argparse


@dataclass
class BenchmarkResult:
    scenario: str
    operation: str
    ops_count: int
    total_time_ms: float
    ops_per_sec: float
    avg_latency_ms: float
    p99_latency_ms: float = 0.0
    extra: Dict[str, Any] = None


def generate_content(size: int = 500) -> str:
    """Generate random content"""
    words = ["memory", "agent", "task", "project", "analysis", "data", "result"]
    return " ".join(random.choice(words) for _ in range(size // 7))


def setup_avm():
    """Setup AVM with temp database"""
    tmpdir = tempfile.mkdtemp()
    os.environ['XDG_DATA_HOME'] = tmpdir
    
    from avm import AVM
    avm = AVM(agent_id="bench")
    return avm, tmpdir


def setup_raw_files():
    """Setup raw file directory"""
    tmpdir = tempfile.mkdtemp()
    return tmpdir


# ═══════════════════════════════════════════════════════════════
# Scenario 1: Single Agent Continuous Work
# ═══════════════════════════════════════════════════════════════

def bench_single_agent_avm(n_memories: int = 500, n_recalls: int = 50) -> List[BenchmarkResult]:
    """Benchmark single agent with AVM"""
    avm, tmpdir = setup_avm()
    results = []
    
    # Write memories
    latencies = []
    start = time.perf_counter()
    for i in range(n_memories):
        content = generate_content()
        t0 = time.perf_counter()
        avm.write(f"/memory/item_{i}.md", content, meta={"importance": random.random()})
        latencies.append((time.perf_counter() - t0) * 1000)
    total_time = (time.perf_counter() - start) * 1000
    
    results.append(BenchmarkResult(
        scenario="single_agent",
        operation="write",
        ops_count=n_memories,
        total_time_ms=total_time,
        ops_per_sec=n_memories / (total_time / 1000),
        avg_latency_ms=sum(latencies) / len(latencies),
        p99_latency_ms=sorted(latencies)[int(len(latencies) * 0.99)],
    ))
    
    # Read (with cache)
    latencies = []
    start = time.perf_counter()
    for i in range(n_memories):
        t0 = time.perf_counter()
        avm.read(f"/memory/item_{i}.md")
        latencies.append((time.perf_counter() - t0) * 1000)
    total_time = (time.perf_counter() - start) * 1000
    
    results.append(BenchmarkResult(
        scenario="single_agent",
        operation="read",
        ops_count=n_memories,
        total_time_ms=total_time,
        ops_per_sec=n_memories / (total_time / 1000),
        avg_latency_ms=sum(latencies) / len(latencies),
        p99_latency_ms=sorted(latencies)[int(len(latencies) * 0.99)],
    ))
    
    # Search
    latencies = []
    start = time.perf_counter()
    for i in range(n_recalls):
        t0 = time.perf_counter()
        avm.search("analysis project", limit=10)
        latencies.append((time.perf_counter() - t0) * 1000)
    total_time = (time.perf_counter() - start) * 1000
    
    results.append(BenchmarkResult(
        scenario="single_agent",
        operation="search",
        ops_count=n_recalls,
        total_time_ms=total_time,
        ops_per_sec=n_recalls / (total_time / 1000),
        avg_latency_ms=sum(latencies) / len(latencies),
        p99_latency_ms=sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0,
    ))
    
    # Recall (AgentMemory)
    from avm.agent_memory import AgentMemory
    mem = AgentMemory(avm, "bench")
    
    # Remember some with proper format
    for i in range(20):
        mem.remember(f"Important finding about topic {i}: " + generate_content(200), 
                    title=f"Topic {i}", importance=0.8)
    
    latencies = []
    start = time.perf_counter()
    for i in range(n_recalls):
        t0 = time.perf_counter()
        mem.recall(f"topic {i % 20}", max_tokens=500)
        latencies.append((time.perf_counter() - t0) * 1000)
    total_time = (time.perf_counter() - start) * 1000
    
    results.append(BenchmarkResult(
        scenario="single_agent",
        operation="recall",
        ops_count=n_recalls,
        total_time_ms=total_time,
        ops_per_sec=n_recalls / (total_time / 1000),
        avg_latency_ms=sum(latencies) / len(latencies),
        p99_latency_ms=sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0,
    ))
    
    return results


def bench_single_agent_raw(n_memories: int = 500, n_recalls: int = 50) -> List[BenchmarkResult]:
    """Benchmark single agent with raw files"""
    tmpdir = setup_raw_files()
    memory_dir = Path(tmpdir) / "memory"
    memory_dir.mkdir()
    results = []
    
    # Write
    latencies = []
    start = time.perf_counter()
    for i in range(n_memories):
        content = generate_content()
        t0 = time.perf_counter()
        (memory_dir / f"item_{i}.md").write_text(content)
        latencies.append((time.perf_counter() - t0) * 1000)
    total_time = (time.perf_counter() - start) * 1000
    
    results.append(BenchmarkResult(
        scenario="single_agent_raw",
        operation="write",
        ops_count=n_memories,
        total_time_ms=total_time,
        ops_per_sec=n_memories / (total_time / 1000),
        avg_latency_ms=sum(latencies) / len(latencies),
        p99_latency_ms=sorted(latencies)[int(len(latencies) * 0.99)],
    ))
    
    # Read
    latencies = []
    start = time.perf_counter()
    for i in range(n_memories):
        t0 = time.perf_counter()
        (memory_dir / f"item_{i}.md").read_text()
        latencies.append((time.perf_counter() - t0) * 1000)
    total_time = (time.perf_counter() - start) * 1000
    
    results.append(BenchmarkResult(
        scenario="single_agent_raw",
        operation="read",
        ops_count=n_memories,
        total_time_ms=total_time,
        ops_per_sec=n_memories / (total_time / 1000),
        avg_latency_ms=sum(latencies) / len(latencies),
        p99_latency_ms=sorted(latencies)[int(len(latencies) * 0.99)],
    ))
    
    # Search (grep simulation)
    import subprocess
    latencies = []
    start = time.perf_counter()
    for i in range(min(n_recalls, 20)):  # grep is slow
        t0 = time.perf_counter()
        subprocess.run(
            ["grep", "-l", "analysis", str(memory_dir)],
            capture_output=True,
            timeout=5
        )
        latencies.append((time.perf_counter() - t0) * 1000)
    total_time = (time.perf_counter() - start) * 1000
    
    results.append(BenchmarkResult(
        scenario="single_agent_raw",
        operation="search",
        ops_count=len(latencies),
        total_time_ms=total_time,
        ops_per_sec=len(latencies) / (total_time / 1000) if total_time > 0 else 0,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
        p99_latency_ms=sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0,
    ))
    
    return results


# ═══════════════════════════════════════════════════════════════
# Scenario 2: Multi-Agent Collaboration
# ═══════════════════════════════════════════════════════════════

def bench_multi_agent_avm(n_agents: int = 5, ops_per_agent: int = 100) -> List[BenchmarkResult]:
    """Benchmark multi-agent concurrent access"""
    avm, tmpdir = setup_avm()
    results = []
    
    # Setup subscriptions
    from avm.subscriptions import get_subscription_store, SubscriptionMode
    sub_store = get_subscription_store()
    for i in range(n_agents):
        sub_store.subscribe(f"agent_{i}", "/shared/*", mode=SubscriptionMode.BATCHED)
    
    write_latencies = []
    read_latencies = []
    
    def agent_work(agent_id: int):
        """Simulate agent work"""
        local_write_lat = []
        local_read_lat = []
        
        for j in range(ops_per_agent):
            # Write to shared
            content = generate_content(200)
            t0 = time.perf_counter()
            avm.write(f"/shared/agent_{agent_id}_item_{j}.md", content)
            local_write_lat.append((time.perf_counter() - t0) * 1000)
            
            # Read from another agent
            other = (agent_id + 1) % n_agents
            t0 = time.perf_counter()
            avm.read(f"/shared/agent_{other}_item_{j % max(1, j)}.md")
            local_read_lat.append((time.perf_counter() - t0) * 1000)
        
        return local_write_lat, local_read_lat
    
    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_agents) as executor:
        futures = [executor.submit(agent_work, i) for i in range(n_agents)]
        for future in concurrent.futures.as_completed(futures):
            w, r = future.result()
            write_latencies.extend(w)
            read_latencies.extend(r)
    total_time = (time.perf_counter() - start) * 1000
    
    total_ops = n_agents * ops_per_agent
    
    results.append(BenchmarkResult(
        scenario="multi_agent",
        operation="concurrent_write",
        ops_count=total_ops,
        total_time_ms=total_time,
        ops_per_sec=total_ops / (total_time / 1000),
        avg_latency_ms=sum(write_latencies) / len(write_latencies),
        p99_latency_ms=sorted(write_latencies)[int(len(write_latencies) * 0.99)],
        extra={"n_agents": n_agents},
    ))
    
    results.append(BenchmarkResult(
        scenario="multi_agent",
        operation="concurrent_read",
        ops_count=total_ops,
        total_time_ms=total_time,
        ops_per_sec=total_ops / (total_time / 1000),
        avg_latency_ms=sum(read_latencies) / len(read_latencies),
        p99_latency_ms=sorted(read_latencies)[int(len(read_latencies) * 0.99)],
        extra={"n_agents": n_agents},
    ))
    
    # Check pending notifications
    total_pending = sum(len(sub_store.get_pending(f"agent_{i}")) for i in range(n_agents))
    results.append(BenchmarkResult(
        scenario="multi_agent",
        operation="subscription_accumulation",
        ops_count=total_pending,
        total_time_ms=0,
        ops_per_sec=0,
        avg_latency_ms=0,
        extra={"pending_per_agent": total_pending / n_agents},
    ))
    
    return results


# ═══════════════════════════════════════════════════════════════
# Scenario 3: Cold Start with Large History
# ═══════════════════════════════════════════════════════════════

def bench_cold_start(n_history: int = 2000, n_queries: int = 20) -> List[BenchmarkResult]:
    """Benchmark cold start performance"""
    avm, tmpdir = setup_avm()
    results = []
    
    # Populate large history
    print(f"    Populating {n_history} historical memories...")
    for i in range(n_history):
        avm.write(f"/memory/history/item_{i}.md", generate_content(300))
    
    # Cold start simulation: new AVM instance
    from avm import AVM
    avm2 = AVM(agent_id="cold_start")
    
    # First query (cold)
    latencies = []
    start = time.perf_counter()
    for i in range(n_queries):
        t0 = time.perf_counter()
        avm2.search("analysis project data", limit=10)
        latencies.append((time.perf_counter() - t0) * 1000)
    total_time = (time.perf_counter() - start) * 1000
    
    results.append(BenchmarkResult(
        scenario="cold_start",
        operation="first_search",
        ops_count=n_queries,
        total_time_ms=total_time,
        ops_per_sec=n_queries / (total_time / 1000),
        avg_latency_ms=sum(latencies) / len(latencies),
        p99_latency_ms=sorted(latencies)[int(len(latencies) * 0.99)],
        extra={"history_size": n_history},
    ))
    
    # Warm queries (after cache populated)
    latencies = []
    start = time.perf_counter()
    for i in range(n_queries):
        t0 = time.perf_counter()
        avm2.search("analysis project data", limit=10)
        latencies.append((time.perf_counter() - t0) * 1000)
    total_time = (time.perf_counter() - start) * 1000
    
    results.append(BenchmarkResult(
        scenario="cold_start",
        operation="warm_search",
        ops_count=n_queries,
        total_time_ms=total_time,
        ops_per_sec=n_queries / (total_time / 1000),
        avg_latency_ms=sum(latencies) / len(latencies),
        p99_latency_ms=sorted(latencies)[int(len(latencies) * 0.99)],
        extra={"history_size": n_history},
    ))
    
    return results


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def print_results(results: List[BenchmarkResult], as_json: bool = False):
    if as_json:
        print(json.dumps([asdict(r) for r in results], indent=2))
        return
    
    print("\n" + "=" * 70)
    print("BENCHMARK RESULTS")
    print("=" * 70)
    
    current_scenario = None
    for r in results:
        if r.scenario != current_scenario:
            current_scenario = r.scenario
            print(f"\n### {r.scenario.upper().replace('_', ' ')}")
            print("-" * 50)
        
        print(f"  {r.operation}:")
        print(f"    Ops: {r.ops_count:,}")
        print(f"    Total: {r.total_time_ms:.1f} ms")
        print(f"    Throughput: {r.ops_per_sec:.1f} ops/sec")
        print(f"    Latency: avg={r.avg_latency_ms:.2f}ms p99={r.p99_latency_ms:.2f}ms")
        if r.extra:
            print(f"    Extra: {r.extra}")


def main():
    parser = argparse.ArgumentParser(description="AVM Comprehensive Benchmark")
    parser.add_argument("--scenario", choices=["single", "multi", "cold", "all"], default="all")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--small", action="store_true", help="Smaller dataset for quick test")
    args = parser.parse_args()
    
    all_results = []
    
    scale = 0.2 if args.small else 1.0
    
    if args.scenario in ("single", "all"):
        print("\n[1/4] Single Agent (AVM)...")
        all_results.extend(bench_single_agent_avm(
            n_memories=int(500 * scale),
            n_recalls=int(50 * scale)
        ))
        
        print("[2/4] Single Agent (Raw Files)...")
        all_results.extend(bench_single_agent_raw(
            n_memories=int(500 * scale),
            n_recalls=int(20 * scale)
        ))
    
    if args.scenario in ("multi", "all"):
        print("[3/4] Multi-Agent Collaboration...")
        all_results.extend(bench_multi_agent_avm(
            n_agents=5,
            ops_per_agent=int(100 * scale)
        ))
    
    if args.scenario in ("cold", "all"):
        print("[4/4] Cold Start...")
        all_results.extend(bench_cold_start(
            n_history=int(2000 * scale),
            n_queries=int(20 * scale)
        ))
    
    print_results(all_results, as_json=args.json)


if __name__ == "__main__":
    main()
