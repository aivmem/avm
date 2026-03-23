#!/usr/bin/env python3
"""
AVM Unit Benchmark - No LLM required.
Tests core AVM operations: write, read, recall, search.
"""

import json
import subprocess
import time
import random
import string
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import List


def random_text(n_words: int = 20) -> str:
    words = ["data", "analysis", "report", "system", "user", "config", "error",
             "deploy", "test", "feature", "bug", "fix", "optimize", "scale",
             "monitor", "alert", "metric", "log", "trace", "cache", "queue",
             "async", "sync", "batch", "stream", "api", "rest", "grpc"]
    return " ".join(random.choices(words, k=n_words))


def random_id(n: int = 6) -> str:
    return ''.join(random.choices(string.ascii_lowercase, k=n))


@dataclass
class BenchResult:
    operation: str
    n_items: int
    total_ms: float
    avg_ms: float
    ops_per_sec: float
    success: bool


def run_avm(args: List[str], input_text: str = None, timeout: int = 30) -> tuple:
    """Run AVM command."""
    start = time.time()
    try:
        result = subprocess.run(
            ["avm"] + args,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = (time.time() - start) * 1000
        return result.returncode == 0, result.stdout, duration
    except:
        return False, "", timeout * 1000


def bench_write(n: int) -> BenchResult:
    """Benchmark write operations."""
    agent = f"bench_write_{random_id()}"
    times = []
    
    for i in range(n):
        content = f"Memory {i}: {random_text(30)}"
        success, _, duration = run_avm([
            "remember", "-a", agent, "-c", content, "-i", "0.5"
        ])
        times.append(duration)
    
    total = sum(times)
    return BenchResult(
        operation="write",
        n_items=n,
        total_ms=total,
        avg_ms=total / n,
        ops_per_sec=n / (total / 1000),
        success=True,
    )


def bench_recall(n: int) -> BenchResult:
    """Benchmark recall operations."""
    agent = f"bench_recall_{random_id()}"
    
    # Pre-populate
    for i in range(50):
        content = f"Pre-populated memory {i}: {random_text(20)}"
        run_avm(["remember", "-a", agent, "-c", content])
    
    times = []
    queries = ["data analysis", "bug fix", "deploy test", "api monitor", "cache sync"]
    
    for i in range(n):
        q = queries[i % len(queries)]
        success, output, duration = run_avm([
            "recall", "-a", agent, "-t", "300", q
        ])
        times.append(duration)
    
    total = sum(times)
    return BenchResult(
        operation="recall",
        n_items=n,
        total_ms=total,
        avg_ms=total / n,
        ops_per_sec=n / (total / 1000),
        success=True,
    )


def bench_recall_empty(n: int) -> BenchResult:
    """Benchmark recall with high min_relevance (tests early exit)."""
    agent = f"bench_empty_{random_id()}"
    times = []
    
    for i in range(n):
        # Query with gibberish that won't match anything
        success, output, duration = run_avm([
            "recall", "-a", agent, "-t", "100", "-r", "0.9",
            f"xyzzy_{random_id()}_plugh"
        ])
        times.append(duration)
        # Verify empty return
        if output.strip():
            print(f"  Warning: expected empty, got {len(output)} chars")
    
    total = sum(times)
    return BenchResult(
        operation="recall_empty",
        n_items=n,
        total_ms=total,
        avg_ms=total / n,
        ops_per_sec=n / (total / 1000),
        success=True,
    )


def bench_list(n: int) -> BenchResult:
    """Benchmark list operations."""
    times = []
    
    for i in range(n):
        success, _, duration = run_avm(["list", "/memory/", "--json"])
        times.append(duration)
    
    total = sum(times)
    return BenchResult(
        operation="list",
        n_items=n,
        total_ms=total,
        avg_ms=total / n,
        ops_per_sec=n / (total / 1000),
        success=True,
    )


def bench_stats(n: int) -> BenchResult:
    """Benchmark memory-stats operations."""
    agent = f"bench_stats_{random_id()}"
    
    # Pre-populate
    for i in range(20):
        run_avm(["remember", "-a", agent, "-c", f"Content {i}"])
    
    times = []
    for i in range(n):
        success, _, duration = run_avm(["memory-stats", "-a", agent])
        times.append(duration)
    
    total = sum(times)
    return BenchResult(
        operation="stats",
        n_items=n,
        total_ms=total,
        avg_ms=total / n,
        ops_per_sec=n / (total / 1000),
        success=True,
    )


def bench_batch_write(n_items: int) -> BenchResult:
    """Benchmark batch write (comparing N individual vs 1 batch)."""
    agent = f"bench_batch_{random_id()}"
    
    # Time N individual writes
    start = time.time()
    for i in range(n_items):
        run_avm(["remember", "-a", agent, "-c", f"Individual {i}"])
    individual_ms = (time.time() - start) * 1000
    
    # Note: batch write not exposed in CLI yet, just measure individual
    return BenchResult(
        operation=f"write_x{n_items}",
        n_items=n_items,
        total_ms=individual_ms,
        avg_ms=individual_ms / n_items,
        ops_per_sec=n_items / (individual_ms / 1000),
        success=True,
    )


def main():
    print("="*70)
    print("AVM UNIT BENCHMARK (No LLM)")
    print("="*70)
    
    results = []
    
    # Write benchmark
    print("\n[1/6] Write benchmark...")
    for n in [10, 50, 100]:
        print(f"  n={n}...", end=" ", flush=True)
        r = bench_write(n)
        results.append(r)
        print(f"{r.avg_ms:.1f}ms/op, {r.ops_per_sec:.1f} ops/s")
    
    # Recall benchmark (slow due to embedding model load)
    print("\n[2/6] Recall benchmark...")
    for n in [3, 5]:
        print(f"  n={n}...", end=" ", flush=True)
        r = bench_recall(n)
        results.append(r)
        print(f"{r.avg_ms:.1f}ms/op, {r.ops_per_sec:.1f} ops/s")
    
    # Empty recall benchmark (tests min_relevance filter)
    print("\n[3/6] Empty recall benchmark (min_relevance=0.9)...")
    for n in [3, 5]:
        print(f"  n={n}...", end=" ", flush=True)
        r = bench_recall_empty(n)
        results.append(r)
        print(f"{r.avg_ms:.1f}ms/op, {r.ops_per_sec:.1f} ops/s")
    
    # List benchmark
    print("\n[4/6] List benchmark...")
    for n in [10, 20]:
        print(f"  n={n}...", end=" ", flush=True)
        r = bench_list(n)
        results.append(r)
        print(f"{r.avg_ms:.1f}ms/op, {r.ops_per_sec:.1f} ops/s")
    
    # Stats benchmark
    print("\n[5/6] Stats benchmark...")
    for n in [10, 20]:
        print(f"  n={n}...", end=" ", flush=True)
        r = bench_stats(n)
        results.append(r)
        print(f"{r.avg_ms:.1f}ms/op, {r.ops_per_sec:.1f} ops/s")
    
    # Batch write benchmark
    print("\n[6/6] Batch write benchmark...")
    for n in [10, 50]:
        print(f"  n={n}...", end=" ", flush=True)
        r = bench_batch_write(n)
        results.append(r)
        print(f"{r.avg_ms:.1f}ms/op, {r.ops_per_sec:.1f} ops/s")
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"{'Operation':<20} {'N':>6} {'Avg (ms)':>10} {'Ops/s':>10}")
    print("-"*50)
    
    for r in results:
        print(f"{r.operation:<20} {r.n_items:>6} {r.avg_ms:>10.1f} {r.ops_per_sec:>10.1f}")
    
    # Save results
    outfile = Path(__file__).parent / "results" / "unit_benchmark.json"
    with open(outfile, 'w') as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": [asdict(r) for r in results],
        }, f, indent=2)
    
    print(f"\nResults saved to: {outfile}")


if __name__ == "__main__":
    random.seed(42)
    main()
