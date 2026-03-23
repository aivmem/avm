---
title: "AVM Multi-Agent Benchmark: Measuring Memory's Value"
date: 2026-03-23
tags: ["avm", "benchmark", "multi-agent", "llm"]
author: "Dylan Shi"
draft: false
---

# AVM Multi-Agent Benchmark: Quantifying Persistent Memory's Value

We ran comprehensive benchmarks to measure AVM's impact on multi-agent collaboration. The results demonstrate where persistent memory provides the most value.

## TL;DR

| Scenario | Baseline | AVM | Improvement |
|----------|----------|-----|-------------|
| Context Overflow | 50% | **88%** | **+38%** |
| Knowledge Retrieval | 47% | **67%** | **+20%** |
| Full Collaboration | 100% | 100% | — |

**Key finding**: AVM provides the most value when agents need to recall specific details that exceed LLM context limits or share knowledge across sessions.

## Benchmark Design

### Scenarios Tested

We created 48 scenarios across 5 categories:

1. **Collaborative Coding** (10) — Multi-agent software development
2. **Knowledge Retrieval** (15) — Cross-agent knowledge lookup
3. **Information Sync** (10) — Real-time data propagation
4. **Real-World Cases** (5) — End-to-end workflows
5. **Context Overflow** (8) — Beyond-context-limit recall

### Methodology

Each scenario runs twice:
- **Baseline**: Agents only see accumulated conversation context
- **AVM**: Agents can `recall` from AVM and `remember` outputs

Metrics:
- Success rate (task completion)
- Assertion pass rate (specific correctness checks)
- Token usage (overhead measurement)

## Results

### Context Overflow: +38% Accuracy

The highest-value scenario. When agents are "compacted" (lost detailed context), AVM enables recall of specific details.

```
Scenario: Long Conversation Recall
Question: "What email for password resets?"

Baseline: "I don't have information about email addresses..."
AVM: "security@company.com" ✓ (recalled from /decisions/security.md)
```

| Scenario | Baseline | AVM |
|----------|----------|-----|
| Long Conversation | ✗ | ✓ |
| Multi-Session Project | ✓ | ✓ |
| Interruption Recovery | ✓ | ✗ |
| Thread Context | ✗ | ✓ |
| Temporal Reasoning | ✗ | ✓ |
| Contradiction Resolution | ✗ | ✓ |

**4/8 → 7/8 correct (+38%)**

### Knowledge Retrieval: +20% Assertions

Cross-agent knowledge sharing shows clear improvement:

```
Scenario: Architecture Decision Records
Task: "Should we split the monolith? Team grew from 10 to 25."

Baseline: Generic advice about microservices
AVM: Recalls ADR-007 (monolith decision), notes team size change,
     provides contextualized recommendation ✓
```

**24/51 → 34/51 assertions passed (+20%)**

### Full Collaboration: 100% Both

For scenarios where all context fits in conversation, both approaches succeed. AVM adds overhead but provides knowledge persistence for future sessions.

## Overhead Analysis

| Mode | Tokens | Notes |
|------|--------|-------|
| Baseline | 14,240 | Direct agent output |
| AVM | 14,154 + 16,202 overhead | Recall tokens add context |

AVM recall adds ~400-600 tokens per agent. This is acceptable when:
- Context would otherwise be lost
- Knowledge needs to persist across sessions
- Multiple agents need shared state

## Recommendations

### When to Use AVM

✅ **High Value**:
- Long conversations (>50 turns)
- Multi-session projects
- Cross-agent knowledge sharing
- Regulatory/compliance lookups
- Historical incident analysis

⚠️ **Moderate Value**:
- Complex multi-step tasks
- Code review with context
- Meeting synthesis

❌ **Low Value** (use baseline):
- Simple one-shot tasks
- Self-contained conversations
- No knowledge reuse needed

### Optimization Tips

1. **Selective Recall**: Only recall when task requires historical knowledge
2. **Token Budget**: Use `-t 300` for focused recall, `-t 1000` for comprehensive
3. **Structured Storage**: Use consistent paths (`/decisions/`, `/bugs/`, `/meetings/`)
4. **Importance Tagging**: Mark critical memories for priority retrieval

## Conclusion

AVM's value is context-dependent:
- **+38% accuracy** for context overflow scenarios
- **+20% assertions** for knowledge retrieval
- **Zero improvement** for simple tasks (expected)

The benchmark validates AVM's core thesis: persistent memory matters when LLM context limits become constraints.

## Reproduce

```bash
git clone https://github.com/aivmem/avm
cd avm/benchmarks
pip install tiktoken

# Run all benchmarks (parallel)
python run_parallel.py

# Specific tests
python run_context_overflow.py
python run_knowledge_retrieval.py
```

Results saved to `results/*.json`.

---

*Benchmark conducted March 23, 2026 using Claude Opus. 48 scenarios, 150+ agent invocations.*
