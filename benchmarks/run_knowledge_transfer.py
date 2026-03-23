#!/usr/bin/env python3
"""
Knowledge Transfer Test - The real AVM value proposition.

Phase 1: Expert agent solves a tricky problem, stores solution in AVM
Phase 2: New agent faces similar problem
  - Baseline: No access to expert's knowledge, must figure it out
  - AVM: Can recall expert's solution

This tests cross-session knowledge transfer.
"""

import json
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone

from runner import BenchmarkRunner
from agent_executor import run_codex, count_tokens
from avm_integration import avm_recall, avm_remember, avm_memory_stats


# The tricky problem: timezone-aware datetime comparison
TRICKY_PROBLEM = """
Bug report: "Events scheduled for 'now' are being marked as past events"

Code:
```python
from datetime import datetime

def is_past_event(event_time: datetime) -> bool:
    return event_time < datetime.utcnow()

# Usage
event = get_event_from_db()  # Returns timezone-aware datetime (UTC)
if is_past_event(event.scheduled_at):
    mark_as_past(event)
```

Error: TypeError: can't compare offset-naive and offset-aware datetimes
"""

EXPERT_SOLUTION = """
Root cause: datetime.utcnow() returns timezone-naive datetime, but DB returns timezone-aware.

Fix:
```python
from datetime import datetime, timezone

def is_past_event(event_time: datetime) -> bool:
    return event_time < datetime.now(timezone.utc)
```

Key insight: Always use datetime.now(timezone.utc) instead of datetime.utcnow() 
when comparing with timezone-aware datetimes. utcnow() is deprecated in Python 3.12+.
"""


def phase1_expert_solves():
    """Expert agent solves the problem and stores in AVM."""
    print("\n" + "="*60)
    print("PHASE 1: Expert solves the tricky datetime problem")
    print("="*60)
    
    # Store expert knowledge in AVM
    result = avm_remember(
        content=f"[SOLVED] Datetime comparison bug\n\nProblem: {TRICKY_PROBLEM}\n\nSolution: {EXPERT_SOLUTION}",
        agent_id="expert_dev",
        importance=0.9,
        title="datetime_timezone_fix"
    )
    
    print(f"Expert knowledge stored: {result.success}")
    print(f"Tokens stored: ~{len(EXPERT_SOLUTION.split())}")
    return result.success


def phase2_baseline(runner: BenchmarkRunner) -> dict:
    """New agent tries to solve WITHOUT AVM knowledge."""
    print("\n" + "-"*60)
    print("PHASE 2 BASELINE: New agent has NO access to expert knowledge")
    print("-"*60)
    
    run = runner.start_run({
        "id": "kt-baseline",
        "name": "Knowledge Transfer (Baseline)",
        "agents": [{"id": "new_dev", "role": "Fix the bug"}],
        "assertions": ["Bug is fixed correctly"],
    })
    
    task = f"""You are a new developer. Fix this bug:

{TRICKY_PROBLEM}

Provide the fix and explain why it works.
"""
    
    with tempfile.TemporaryDirectory() as workdir:
        start = time.time()
        response = run_codex(task, workdir=workdir, timeout=60)
        latency = (time.time() - start) * 1000
        
        runner.log_event("new_dev", "llm_call",
            details={"output_preview": response.output[:200]},
            tokens_used=response.tokens_used,
            latency_ms=latency
        )
        
        print(f"Success: {response.success}")
        print(f"Tokens: {response.tokens_used}")
        print(f"Latency: {latency:.0f}ms")
        print(f"Output: {response.output[:300]}...")
        
        # Check if solution mentions timezone.utc
        correct = "timezone.utc" in response.output or "datetime.now(timezone.utc)" in response.output
        print(f"Correct solution: {'✓' if correct else '✗'}")
    
    result = {
        "success": response.success,
        "correct": correct,
        "tokens": response.tokens_used,
        "latency_ms": latency,
        "avm_overhead": 0,
    }
    
    runner.end_run(result)
    return result


