#!/usr/bin/env python3
"""
Librarian Performance Benchmark

Measures the impact of Librarian on multi-agent knowledge discovery.
"""

import os
import time
import statistics
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


def create_avm_for_agent(tmpdir: str, agent_id: str):
    """Create AVM instance for a specific agent."""
    os.environ['XDG_DATA_HOME'] = tmpdir
    
    from avm import AVM
    from avm.config import AVMConfig, PermissionRule
    
    config = AVMConfig(
        permissions=[
            PermissionRule(pattern="/memory/*", access="rw"),
            PermissionRule(pattern="/shared/*", access="rw"),
        ],
        embedding={"enabled": True, "backend": "local", "model": "all-MiniLM-L6-v2", "auto_index": True},
        performance={"hot_cache": True, "cache_size": 100, "wal_mode": True},
    )
    
    return AVM(config=config, agent_id=agent_id)


def setup_memories(tmpdir: str, agents: list, memories_per_agent: int = 10):
    """Set up memories for each agent."""
    topics = ["trading", "research", "crypto", "macro", "technical"]
    
    for agent in agents:
        avm = create_avm_for_agent(tmpdir, agent)
        mem = avm.agent_memory(agent)
        for j in range(memories_per_agent):
            topic = topics[j % len(topics)]
            content = f"Agent {agent} observation about {topic}: data point #{j}"
            mem.remember(content, importance=0.5 + (j % 5) * 0.1, tags=[topic])
    
    # Add shared memories
    avm = create_avm_for_agent(tmpdir, "shared_writer")
    for i in range(5):
        topic = topics[i % len(topics)]
        avm.write(f"/memory/shared/{topic}_{i}.md", f"Shared knowledge about {topic}")
    
    return avm  # Return last one for vfs access


def bench_traditional_vs_librarian(avm, agents: list, iterations: int = 30):
    """Compare traditional multi-agent recall vs Librarian single query."""
    from avm.librarian import Librarian
    
    librarian = Librarian(avm.store)
    for agent in agents:
        librarian.register_agent(agent)
    
    query = "trading market analysis"
    
    # Traditional: query each agent separately
    trad_latencies = []
    for _ in range(iterations):
        start = time.perf_counter()
        for agent in agents:
            # Simulate: search + filter for agent
            avm.search(f"{query} {agent}", limit=10)
        trad_latencies.append((time.perf_counter() - start) * 1000)
    
    # Librarian: single query
    lib_latencies = []
    for _ in range(iterations):
        start = time.perf_counter()
        response = librarian.query(agents[0], query)
        lib_latencies.append((time.perf_counter() - start) * 1000)
    
    return {
        "traditional": {
            "p50_ms": statistics.median(trad_latencies),
            "p99_ms": sorted(trad_latencies)[int(len(trad_latencies) * 0.99)],
            "hops": 4 * len(agents),  # Each search = 4 hops
        },
        "librarian": {
            "p50_ms": statistics.median(lib_latencies),
            "p99_ms": sorted(lib_latencies)[int(len(lib_latencies) * 0.99)],
            "hops": 1,
        },
    }


def bench_who_knows(avm, agents: list, iterations: int = 100):
    """Measure who-knows lookup."""
    from avm.librarian import Librarian
    
    librarian = Librarian(avm.store)
    for agent in agents:
        librarian.register_agent(agent)
    
    latencies = []
    for _ in range(iterations):
        start = time.perf_counter()
        result = librarian.who_knows("trading")
        latencies.append((time.perf_counter() - start) * 1000)
    
    return {
        "p50_ms": statistics.median(latencies),
        "p99_ms": sorted(latencies)[int(len(latencies) * 0.99)],
    }


