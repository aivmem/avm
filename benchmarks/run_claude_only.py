#!/usr/bin/env python3
"""
Run ALL benchmark scenarios using Claude Code only.
Uses claude-sonnet-4-6 for all agents.
"""

import json
import subprocess
import time
import tempfile
import random
from pathlib import Path
from datetime import datetime, timezone

try:
    import tiktoken
    _encoder = tiktoken.encoding_for_model("gpt-4")
    def count_tokens(text: str) -> int:
        return len(_encoder.encode(text))
except ImportError:
    def count_tokens(text: str) -> int:
        return int(len(text.split()) * 1.3)


def run_claude(task: str, context: str = "", timeout: int = 90) -> dict:
    """Run Claude Code with task."""
    full_prompt = f"{context}\n\nTask: {task}" if context else task
    
    cmd = [
        "claude",
        "--print",
        "--permission-mode", "bypassPermissions",
        "--model", "claude-opus-4-5",
        full_prompt
    ]
    
    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        latency = (time.time() - start) * 1000
        output = result.stdout
        
        return {
            "success": result.returncode == 0 and len(output) > 10,
            "output": output[:500],
            "tokens": count_tokens(output),
            "latency_ms": latency,
            "error": result.stderr[:200] if result.returncode != 0 else ""
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "tokens": 0, "latency_ms": timeout*1000, "error": "Timeout"}
    except Exception as e:
        return {"success": False, "output": "", "tokens": 0, "latency_ms": 0, "error": str(e)}


def run_avm(args: list, input_text: str = None, timeout: int = 30) -> tuple:
    """Run AVM command."""
    try:
        result = subprocess.run(
            ["avm"] + args,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout
    except:
        return False, ""


def run_scenario(scenario: dict, use_avm: bool, shared_context: dict = None) -> dict:
    """Run a single scenario with multiple agents."""
    results = {
        "scenario_id": scenario["id"],
        "scenario_name": scenario["name"],
        "use_avm": use_avm,
        "agents": [],
        "total_tokens": 0,
        "avm_overhead": 0,
        "success": True,
    }
    
    # Build context from previous agents
    accumulated_context = ""
    if "provided_code" in scenario:
        accumulated_context = f"Code:\n```\n{scenario['provided_code']}\n```\n"
    if "initial_context" in scenario:
        accumulated_context += f"\nContext: {scenario['initial_context']}\n"
    
    for agent in scenario.get("agents", []):
        agent_id = agent["id"]
        role = agent["role"]
        
        # If using AVM, recall relevant context
        avm_tokens = 0
        if use_avm:
            success, recalled = run_avm([
                "recall", "-a", agent_id, "-t", "300",
                f"{scenario['name']} {role}"
            ])
            if success and recalled.strip():
                accumulated_context += f"\n[AVM Recall]: {recalled[:500]}\n"
                avm_tokens = count_tokens(recalled)
        
        # Build agent task
        task = f"You are {agent_id} ({role}). {accumulated_context}\n\nDo your part of this task."
        
        # Execute
        response = run_claude(task)
        
        results["agents"].append({
            "id": agent_id,
            "role": role,
            "success": response["success"],
            "tokens": response["tokens"],
            "avm_tokens": avm_tokens,
            "output_preview": response["output"][:200]
        })
        
        results["total_tokens"] += response["tokens"]
        results["avm_overhead"] += avm_tokens
        
        if not response["success"]:
            results["success"] = False
        
        # Add output to context for next agent
        accumulated_context += f"\n[{agent_id}]: {response['output'][:300]}\n"
        
        # If using AVM, store agent output
        if use_avm and response["success"]:
            run_avm([
                "remember", "-a", agent_id, 
                "-c", f"{scenario['name']}: {response['output'][:500]}"
            ])
    
    return results


def load_scenarios() -> list:
    """Load all scenario files."""
    scenarios_dir = Path(__file__).parent / "scenarios"
    all_scenarios = []
    
    for json_file in scenarios_dir.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
                scenarios = data.get("scenarios", [])
                for s in scenarios:
                    s["_source"] = json_file.name
                all_scenarios.extend(scenarios)
        except:
            pass
    
    return all_scenarios


def main():
    print("="*70)
    print("CLAUDE-ONLY BENCHMARK SUITE")
    print("Running all 48 scenarios with Claude Sonnet")
    print("="*70)
    
    scenarios = load_scenarios()
    print(f"\nLoaded {len(scenarios)} scenarios")
    
    # Run all scenarios
    print(f"Running ALL {len(scenarios)} scenarios")
    
    all_results = []
    
    for i, scenario in enumerate(scenarios):
        print(f"\n[{i+1}/{len(scenarios)}] {scenario['id']}: {scenario['name']}")
        
        # Run baseline (no AVM)
        print("  [BASELINE] Running without AVM...")
        baseline = run_scenario(scenario, use_avm=False)
        
        # Run with AVM
        print("  [AVM] Running with AVM...")
        with_avm = run_scenario(scenario, use_avm=True)
        
        all_results.append({
            "scenario": scenario["id"],
            "name": scenario["name"],
            "source": scenario.get("_source", "unknown"),
            "baseline": baseline,
            "avm": with_avm,
        })
        
        # Print summary
        b_ok = sum(1 for a in baseline["agents"] if a["success"])
        a_ok = sum(1 for a in with_avm["agents"] if a["success"])
        print(f"  Baseline: {b_ok}/{len(baseline['agents'])} agents, {baseline['total_tokens']} tokens")
        print(f"  AVM: {a_ok}/{len(with_avm['agents'])} agents, {with_avm['total_tokens']} tokens (+{with_avm['avm_overhead']} AVM overhead)")
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    baseline_tokens = sum(r["baseline"]["total_tokens"] for r in all_results)
    avm_tokens = sum(r["avm"]["total_tokens"] for r in all_results)
    avm_overhead = sum(r["avm"]["avm_overhead"] for r in all_results)
    
    baseline_success = sum(1 for r in all_results if r["baseline"]["success"])
    avm_success = sum(1 for r in all_results if r["avm"]["success"])
    
    print(f"Scenarios run: {len(all_results)}")
    print(f"Baseline success: {baseline_success}/{len(all_results)}")
    print(f"AVM success: {avm_success}/{len(all_results)}")
    print(f"Baseline tokens: {baseline_tokens}")
    print(f"AVM tokens: {avm_tokens} (overhead: {avm_overhead})")
    
    # Save results
    outfile = Path(__file__).parent / "results" / "claude_only_benchmark.json"
    with open(outfile, 'w') as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scenarios_run": len(all_results),
            "summary": {
                "baseline_success": baseline_success,
                "avm_success": avm_success,
                "baseline_tokens": baseline_tokens,
                "avm_tokens": avm_tokens,
                "avm_overhead": avm_overhead,
            },
            "results": all_results,
        }, f, indent=2)
    
    print(f"\nResults saved to: {outfile}")


if __name__ == "__main__":
    random.seed(42)
    main()
