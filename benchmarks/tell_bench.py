#!/usr/bin/env python3
"""
Tell System Benchmark

Measures:
1. Cross-agent message delivery latency
2. Priority queue ordering
3. Throughput at scale
4. Webhook trigger latency
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
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from avm.store import AVMStore
from avm.tell import TellStore, Tell, TellPriority


@dataclass
class TellBenchmarkConfig:
    """Benchmark configuration"""
    num_agents: int = 10
    messages_per_agent: int = 100
    priorities: List[str] = field(default_factory=lambda: ["low", "normal", "urgent"])
    seed: int = 42


@dataclass
class TellBenchmarkResult:
    """Benchmark results"""
    # Latency (ms)
    write_avg_ms: float = 0.0
    write_p99_ms: float = 0.0
    read_avg_ms: float = 0.0
    read_p99_ms: float = 0.0
    
    # Throughput
    writes_per_sec: float = 0.0
    reads_per_sec: float = 0.0
    
    # Priority ordering
    priority_ordering_correct: float = 0.0
    
    # Scale
    total_messages: int = 0
    total_agents: int = 0
    
    def to_dict(self) -> Dict:
        return {
            "latency_ms": {
                "write_avg": round(self.write_avg_ms, 3),
                "write_p99": round(self.write_p99_ms, 3),
                "read_avg": round(self.read_avg_ms, 3),
                "read_p99": round(self.read_p99_ms, 3),
            },
            "throughput": {
                "writes_per_sec": round(self.writes_per_sec, 1),
                "reads_per_sec": round(self.reads_per_sec, 1),
            },
            "correctness": {
                "priority_ordering": round(self.priority_ordering_correct, 4),
            },
            "scale": {
                "total_messages": self.total_messages,
                "total_agents": self.total_agents,
            }
        }


class TellBenchmark:
    """Benchmark harness for Tell system"""
    
    def __init__(self, config: TellBenchmarkConfig):
        self.config = config
        self.tmpdir = tempfile.mkdtemp()
        self.store = AVMStore(os.path.join(self.tmpdir, "bench.db"))
        self.tell_store = TellStore(os.path.join(self.tmpdir, "tell.db"))
        
        random.seed(config.seed)
        self.agents = [f"agent_{i:03d}" for i in range(config.num_agents)]
    
    def benchmark_write(self) -> Tuple[List[float], List[int]]:
        """Benchmark write performance"""
        latencies = []
        tell_ids = []
        
        priority_map = {
            "low": TellPriority.LOW,
            "normal": TellPriority.NORMAL,
            "urgent": TellPriority.URGENT,
        }
        
        for _ in range(self.config.messages_per_agent):
            for agent in self.agents:
                # Pick random recipient (not self)
                recipients = [a for a in self.agents if a != agent]
                to_agent = random.choice(recipients)
                priority = random.choice(self.config.priorities)
                
                content = f"Message from {agent} to {to_agent}: {random.randint(1000, 9999)}"
                
                start = time.perf_counter()
                tell_id = self.tell_store.send(
                    from_agent=agent,
                    to_agent=to_agent,
                    content=content,
                    priority=priority_map[priority],
                )
                elapsed_ms = (time.perf_counter() - start) * 1000
                
                latencies.append(elapsed_ms)
                tell_ids.append(tell_id)
        
        return latencies, tell_ids
    
    def benchmark_read(self) -> List[float]:
        """Benchmark read performance"""
        latencies = []
        
        for agent in self.agents:
            start = time.perf_counter()
            tells = self.tell_store.get_unread(agent)[:100]
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)
            
            # Mark as read
            if tells:
                self.tell_store.mark_read([t.id for t in tells])
        
        return latencies
    
    def benchmark_priority_ordering(self) -> float:
        """Verify priority ordering"""
        # Clear and send new messages with known priorities
        test_agent = "priority_test_agent"
        
        # Send messages in random order but with different priorities
        messages = [
            ("low1", TellPriority.LOW),
            ("urgent1", TellPriority.URGENT),
            ("normal1", TellPriority.NORMAL),
            ("low2", TellPriority.LOW),
            ("urgent2", TellPriority.URGENT),
            ("normal2", TellPriority.NORMAL),
        ]
        
        random.shuffle(messages)
        
        for content, priority in messages:
            self.tell_store.send(
                from_agent="sender",
                to_agent=test_agent,
                content=content,
                priority=priority,
            )
        
        # Read back - should be ordered by priority (urgent first)
        tells = self.tell_store.get_unread(test_agent)[:10]
        
        # Check ordering (urgent > normal > low)
        expected_order = [TellPriority.URGENT, TellPriority.URGENT,
                         TellPriority.NORMAL, TellPriority.NORMAL,
                         TellPriority.LOW, TellPriority.LOW]
        
        correct = 0
        for i, tell in enumerate(tells[:len(expected_order)]):
            if tell.priority == expected_order[i]:
                correct += 1
        
        return correct / len(expected_order)
    
    def run_benchmark(self) -> TellBenchmarkResult:
        """Run full benchmark"""
        result = TellBenchmarkResult()
        result.total_agents = self.config.num_agents
        
        # Write benchmark
        print("Running write benchmark...")
        write_start = time.perf_counter()
        write_latencies, tell_ids = self.benchmark_write()
        write_elapsed = time.perf_counter() - write_start
        
        result.total_messages = len(tell_ids)
        result.write_avg_ms = sum(write_latencies) / len(write_latencies)
        write_latencies.sort()
        result.write_p99_ms = write_latencies[int(len(write_latencies) * 0.99)]
        result.writes_per_sec = len(tell_ids) / write_elapsed
        
        # Read benchmark
        print("Running read benchmark...")
        read_start = time.perf_counter()
        read_latencies = self.benchmark_read()
        read_elapsed = time.perf_counter() - read_start
        
        result.read_avg_ms = sum(read_latencies) / len(read_latencies)
        read_latencies.sort()
        result.read_p99_ms = read_latencies[int(len(read_latencies) * 0.99)]
        result.reads_per_sec = len(read_latencies) / read_elapsed
        
        # Priority ordering
        print("Testing priority ordering...")
        result.priority_ordering_correct = self.benchmark_priority_ordering()
        
        return result
    
    def cleanup(self):
        """Cleanup"""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def run_scale_benchmark(max_agents: int = 50, step: int = 10):
    """Run benchmark at different scales"""
    results = []
    
    for num_agents in range(10, max_agents + 1, step):
        config = TellBenchmarkConfig(
            num_agents=num_agents,
            messages_per_agent=50,
        )
        
        bench = TellBenchmark(config)
        result = bench.run_benchmark()
        bench.cleanup()
        
        results.append({
            "agents": num_agents,
            "messages": result.total_messages,
            **result.to_dict()
        })
        
        print(f"[{num_agents} agents] Write: {result.write_avg_ms:.3f}ms, "
              f"Read: {result.read_avg_ms:.3f}ms, "
              f"Throughput: {result.writes_per_sec:.0f}/s")
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Tell System Benchmark")
    parser.add_argument("--agents", "-a", type=int, default=10, help="Number of agents")
    parser.add_argument("--messages", "-m", type=int, default=100, help="Messages per agent")
    parser.add_argument("--scale", action="store_true", help="Run scale benchmark")
    parser.add_argument("--max-agents", type=int, default=50, help="Max agents for scale test")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    if args.scale:
        results = run_scale_benchmark(args.max_agents)
        if args.json:
            print(json.dumps(results, indent=2))
        return
    
    config = TellBenchmarkConfig(
        num_agents=args.agents,
        messages_per_agent=args.messages,
    )
    
    bench = TellBenchmark(config)
    result = bench.run_benchmark()
    bench.cleanup()
    
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("\n" + "=" * 50)
        print("TELL SYSTEM BENCHMARK RESULTS")
        print("=" * 50)
        print(f"\nScale: {result.total_agents} agents, {result.total_messages} messages")
        print(f"\nWrite Performance:")
        print(f"  Average: {result.write_avg_ms:.3f}ms")
        print(f"  P99:     {result.write_p99_ms:.3f}ms")
        print(f"  Throughput: {result.writes_per_sec:.1f} writes/sec")
        print(f"\nRead Performance:")
        print(f"  Average: {result.read_avg_ms:.3f}ms")
        print(f"  P99:     {result.read_p99_ms:.3f}ms")
        print(f"  Throughput: {result.reads_per_sec:.1f} reads/sec")
        print(f"\nCorrectness:")
        print(f"  Priority Ordering: {result.priority_ordering_correct:.2%}")


if __name__ == "__main__":
    main()