def bench_privacy_policy(avm, agents: list, iterations: int = 50):
    """Measure privacy policy overhead."""
    from avm.librarian import Librarian, PrivacyPolicy
    
    # No privacy
    lib_none = Librarian(avm.store, privacy_policy=PrivacyPolicy("full"))
    for agent in agents:
        lib_none.register_agent(agent)
    
    none_latencies = []
    for _ in range(iterations):
        start = time.perf_counter()
        lib_none.query(agents[0], "trading")
        none_latencies.append((time.perf_counter() - start) * 1000)
    
    # With privacy
    lib_priv = Librarian(avm.store, privacy_policy=PrivacyPolicy("owner"))
    for agent in agents:
        lib_priv.register_agent(agent)
    
    priv_latencies = []
    for _ in range(iterations):
        start = time.perf_counter()
        lib_priv.query(agents[0], "trading")
        priv_latencies.append((time.perf_counter() - start) * 1000)
    
    p50_none = statistics.median(none_latencies)
    p50_priv = statistics.median(priv_latencies)
    
    return {
        "no_privacy_p50_ms": p50_none,
        "with_privacy_p50_ms": p50_priv,
        "overhead_ms": p50_priv - p50_none,
        "overhead_pct": ((p50_priv - p50_none) / p50_none * 100) if p50_none > 0 else 0,
    }


def bench_scalability(tmpdir: str, max_agents: int = 16):
    """Measure scalability with agent count."""
    from avm.librarian import Librarian
    
    results = []
    
    for n in [2, 4, 8, 16]:
        if n > max_agents:
            break
        
        agents = [f"scale_{i}" for i in range(n)]
        avm = setup_memories(tmpdir, agents, memories_per_agent=5)
        
        librarian = Librarian(avm.store)
        for agent in agents:
            librarian.register_agent(agent)
        
        latencies = []
        for _ in range(30):
            start = time.perf_counter()
            librarian.who_knows("scale_test")
            latencies.append((time.perf_counter() - start) * 1000)
        
        results.append({
            "n_agents": n,
            "p50_ms": statistics.median(latencies),
            "p99_ms": sorted(latencies)[int(len(latencies) * 0.99)],
        })
    
    return results


def main():
    print("=" * 60)
    print("LIBRARIAN BENCHMARK")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        agents = ["akashi", "trader", "analyst", "researcher", "watcher"]
        
        print("\n[1] Setting up multi-agent environment...")
        avm = setup_memories(tmpdir, agents, memories_per_agent=10)
        print(f"    Created {len(agents)} agents with 10 memories each")
        
        print("\n[2] Traditional vs Librarian Query...")
        cmp = bench_traditional_vs_librarian(avm, agents)
        print(f"    Traditional (5 agents):")
        print(f"      p50: {cmp['traditional']['p50_ms']:.2f}ms")
        print(f"      Hops: {cmp['traditional']['hops']}")
        print(f"    Librarian:")
        print(f"      p50: {cmp['librarian']['p50_ms']:.2f}ms")
        print(f"      Hops: {cmp['librarian']['hops']}")
        
        hop_reduction = (1 - cmp['librarian']['hops'] / cmp['traditional']['hops']) * 100
        print(f"    → Hop reduction: {hop_reduction:.0f}%")
        
        print("\n[3] Who-Knows Lookup...")
        wk = bench_who_knows(avm, agents)
        print(f"    p50: {wk['p50_ms']:.2f}ms, p99: {wk['p99_ms']:.2f}ms")
        
        print("\n[4] Privacy Policy Overhead...")
        priv = bench_privacy_policy(avm, agents)
        print(f"    No privacy:   {priv['no_privacy_p50_ms']:.2f}ms")
        print(f"    With privacy: {priv['with_privacy_p50_ms']:.2f}ms")
        print(f"    Overhead:     {priv['overhead_ms']:.2f}ms ({priv['overhead_pct']:.1f}%)")
        
        print("\n[5] Scalability...")
        scale = bench_scalability(tmpdir)
        for row in scale:
            print(f"    {row['n_agents']:2d} agents: p50={row['p50_ms']:.2f}ms")
        
        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"  Hop Reduction:      {hop_reduction:.0f}%")
        print(f"  Librarian p50:      {cmp['librarian']['p50_ms']:.2f}ms")
        print(f"  Who-Knows p50:      {wk['p50_ms']:.2f}ms")
        print(f"  Privacy Overhead:   {priv['overhead_pct']:.1f}%")
        
        # Output for blog
        import json
        results = {
            "comparison": cmp,
            "who_knows": wk,
            "privacy": priv,
            "scalability": scale,
            "hop_reduction_pct": hop_reduction,
        }
        print("\n" + "=" * 60)
        print("JSON OUTPUT")
        print("=" * 60)
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
