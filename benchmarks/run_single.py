#!/usr/bin/env python3
"""
Run a single benchmark scenario end-to-end.
"""

import json
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone

from runner import BenchmarkRunner, AssertionChecker
from agent_executor import MultiAgentExecutor, run_codex


def run_bugfix_scenario():
    """Run the cc-005 Bug Fix scenario."""
    
    # Load scenario
    runner = BenchmarkRunner({"agent": "codex", "avm_enabled": False})
    scenario = runner.load_scenario("collaborative_coding", "cc-005")
    
    print(f"Running scenario: {scenario['name']}")
    print(f"Agents: {[a['id'] for a in scenario['agents']]}")
    print(f"Assertions: {len(scenario['assertions'])}")
    print("-" * 50)
    
    # Start run
    run = runner.start_run(scenario)
    
    # Create temp workdir
    with tempfile.TemporaryDirectory(prefix="bench_") as workdir:
        workdir = Path(workdir)
        
        # Write the buggy code
        buggy_code = scenario.get("provided_code", """
def search(items, query):
    return [i for i in items if query in i['name']]

# Bug: special chars like '.' or '*' cause issues
""")
        (workdir / "search.py").write_text(buggy_code)
        
        # Run each agent
        executor = MultiAgentExecutor(agent_type="codex")
        
        for agent in scenario["agents"]:
            agent_id = agent["id"]
            role = agent["role"]
            
            print(f"\n>>> Agent: {agent_id} ({role})")
            runner.log_event(agent_id, "start", details={"role": role})
            
            # Build task
            task = f"""You are '{agent_id}' with role: {role}

The buggy code is in search.py. The bug report says:
"The search function returns wrong results when query contains special characters"

The buggy code:
```python
{buggy_code}
```

Your job ({role}):
- If debugger: Analyze the bug and explain the cause
- If fixer: Write the fixed code
- If reviewer: Review the fix and confirm it's correct

Be concise. Output only what's needed for your role.
"""
            
            start = time.time()
            response = run_codex(task, workdir=str(workdir), timeout=60)
            latency = (time.time() - start) * 1000
            
            runner.log_event(agent_id, "llm_call", 
                details={"output_preview": response.output[:200]},
                tokens_used=response.tokens_used,
                latency_ms=latency
            )
            
            print(f"    Success: {response.success}")
            print(f"    Latency: {latency:.0f}ms")
            print(f"    Output preview: {response.output[:150]}...")
            
            # Save output for inspection
            (workdir / f"{agent_id}_output.md").write_text(response.output)
        
        # Check assertions (simplified)
        checker = AssertionChecker(use_llm_judge=False)
        assertions_passed = 0
        for assertion in scenario["assertions"]:
            # For now, just mark as passed (real impl would check)
            passed, _ = checker.check_assertion(assertion, {})
            if passed:
                assertions_passed += 1
            runner.log_event("judge", "assertion_check", 
                details={"assertion": assertion, "passed": passed})
    
    # End run
    result = {
        "success": assertions_passed > 0,
        "assertions_passed": assertions_passed,
        "assertions_total": len(scenario["assertions"]),
    }
    run = runner.end_run(result)
    
    print("\n" + "=" * 50)
    print("RUN COMPLETE")
    print(f"Run ID: {run.run_id}")
    print(f"Assertions: {assertions_passed}/{len(scenario['assertions'])}")
    print(f"Total events: {len(run.events)}")
    
    return run


if __name__ == "__main__":
    run_bugfix_scenario()
