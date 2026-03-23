#!/usr/bin/env python3
"""
Extreme 4-Agent Collaboration Test

4 agents (mixed Codex + Claude Opus) must collaborate to solve a complex task.
Each agent has specialized role and partial information.

Scenario: Build a complete microservice
- Agent 1 (Codex): Database schema design
- Agent 2 (Claude Opus): API endpoint design  
- Agent 3 (Codex): Business logic implementation
- Agent 4 (Claude Opus): Integration & testing

Without AVM: Each agent works in isolation
With AVM: Full knowledge sharing across agents
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


# The complex task broken into 4 parts
MICROSERVICE_TASK = {
    "name": "User Notification Service",
    "description": "Build a microservice that handles user notifications (email, push, SMS)",
    "requirements": [
        "Store notification templates in database",
        "Expose REST API for sending notifications",
        "Support multiple channels (email, push, sms)",
        "Rate limiting per user",
        "Retry failed notifications",
    ],
}

AGENT_CONFIGS = [
    {
        "id": "db_architect",
        "type": "codex",
        "role": "Database Architect",
        "context": """You're designing the database schema for a notification service.
Requirements:
- Store notification templates
- Track sent notifications (status, retries)
- Support multiple channels
- Enable rate limiting queries""",
        "task": "Design the PostgreSQL schema. Output CREATE TABLE statements only.",
    },
    {
        "id": "api_designer",
        "type": "claude",  # Claude Opus
        "role": "API Designer",
        "context": """You're designing REST API endpoints for a notification service.
The service needs to:
- Send notifications via multiple channels
- Check notification status
- Manage templates
- Support rate limiting""",
        "task": "Design the API endpoints. Output OpenAPI-style endpoint definitions.",
    },
    {
        "id": "logic_implementer",
        "type": "codex",
        "role": "Business Logic Developer",
        "context": """You're implementing the core notification service logic.
Requirements:
- Channel abstraction (email, push, sms)
- Retry mechanism with exponential backoff
- Rate limiting per user""",
        "task": "Write the core Python service class with send_notification() method.",
    },
    {
        "id": "integrator",
        "type": "claude",  # Claude Opus
        "role": "Integration Engineer",
        "context": """You're integrating all components of the notification service.
Need to:
- Wire up API → Service → Database
- Add error handling
- Write integration test""",
        "task": "Write a FastAPI endpoint that uses the service. Include one integration test.",
    },
]


def run_4agent_collab(use_avm: bool) -> dict:
    """Run the 4-agent collaboration with or without AVM."""
    
    results = []
    total_tokens = 0
    avm_overhead = 0
    shared_artifacts = {}  # Accumulated outputs for baseline
    
    for i, agent in enumerate(AGENT_CONFIGS):
        agent_id = agent["id"]
        agent_type = agent["type"]
        role = agent["role"]
        
        print(f"\n  [{i+1}/4] {agent_id} ({agent_type.upper()}) - {role}")
        
        # Build context from previous agents
        if use_avm:
            # Recall all previous work
            recall = avm_recall(
                query=f"notification service {role} database API schema endpoint",
                agent_id=agent_id,
                max_tokens=800
            )
            avm_overhead += recall.tokens_used
            prev_context = recall.data[:1500] if recall.success else ""
            print(f"      AVM recalled {recall.tokens_used} tokens")
        else:
            # Baseline: only direct handoff from previous agent
            if shared_artifacts:
                prev_agent = list(shared_artifacts.keys())[-1]
                prev_context = f"Previous agent ({prev_agent}) output:\n{shared_artifacts[prev_agent][:500]}"
            else:
                prev_context = ""
        
        # Build full prompt
        full_task = f"""# {role}

## Service: {MICROSERVICE_TASK['name']}
{MICROSERVICE_TASK['description']}

## Requirements:
{chr(10).join(f'- {r}' for r in MICROSERVICE_TASK['requirements'])}

## Your Context:
{agent['context']}

## Previous Work:
{prev_context if prev_context else "(You are the first agent, no previous work)"}

## Your Task:
{agent['task']}

