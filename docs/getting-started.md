# Getting Started with AVM

## Installation

```bash
pip install -e .

# Optional: FUSE mount support
pip install fusepy
# macOS: brew install macfuse
# Linux: apt install fuse3
```

## Your First Memory

```python
from avm import AVM

# Create AVM instance
avm = AVM()

# Write a memory
avm.write("/memory/notes/hello.md", """
# Hello AVM

This is my first memory!
""")

# Read it back
node = avm.read("/memory/notes/hello.md")
print(node.content)

# Search
results = avm.search("hello")
for node, score in results:
    print(f"{score:.2f} {node.path}")
```

## Using Agent Memory

Agent Memory provides token-aware recall for LLM context:

```python
# Create an agent
trader = avm.agent_memory("trader")

# Remember observations
trader.remember(
    "NVDA RSI at 72, showing overbought signals",
    title="nvda_observation",
    importance=0.9,
    tags=["market", "nvda", "technical"]
)

trader.remember(
    "Fed meeting tomorrow, expect volatility",
    title="macro_alert",
    importance=0.8,
    tags=["macro", "fed"]
)

# Recall with token budget
context = trader.recall("NVDA risk", max_tokens=500)
print(context)
# Output: Relevant memories formatted for LLM context
```

## Navigation (When You Forget)

```python
# Don't know what's in memory? Start here:
trader.topics()
# Shows: technical: 5, macro: 3, lessons: 2

# Browse the tree
trader.browse("/memory", depth=2)
# Shows: 📁 private/trader (8 items)

# View recent activity
trader.timeline(days=7)
# Shows: [Mon 14:30] nvda_observation...

# Follow knowledge graph links
trader.explore("/memory/private/trader/nvda.md", depth=2)
# Shows: Hop 1: [related] macd_analysis.md
```

## CLI Usage

```bash
# Write
avm write /memory/lesson.md --content "Always use stop-loss"

# Read  
avm read /memory/lesson.md

# Search
avm search "stop-loss"

# Agent recall
avm recall "risk management" --agent trader --max-tokens 1000
```

## FUSE Mount

Mount AVM as a filesystem:

```bash
avm-mount /mnt/avm --user trader
```

Then use standard tools:

```bash
ls /mnt/avm/memory/
cat /mnt/avm/memory/lesson.md
echo "New insight" >> /mnt/avm/memory/log.md

# Virtual nodes
cat /mnt/avm/memory/lesson.md:meta   # JSON metadata
cat /mnt/avm/memory/:search?q=RSI    # Search
```

## MCP Server

For AI agent integration:

```bash
avm-mcp --user trader
```

Configure in your MCP client:
```yaml
avm-memory:
  command: avm-mcp
  args: ["--user", "trader"]
```

## Next Steps

- [Agent Memory Guide](./agent-memory.md)
- [Knowledge Graph](./knowledge-graph.md)
- [Multi-Agent Setup](./multi-agent.md)
- [Configuration](./configuration.md)