def phase2_with_avm(runner: BenchmarkRunner) -> dict:
    """New agent solves WITH AVM knowledge recall."""
    print("\n" + "-"*60)
    print("PHASE 2 AVM: New agent can recall expert's solution")
    print("-"*60)
    
    run = runner.start_run({
        "id": "kt-avm",
        "name": "Knowledge Transfer (AVM)",
        "agents": [{"id": "new_dev_avm", "role": "Fix the bug"}],
        "assertions": ["Bug is fixed correctly"],
    })
    
    # Recall expert knowledge
    print("Recalling expert knowledge...")
    recall_result = avm_recall(
        query="datetime timezone comparison bug fix utcnow",
        agent_id="new_dev_avm",
        max_tokens=500
    )
    
    runner.log_event("new_dev_avm", "avm_recall",
        details={"success": recall_result.success, "tokens": recall_result.tokens_used},
        tokens_used=recall_result.tokens_used,
        latency_ms=recall_result.latency_ms
    )
    
    print(f"Recall success: {recall_result.success}")
    print(f"Recall tokens: {recall_result.tokens_used}")
    
    recalled_knowledge = recall_result.data if recall_result.success else ""
    
    task = f"""You are a new developer. Fix this bug:

{TRICKY_PROBLEM}

## Knowledge from team (retrieved from shared memory):
{recalled_knowledge[:1000] if recalled_knowledge else "(no relevant knowledge found)"}

Provide the fix and explain why it works.
"""
    
    with tempfile.TemporaryDirectory() as workdir:
        start = time.time()
        response = run_codex(task, workdir=workdir, timeout=60)
        latency = (time.time() - start) * 1000
        
        runner.log_event("new_dev_avm", "llm_call",
            details={"output_preview": response.output[:200]},
            tokens_used=response.tokens_used,
            latency_ms=latency
        )
        
        print(f"Success: {response.success}")
        print(f"Tokens: {response.tokens_used}")
        print(f"Latency: {latency:.0f}ms")
        print(f"Output: {response.output[:300]}...")
        
        correct = "timezone.utc" in response.output or "datetime.now(timezone.utc)" in response.output
        print(f"Correct solution: {'✓' if correct else '✗'}")
    
    result = {
        "success": response.success,
        "correct": correct,
        "tokens": response.tokens_used,
        "latency_ms": latency,
        "avm_overhead": recall_result.tokens_used,
        "total_tokens": response.tokens_used + recall_result.tokens_used,
    }
    
    runner.end_run(result)
    return result


def main():
    print("="*60)
    print("KNOWLEDGE TRANSFER TEST")
    print("Testing cross-session knowledge sharing via AVM")
    print("="*60)
    
    # Phase 1: Store expert knowledge
    phase1_expert_solves()
    
    # Phase 2: Compare baseline vs AVM
    runner = BenchmarkRunner({"test": "knowledge_transfer"})
    
    baseline = phase2_baseline(runner)
    avm = phase2_with_avm(runner)
    
    # Summary
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)
    print(f"{'Metric':<25} {'Baseline':>15} {'AVM':>15}")
    print("-"*55)
    print(f"{'Task Tokens':<25} {baseline['tokens']:>15} {avm['tokens']:>15}")
    print(f"{'AVM Overhead':<25} {baseline['avm_overhead']:>15} {avm['avm_overhead']:>15}")
    print(f"{'Total Tokens':<25} {baseline['tokens']:>15} {avm['total_tokens']:>15}")
    print(f"{'Latency (ms)':<25} {baseline['latency_ms']:>15.0f} {avm['latency_ms']:>15.0f}")
    print(f"{'Correct Solution':<25} {'✓' if baseline['correct'] else '✗':>15} {'✓' if avm['correct'] else '✗':>15}")
    
    # Save
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "test": "knowledge_transfer",
        "baseline": baseline,
        "avm": avm,
    }
    
    outfile = Path(__file__).parent / "results" / "knowledge_transfer.json"
    with open(outfile, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\nSaved to {outfile}")


if __name__ == "__main__":
    main()
