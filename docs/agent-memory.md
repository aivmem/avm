# Agent Memory Guide

Agent Memory is AVM's high-level API for LLM agents. It provides:
- Token-aware recall (fit any context budget)
- Importance/recency scoring
- Private + shared namespaces
- Tags and metadata

## Creating an Agent

```python
from avm import AVM

avm = AVM()
trader = avm.agent_memory("trader")
```

Each agent gets:
- Private namespace: `/memory/private/trader/*`
- Access to shared: `/memory/shared/*`

## Remembering

```python
# Basic
trader.remember("Market observation here")

# With metadata
trader.remember(
    "NVDA showing weakness at $900 resistance",
    title="nvda_resistance",      # Optional filename
    importance=0.9,               # 0.0-1.0, affects recall ranking
    tags=["market", "nvda"]       # For filtering/discovery
)

# Share with other agents
trader.remember(
    "Fed announces rate hold",
    namespace="market"            # Goes to /memory/shared/market/
)
```

## Recalling

```python
# Basic recall with token budget
context = trader.recall("NVDA risk", max_tokens=500)

# Scoring strategies
from avm.agent_memory import ScoringStrategy

# Prefer recent memories
context = trader.recall("market", strategy=ScoringStrategy.RECENCY)

# Prefer important memories  
context = trader.recall("lessons", strategy=ScoringStrategy.IMPORTANCE)

# Balance all factors (default)
context = trader.recall("trading", strategy=ScoringStrategy.BALANCED)
```

## Output Format

Recall returns formatted markdown:

```markdown
## Relevant Memory (3 items, ~120 tokens)

[/memory/private/trader/nvda_alert.md] (0.85)
*Created: 2026-03-05 14:30 UTC*
NVDA showing weakness at $900...
*Tags: market, nvda*
---

[/memory/private/trader/lesson_stoploss.md] (0.72)
*Created: 2026-03-04 10:00 UTC*
Always use stop-loss orders...
---

*Tokens: ~120/500 | Strategy: balanced | Query: "NVDA"*
```

## Navigation

When you don't know what to search for:

```python
# Topic overview
trader.topics()
# ## Memory Topics
# ### By Category:
#   📁 private: 15 memories
# ### By Tag:
#   🏷️ market: 5, technical: 3, macro: 2

# Browse structure
trader.browse("/memory", depth=2)
# 📁 private (15)
#   📁 trader (15)

# Timeline
trader.timeline(days=7)
# ### 2026-03-05
#   [14:30] nvda_alert: NVDA showing...
#   [10:00] btc_note: BTC holding...

# Graph exploration
trader.explore("/memory/private/trader/nvda.md", depth=2)
# ## Starting from: nvda.md
# ### Hop 1:
#   [related] macd_analysis.md
```

## Tags

```python
# Get tag cloud
cloud = trader.tag_cloud()
# {"market": 5, "technical": 3, "nvda": 2, ...}

# Find by tag
nodes = trader.by_tag("market")

# Suggest tags for content
tags = trader.suggest_tags("RSI overbought signal on NVDA")
# ["technical", "nvda", "rsi"]
```

## Time Queries

```python
# Recall from specific time range
context = trader.recall_recent(
    "market observations",
    days=7,
    max_tokens=1000
)
```

## Statistics

```python
stats = trader.stats()
# {
#   "private_count": 15,
#   "shared_count": 3,
#   "total_tokens": 4500
# }
```

## Export/Import

```python
# Export to JSONL
data = trader.export(format="jsonl")

# Export to Markdown
md = trader.export(format="markdown")

# Import from JSONL
count = trader.import_memories(jsonl_data)
```

## Best Practices

1. **Set importance** - Lessons and key insights should be 0.9+
2. **Use tags consistently** - Helps with discovery
3. **Title your memories** - Makes browsing easier
4. **Share appropriately** - Use namespaces for multi-agent collaboration
5. **Recall with budget** - Always set `max_tokens` to fit your context window
