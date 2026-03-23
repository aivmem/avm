#!/usr/bin/env python3
"""
Run all benchmark scenarios in both baseline and AVM modes.
"""

import json
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone

from runner import BenchmarkRunner
from agent_executor import run_codex, count_tokens
from avm_integration import avm_recall, avm_remember


def run_scenario(scenario: dict, with_avm: bool = False) -> dict:
    """Run a single scenario with or without AVM."""
    
    config = {"agent": "codex", "avm_enabled": with_avm}
    runner = BenchmarkRunner(config)
    run = runner.start_run(scenario)
    
    avm_overhead_tokens = 0
    task_tokens = 0
    
    # Get scenario-specific code/context
    buggy_code = scenario.get("provided_code", """
def process(data):
    return data
""")
    
    task_description = scenario.get("description", "Complete the task")
    
    with tempfile.TemporaryDirectory(prefix="bench_") as workdir:
        workdir = Path(workdir)
        (workdir / "code.py").write_text(buggy_code)
        
        previous_outputs = []
        
        for agent in scenario.get("agents", []):
            agent_id = f"bench_{agent['id']}" if with_avm else agent['id']
            role = agent["role"]
            
            runner.log_event(agent_id, "start", details={"role": role})
            
            recalled_context = ""
            if with_avm:
                # AVM recall
                recall_result = avm_recall(
                    query=f"{task_description} {role}",
                    agent_id=agent_id,
                    max_tokens=300
                )
                runner.log_event(agent_id, "avm_recall",
                    details={"success": recall_result.success, "tokens": recall_result.tokens_used},
                    tokens_used=recall_result.tokens_used,
                    latency_ms=recall_result.latency_ms
                )
                avm_overhead_tokens += recall_result.tokens_used
                recalled_context = recall_result.data if recall_result.success else ""
            
            # Build context from previous agents
            prev_context = ""
            if previous_outputs:
                prev_context = "\n\n".join([f"## {name}'s output:\n{out}" 
                                           for name, out in previous_outputs])
            
            # Build task
            task = f"""You are '{agent_id}' with role: {role}

## Task: {task_description}

{f"## Shared Memory (AVM):{chr(10)}{recalled_context}" if recalled_context else ""}

{f"## Previous Agents:{chr(10)}{prev_context}" if prev_context else ""}

## Code:
```python
{buggy_code}
```

## Assertions to satisfy:
{chr(10).join(f'- {a}' for a in scenario.get('assertions', [])[:3])}

Complete your role. Be concise.
"""
            
            # Run agent
            response = run_codex(task, workdir=str(workdir), timeout=90)
            
            runner.log_event(agent_id, "llm_call",
                details={"output_preview": response.output[:150], "success": response.success},
                tokens_used=response.tokens_used,
                latency_ms=response.latency_ms
            )
            
            task_tokens += response.tokens_used
            
            if with_avm and response.success and response.output:
                # AVM remember
                remember_result = avm_remember(
                    content=f"[{agent_id}] {response.output[:400]}",
                    agent_id=agent_id,
                    importance=0.6
                )
                runner.log_event(agent_id, "avm_remember",
                    details={"success": remember_result.success},
                    tokens_used=remember_result.tokens_used,
                    latency_ms=remember_result.latency_ms
                )
                avm_overhead_tokens += remember_result.tokens_used
            
            previous_outputs.append((agent_id, response.output[:200]))
    
    result = {
        "success": True,
        "mode": "avm" if with_avm else "baseline",
        "token_breakdown": {
            "avm_overhead": avm_overhead_tokens,
            "task_tokens": task_tokens,
            "total": avm_overhead_tokens + task_tokens,
        }
    }
    
    run = runner.end_run(result)
    return run.to_dict()


def main():
    runner = BenchmarkRunner({})
    scenarios = runner.list_scenarios()
    
    # Filter to run a subset for now
    selected = [
        ("collaborative_coding", "cc-001"),  # REST API
        ("collaborative_coding", "cc-005"),  # Bug Fix
        ("knowledge_retrieval", "kr-001"),   # Project Handoff
        ("knowledge_retrieval", "kr-004"),   # Error Pattern
    ]
    
    results = []
    
    for category, scenario_id in selected:
        scenario = runner.load_scenario(category, scenario_id)
        print(f"\n{'='*60}")
        print(f"SCENARIO: {scenario['name']} ({scenario_id})")
        print(f"{'='*60}")
        
        # Run baseline
        print(f"\n[BASELINE] Running...")
        baseline = run_scenario(scenario, with_avm=False)
        print(f"[BASELINE] Tokens: {baseline['result']['token_breakdown']['total']}")
        
        # Run with AVM
        print(f"\n[AVM] Running...")
        avm = run_scenario(scenario, with_avm=True)
        print(f"[AVM] Tokens: {avm['result']['token_breakdown']['total']} "
              f"(overhead: {avm['result']['token_breakdown']['avm_overhead']})")
        
        results.append({
            "scenario_id": scenario_id,
            "name": scenario["name"],
            "baseline": baseline["result"]["token_breakdown"],
            "avm": avm["result"]["token_breakdown"],
        })
    
    # Print summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"{'Scenario':<30} {'Baseline':>10} {'AVM':>10} {'Overhead':>10} {'Diff':>10}")
    print("-" * 70)
    
    for r in results:
        diff = r['avm']['total'] - r['baseline']['total']
        diff_pct = (diff / r['baseline']['total'] * 100) if r['baseline']['total'] > 0 else 0
        print(f"{r['name'][:28]:<30} {r['baseline']['total']:>10} {r['avm']['total']:>10} "
              f"{r['avm']['avm_overhead']:>10} {diff_pct:>+9.1f}%")
    
    # Save summary
    summary_file = Path(__file__).parent / "results" / "summary.json"
    with open(summary_file, 'w') as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": results,
        }, f, indent=2)
    
    print(f"\nSummary saved to {summary_file}")


if __name__ == "__main__":
    main()
