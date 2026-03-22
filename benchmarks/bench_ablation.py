#!/usr/bin/env python3
"""
AVM Ablation Study Benchmark

Tests the impact of individual optimizations by enabling/disabling them.

Configurations tested:
1. baseline: all optimizations OFF
2. wal_only: only WAL mode ON
3. cache_only: only hot cache ON
4. async_only: only async embedding ON
5. all_on: all optimizations ON (default)

Usage:
    python benchmarks/bench_ablation.py
    python benchmarks/bench_ablation.py --json
    python benchmarks/bench_ablation.py --config wal_only
"""

import time
import tempfile
import os
import json
import random
import argparse
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any


# Ablation configurations
CONFIGS = {
    "baseline": {
        "wal_mode": False,
        "async_embedding": False,
        "hot_cache": False,
        "sync_mode": "FULL",
    },
    "wal_only": {
        "wal_mode": True,
        "async_embedding": False,
        "hot_cache": False,
        "sync_mode": "NORMAL",
    },
    "cache_only": {
        "wal_mode": False,
        "async_embedding": False,
        "hot_cache": True,
        "cache_size": 100,
        "sync_mode": "FULL",
    },
    "async_only": {
        "wal_mode": False,
        "async_embedding": True,
        "hot_cache": False,
        "sync_mode": "FULL",
    },
    "wal_cache": {
        "wal_mode": True,
        "async_embedding": False,
        "hot_cache": True,
        "cache_size": 100,
        "sync_mode": "NORMAL",
    },
    "wal_async": {
        "wal_mode": True,
        "async_embedding": True,
        "hot_cache": False,
        "sync_mode": "NORMAL",
    },
    "all_on": {
        "wal_mode": True,
        "async_embedding": True,
        "hot_cache": True,
        "cache_size": 100,
        "sync_mode": "NORMAL",
    },
}


@dataclass
class AblationResult:
    config_name: str
    config: Dict[str, Any]
    write_ops_sec: float
    write_latency_ms: float
    read_ops_sec: float
    read_latency_ms: float
    search_ops_sec: float
    search_latency_ms: float


