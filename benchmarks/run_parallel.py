#!/usr/bin/env python3
"""
Parallel benchmark runner - runs scenarios concurrently for speed.
"""

import json
import subprocess
import time
import random
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import tiktoken
    _encoder = tiktoken.encoding_for_model("gpt-4")
    def count_tokens(text: str) -> int:
        return len(_encoder.encode(text))
except ImportError:
    def count_tokens(text: str) -> int:
        return int(len(text.split()) * 1.3)


def run_claude(task: str, timeout: int = 60) -> dict:
    cmd = [
        "claude", "--print", "--permission-mode", "bypassPermissions",
        "--model", "claude-opus-4-5", task
    ]
    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout
        return {
            "success": result.returncode == 0 and len(output) > 10,
            "output": output[:500],
            "tokens": count_tokens(output),
            "latency_ms": (time.time() - start) * 1000,
        }
    except:
        return {"success": False, "output": "", "tokens": 0, "latency_ms": timeout*1000}


def run_avm(args: list, input_text: str = None) -> tuple:
    try:
        result = subprocess.run(
            ["avm"] + args, input=input_text,
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout.replace('\x00', '').encode('utf-8', errors='ignore').decode('utf-8')
        return result.returncode == 0, output
    except:
        return False, ""


def run_scenario(scenario: dict, use_avm: bool) -> dict:
    """Run a single scenario."""
    results = {
        "scenario_id": scenario["id"],
        "use_avm": use_avm,
        "agents": [],
        "total_tokens": 0,
        "avm_overhead": 0,
        "success": True,
    }
    
    accumulated_context = ""
    if "provided_code" in scenario:
        accumulated_context = f"Code:\n```\n{scenario['provided_code']}\n```\n"
    if "initial_context" in scenario:
        accumulated_context += f"\nContext: {scenario['initial_context']}\n"
    
    for agent in scenario.get("agents", []):
        agent_id = agent["id"]
        role = agent["role"]
        
        avm_tokens = 0
        if use_avm:
            success, recalled = run_avm([
                "recall", "-a", agent_id, "-t", "200",
                f"{scenario['name']} {role}"
            ])
            if success and recalled.strip():
                accumulated_context += f"\n[AVM]: {recalled[:300]}\n"
                avm_tokens = count_tokens(recalled)
        
        task = f"You are {agent_id} ({role}). {accumulated_context}\n\nDo your part briefly (max 100 words)."
        response = run_claude(task)
        
        results["agents"].append({
            "id": agent_id,
            "success": response["success"],
            "tokens": response["tokens"],
        })
        
        results["total_tokens"] += response["tokens"]
        results["avm_overhead"] += avm_tokens
        
        if not response["success"]:
            results["success"] = False
        
        accumulated_context += f"\n[{agent_id}]: {response['output'][:200]}\n"
        
        if use_avm and response["success"]:
            run_avm(["remember", "-a", agent_id, "-c", response['output'][:300]])
    
    return results


def run_single(args):
    scenario, mode = args
    return run_scenario(scenario, use_avm=(mode == "avm"))


def load_scenarios() -> list:
    scenarios_dir = Path(__file__).parent / "scenarios"
    all_scenarios = []
    
    for json_file in scenarios_dir.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
                scenarios = data.get("scenarios", [])
                # Filter out scenarios without agents
                scenarios = [s for s in scenarios if s.get("agents")]
                for s in scenarios:
                    s["_source"] = json_file.name
                all_scenarios.extend(scenarios)
        except:
            pass
    
    return all_scenarios


def main():
    print("="*70)
    print("PARALLEL BENCHMARK (Claude Opus)")
    print("="*70)
    
    scenarios = load_scenarios()
    print(f"Loaded {len(scenarios)} scenarios with agents")
    
    # Prepare jobs: each scenario runs twice (baseline + AVM)
    jobs = []
    for s in scenarios:
        jobs.append((s, "baseline"))
        jobs.append((s, "avm"))
    
    print(f"Running {len(jobs)} jobs with 4 parallel workers...")
    
    results_by_scenario = {}
    completed = 0
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(run_single, job): job for job in jobs}
        
        for future in as_completed(futures):
            job = futures[future]
            scenario, mode = job
            sid = scenario["id"]
            
            try:
                result = future.result()
                
                if sid not in results_by_scenario:
                    results_by_scenario[sid] = {"id": sid, "name": scenario["name"]}
                
                results_by_scenario[sid][mode] = result
                
                completed += 1
                if completed % 10 == 0:
                    print(f"  {completed}/{len(jobs)} jobs done...")
                    
            except Exception as e:
                print(f"  Error in {sid}/{mode}: {e}")
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    all_results = list(results_by_scenario.values())
    
    baseline_success = sum(1 for r in all_results if r.get("baseline", {}).get("success", False))
    avm_success = sum(1 for r in all_results if r.get("avm", {}).get("success", False))
    baseline_tokens = sum(r.get("baseline", {}).get("total_tokens", 0) for r in all_results)
    avm_tokens = sum(r.get("avm", {}).get("total_tokens", 0) for r in all_results)
    avm_overhead = sum(r.get("avm", {}).get("avm_overhead", 0) for r in all_results)
    
    print(f"Scenarios: {len(all_results)}")
    print(f"Baseline success: {baseline_success}/{len(all_results)}")
    print(f"AVM success: {avm_success}/{len(all_results)}")
    print(f"Baseline tokens: {baseline_tokens}")
    print(f"AVM tokens: {avm_tokens} (overhead: {avm_overhead})")
    
    # Save
    outfile = Path(__file__).parent / "results" / "parallel_benchmark.json"
    with open(outfile, 'w') as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "scenarios": len(all_results),
                "baseline_success": baseline_success,
                "avm_success": avm_success,
                "baseline_tokens": baseline_tokens,
                "avm_tokens": avm_tokens,
                "avm_overhead": avm_overhead,
            },
            "results": all_results,
        }, f, indent=2)
    
    print(f"\nSaved to: {outfile}")


if __name__ == "__main__":
    main()
