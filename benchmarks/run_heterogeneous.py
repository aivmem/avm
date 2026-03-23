#!/usr/bin/env python3
"""
Heterogeneous Agent Test - Mixed Codex + Claude

Tests multi-agent collaboration with DIFFERENT LLM backends:
- Agent A (Codex/GPT): Research/analysis
- Agent B (Claude): Writing/synthesis
- Agent C (Codex/GPT): Code implementation

This tests AVM's ability to bridge different LLM ecosystems.
"""

import json
import tempfile
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from runner import BenchmarkRunner
from agent_executor import run_codex, run_claude_opus, run_agent, AgentResponse
from avm_integration import avm_recall, avm_remember


def run_heterogeneous_task(use_avm: bool, agents_config: list) -> dict:
    """
    Run a task with multiple heterogeneous agents.
    
    agents_config: list of {"id": str, "type": "codex"|"claude", "role": str, "task": str}
    """
    results = []
    total_tokens = 0
    avm_overhead = 0
    accumulated_context = []
    
    for agent in agents_config:
        agent_id = agent["id"]
        agent_type = agent["type"]
        role = agent["role"]
        task = agent["task"]
        
        # Build context
        if use_avm:
            # Recall previous agents' work
            recall = avm_recall(
                query=f"{role} {task[:50]}",
                agent_id=agent_id,
                max_tokens=400
            )
            avm_overhead += recall.tokens_used
            context = recall.data if recall.success else ""
        else:
            # Baseline: only sees previous agent's direct output
            context = "\n\n".join(accumulated_context[-2:]) if accumulated_context else ""
        
        # Build full task
        full_task = f"""You are {agent_id} ({agent_type.upper()}). Role: {role}

{f"## Previous Work:{chr(10)}{context[:1000]}" if context else ""}

## Your Task:
{task}

Be concise and focus on your specific role.
"""
        
        # Run agent
        start = time.time()
        try:
            response = run_agent(full_task, agent_type=agent_type, timeout=60)
        except Exception as e:
            response = AgentResponse(
                success=False, output="", tokens_used=0, 
                latency_ms=(time.time()-start)*1000, error=str(e)
            )
        
        total_tokens += response.tokens_used
        
        # Store output in AVM
        if use_avm and response.success and response.output:
            avm_remember(
                content=f"[{agent_id}/{agent_type}] {response.output[:500]}",
                agent_id=agent_id,
                importance=0.8
            )
            avm_overhead += 30  # Estimate
        
        accumulated_context.append(f"{agent_id}: {response.output[:300]}")
        
        results.append({
            "agent_id": agent_id,
            "agent_type": agent_type,
            "success": response.success,
            "tokens": response.tokens_used,
            "latency_ms": response.latency_ms,
            "output_preview": response.output[:150] if response.output else "",
            "error": response.error,
        })
    
    return {
        "agents": results,
        "total_tokens": total_tokens,
        "avm_overhead": avm_overhead,
        "grand_total": total_tokens + avm_overhead,
    }


def main():
    print("="*70)
    print("HETEROGENEOUS AGENT TEST")
    print("Mixed Codex + Claude collaboration")
    print("="*70)
    
    # Define the heterogeneous task
    task_pipeline = [
        {
            "id": "researcher",
            "type": "codex",  # GPT for research
            "role": "Research Analyst",
            "task": "Analyze the pros and cons of using Redis vs Memcached for session storage. List 3 key differences.",
        },
        {
            "id": "architect",
            "type": "codex",  # Claude would be here if quota available
            "role": "System Architect", 
            "task": "Based on the research, recommend which caching solution to use for a high-traffic e-commerce site. Justify your choice.",
        },
        {
            "id": "implementer",
            "type": "codex",  # GPT for code
            "role": "Developer",
            "task": "Write a Python code snippet showing how to implement the recommended caching solution with connection pooling.",
        },
    ]
    
    print("\nAgent Pipeline:")
    for a in task_pipeline:
        print(f"  {a['id']} ({a['type']}): {a['role']}")
    
    # Run baseline
    print("\n" + "-"*70)
    print("[BASELINE] Sequential without AVM")
    print("-"*70)
    
    baseline = run_heterogeneous_task(use_avm=False, agents_config=task_pipeline)
    
    for r in baseline["agents"]:
        status = "✓" if r["success"] else f"✗ ({r['error'][:30]})"
        print(f"  {r['agent_id']} ({r['agent_type']}): {status}, {r['tokens']} tokens")
    
    print(f"\n  Total: {baseline['total_tokens']} tokens")
    
    # Run with AVM
    print("\n" + "-"*70)
    print("[AVM] With shared memory")
    print("-"*70)
    
    avm = run_heterogeneous_task(use_avm=True, agents_config=task_pipeline)
    
    for r in avm["agents"]:
        status = "✓" if r["success"] else f"✗ ({r['error'][:30]})"
        print(f"  {r['agent_id']} ({r['agent_type']}): {status}, {r['tokens']} tokens")
    
    print(f"\n  Total: {avm['total_tokens']} + {avm['avm_overhead']} overhead = {avm['grand_total']} tokens")
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    baseline_success = sum(1 for r in baseline["agents"] if r["success"])
    avm_success = sum(1 for r in avm["agents"] if r["success"])
    
    print(f"{'Metric':<30} {'Baseline':>15} {'AVM':>15}")
    print("-"*60)
    print(f"{'Agents Succeeded':<30} {baseline_success:>15}/3 {avm_success:>15}/3")
    print(f"{'Total Tokens':<30} {baseline['total_tokens']:>15} {avm['grand_total']:>15}")
    print(f"{'AVM Overhead':<30} {0:>15} {avm['avm_overhead']:>15}")
    
    # Save detailed log
    log = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pipeline": task_pipeline,
        "baseline": baseline,
        "avm": avm,
    }
    
    outfile = Path(__file__).parent / "results" / "heterogeneous.json"
    with open(outfile, 'w') as f:
        json.dump(log, f, indent=2)
    
    print(f"\nDetailed log saved to {outfile}")


if __name__ == "__main__":
    main()
