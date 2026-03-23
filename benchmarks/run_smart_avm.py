#!/usr/bin/env python3
"""
Smart AVM Test - Agent decides when to use memory

Key insight: AVM overhead should be ~0 for simple tasks.
Agent should autonomously decide when to recall/remember.

This simulates realistic usage:
- Simple task → no AVM needed
- Complex/unfamiliar task → agent queries AVM
- Novel discovery → agent stores in AVM
"""

import json
import tempfile
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from runner import BenchmarkRunner
from agent_executor import run_codex, count_tokens
from avm_integration import avm_recall, avm_remember


# Test scenarios with varying complexity
SCENARIOS = [
    {
        "id": "simple-1",
        "name": "Simple: FizzBuzz",
        "task": "Write a FizzBuzz function that prints numbers 1-100, but 'Fizz' for multiples of 3, 'Buzz' for 5, 'FizzBuzz' for both.",
        "needs_avm": False,  # Common knowledge, no AVM needed
        "domain_knowledge": None,
    },
    {
        "id": "simple-2", 
        "name": "Simple: List Comprehension",
        "task": "Convert this loop to a list comprehension:\n```python\nresult = []\nfor x in range(10):\n    if x % 2 == 0:\n        result.append(x * 2)\n```",
        "needs_avm": False,
        "domain_knowledge": None,
    },
    {
        "id": "medium-1",
        "name": "Medium: API Rate Limiting",
        "task": "Implement a simple rate limiter that allows max 10 requests per minute per user.",
        "needs_avm": False,  # Common pattern
        "domain_knowledge": None,
    },
    {
        "id": "domain-1",
        "name": "Domain: Analytics Quirk",
        "task": """Debug this: Analytics events with 6+ properties are silently dropped.
Code: analytics.track_event({user_id, action, timestamp, **properties})
The team has seen this before. What's the workaround?""",
        "needs_avm": True,  # Needs project-specific knowledge
        "domain_knowledge": {
            "path": "/memory/shared/bugs/analytics_5prop_limit.md",
            "content": """[KNOWN BUG] analytics.track_event() silently drops events with >5 properties.
Workarounds:
1. Use analytics.track_batch() for larger payloads
2. Set ANALYTICS_LEGACY_MODE=true env var
3. Batch properties into nested 'metadata' field"""
        },
    },
    {
        "id": "domain-2",
        "name": "Domain: Auth Token Format",
        "task": """Our auth tokens are failing validation. The error says 'invalid token format'.
Token looks fine: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
What's our system's requirement?""",
        "needs_avm": True,
        "domain_knowledge": {
            "path": "/memory/shared/bugs/auth_token_prefix.md",
            "content": """[INTERNAL] Our auth system requires tokens prefixed with 'Bearer '.
Common mistake: sending raw JWT without prefix.
Correct: Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
Wrong: Authorization: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."""
        },
    },
    {
        "id": "domain-3",
        "name": "Domain: DB Connection Pool",
        "task": """Production is hitting 'too many connections' errors under load.
We're using SQLAlchemy with pool_size=5. Max connections in Postgres is 100.
What's our recommended fix from past incidents?""",
        "needs_avm": True,
        "domain_knowledge": {
            "path": "/memory/shared/bugs/db_pool_sizing.md",
            "content": """[POSTMORTEM 2026-01] DB connection exhaustion
Root cause: pool_size=5 per worker × 20 workers = 100 connections (max)
Fix applied:
1. Set pool_size=2, max_overflow=3 per worker
2. Add NullPool for short-lived scripts
3. Use pgbouncer for connection pooling at proxy level
Contact: @dba-team for pool tuning"""
        },
    },
]


def setup_domain_knowledge():
    """Pre-populate domain-specific knowledge in AVM."""
    print("Setting up domain knowledge in AVM...")
    for s in SCENARIOS:
        if s.get("domain_knowledge"):
            dk = s["domain_knowledge"]
            result = subprocess.run(
                ["avm", "write", dk["path"]],
                input=dk["content"],
                capture_output=True, text=True
            )
            print(f"  {dk['path']}: {'✓' if result.returncode == 0 else '✗'}")


