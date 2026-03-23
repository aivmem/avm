#!/usr/bin/env python3
"""
Context Overflow Benchmark - Tests AVM's value for preserving context beyond LLM limits.

These scenarios have no agents - they test single agent recall with/without AVM.
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
    """Run Claude Opus with task."""
    cmd = [
        "claude",
        "--print",
        "--permission-mode", "bypassPermissions",
        "--model", "claude-opus-4-5",
        task
    ]
    
    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        latency = (time.time() - start) * 1000
        output = result.stdout
        
        return {
            "success": result.returncode == 0 and len(output) > 10,
            "output": output,
            "tokens": count_tokens(output),
            "latency_ms": latency,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "tokens": 0, "latency_ms": timeout*1000}
    except Exception as e:
        return {"success": False, "output": str(e), "tokens": 0, "latency_ms": 0}


def run_avm(args: list, input_text: str = None) -> tuple:
    """Run AVM command."""
    try:
        result = subprocess.run(
            ["avm"] + args,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0, result.stdout
    except:
        return False, ""


def check_answer(output: str, expected: str) -> bool:
    """Check if output contains expected answer."""
    output_lower = output.lower()
    expected_lower = expected.lower()
    
    # Check for exact match or key parts
    if expected_lower in output_lower:
        return True
    
    # Check key parts (split by common separators)
    for part in expected_lower.replace(",", " ").split():
        if len(part) > 3 and part in output_lower:
            return True
    
    return False


def run_scenario(scenario: dict) -> dict:
    """Run a context overflow scenario."""
    results = {
        "scenario_id": scenario["id"],
        "scenario_name": scenario["name"],
        "baseline": {},
        "avm": {},
    }
    
    # Get scenario data
    compact_summary = scenario.get("compact_summary", "")
    test_question = scenario.get("test_question", "")
    expected_answer = scenario.get("expected_answer", "")
    avm_stored = scenario.get("avm_stored", {})
    
    # === BASELINE ===
    # Agent only has compact_summary, not full context
    baseline_prompt = f"""You are an AI assistant continuing a conversation. 
Here's what you remember from previous sessions:

{compact_summary}

User's question: {test_question}

Answer concisely based on what you remember."""

    print("    [BASELINE] Running with only compact summary...")
    baseline_response = run_claude(baseline_prompt)
    baseline_correct = check_answer(baseline_response["output"], expected_answer)
    
    results["baseline"] = {
        "correct": baseline_correct,
        "output": baseline_response["output"][:300],
        "tokens": baseline_response["tokens"],
        "latency_ms": baseline_response["latency_ms"],
    }
    
    # === AVM ===
    # Store context in AVM first
    agent_id = f"co_test_{scenario['id']}"
    
    for path, content in avm_stored.items():
        run_avm(["write", f"/memory/private/{agent_id}{path}"], input_text=content)
    
    # Recall from AVM
    success, recalled = run_avm([
        "recall", "-a", agent_id, "-t", "500",
        test_question
    ])
    
    # Clean recalled text (remove null bytes and control chars)
    if recalled:
        recalled = recalled.replace('\x00', '').encode('utf-8', errors='ignore').decode('utf-8')
    
    avm_prompt = f"""You are an AI assistant continuing a conversation.
Here's what you remember from previous sessions:

{compact_summary}

You also have access to stored notes:
{recalled if recalled else "(no relevant notes found)"}

User's question: {test_question}

Answer concisely based on what you remember and your stored notes."""

    print("    [AVM] Running with AVM recall...")
    avm_response = run_claude(avm_prompt)
    avm_correct = check_answer(avm_response["output"], expected_answer)
    
    results["avm"] = {
        "correct": avm_correct,
        "output": avm_response["output"][:300],
        "tokens": avm_response["tokens"],
        "latency_ms": avm_response["latency_ms"],
        "avm_recall": recalled[:200] if recalled else "",
        "avm_overhead": count_tokens(recalled) if recalled else 0,
    }
    
    return results


def main():
    print("="*70)
    print("CONTEXT OVERFLOW BENCHMARK")
    print("Testing AVM's value for preserving context beyond LLM limits")
    print("="*70)
    
    # Load scenarios
    scenarios_file = Path(__file__).parent / "scenarios" / "context_overflow.json"
    with open(scenarios_file) as f:
        data = json.load(f)
    
    scenarios = data.get("scenarios", [])
    print(f"\nLoaded {len(scenarios)} scenarios")
    
    all_results = []
    baseline_correct = 0
    avm_correct = 0
    
    for i, scenario in enumerate(scenarios):
        print(f"\n[{i+1}/{len(scenarios)}] {scenario['id']}: {scenario['name']}")
        
        result = run_scenario(scenario)
        all_results.append(result)
        
        b_ok = "✓" if result["baseline"]["correct"] else "✗"
        a_ok = "✓" if result["avm"]["correct"] else "✗"
        
        if result["baseline"]["correct"]:
            baseline_correct += 1
        if result["avm"]["correct"]:
            avm_correct += 1
        
        print(f"    Baseline: {b_ok} ({result['baseline']['tokens']} tokens)")
        print(f"    AVM: {a_ok} ({result['avm']['tokens']} tokens, +{result['avm'].get('avm_overhead', 0)} overhead)")
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"Scenarios: {len(scenarios)}")
    print(f"Baseline correct: {baseline_correct}/{len(scenarios)} ({100*baseline_correct/len(scenarios):.0f}%)")
    print(f"AVM correct: {avm_correct}/{len(scenarios)} ({100*avm_correct/len(scenarios):.0f}%)")
    print(f"Improvement: +{avm_correct - baseline_correct} scenarios")
    
    # Save results
    outfile = Path(__file__).parent / "results" / "context_overflow_benchmark.json"
    with open(outfile, 'w') as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total": len(scenarios),
                "baseline_correct": baseline_correct,
                "avm_correct": avm_correct,
            },
            "results": all_results,
        }, f, indent=2)
    
    print(f"\nResults saved to: {outfile}")


if __name__ == "__main__":
    main()
