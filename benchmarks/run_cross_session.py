#!/usr/bin/env python3
"""
Cross-Session Knowledge Test - Real company scenario

Simulates:
1. Discussion in #dev channel (Akashi answers a question)
2. Same question asked later in private chat (Kearsarge)
3. Compare: with AVM gossip vs without

This is the core AVM value proposition for multi-agent systems.
"""

import json
import tempfile
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from runner import BenchmarkRunner
from agent_executor import run_codex, count_tokens
from avm_integration import avm_recall, avm_remember


# Real scenarios from company operations
CROSS_SESSION_SCENARIOS = [
    {
        "id": "redis-timeout",
        "channel_discussion": {
            "channel": "#dev",
            "agent": "akashi",
            "question": "Redis 连接老是超时，怎么配置比较好？",
            "answer": """Redis 超时配置最佳实践：
1. socket_timeout=5 (秒)
2. socket_connect_timeout=2 (建连超时)  
3. retry_on_timeout=True
4. health_check_interval=30

代码：
```python
redis.Redis(
    host='localhost',
    socket_timeout=5,
    socket_connect_timeout=2,
    retry_on_timeout=True,
    health_check_interval=30
)
```"""
        },
        "later_question": {
            "channel": "private",
            "agent": "kearsarge", 
            "question": "Redis 连接超时怎么配置？我记得之前在 #dev 讨论过",
        },
    },
    {
        "id": "docker-memory",
        "channel_discussion": {
            "channel": "#dev",
            "agent": "akashi",
            "question": "Docker 容器 OOM 了，怎么限制内存？",
            "answer": """Docker 内存限制：
1. docker run -m 512m (硬限制)
2. --memory-reservation=256m (软限制)
3. --oom-kill-disable (谨慎使用)

docker-compose:
```yaml
services:
  app:
    mem_limit: 512m
    mem_reservation: 256m
```

监控：docker stats"""
        },
        "later_question": {
            "channel": "private",
            "agent": "kearsarge",
            "question": "Docker 怎么限制内存来着？之前好像讨论过",
        },
    },
    {
        "id": "git-rebase",
        "channel_discussion": {
            "channel": "#dev",
            "agent": "akashi",
            "question": "rebase 冲突太多了，有什么技巧吗？",
            "answer": """Git rebase 冲突处理技巧：
1. 小步 rebase: git rebase -i HEAD~3 (不要一次 rebase 太多)
2. 用 rerere 自动记录解决方案: git config rerere.enabled true
3. 冲突太多时用 git rebase --abort, 改用 merge
4. 推荐流程: fetch → rebase origin/main → 解决冲突 → continue

黄金法则：只 rebase 未 push 的 commit"""
        },
        "later_question": {
            "channel": "private",
            "agent": "kearsarge",
            "question": "git rebase 冲突多的时候怎么处理比较好？",
        },
    },
]


def simulate_channel_discussion(scenario: dict):
    """Simulate a discussion in #dev channel, store in AVM."""
    disc = scenario["channel_discussion"]
    
    # Store the discussion as shared knowledge
    content = f"""[{disc['channel']}] Q&A by {disc['agent']}

Q: {disc['question']}

A: {disc['answer']}

---
Recorded: {datetime.now(timezone.utc).isoformat()}
"""
    
    path = f"/memory/shared/discussions/{scenario['id']}.md"
    result = subprocess.run(
        ["avm", "write", path],
        input=content,
        capture_output=True, text=True
    )
    
    return result.returncode == 0, path


def answer_without_avm(question: str) -> dict:
    """Answer question without access to AVM (baseline)."""
    task = f"""用户问: {question}

你是 Kearsarge，公司的 AI 助手。回答这个技术问题。
如果不确定，说"我不太确定，建议问一下研发"。
"""
    
    with tempfile.TemporaryDirectory() as workdir:
        response = run_codex(task, workdir=workdir, timeout=45)
    
    return {
        "tokens": response.tokens_used,
        "output": response.output,
        "success": response.success,
    }


def answer_with_avm(question: str, scenario_id: str) -> dict:
    """Answer question with AVM access."""
    
    # Recall relevant discussions
    recall_result = avm_recall(
        query=question,
        agent_id="kearsarge",
        max_tokens=400
    )
    
    recalled = recall_result.data if recall_result.success else ""
    
    task = f"""用户问: {question}

你是 Kearsarge，公司的 AI 助手。

## 团队讨论记录 (from AVM):
{recalled[:800] if recalled else "(没有找到相关记录)"}

根据之前的讨论回答。如果找到了相关讨论，引用它。
"""
    
    with tempfile.TemporaryDirectory() as workdir:
        response = run_codex(task, workdir=workdir, timeout=45)
    
    return {
        "tokens": response.tokens_used,
        "avm_overhead": recall_result.tokens_used,
        "total": response.tokens_used + recall_result.tokens_used,
        "output": response.output,
        "success": response.success,
        "found_discussion": scenario_id in recalled.lower() or any(
            keyword in recalled.lower() 
            for keyword in question.lower().split()[:3]
        ),
    }


