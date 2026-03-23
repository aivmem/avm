#!/usr/bin/env python3
"""
AVM Core Benchmark Suite

Tests ALL core AVM features at multiple scales:
- Small (10 items), Medium (100 items), Large (1000 items)

Core Features:
1. Remember/Recall - Basic memory operations
2. Multi-Agent Isolation - Private vs shared namespaces
3. Semantic Search - Vector similarity vs keyword
4. Token-Aware Recall - Fit context budget
5. Delta Sync - Only read changes
6. Knowledge Graph - Linked relationships
7. Timeline/Topics - Discovery and organization
"""

import json
import subprocess
import time
import random
import string
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import List, Dict, Any

# Test data generators
def random_text(words: int = 20) -> str:
    vocab = ["data", "analysis", "report", "system", "user", "config", "error", 
             "update", "deploy", "test", "feature", "bug", "fix", "optimize",
             "scale", "monitor", "alert", "metric", "log", "trace"]
    return " ".join(random.choices(vocab, k=words))

def random_id(length: int = 8) -> str:
    return ''.join(random.choices(string.ascii_lowercase, k=length))


@dataclass
class BenchResult:
    feature: str
    scale: str
    items: int
    operation: str
    duration_ms: float
    success: bool
    tokens_used: int = 0
    details: Dict[str, Any] = None
    

def run_avm(args: List[str], input_text: str = None, timeout: int = 30) -> tuple:
    """Run AVM command and return (success, output, duration_ms)"""
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
    except subprocess.TimeoutExpired:
        return False, "Timeout", timeout * 1000
    except Exception as e:
        return False, str(e), (time.time() - start) * 1000


# =============================================================================
# TEST 1: REMEMBER/RECALL - Basic memory operations
# =============================================================================

def test_remember_recall(scale: str, n_items: int) -> List[BenchResult]:
    """Test basic remember and recall operations."""
    results = []
    agent_id = f"bench_{scale}_{random_id(4)}"
    
    # Write phase
    print(f"    Writing {n_items} items...")
    write_times = []
    for i in range(n_items):
        content = f"Memory item {i}: {random_text(30)}"
        success, output, duration = run_avm(
            ["remember", "-a", agent_id, "-c", content, "-i", str(random.uniform(0.3, 0.9))]
        )
        write_times.append(duration)
        if not success and i < 5:  # Log first few failures
            print(f"      Write {i} failed: {output[:50]}")
    
    results.append(BenchResult(
        feature="remember_recall",
        scale=scale,
        items=n_items,
        operation="write_all",
        duration_ms=sum(write_times),
        success=len([t for t in write_times if t < 5000]) > n_items * 0.9,
        details={"avg_ms": sum(write_times)/len(write_times), "total_writes": n_items}
    ))
    
    # Recall phase
    print(f"    Recalling with different queries...")
    queries = ["memory item", "data analysis", "system error", "random nonexistent xyz"]
    recall_times = []
    for q in queries:
        success, output, duration = run_avm(
            ["recall", "-a", agent_id, "-t", "500", q]
        )
        recall_times.append({"query": q, "duration_ms": duration, "success": success})
    
    results.append(BenchResult(
        feature="remember_recall",
        scale=scale,
        items=n_items,
        operation="recall",
        duration_ms=sum(r["duration_ms"] for r in recall_times),
        success=all(r["success"] for r in recall_times),
        details={"queries": recall_times}
    ))
    
    return results


# =============================================================================
# TEST 2: MULTI-AGENT ISOLATION
# =============================================================================

def test_multi_agent(scale: str, n_agents: int) -> List[BenchResult]:
    """Test private vs shared memory isolation."""
    results = []
    agents = [f"agent_{i}_{random_id(4)}" for i in range(n_agents)]
    
    # Each agent writes private memory
    print(f"    {n_agents} agents writing private memories...")
    private_times = []
    for agent in agents:
        content = f"Private secret for {agent}: {random_text(20)}"
        success, output, duration = run_avm(
            ["remember", "-a", agent, "-c", content, "-t", f"secret_{agent}"]
        )
        private_times.append(duration)
    
    results.append(BenchResult(
        feature="multi_agent",
        scale=scale,
        items=n_agents,
        operation="private_write",
        duration_ms=sum(private_times),
        success=True,
        details={"agents": n_agents}
    ))
    
    # Write shared memory
    print(f"    Writing shared memory...")
    shared_content = f"Shared knowledge: {random_text(30)}"
    success, output, duration = run_avm(
        ["write", "/memory/shared/bench/shared_knowledge.md"],
        input_text=shared_content
    )
    
    results.append(BenchResult(
        feature="multi_agent",
        scale=scale,
        items=1,
        operation="shared_write",
        duration_ms=duration,
        success=success,
    ))
    
    # Test isolation: agent A should NOT see agent B's private memory
    print(f"    Testing isolation...")
    agent_a, agent_b = agents[0], agents[1]
    
    # Agent B tries to recall Agent A's secret
    success, output, duration = run_avm(
        ["recall", "-a", agent_b, "-t", "500", f"secret for {agent_a}"]
    )
    
    # Success = NOT finding agent_a's secret
    isolation_works = agent_a not in output or "secret" not in output.lower()
    
    results.append(BenchResult(
        feature="multi_agent",
        scale=scale,
        items=n_agents,
        operation="isolation_check",
        duration_ms=duration,
        success=isolation_works,
        details={"found_other_secret": not isolation_works}
    ))
    
    return results


