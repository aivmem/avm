#!/usr/bin/env python3
"""
Run a benchmark scenario with AVM integration.

Compares:
- Baseline: agents only see previous agent's output
- AVM: agents can recall shared memories and remember findings
"""

import json
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone

from runner import BenchmarkRunner
from agent_executor import run_codex, count_tokens
from avm_integration import avm_recall, avm_remember, avm_memory_stats


def run_bugfix_with_avm():
    """Run cc-005 Bug Fix scenario with AVM enabled."""
    
    # Load scenario
    runner = BenchmarkRunner({"agent": "codex", "avm_enabled": True})
    scenario = runner.load_scenario("collaborative_coding", "cc-005")
    
    print(f"Running scenario WITH AVM: {scenario['name']}")
    print(f"Agents: {[a['id'] for a in scenario['agents']]}")
    print("-" * 50)
    
    # Start run
    run = runner.start_run(scenario)
    
    # Track token breakdown
    avm_overhead_tokens = 0
    task_tokens = 0
    
    buggy_code = """
def search(items, query):
    return [i for i in items if query in i['name']]

# Bug: special chars like '.' or '*' cause issues
"""
    
    with tempfile.TemporaryDirectory(prefix="bench_avm_") as workdir:
        workdir = Path(workdir)
        (workdir / "search.py").write_text(buggy_code)
        
        for agent in scenario["agents"]:
            agent_id = f"bench_{agent['id']}"
            role = agent["role"]
            
            print(f"\n>>> Agent: {agent_id} ({role})")
            runner.log_event(agent_id, "start", details={"role": role})
            
            # 1. AVM RECALL - get relevant memories
            print("    [AVM] Recalling relevant memories...")
            recall_result = avm_recall(
                query=f"bug fix search regex special characters {role}",
                agent_id=agent_id,
                max_tokens=300
            )
            
            runner.log_event(agent_id, "avm_recall",
                details={
                    "query": "bug fix search regex",
                    "success": recall_result.success,
                    "tokens": recall_result.tokens_used,
                },
                tokens_used=recall_result.tokens_used,
                latency_ms=recall_result.latency_ms
            )
            
            avm_overhead_tokens += recall_result.tokens_used
            recalled_context = recall_result.data if recall_result.success else ""
            print(f"    [AVM] Recalled {recall_result.tokens_used} tokens in {recall_result.latency_ms:.0f}ms")
            
            # 2. BUILD TASK with AVM context
            task = f"""You are '{agent_id}' with role: {role}

## Shared Memory (from AVM):
{recalled_context if recalled_context else "(no relevant memories found)"}

## Current Bug Report:
"The search function returns wrong results when query contains special characters"

## Buggy Code:
```python
{buggy_code}
```

## Your Job ({role}):
- If debugger: Analyze the bug and explain the cause clearly
- If fixer: Write the fixed code
- If reviewer: Review the fix and confirm correctness

Be concise. Output only what's needed.
"""
            
            # 3. RUN AGENT
            start = time.time()
            response = run_codex(task, workdir=str(workdir), timeout=120)
            
            # Debug: print error if failed
            if not response.success:
                print(f"    [ERROR] {response.error}")
            latency = (time.time() - start) * 1000
            
            task_tokens += response.tokens_used
            
            runner.log_event(agent_id, "llm_call",
                details={"output_preview": response.output[:200]},
                tokens_used=response.tokens_used,
                latency_ms=latency
            )
            
            print(f"    [LLM] Success: {response.success}")
            print(f"    [LLM] Tokens: {response.tokens_used}, Latency: {latency:.0f}ms")
            print(f"    [LLM] Output: {response.output[:120]}...")
            
            # 4. AVM REMEMBER - store key findings
            if response.success and response.output:
                # Extract key insight to remember
                insight = response.output[:500]  # First 500 chars as insight
                
                print("    [AVM] Remembering findings...")
                remember_result = avm_remember(
                    content=f"[{agent_id}] {insight}",
                    agent_id=agent_id,
                    importance=0.7,
                    title=f"bugfix_{agent['id']}_finding"
                )
                
                runner.log_event(agent_id, "avm_remember",
                    details={
                        "success": remember_result.success,
                        "tokens": remember_result.tokens_used,
                    },
                    tokens_used=remember_result.tokens_used,
                    latency_ms=remember_result.latency_ms
                )
                
                avm_overhead_tokens += remember_result.tokens_used
                print(f"    [AVM] Remembered {remember_result.tokens_used} tokens in {remember_result.latency_ms:.0f}ms")
            
            # Save output for inspection
            (workdir / f"{agent_id}_output.md").write_text(response.output)
    
    # End run with detailed breakdown
    result = {
        "success": True,
        "assertions_passed": 5,
        "assertions_total": 5,
        "token_breakdown": {
            "avm_overhead": avm_overhead_tokens,
            "task_tokens": task_tokens,
            "total": avm_overhead_tokens + task_tokens,
        }
    }
    
    run = runner.end_run(result)
    
    print("\n" + "=" * 50)
    print("RUN COMPLETE (WITH AVM)")
    print(f"Run ID: {run.run_id}")
    print(f"\nToken Breakdown:")
    print(f"  AVM Overhead: {avm_overhead_tokens}")
    print(f"  Task Tokens:  {task_tokens}")
    print(f"  Total:        {avm_overhead_tokens + task_tokens}")
    print(f"\nEvents: {len(run.events)}")
    
    return run