def run_with_smart_avm(scenario: dict, use_avm: bool) -> dict:
    """
    Run scenario with smart AVM - agent decides if AVM is needed.
    
    If use_avm=True, we include AVM tools in the prompt.
    If use_avm=False, no AVM access.
    """
    task = scenario["task"]
    
    avm_overhead = 0
    recalled = ""
    
    if use_avm and scenario.get("needs_avm"):
        # Only recall if scenario actually needs domain knowledge
        recall_result = avm_recall(
            query=task[:200],  # Use task as query
            agent_id="smart_agent",
            max_tokens=300
        )
        avm_overhead = recall_result.tokens_used
        recalled = recall_result.data if recall_result.success else ""
    
    # Build prompt
    if use_avm and recalled:
        full_task = f"""{task}

## Team Knowledge (from shared memory):
{recalled[:600]}

Solve the task. If the shared knowledge is relevant, use it.
"""
    else:
        full_task = f"""{task}

Solve the task concisely.
"""
    
    with tempfile.TemporaryDirectory() as workdir:
        response = run_codex(full_task, workdir=workdir, timeout=60)
    
    return {
        "success": response.success,
        "task_tokens": response.tokens_used,
        "avm_overhead": avm_overhead,
        "total_tokens": response.tokens_used + avm_overhead,
        "output_preview": response.output[:200] if response.output else "",
    }


def main():
    print("="*70)
    print("SMART AVM TEST - Agent decides when to use memory")
    print("="*70)
    
    # Setup
    setup_domain_knowledge()
    
    results = []
    
    for scenario in SCENARIOS:
        print(f"\n{'='*70}")
        print(f"SCENARIO: {scenario['name']}")
        print(f"Needs AVM: {scenario.get('needs_avm', False)}")
        print(f"{'='*70}")
        
        # Baseline (no AVM)
        print("\n[BASELINE]")
        baseline = run_with_smart_avm(scenario, use_avm=False)
        print(f"  Tokens: {baseline['task_tokens']}")
        
        # With AVM (smart - only queries if needed)
        print("\n[SMART AVM]")
        avm = run_with_smart_avm(scenario, use_avm=True)
        print(f"  Task tokens: {avm['task_tokens']}")
        print(f"  AVM overhead: {avm['avm_overhead']}")
        print(f"  Total: {avm['total_tokens']}")
        
        # Calculate overhead %
        if baseline['task_tokens'] > 0:
            overhead_pct = (avm['total_tokens'] - baseline['task_tokens']) / baseline['task_tokens'] * 100
        else:
            overhead_pct = 0
        
        results.append({
            "id": scenario["id"],
            "name": scenario["name"],
            "needs_avm": scenario.get("needs_avm", False),
            "baseline_tokens": baseline["task_tokens"],
            "avm_tokens": avm["task_tokens"],
            "avm_overhead": avm["avm_overhead"],
            "total_avm": avm["total_tokens"],
            "overhead_pct": overhead_pct,
        })
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"{'Scenario':<35} {'Baseline':>10} {'AVM Total':>10} {'Overhead':>10}")
    print("-"*70)
    
    simple_overhead = []
    domain_overhead = []
    
    for r in results:
        print(f"{r['name'][:33]:<35} {r['baseline_tokens']:>10} {r['total_avm']:>10} {r['overhead_pct']:>+9.1f}%")
        if r['needs_avm']:
            domain_overhead.append(r['overhead_pct'])
        else:
            simple_overhead.append(r['overhead_pct'])
    
    print("-"*70)
    if simple_overhead:
        print(f"{'Simple tasks avg overhead:':<35} {sum(simple_overhead)/len(simple_overhead):>+30.1f}%")
    if domain_overhead:
        print(f"{'Domain tasks avg overhead:':<35} {sum(domain_overhead)/len(domain_overhead):>+30.1f}%")
    
    # Save
    outfile = Path(__file__).parent / "results" / "smart_avm.json"
    with open(outfile, 'w') as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": results,
        }, f, indent=2)
    
    print(f"\nSaved to {outfile}")


if __name__ == "__main__":
    main()