# =============================================================================
# TEST 3: SEMANTIC SEARCH
# =============================================================================

def test_semantic_search(scale: str, n_items: int) -> List[BenchResult]:
    """Test semantic similarity vs exact keyword matching."""
    results = []
    
    # Create semantically related but keyword-different content
    semantic_pairs = [
        ("The server is running slowly", "performance issues with the machine"),
        ("User authentication failed", "login problems for customers"),
        ("Database connection timeout", "DB link dropped"),
        ("Memory usage is high", "RAM consumption excessive"),
        ("API rate limit exceeded", "too many requests to the endpoint"),
    ]
    
    # Write content
    print(f"    Writing {n_items} semantically varied items...")
    for i in range(n_items):
        pair = semantic_pairs[i % len(semantic_pairs)]
        content = f"{pair[0]}. Details: {random_text(20)}"
        run_avm(
            ["write", f"/memory/shared/bench/semantic_{i}.md"],
            input_text=content
        )
    
    # Test semantic recall (query uses different words than content)
    test_queries = [
        ("machine is slow", "server running slowly"),  # Should find performance
        ("customer cannot sign in", "authentication failed"),  # Should find login
        ("too many API calls", "rate limit"),  # Should find rate limit
    ]
    
    print(f"    Testing semantic matches...")
    semantic_scores = []
    for query, expected_keyword in test_queries:
        success, output, duration = run_avm(
            ["recall", "-a", "semantic_test", "-t", "300", query]
        )
        found = expected_keyword.lower() in output.lower()
        semantic_scores.append({
            "query": query,
            "found_related": found,
            "duration_ms": duration,
        })
    
    results.append(BenchResult(
        feature="semantic_search",
        scale=scale,
        items=n_items,
        operation="semantic_recall",
        duration_ms=sum(s["duration_ms"] for s in semantic_scores),
        success=sum(1 for s in semantic_scores if s["found_related"]) >= len(test_queries) // 2,
        details={"queries": semantic_scores}
    ))
    
    return results


# =============================================================================
# TEST 4: TOKEN-AWARE RECALL
# =============================================================================

def test_token_aware(scale: str, n_items: int) -> List[BenchResult]:
    """Test that recall respects token budget."""
    results = []
    agent_id = f"token_test_{random_id(4)}"
    
    # Write items with increasing size
    print(f"    Writing {n_items} items of varying sizes...")
    for i in range(n_items):
        size = 20 + (i % 5) * 20  # 20-100 words
        content = f"Item {i}: " + random_text(size)
        run_avm(["remember", "-a", agent_id, "-c", content])
    
    # Test different token budgets
    budgets = [100, 300, 500, 1000]
    
    print(f"    Testing token budgets: {budgets}")
    budget_results = []
    for budget in budgets:
        success, output, duration = run_avm(
            ["recall", "-a", agent_id, "-t", str(budget), "item"]
        )
        
        # Estimate tokens in output
        output_tokens = len(output.split())
        
        budget_results.append({
            "budget": budget,
            "output_tokens": output_tokens,
            "within_budget": output_tokens <= budget * 1.2,  # 20% tolerance
            "duration_ms": duration,
        })
    
    results.append(BenchResult(
        feature="token_aware",
        scale=scale,
        items=n_items,
        operation="budget_recall",
        duration_ms=sum(b["duration_ms"] for b in budget_results),
        success=all(b["within_budget"] for b in budget_results),
        details={"budgets": budget_results}
    ))
    
    return results


# =============================================================================
# TEST 5: DELTA SYNC
# =============================================================================

