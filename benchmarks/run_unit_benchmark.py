#!/usr/bin/env python3
"""
AVM Unit Benchmark - No LLM required.
Tests core AVM operations: write, read, recall, search.

Uses in-process API calls for accurate timing (avoids CLI subprocess overhead).
"""

import json
import subprocess
import time
import random
import string
import sys
import os
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import List

# Suppress warnings
import warnings
warnings.filterwarnings('ignore')
os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
os.environ['TRANSFORMERS_VERBOSITY'] = 'error'

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from avm.core import AVM
from avm.config import load_config


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


def get_avm() -> AVM:
    """Get shared AVM instance."""
    global _avm
    if '_avm' not in globals():
        import io
        import contextlib
        with contextlib.redirect_stderr(io.StringIO()):
            config = load_config()
            _avm = AVM(config)
    return _avm


def bench_write(n: int) -> BenchResult:
    """Benchmark write operations (in-process)."""
    avm = get_avm()
    agent_id = f"bench_write_{random_id()}"
    memory = avm.agent_memory(agent_id)
    times = []
    
    for i in range(n):
        content = f"Memory {i}: {random_text(30)}"
        start = time.time()
        memory.remember(content, importance=0.5)
        times.append((time.time() - start) * 1000)
    
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
    """Benchmark recall operations (in-process with warm model)."""
    avm = get_avm()
    agent_id = f"bench_recall_{random_id()}"
    memory = avm.agent_memory(agent_id)
    
    # Pre-populate
    for i in range(50):
        content = f"Pre-populated memory {i}: {random_text(20)}"
        memory.remember(content)
    
    times = []
    queries = ["data analysis", "bug fix", "deploy test", "api monitor", "cache sync"]
    
    for i in range(n):
        q = queries[i % len(queries)]
        start = time.time()
        result = memory.recall(q, max_tokens=300)
        times.append((time.time() - start) * 1000)
    
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
    avm = get_avm()
    agent_id = f"bench_empty_{random_id()}"
    memory = avm.agent_memory(agent_id)
    times = []
    
    for i in range(n):
        # Query with gibberish that won't match anything
        start = time.time()
        result = memory.recall(f"xyzzy_{random_id()}_plugh", max_tokens=100, min_relevance=0.9)
        times.append((time.time() - start) * 1000)
        # Verify empty return
        if result.strip():
            print(f"  Warning: expected empty, got {len(result)} chars")
    
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
    """Benchmark list operations (in-process)."""
    avm = get_avm()
    times = []
    
    for i in range(n):
        start = time.time()
        nodes = avm.list("/memory/")
        times.append((time.time() - start) * 1000)
    
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
    """Benchmark memory-stats operations (in-process)."""
    avm = get_avm()
    agent_id = f"bench_stats_{random_id()}"
    memory = avm.agent_memory(agent_id)
    
    # Pre-populate
    for i in range(20):
        memory.remember(f"Content {i}")
    
    times = []
    for i in range(n):
        start = time.time()
        stats = memory.stats()
        times.append((time.time() - start) * 1000)
    
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
    """Benchmark batch write."""
    avm = get_avm()
    agent_id = f"bench_batch_{random_id()}"
    memory = avm.agent_memory(agent_id)
    
    items = [{"content": f"Batch item {i}: {random_text(15)}"} for i in range(n_items)]
    
    start = time.time()
    results = memory.batch_remember(items)
    batch_ms = (time.time() - start) * 1000
    
    return BenchResult(
        operation=f"batch_x{n_items}",
        n_items=n_items,
        total_ms=batch_ms,
        avg_ms=batch_ms / n_items,
        ops_per_sec=n_items / (batch_ms / 1000),
        success=len(results) == n_items,
    )


def main():
    import io
    import contextlib
    
    print("="*70)
    print("AVM UNIT BENCHMARK (No LLM, In-Process)")
    print("="*70)
    
    # Warmup: load model once
    print("\nWarming up embedding model...")
    with contextlib.redirect_stderr(io.StringIO()):
        avm = get_avm()
        if avm._embedding_store:
            avm._embedding_store.backend.warmup()
    print("  Done.")
    
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
