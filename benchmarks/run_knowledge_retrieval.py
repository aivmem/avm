#!/usr/bin/env python3
"""
Knowledge Retrieval Benchmark - Tests cross-agent knowledge sharing.
"""

import json
import subprocess
import time
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


def run_claude(task: str, timeout: int = 90) -> dict:
    cmd = [
        "claude", "--print", "--permission-mode", "bypassPermissions",
        "--model", "claude-opus-4-5", task
    ]
    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "success": result.returncode == 0 and len(result.stdout) > 10,
            "output": result.stdout,
            "tokens": count_tokens(result.stdout),
            "latency_ms": (time.time() - start) * 1000,
        }
    except:
        return {"success": False, "output": "", "tokens": 0, "latency_ms": timeout*1000}


def run_avm(args: list, input_text: str = None) -> tuple:
    try:
        result = subprocess.run(
            ["avm"] + args, input=input_text,
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.replace('\x00', '').encode('utf-8', errors='ignore').decode('utf-8')
        return result.returncode == 0, output
    except:
        return False, ""


def check_assertions(output: str, assertions: list) -> tuple:
    """Check how many assertions pass."""
    passed = 0
    for assertion in assertions:
        # Simple keyword check
        keywords = assertion.lower().split()[:3]  # First 3 words
        if any(kw in output.lower() for kw in keywords if len(kw) > 3):
            passed += 1
    return passed, len(assertions)


def run_scenario(scenario: dict) -> dict:
    results = {
        "id": scenario["id"],
        "name": scenario["name"],
        "baseline": {},
        "avm": {},
    }
    
    # Setup: store preloaded knowledge in AVM
    setup = scenario.get("setup", {})
    preloaded = setup.get("preloaded_knowledge", [])
    
    for i, item in enumerate(preloaded):
        content = json.dumps(item) if isinstance(item, dict) else str(item)
        run_avm(["write", f"/memory/shared/kr/{scenario['id']}/item_{i}.md"], input_text=content)
    
    task = scenario.get("task", scenario.get("current_issue", scenario["description"]))
    assertions = scenario.get("assertions", [])
    
    # === BASELINE ===
    baseline_prompt = f"""You are a support agent. Answer this question based on your general knowledge.

Question: {task}

Be specific and concise."""

    print("    [BASELINE] Running...")
    b_resp = run_claude(baseline_prompt)
    b_passed, b_total = check_assertions(b_resp["output"], assertions)
    
    results["baseline"] = {
        "success": b_resp["success"],
        "output": b_resp["output"][:300],
        "tokens": b_resp["tokens"],
        "assertions_passed": f"{b_passed}/{b_total}",
    }
    
    # === AVM ===
    agent_id = f"kr_agent_{scenario['id']}"
    success, recalled = run_avm(["recall", "-a", agent_id, "-t", "500", task])
    
    avm_prompt = f"""You are a support agent with access to a knowledge base.

Knowledge Base Results:
{recalled if recalled else "(no results)"}

Question: {task}

Answer based on the knowledge base. Be specific."""

    print("    [AVM] Running...")
    a_resp = run_claude(avm_prompt)
    a_passed, a_total = check_assertions(a_resp["output"], assertions)
    
    results["avm"] = {
        "success": a_resp["success"],
        "output": a_resp["output"][:300],
        "tokens": a_resp["tokens"],
        "assertions_passed": f"{a_passed}/{a_total}",
        "avm_overhead": count_tokens(recalled) if recalled else 0,
    }
    
    return results


def main():
    print("="*70)
    print("KNOWLEDGE RETRIEVAL BENCHMARK")
    print("="*70)
    
    # Load both knowledge_retrieval files
    scenarios_dir = Path(__file__).parent / "scenarios"
    scenarios = []
    
    for f in ["knowledge_retrieval.json", "knowledge_retrieval_extended.json"]:
        path = scenarios_dir / f
        if path.exists():
            with open(path) as fp:
                data = json.load(fp)
                scenarios.extend(data.get("scenarios", []))
    
    print(f"\nLoaded {len(scenarios)} scenarios")
    
    all_results = []
    
    for i, scenario in enumerate(scenarios):
        print(f"\n[{i+1}/{len(scenarios)}] {scenario['id']}: {scenario['name']}")
        result = run_scenario(scenario)
        all_results.append(result)
        
        print(f"    Baseline: {result['baseline']['assertions_passed']} assertions, {result['baseline']['tokens']} tokens")
        print(f"    AVM: {result['avm']['assertions_passed']} assertions, {result['avm']['tokens']} tokens (+{result['avm']['avm_overhead']} overhead)")
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    # Calculate totals
    b_passed_total = sum(int(r["baseline"]["assertions_passed"].split("/")[0]) for r in all_results)
    a_passed_total = sum(int(r["avm"]["assertions_passed"].split("/")[0]) for r in all_results)
    total_assertions = sum(int(r["baseline"]["assertions_passed"].split("/")[1]) for r in all_results)
    
    print(f"Scenarios: {len(scenarios)}")
    print(f"Baseline assertions: {b_passed_total}/{total_assertions}")
    print(f"AVM assertions: {a_passed_total}/{total_assertions}")
    print(f"Improvement: +{a_passed_total - b_passed_total} assertions")
    
    # Save
    outfile = Path(__file__).parent / "results" / "knowledge_retrieval_benchmark.json"
    with open(outfile, 'w') as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_scenarios": len(scenarios),
                "baseline_assertions": b_passed_total,
                "avm_assertions": a_passed_total,
                "total_assertions": total_assertions,
            },
            "results": all_results,
        }, f, indent=2)
    
    print(f"\nResults saved to: {outfile}")


if __name__ == "__main__":
    main()