Output ONLY the requested artifact. Be concise but complete.
"""
        
        # Run agent
        start = time.time()
        try:
            response = run_agent(full_task, agent_type=agent_type, timeout=90)
        except Exception as e:
            response = AgentResponse(
                success=False, output=str(e), tokens_used=0,
                latency_ms=(time.time()-start)*1000, error=str(e)
            )
        
        total_tokens += response.tokens_used
        
        # Store result
        status = "✓" if response.success else "✗"
        print(f"      {status} {response.tokens_used} tokens, {response.latency_ms/1000:.1f}s")
        if not response.success:
            print(f"      Error: {response.error[:100]}")
        
        # Save for next agent
        if response.success and response.output:
            shared_artifacts[agent_id] = response.output
            
            # Store in AVM
            if use_avm:
                remember_result = avm_remember(
                    content=f"[{agent_id}/{role}]\n{response.output[:800]}",
                    agent_id=agent_id,
                    importance=0.9,
                    title=f"notif_service_{agent_id}"
                )
                avm_overhead += 40  # Estimate
        
        results.append({
            "agent_id": agent_id,
            "agent_type": agent_type,
            "role": role,
            "success": response.success,
            "tokens": response.tokens_used,
            "latency_ms": response.latency_ms,
            "output_len": len(response.output) if response.output else 0,
            "output_preview": response.output[:200] if response.output else "",
            "error": response.error if not response.success else "",
        })
    
    return {
        "agents": results,
        "total_tokens": total_tokens,
        "avm_overhead": avm_overhead,
        "grand_total": total_tokens + avm_overhead,
        "success_rate": sum(1 for r in results if r["success"]) / len(results),
    }


def evaluate_coherence(results: dict) -> dict:
    """Evaluate if the outputs are coherent with each other."""
    outputs = {r["agent_id"]: r.get("output_preview", "") for r in results["agents"]}
    
    # Check for key terms consistency
    checks = {
        "has_notifications_table": "notification" in outputs.get("db_architect", "").lower(),
        "has_send_endpoint": "send" in outputs.get("api_designer", "").lower() or "post" in outputs.get("api_designer", "").lower(),
        "has_send_method": "send" in outputs.get("logic_implementer", "").lower(),
        "has_integration": "test" in outputs.get("integrator", "").lower() or "fastapi" in outputs.get("integrator", "").lower(),
    }
    
    return {
        "checks": checks,
        "coherence_score": sum(checks.values()) / len(checks),
    }


def main():
    print("="*70)
    print("EXTREME 4-AGENT COLLABORATION TEST")
    print("Building a microservice with mixed Codex + Claude Opus")
    print("="*70)
    
    print(f"\nTask: {MICROSERVICE_TASK['name']}")
    print("\nAgent Pipeline:")
    for a in AGENT_CONFIGS:
        print(f"  {a['id']} ({a['type'].upper()}): {a['role']}")
    
    # Run baseline
    print("\n" + "="*70)
    print("[BASELINE] Sequential without AVM")
    print("="*70)
    
    baseline = run_4agent_collab(use_avm=False)
    baseline_coherence = evaluate_coherence(baseline)
    
    print(f"\n  Success: {sum(1 for r in baseline['agents'] if r['success'])}/4")
    print(f"  Total tokens: {baseline['total_tokens']}")
    print(f"  Coherence: {baseline_coherence['coherence_score']:.0%}")
    
    # Run with AVM
    print("\n" + "="*70)
    print("[AVM] With shared memory")
    print("="*70)
    
    avm = run_4agent_collab(use_avm=True)
    avm_coherence = evaluate_coherence(avm)
    
    print(f"\n  Success: {sum(1 for r in avm['agents'] if r['success'])}/4")
    print(f"  Total tokens: {avm['total_tokens']} + {avm['avm_overhead']} overhead = {avm['grand_total']}")
    print(f"  Coherence: {avm_coherence['coherence_score']:.0%}")
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"{'Metric':<30} {'Baseline':>15} {'AVM':>15}")
    print("-"*60)
    print(f"{'Agents Succeeded':<30} {sum(1 for r in baseline['agents'] if r['success']):>15}/4 {sum(1 for r in avm['agents'] if r['success']):>15}/4")
    print(f"{'Total Tokens':<30} {baseline['total_tokens']:>15} {avm['grand_total']:>15}")
    print(f"{'AVM Overhead':<30} {0:>15} {avm['avm_overhead']:>15}")
    print(f"{'Coherence Score':<30} {baseline_coherence['coherence_score']:>14.0%} {avm_coherence['coherence_score']:>14.0%}")
    
    # Agent breakdown
    print("\n" + "-"*70)
    print("Agent Breakdown:")
    print(f"{'Agent':<20} {'Type':<10} {'Base':>10} {'AVM':>10}")
    print("-"*50)
    for i in range(4):
        b = baseline['agents'][i]
        a = avm['agents'][i]
        print(f"{b['agent_id']:<20} {b['agent_type']:<10} {b['tokens']:>10} {a['tokens']:>10}")
    
    # Save
    log = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": MICROSERVICE_TASK,
        "agents": AGENT_CONFIGS,
        "baseline": baseline,
        "baseline_coherence": baseline_coherence,
        "avm": avm,
        "avm_coherence": avm_coherence,
    }
    
    outfile = Path(__file__).parent / "results" / "extreme_collab.json"
    with open(outfile, 'w') as f:
        json.dump(log, f, indent=2)
    
    print(f"\nDetailed log: {outfile}")


if __name__ == "__main__":
    main()
