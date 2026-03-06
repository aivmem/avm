# Knowledge Graph

AVM supports linking memories to create a knowledge graph. This enables:
- Discovering related content
- Following chains of reasoning
- Multi-hop exploration

## Creating Links

```python
from avm import AVM
from avm.graph import EdgeType

avm = AVM()

# Write some memories
avm.write("/memory/market/nvda.md", "NVDA analysis...")
avm.write("/memory/market/amd.md", "AMD analysis...")
avm.write("/memory/lessons/chips.md", "Chip sector lessons...")

# Link related content
avm.link(
    "/memory/market/nvda.md",
    "/memory/market/amd.md",
    EdgeType.PEER           # Same-level relationship
)

avm.link(
    "/memory/market/nvda.md",
    "/memory/lessons/chips.md",
    EdgeType.DERIVED        # This was derived from that
)
```

## Edge Types

| Type | Meaning | Example |
|------|---------|---------|
| `RELATED` | General relationship | Analysis → Related analysis |
| `PEER` | Same level/category | NVDA ↔ AMD (both chip stocks) |
| `PARENT` | Hierarchical | Sector → Individual stock |
| `CITATION` | References | Report → Source data |
| `DERIVED` | Derived from | Signal → Indicator it came from |

## Querying Links

```python
# Get all links from a node
edges = avm.links("/memory/market/nvda.md")
for edge in edges:
    print(f"{edge.source} --[{edge.edge_type}]--> {edge.target}")

# With agent memory - explore via graph
trader = avm.agent_memory("trader")
result = trader.explore("/memory/market/nvda.md", depth=2)
print(result)
# ## Starting from: nvda.md
# ### Hop 1:
#   [peer] /memory/market/amd.md
#   [derived] /memory/lessons/chips.md
# ### Hop 2:
#   [related] /memory/macro/rates.md
```

## Graph Traversal

```python
from avm.graph import KVGraph

# Load the full graph
graph = avm.store.load_graph()

# Find path between nodes
path = graph.find_path(
    "/memory/market/nvda.md",
    "/memory/lessons/risk.md"
)
# ['/memory/market/nvda.md', '/memory/lessons/chips.md', '/memory/lessons/risk.md']

# Get subgraph around a node
subgraph = graph.subgraph("/memory/market/nvda.md", depth=2)
```

## Use Cases

### 1. Derived Memories

When an agent derives a conclusion from sources:

```python
trader.remember(
    "Chip sector showing weakness across the board",
    title="chip_weakness",
    derived_from=[
        "/memory/market/nvda.md",
        "/memory/market/amd.md",
        "/memory/market/intc.md"
    ]
)
```

### 2. Citation Chains

Track where information came from:

```python
# Original source
avm.write("/memory/data/q4_earnings.md", "Q4 earnings data...")

# Analysis citing the source
avm.write("/memory/analysis/nvda_q4.md", "NVDA Q4 analysis...")
avm.link(
    "/memory/analysis/nvda_q4.md",
    "/memory/data/q4_earnings.md",
    EdgeType.CITATION
)
```

### 3. Hierarchical Knowledge

Organize by topic hierarchy:

```python
# Parent topic
avm.write("/memory/topics/technical.md", "Technical analysis...")

# Child topics
avm.write("/memory/topics/rsi.md", "RSI indicator...")
avm.write("/memory/topics/macd.md", "MACD indicator...")

avm.link("/memory/topics/rsi.md", "/memory/topics/technical.md", EdgeType.PARENT)
avm.link("/memory/topics/macd.md", "/memory/topics/technical.md", EdgeType.PARENT)
```

## FUSE Access

Via filesystem mount:

```bash
# Read links
cat /mnt/avm/memory/market/nvda.md:links
# [{"target": "/memory/market/amd.md", "type": "peer"}, ...]

# Add a link
echo "/memory/lessons/risk.md:related" >> /mnt/avm/memory/market/nvda.md:links
```

## Best Practices

1. **Use appropriate edge types** - Makes traversal meaningful
2. **Link during creation** - Easier than retroactively linking
3. **Don't over-link** - Quality over quantity
4. **Use `explore()`** - For discovery when you're lost
