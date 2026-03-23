#!/usr/bin/env python3
"""
Domain-Specific Knowledge Test

Tests AVM value with knowledge that's NOT in training data:
- Project-specific API quirks
- Internal conventions
- Custom workarounds

Phase 1: Expert discovers and documents a project-specific issue
Phase 2: New developer faces the same issue
"""

import json
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone

from runner import BenchmarkRunner
from agent_executor import run_codex, count_tokens
from avm_integration import avm_recall, avm_remember


# Project-specific knowledge (not in any training data)
PROJECT_QUIRK = """
Our internal API has a bug: when calling `analytics.track_event()` with 
more than 5 properties, the API silently drops the request without error.

The workaround discovered by the team:
1. Batch properties into groups of 5
2. Use `analytics.track_batch()` for larger payloads
3. Or set `ANALYTICS_LEGACY_MODE=true` env var to use the old endpoint
"""

PROBLEM_SCENARIO = """
Bug report from QA:
"Analytics events with custom properties aren't being recorded.
Events with 3-4 properties work fine, but events with 6+ properties disappear."

Code:
```python
def track_user_action(user_id, action, **properties):
    event_data = {
        "user_id": user_id,
        "action": action,
        "timestamp": time.time(),
        **properties  # Can be 1-10 custom properties
    }
    analytics.track_event(event_data)
```

This code works for simple events but fails silently for complex ones.
What's wrong and how to fix it?
"""


def phase1_store_knowledge():
    """Store project-specific knowledge in AVM."""
    print("\n" + "="*60)
    print("PHASE 1: Storing project-specific knowledge")
    print("="*60)
    
    # Store in SHARED memory so all agents can access
    import subprocess
    content = f"[INTERNAL BUG] Analytics API 5-property limit\n\n{PROJECT_QUIRK}"
    result_proc = subprocess.run(
        ["avm", "write", "/memory/shared/bugs/analytics_quirk.md"],
        input=content,
        capture_output=True, text=True
    )
    
    class FakeResult:
        success = result_proc.returncode == 0
    result = FakeResult()
    
    print(f"Knowledge stored: {result.success}")
    return result.success


def run_test(with_avm: bool, runner: BenchmarkRunner) -> dict:
    """Run the test with or without AVM."""
    mode = "AVM" if with_avm else "BASELINE"
    print(f"\n" + "-"*60)
    print(f"PHASE 2 {mode}: {'With' if with_avm else 'Without'} project knowledge")
    print("-"*60)
    
    run = runner.start_run({
        "id": f"domain-{mode.lower()}",
        "name": f"Domain Knowledge ({mode})",
        "agents": [{"id": "dev", "role": "Debug and fix"}],
        "assertions": ["Identifies the 5-property limit", "Provides correct workaround"],
    })
    
    recalled = ""
    recall_tokens = 0
    
    if with_avm:
        print("Recalling project knowledge...")
        recall_result = avm_recall(
            query="analytics track_event properties limit bug workaround",
            agent_id="new_hire",
            max_tokens=400
        )
        recalled = recall_result.data if recall_result.success else ""
        recall_tokens = recall_result.tokens_used
        print(f"Recall tokens: {recall_tokens}")
        
        runner.log_event("dev", "avm_recall",
            details={"tokens": recall_tokens},
            tokens_used=recall_tokens,
            latency_ms=recall_result.latency_ms
        )
    
    task = f"""Debug this issue:

{PROBLEM_SCENARIO}

{"## Team Knowledge (from shared memory):" + chr(10) + recalled[:800] if recalled else ""}

What's causing the silent failure? How would you fix it?
Hint: Look for API limitations or undocumented behavior.
"""
    
    with tempfile.TemporaryDirectory() as workdir:
        start = time.time()
        response = run_codex(task, workdir=workdir, timeout=60)
        latency = (time.time() - start) * 1000
        
        runner.log_event("dev", "llm_call",
            details={"output_preview": response.output[:200]},
            tokens_used=response.tokens_used,
            latency_ms=latency
        )
        
        print(f"Success: {response.success}")
        print(f"Tokens: {response.tokens_used}")
        print(f"Output preview: {response.output[:400]}...")
        
        # Check if solution identifies the property limit issue
        output_lower = response.output.lower()
        found_limit = any(x in output_lower for x in [
            "5 properties", "property limit", "5-property", 
            "batch", "track_batch", "legacy_mode"
        ])
        
        # Generic answers don't count
        generic = any(x in output_lower for x in [
            "check the logs", "add error handling", "debug", "print"
        ]) and not found_limit
        
        correct = found_limit and not generic
        print(f"Found specific issue: {'✓' if correct else '✗'}")
    
    result = {
        "success": response.success,
        "correct": correct,
        "found_limit": found_limit,
        "tokens": response.tokens_used,
        "avm_overhead": recall_tokens,
        "total": response.tokens_used + recall_tokens,
        "latency_ms": latency,
    }
    
    runner.end_run(result)
    return result


def main():
    print("="*60)
    print("DOMAIN-SPECIFIC KNOWLEDGE TEST")
    print("Testing project-specific knowledge sharing")
    print("="*60)
    
    phase1_store_knowledge()
    
    runner = BenchmarkRunner({"test": "domain_knowledge"})
    
    baseline = run_test(with_avm=False, runner=runner)
    avm = run_test(with_avm=True, runner=runner)
    
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)
    print(f"{'Metric':<25} {'Baseline':>15} {'AVM':>15}")
    print("-"*55)
    print(f"{'Task Tokens':<25} {baseline['tokens']:>15} {avm['tokens']:>15}")
    print(f"{'AVM Overhead':<25} {baseline['avm_overhead']:>15} {avm['avm_overhead']:>15}")
    print(f"{'Total Tokens':<25} {baseline['total']:>15} {avm['total']:>15}")
    print(f"{'Found Specific Issue':<25} {'✓' if baseline['found_limit'] else '✗':>15} {'✓' if avm['found_limit'] else '✗':>15}")
    print(f"{'Correct Solution':<25} {'✓' if baseline['correct'] else '✗':>15} {'✓' if avm['correct'] else '✗':>15}")
    
    if avm['correct'] and not baseline['correct']:
        print("\n🎯 AVM ADVANTAGE: Only AVM mode found the project-specific issue!")
    elif baseline['correct'] and avm['correct']:
        print("\n⚖️ Both found the issue (may need harder test case)")
    elif not baseline['correct'] and not avm['correct']:
        print("\n❌ Neither found the issue (knowledge retrieval may need tuning)")
    
    # Save
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "test": "domain_knowledge",
        "baseline": baseline,
        "avm": avm,
    }
    
    outfile = Path(__file__).parent / "results" / "domain_knowledge.json"
    with open(outfile, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\nSaved to {outfile}")


if __name__ == "__main__":
    main()