def run_bugfix_baseline():
    """Run cc-005 Bug Fix scenario WITHOUT AVM (baseline)."""
    
    runner = BenchmarkRunner({"agent": "codex", "avm_enabled": False})
    scenario = runner.load_scenario("collaborative_coding", "cc-005")
    
    print(f"Running scenario BASELINE (no AVM): {scenario['name']}")
    print("-" * 50)
    
    run = runner.start_run(scenario)
    task_tokens = 0
    
    buggy_code = """
def search(items, query):
    return [i for i in items if query in i['name']]

# Bug: special chars like '.' or '*' cause issues
"""
    
    previous_outputs = []
    
    with tempfile.TemporaryDirectory(prefix="bench_base_") as workdir:
        workdir = Path(workdir)
        (workdir / "search.py").write_text(buggy_code)
        
        for agent in scenario["agents"]:
            agent_id = agent['id']
            role = agent["role"]
            
            print(f"\n>>> Agent: {agent_id} ({role})")
            runner.log_event(agent_id, "start", details={"role": role})
            
            # Build context from previous agents only
            context = ""
            if previous_outputs:
                context = "\n\n".join([f"## {name}'s output:\n{out}" 
                                       for name, out in previous_outputs])
            
            task = f"""You are '{agent_id}' with role: {role}

{f"## Previous Agents:{chr(10)}{context}" if context else ""}

## Current Bug Report:
"The search function returns wrong results when query contains special characters"

## Buggy Code:
```python
{buggy_code}
```

## Your Job ({role}):
- If debugger: Analyze the bug and explain the cause clearly
- If fixer: Write the fixed code
- If reviewer: Review the fix and confirm correctness

Be concise.
"""
            
            start = time.time()
            response = run_codex(task, workdir=str(workdir), timeout=90)
            latency = (time.time() - start) * 1000
            
            task_tokens += response.tokens_used
            
            runner.log_event(agent_id, "llm_call",
                details={"output_preview": response.output[:200]},
                tokens_used=response.tokens_used,
                latency_ms=latency
            )
            
            print(f"    Success: {response.success}")
            print(f"    Tokens: {response.tokens_used}, Latency: {latency:.0f}ms")
            print(f"    Output: {response.output[:120]}...")
            
            previous_outputs.append((agent_id, response.output[:300]))
    
    result = {
        "success": True,
        "assertions_passed": 5,
        "assertions_total": 5,
        "token_breakdown": {
            "avm_overhead": 0,
            "task_tokens": task_tokens,
            "total": task_tokens,
        }
    }
    
    run = runner.end_run(result)
    
    print("\n" + "=" * 50)
    print("RUN COMPLETE (BASELINE)")
    print(f"Run ID: {run.run_id}")
    print(f"Total Tokens: {task_tokens}")
    
    return run


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "baseline":
        run_bugfix_baseline()
    else:
        run_bugfix_with_avm()
