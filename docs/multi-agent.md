# Multi-Agent Setup

AVM supports multiple agents with isolated private memories and optional shared namespaces.

## Architecture

```
/memory/
├── private/
│   ├── trader/       # Only trader can access
│   │   └── *.md
│   └── analyst/      # Only analyst can access
│       └── *.md
└── shared/
    ├── market/       # Both can access
    │   └── *.md
    └── signals/      # Both can access
        └── *.md
```

## Creating Agents

```python
from avm import AVM

avm = AVM()

# Create two agents
trader = avm.agent_memory("trader")
analyst = avm.agent_memory("analyst")
```

## Private Memories

Each agent's `remember()` goes to their private namespace by default:

```python
# Trader stores privately
trader.remember("NVDA looks weak", title="nvda_view")
# Stored at: /memory/private/trader/nvda_view.md

# Analyst stores privately  
analyst.remember("SPY pattern forming", title="spy_pattern")
# Stored at: /memory/private/analyst/spy_pattern.md
```

Agents cannot see each other's private memories:

```python
# Trader can recall their own
trader.recall("NVDA")  # ✓ Finds nvda_view.md

# Trader cannot recall analyst's private memory
trader.recall("SPY pattern")  # ✗ Returns nothing
```

## Shared Memories

Use namespaces to share:

```python
# Analyst shares to market namespace
analyst.remember(
    "Bearish divergence on major indices",
    title="market_signal",
    namespace="market"
)
# Stored at: /memory/shared/market/market_signal.md

# Trader can now see it
trader.recall("bearish divergence", include_shared=True)
# ✓ Finds the shared memory
```

## Namespace Permissions

Configure who can access what:

```yaml
# config.yaml
agents:
  trader:
    namespaces:
      - market     # Can read/write
      - signals    # Can read/write
  analyst:
    namespaces:
      - market     # Can read/write
      - research   # Can read/write
  readonly_bot:
    namespaces:
      - market: ro  # Read only
```

## Recall with Namespace Filter

```python
# Only recall from specific shared namespaces
context = trader.recall(
    "market signals",
    include_shared=True,
    namespaces=["market", "signals"]  # Limit scope
)
```

## Agent Statistics

```python
trader.stats()
# {
#   "private_count": 15,
#   "shared_count": 5,
#   "agent_id": "trader"
# }

analyst.stats()
# {
#   "private_count": 8,
#   "shared_count": 5,  # Same shared memories
#   "agent_id": "analyst"
# }
```

## Audit Logging

Track who wrote what:

```python
# Enable audit logging
avm.enable_audit_log()

# Query audit log
logs = avm.audit_log(agent_id="trader", limit=10)
for entry in logs:
    print(f"{entry.timestamp} {entry.agent_id} {entry.action} {entry.path}")
```

## Use Cases

### 1. Analyst → Trader Pipeline

```python
# Analyst does research
analyst.remember(
    "NVDA: Overbought, reduce exposure",
    namespace="signals",
    importance=0.9
)

# Trader checks signals
signals = trader.recall("trading signals", namespaces=["signals"])
```

### 2. Shared Knowledge Base

```python
# Anyone can contribute to shared knowledge
trader.remember("Stop-loss lesson learned", namespace="lessons")
analyst.remember("Pattern recognition tip", namespace="lessons")

# Anyone can recall
context = trader.recall("trading lessons", namespaces=["lessons"])
```

### 3. Read-Only Subscribers

```python
# News bot writes to shared
news_bot = avm.agent_memory("news_bot")
news_bot.remember("Fed announces...", namespace="news")

# Other agents read but can't write
# (configured via permissions)
```

## Best Practices

1. **Default to private** - Only share what needs sharing
2. **Use namespaces semantically** - `market`, `signals`, `lessons`, etc.
3. **Set importance on shared** - Help receivers prioritize
4. **Enable audit logging** - Track who wrote what
5. **Configure permissions** - Principle of least privilege