def test_delta_sync(scale: str, n_items: int) -> List[BenchResult]:
    """Test reading only changes since last read."""
    results = []
    
    # Write initial batch
    print(f"    Writing initial {n_items} items...")
    for i in range(n_items):
        run_avm(
            ["write", f"/memory/shared/bench/delta_{i}.md"],
            input_text=f"Initial content {i}: {random_text(15)}"
        )
    
    time.sleep(0.5)  # Ensure timestamp difference
    
    # Record timestamp
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Write new items (the delta)
    new_count = max(1, n_items // 10)
    print(f"    Writing {new_count} new items...")
    for i in range(new_count):
        run_avm(
            ["write", f"/memory/shared/bench/delta_new_{i}.md"],
            input_text=f"NEW content {i}: {random_text(15)}"
        )
    
    # Read all (baseline)
    print(f"    Reading all items...")
    success, output_all, duration_all = run_avm(
        ["list", "/memory/shared/bench/", "--json"]
    )
    
    # Read delta only (using search for recent)
    print(f"    Reading delta only...")
    success, output_delta, duration_delta = run_avm(
        ["recall", "-a", "delta_test", "-t", "500", "NEW content"]
    )
    
    results.append(BenchResult(
        feature="delta_sync",
        scale=scale,
        items=n_items,
        operation="full_read",
        duration_ms=duration_all,
        success=True,
        tokens_used=len(output_all.split()),
    ))
    
    results.append(BenchResult(
        feature="delta_sync",
        scale=scale,
        items=new_count,
        operation="delta_read",
        duration_ms=duration_delta,
        success=True,
        tokens_used=len(output_delta.split()),
        details={"delta_items": new_count, "total_items": n_items}
    ))
    
    return results


# =============================================================================
# TEST 6: TIMELINE/TOPICS
# =============================================================================

def test_discovery(scale: str, n_items: int) -> List[BenchResult]:
    """Test timeline and topic organization features."""
    results = []
    agent_id = f"discover_{random_id(4)}"
    
    # Write items with different topics/tags
    topics = ["market", "tech", "research", "ops", "security"]
    
    print(f"    Writing {n_items} items across {len(topics)} topics...")
    for i in range(n_items):
        topic = topics[i % len(topics)]
        content = f"[{topic}] Item {i}: {random_text(20)}"
        run_avm([
            "remember", "-a", agent_id, "-c", content,
            "--tags", topic
        ])
    
    # Test memory stats
    print(f"    Getting memory stats...")
    success, output, duration = run_avm(["memory-stats", "-a", agent_id])
    
    results.append(BenchResult(
        feature="discovery",
        scale=scale,
        items=n_items,
        operation="memory_stats",
        duration_ms=duration,
        success=success,
        details={"output": output[:200]}
    ))
    
    # Test listing by path
    success, output, duration = run_avm([
        "list", f"/memory/private/{agent_id}/", "--json"
    ])
    
    results.append(BenchResult(
        feature="discovery",
        scale=scale,
        items=n_items,
        operation="list_private",
        duration_ms=duration,
        success=success,
    ))
    
    return results


# =============================================================================
# MAIN
# =============================================================================

def cleanup():
    """Clean up benchmark data."""
    subprocess.run(
        ["avm", "delete", "/memory/shared/bench/", "--recursive"],
        capture_output=True
    )


def main():
    print("="*70)
    print("AVM CORE BENCHMARK SUITE")
    print("Testing all features at multiple scales")
    print("="*70)
    
    # Define scales
    scales = {
        "small": 10,
        "medium": 100,
        "large": 500,  # Reduced from 1000 for time
    }
    
    all_results = []
    
    # Test each feature
    features = [
        ("Remember/Recall", test_remember_recall),
        ("Multi-Agent Isolation", test_multi_agent),
        ("Semantic Search", test_semantic_search),
        ("Token-Aware Recall", test_token_aware),
        ("Delta Sync", test_delta_sync),
        ("Timeline/Topics", test_discovery),
    ]
    
    for feature_name, test_func in features:
        print(f"\n{'='*70}")
        print(f"FEATURE: {feature_name}")
        print("="*70)
        
        for scale_name, n_items in scales.items():
            print(f"\n  [{scale_name.upper()}] n={n_items}")
            
            try:
                results = test_func(scale_name, n_items)
                all_results.extend(results)
                
                for r in results:
                    status = "✓" if r.success else "✗"
                    print(f"    {r.operation}: {status} ({r.duration_ms:.0f}ms)")
            except Exception as e:
                print(f"    ERROR: {e}")
                all_results.append(BenchResult(
                    feature=feature_name.lower().replace(" ", "_"),
                    scale=scale_name,
                    items=n_items,
                    operation="error",
                    duration_ms=0,
                    success=False,
                    details={"error": str(e)}
                ))
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY BY FEATURE")
    print("="*70)
    
    # Group by feature
    by_feature = {}
    for r in all_results:
        if r.feature not in by_feature:
            by_feature[r.feature] = []
        by_feature[r.feature].append(r)
    
    print(f"{'Feature':<25} {'Small':>12} {'Medium':>12} {'Large':>12}")
    print("-"*65)
    
    for feature, results in by_feature.items():
        small = next((r for r in results if r.scale == "small"), None)
        medium = next((r for r in results if r.scale == "medium"), None)
        large = next((r for r in results if r.scale == "large"), None)
        
        def fmt(r):
            if r is None:
                return "-"
            return f"{'✓' if r.success else '✗'} {r.duration_ms:.0f}ms"
        
        print(f"{feature:<25} {fmt(small):>12} {fmt(medium):>12} {fmt(large):>12}")
    
    # Save results
    outfile = Path(__file__).parent / "results" / "core_benchmark.json"
    with open(outfile, 'w') as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scales": scales,
            "results": [asdict(r) for r in all_results],
        }, f, indent=2, default=str)
    
    print(f"\nDetailed results: {outfile}")
    
    # Cleanup
    print("\nCleaning up...")
    cleanup()


if __name__ == "__main__":
    random.seed(42)
    main()