def generate_content(size: int = 300) -> str:
    words = ["memory", "agent", "task", "project", "analysis", "data", "result", "market", "trading"]
    return " ".join(random.choice(words) for _ in range(size // 8))


def setup_avm(perf_config: Dict[str, Any]):
    """Setup AVM with specific performance config"""
    tmpdir = tempfile.mkdtemp()
    os.environ['XDG_DATA_HOME'] = tmpdir
    
    from avm.config import AVMConfig, PermissionRule
    from avm import AVM
    
    config = AVMConfig(
        permissions=[
            PermissionRule(pattern="/memory/*", access="rw"),
            PermissionRule(pattern="/shared/*", access="rw"),
        ],
        embedding={"enabled": False},  # Disable embedding for fair comparison
        performance=perf_config,
    )
    
    avm = AVM(config=config, agent_id="ablation")
    return avm, tmpdir


def run_benchmark(config_name: str, perf_config: Dict[str, Any], 
                  n_write: int = 100, n_read: int = 100, n_search: int = 20) -> AblationResult:
    """Run benchmark with specific config"""
    print(f"  Testing: {config_name}...")
    
    avm, tmpdir = setup_avm(perf_config)
    
    # Write benchmark
    write_latencies = []
    start = time.perf_counter()
    for i in range(n_write):
        content = generate_content()
        t0 = time.perf_counter()
        avm.write(f"/memory/item_{i}.md", content)
        write_latencies.append((time.perf_counter() - t0) * 1000)
    write_total = (time.perf_counter() - start) * 1000
    write_ops_sec = n_write / (write_total / 1000)
    write_latency_ms = sum(write_latencies) / len(write_latencies)
    
    # Read benchmark (first pass - cold)
    # Then warm reads
    read_latencies = []
    start = time.perf_counter()
    for i in range(n_read):
        t0 = time.perf_counter()
        avm.read(f"/memory/item_{i % n_write}.md")
        read_latencies.append((time.perf_counter() - t0) * 1000)
    read_total = (time.perf_counter() - start) * 1000
    read_ops_sec = n_read / (read_total / 1000)
    read_latency_ms = sum(read_latencies) / len(read_latencies)
    
    # Search benchmark
    search_latencies = []
    start = time.perf_counter()
    for i in range(n_search):
        t0 = time.perf_counter()
        avm.search("analysis project", limit=10)
        search_latencies.append((time.perf_counter() - t0) * 1000)
    search_total = (time.perf_counter() - start) * 1000
    search_ops_sec = n_search / (search_total / 1000) if search_total > 0 else 0
    search_latency_ms = sum(search_latencies) / len(search_latencies) if search_latencies else 0
    
    return AblationResult(
        config_name=config_name,
        config=perf_config,
        write_ops_sec=write_ops_sec,
        write_latency_ms=write_latency_ms,
        read_ops_sec=read_ops_sec,
        read_latency_ms=read_latency_ms,
        search_ops_sec=search_ops_sec,
        search_latency_ms=search_latency_ms,
    )


def print_results(results: List[AblationResult], as_json: bool = False):
    if as_json:
        print(json.dumps([asdict(r) for r in results], indent=2))
        return
    
    print("\n" + "=" * 80)
    print("ABLATION STUDY RESULTS")
    print("=" * 80)
    
    # Find baseline for comparison
    baseline = next((r for r in results if r.config_name == "baseline"), results[0])
    
    print(f"\n{'Config':<15} {'Write ops/s':<12} {'Write lat':<10} {'Read ops/s':<12} {'Read lat':<10} {'Search ops/s':<12}")
    print("-" * 80)
    
    for r in results:
        write_delta = ((r.write_ops_sec / baseline.write_ops_sec) - 1) * 100 if baseline.write_ops_sec > 0 else 0
        read_delta = ((r.read_ops_sec / baseline.read_ops_sec) - 1) * 100 if baseline.read_ops_sec > 0 else 0
        
        write_ops_str = f"{r.write_ops_sec:.1f}"
        if r.config_name != "baseline":
            write_ops_str += f" ({'+' if write_delta >= 0 else ''}{write_delta:.0f}%)"
        
        read_ops_str = f"{r.read_ops_sec:.1f}"
        if r.config_name != "baseline":
            read_ops_str += f" ({'+' if read_delta >= 0 else ''}{read_delta:.0f}%)"
        
        print(f"{r.config_name:<15} {write_ops_str:<12} {r.write_latency_ms:.2f}ms    {read_ops_str:<12} {r.read_latency_ms:.3f}ms   {r.search_ops_sec:.1f}")
    
    # Summary
    print("\n" + "-" * 80)
    print("OPTIMIZATION IMPACT SUMMARY")
    print("-" * 80)
    
    # Calculate individual contributions
    all_on = next((r for r in results if r.config_name == "all_on"), None)
    if all_on and baseline:
        total_write_improvement = all_on.write_ops_sec / baseline.write_ops_sec
        total_read_improvement = all_on.read_ops_sec / baseline.read_ops_sec
        
        print(f"\nTotal improvement (all_on vs baseline):")
        print(f"  Write: {total_write_improvement:.1f}x faster")
        print(f"  Read:  {total_read_improvement:.1f}x faster")
        
        # Individual contributions
        print(f"\nIndividual optimization contributions:")
        
        for config_name in ["wal_only", "cache_only", "async_only"]:
            r = next((r for r in results if r.config_name == config_name), None)
            if r:
                write_contrib = (r.write_ops_sec / baseline.write_ops_sec - 1) * 100
                read_contrib = (r.read_ops_sec / baseline.read_ops_sec - 1) * 100
                
                opt_name = config_name.replace("_only", "").upper()
                print(f"  {opt_name:<15} Write: {'+' if write_contrib >= 0 else ''}{write_contrib:.0f}%  Read: {'+' if read_contrib >= 0 else ''}{read_contrib:.0f}%")


def main():
    parser = argparse.ArgumentParser(description="AVM Ablation Study")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--config", help="Run specific config only")
    parser.add_argument("--small", action="store_true", help="Smaller dataset")
    args = parser.parse_args()
    
    scale = 0.5 if args.small else 1.0
    n_write = int(100 * scale)
    n_read = int(100 * scale)
    n_search = int(20 * scale)
    
    print("AVM Ablation Study")
    print(f"  Write ops: {n_write}, Read ops: {n_read}, Search ops: {n_search}")
    print()
    
    if args.config:
        configs_to_test = {args.config: CONFIGS[args.config]}
    else:
        configs_to_test = CONFIGS
    
    results = []
    for config_name, perf_config in configs_to_test.items():
        result = run_benchmark(config_name, perf_config, n_write, n_read, n_search)
        results.append(result)
    
    print_results(results, as_json=args.json)


if __name__ == "__main__":
    main()