def check_answer_quality(output: str, expected_answer: str) -> dict:
    """Check if the answer contains key information from the original discussion."""
    output_lower = output.lower()
    expected_lower = expected_answer.lower()
    
    # Extract key technical terms from expected answer
    import re
    # Find code-like patterns and technical terms
    code_patterns = re.findall(r'`([^`]+)`|(\w+_\w+)|(\d+[mM])', expected_lower)
    key_terms = [p[0] or p[1] or p[2] for p in code_patterns if any(p)]
    
    # Also check for specific numbers and settings
    numbers = re.findall(r'\d+', expected_lower)
    
    matches = sum(1 for term in key_terms if term in output_lower)
    number_matches = sum(1 for num in numbers if num in output)
    
    total_checks = len(key_terms) + len(numbers)
    total_matches = matches + number_matches
    
    return {
        "score": total_matches / total_checks if total_checks > 0 else 0,
        "key_terms_found": matches,
        "numbers_found": number_matches,
    }


def main():
    print("="*70)
    print("CROSS-SESSION KNOWLEDGE TEST")
    print("Simulating: #dev discussion → later private chat question")
    print("="*70)
    
    results = []
    
    for scenario in CROSS_SESSION_SCENARIOS:
        print(f"\n{'='*70}")
        print(f"SCENARIO: {scenario['id']}")
        print(f"{'='*70}")
        
        # Phase 1: Simulate channel discussion (store in AVM)
        disc = scenario["channel_discussion"]
        print(f"\n[PHASE 1] {disc['channel']} discussion stored...")
        success, path = simulate_channel_discussion(scenario)
        print(f"  Stored at: {path} ({'✓' if success else '✗'})")
        
        # Phase 2: Later question
        later = scenario["later_question"]
        question = later["question"]
        expected = disc["answer"]
        
        print(f"\n[PHASE 2] Later question: '{question[:50]}...'")
        
        # Baseline (no AVM)
        print("\n  [BASELINE] Without AVM...")
        baseline = answer_without_avm(question)
        baseline_quality = check_answer_quality(baseline["output"], expected)
        print(f"    Tokens: {baseline['tokens']}")
        print(f"    Quality score: {baseline_quality['score']:.1%}")
        
        # With AVM
        print("\n  [AVM] With cross-session memory...")
        avm = answer_with_avm(question, scenario["id"])
        avm_quality = check_answer_quality(avm["output"], expected)
        print(f"    Tokens: {avm['tokens']} + {avm['avm_overhead']} overhead = {avm['total']}")
        print(f"    Found discussion: {'✓' if avm['found_discussion'] else '✗'}")
        print(f"    Quality score: {avm_quality['score']:.1%}")
        
        results.append({
            "id": scenario["id"],
            "baseline_tokens": baseline["tokens"],
            "baseline_quality": baseline_quality["score"],
            "avm_tokens": avm["total"],
            "avm_overhead": avm["avm_overhead"],
            "avm_quality": avm_quality["score"],
            "found_discussion": avm["found_discussion"],
            "quality_improvement": avm_quality["score"] - baseline_quality["score"],
        })
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"{'Scenario':<20} {'Base Qual':>10} {'AVM Qual':>10} {'Improve':>10} {'Overhead':>10}")
    print("-"*70)
    
    for r in results:
        print(f"{r['id']:<20} {r['baseline_quality']:>9.0%} {r['avm_quality']:>9.0%} "
              f"{r['quality_improvement']:>+9.0%} {r['avm_overhead']:>10}")
    
    avg_improvement = sum(r['quality_improvement'] for r in results) / len(results)
    avg_overhead = sum(r['avm_overhead'] for r in results) / len(results)
    
    print("-"*70)
    print(f"{'AVERAGE':<20} {'':<10} {'':<10} {avg_improvement:>+9.0%} {avg_overhead:>10.0f}")
    
    if avg_improvement > 0.1:
        print("\n🎯 AVM significantly improves answer quality for cross-session questions!")
    
    # Save
    outfile = Path(__file__).parent / "results" / "cross_session.json"
    with open(outfile, 'w') as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "avg_quality_improvement": avg_improvement,
            "avg_overhead": avg_overhead,
        }, f, indent=2)
    
    print(f"\nSaved to {outfile}")


if __name__ == "__main__":
    main()
