# VFS - AI Virtual Filesystem

A config-driven virtual filesystem for AI agents to read/write structured knowledge via file paths.

## Install

```bash
pip install -e .
```

## Quick Start

```python
from vfs import VFS

vfs = VFS()

# Read/Write
vfs.write("/memory/lesson1.md", "# Trading Lesson\n\nBe cautious when RSI > 70")
node = vfs.read("/memory/lesson1.md")

# Search
results = vfs.search("RSI")

# Link nodes
vfs.link("/memory/lesson1.md", "/market/indicators/NVDA.md", "related_to")
```

## Core Features

### 1. Config-Driven

```yaml
# config.yaml
providers:
  - pattern: "/live/positions*"
    type: alpaca_positions
    ttl: 60
  - pattern: "/live/indicators/*"
    type: technical_indicators
    ttl: 300

permissions:
  - pattern: "/memory/*"
    access: rw
  - pattern: "/live/*"
    access: ro

default_access: ro
```

```python
vfs = VFS(config_path="config.yaml")
```

### 2. Linked Retrieval

Semantic search + full-text search + graph expansion:

```python
# Enable semantic search (optional)
vfs.enable_embedding(model="text-embedding-3-small")
vfs.embed_all()

# Linked retrieval
result = vfs.retrieve("NVDA risk", expand_graph=True)
for node in result.nodes:
    print(f"{result.get_source(node.path)} {node.path}")

# 🎯 /market/indicators/NVDA.md  (semantic match)
# 📝 /memory/lessons/nvda.md     (keyword match)
# 🔗 /market/indicators/AMD.md   (graph expansion)
```

### 3. Dynamic Document Synthesis

Aggregate related nodes into a structured document:

```python
doc = vfs.synthesize("NVDA risk analysis")
print(doc)
```

Output:
```markdown
# NVDA risk analysis (auto-generated)

## Technical Indicators
> 🎯 Source: `/market/indicators/NVDA.md`
RSI: 72 (overbought warning), MACD: death cross forming

## Historical Lessons
> 📝 Source: `/memory/lessons/nvda.md`
Last time RSI > 70, price dropped 15%

## Related Assets
> 🔗 Source: `/market/indicators/AMD.md`
AMD RSI: 65, correlation: 0.85
```

### 4. Agent Memory

Token-aware memory retrieval with multi-agent isolation:

```python
memory = vfs.agent_memory("akashi")

# Write memory
memory.remember(
    "Be cautious when RSI > 70, NVDA dropped 15% last time",
    importance=0.8,
    tags=["trading", "risk"]
)

# Token-aware retrieval
context = memory.recall(
    "NVDA risk",
    max_tokens=4000,
    strategy="balanced"  # importance/recency/relevance/balanced
)
print(context)
```

Output:
```markdown
## Relevant Memory (2 items, ~150 tokens)

[/memory/private/akashi/nvda_lesson.md] (0.85) Be cautious when RSI > 70, NVDA dropped 15% last time

[/memory/shared/trading/risk_rules.md] (0.72) Position size < 15%, always set stop-loss

---
*Tokens: ~150/4000 | Strategy: balanced | Query: "NVDA risk"*
```

#### Path Structure

```
/memory/private/{agent_id}/*   # Private memory
/memory/shared/{namespace}/*   # Shared space
```

#### Scoring Strategies

| Strategy | Description |
|----------|-------------|
| `importance` | By node importance (0-1) |
| `recency` | By last access time (exponential decay, half-life: 1 week) |
| `relevance` | By semantic/keyword relevance |
| `balanced` | Weighted combination (default: relevance 0.5 + importance 0.3 + recency 0.2) |

## CLI

```bash
# Read/Write
vfs read /memory/lesson1.md
vfs write /memory/lesson1.md "content"

# Search
vfs search "RSI"
vfs retrieve "NVDA risk" --depth 2

# Dynamic document
vfs synthesize "NVDA risk analysis"

# Agent Memory
vfs recall "RSI" --agent akashi --max-tokens 2000
vfs remember --agent akashi -c "lesson content" -i 0.8 --tags "trading"
vfs memory-stats --agent akashi

# Links
vfs links /memory/lesson1.md
vfs link /a.md /b.md related_to

# Management
vfs list /memory
vfs history /memory/lesson1.md
vfs refresh /live/indicators/*
vfs config
vfs stats
```

## Provider Types

| Type | Description |
|------|-------------|
| `alpaca_positions` | Alpaca positions |
| `alpaca_orders` | Alpaca orders |
| `technical_indicators` | Technical indicators (Yahoo Finance) |
| `news` | News (RSS) |
| `watchlist` | Watchlist |
| `memory` | Local memory |
| `http_json` | Generic HTTP JSON |

### Custom Provider

```python
from vfs import VFS, register_provider_type
from vfs.providers.base import BaseProvider

class MyProvider(BaseProvider):
    def fetch(self, path: str, params: dict) -> str:
        return f"# Data for {path}\n\nCustom content here"

register_provider_type("my_provider", MyProvider)

# Use in config:
# providers:
#   - pattern: "/custom/*"
#     type: my_provider
```

## Config Examples

### Trading Bot

```yaml
# trading_bot.yaml
providers:
  - pattern: "/live/positions*"
    type: alpaca_positions
    ttl: 60
    params:
      api_key: ${ALPACA_API_KEY}
      api_secret: ${ALPACA_API_SECRET}

  - pattern: "/live/indicators/*"
    type: technical_indicators
    ttl: 300

permissions:
  - pattern: "/memory/private/*"
    access: rw
  - pattern: "/memory/shared/*"
    access: rw
  - pattern: "/live/*"
    access: ro

retrieval:
  default_max_tokens: 4000
  scoring_weights:
    importance: 0.3
    recency: 0.2
    relevance: 0.5
```

### Home Assistant

```yaml
# home_assistant.yaml
providers:
  - pattern: "/devices/*"
    type: http_json
    ttl: 30
    params:
      base_url: ${HA_URL}/api/states
      headers:
        Authorization: "Bearer ${HA_TOKEN}"

  - pattern: "/automations/*"
    type: memory
    ttl: 0

permissions:
  - pattern: "/devices/*"
    access: ro
  - pattern: "/automations/*"
    access: rw
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                      VFS API                        │
│  read() write() search() retrieve() synthesize()   │
├─────────────────────────────────────────────────────┤
│                   AgentMemory                       │
│  recall() remember() share() (token-aware)         │
├─────────────────────────────────────────────────────┤
│                    Retriever                        │
│  Semantic + FTS + Graph Expansion + Synthesis       │
├─────────────────────────────────────────────────────┤
│                   VFSConfig                         │
│  Providers / Permissions / YAML loading             │
├─────────────────────────────────────────────────────┤
│                   VFSStore                          │
│  SQLite + FTS5 + Diff Tracking                      │
├──────────────────────┬──────────────────────────────┤
│      KVGraph         │        EmbeddingStore        │
│  Adjacency List      │   Cosine Similarity Search   │
├──────────────────────┴──────────────────────────────┤
│                    Providers                        │
│  Alpaca | Indicators | News | HTTP | Memory | ...   │
└─────────────────────────────────────────────────────┘
```

## MCP Server (AI Agent Integration)

VFS can be used as an MCP server for AI agents.

### Start Server

```bash
# One MCP per bot (recommended)
vfs-mcp --user akashi --db /shared/vfs.db
vfs-mcp --user yuze --db /shared/vfs.db
```

### MCP Configuration

```yaml
# mcp_servers.yaml (per agent)
vfs-memory:
  command: vfs-mcp
  args:
    - --user
    - akashi
    - --db
    - /shared/vfs.db
```

### Available Tools

| Tool | Description |
|------|-------------|
| `vfs_recall` | Token-controlled memory retrieval |
| `vfs_remember` | Store memory with tags/importance |
| `vfs_search` | Full-text search |
| `vfs_list` | List memories by prefix |
| `vfs_read` | Read specific path |
| `vfs_tags` | Tag cloud |
| `vfs_recent` | Time-based queries |
| `vfs_stats` | Memory statistics |

### Example Usage

```json
// Retrieve context
{
  "name": "vfs_recall",
  "arguments": {
    "query": "NVDA risk",
    "max_tokens": 4000
  }
}

// Store insight
{
  "name": "vfs_remember",
  "arguments": {
    "content": "NVDA showing overbought signals",
    "tags": ["market", "nvda"],
    "importance": 0.8
  }
}
```

### Multi-Bot Architecture

```
┌─────────────────────────────────────────┐
│           OpenClaw Gateway              │
├─────────────────────────────────────────┤
│ Akashi → vfs-mcp --user akashi ─┐       │
│ Yuze   → vfs-mcp --user yuze   ─┼─→ DB  │
│ Laffey → vfs-mcp --user laffey ─┘       │
└─────────────────────────────────────────┘
```

- Each bot has its own MCP process
- Shared database for cross-bot memory
- Auth at startup, no token per request

## Linux-Style Permissions

Unix-like permission system with rwx bits, ownership, and capabilities.

### Setup

```python
vfs.init_permissions({
    "users": {
        "akashi": {
            "groups": ["trading", "admin"],
            "capabilities": ["search_all", "write", "delete", "sudo"]
        },
        "yuze": {
            "groups": ["secretary"],
            "capabilities": ["search_own", "write"]
        },
        "guest": {
            "groups": [],
            "capabilities": []
        }
    }
})
```

### Node Ownership

```python
from vfs import NodeOwnership, mode_to_string

# Each node has owner, group, and mode
ownership = NodeOwnership(
    owner="akashi",
    group="trading",
    mode=0o750  # rwxr-x---
)

print(mode_to_string(0o750))  # "rwxr-x---"
```

### Permission Checks

```python
akashi = vfs.get_user("akashi")
yuze = vfs.get_user("yuze")

# Check permissions
ownership.can_read(akashi)   # True (owner)
ownership.can_write(akashi)  # True (owner has w)
ownership.can_read(yuze)     # False (not in group, other has ---)
```

### Capabilities

| Capability | Description |
|------------|-------------|
| `CAP_ADMIN` | Full system access |
| `CAP_SEARCH_ALL` | Search any path |
| `CAP_SEARCH_OWN` | Search only own paths |
| `CAP_WRITE` | Write to allowed paths |
| `CAP_DELETE` | Delete files |
| `CAP_SHARE` | Share with others |
| `CAP_SUDO` | Temporary privilege elevation |

### Sudo

```python
# Temporarily elevate privileges
akashi = vfs.get_user("akashi")
vfs.sudo(akashi, duration_minutes=5)
```

### API Keys (for Skills)

```python
# Create scoped API key for skill authentication
key = vfs.create_api_key(
    user=akashi,
    paths=["/memory/shared/*"],
    actions=["read", "write"],
    expires_days=30
)

# Authenticate in skill
user = vfs.authenticate(key)
if user:
    # Proceed with user's permissions
    pass
```

## Versions

- **v0.7.0** - Linux-style permissions (rwx, ownership, capabilities, API keys)
- **v0.6.0** - Advanced features (10 features including sync, tags, export)
- **v0.5.0** - Multi-agent support (append-only, audit log)
- **v0.4.0** - Agent Memory (token-aware recall)
- **v0.3.0** - Linked Retrieval + Document Synthesis
- **v0.2.0** - Config-driven providers/permissions
- **v0.1.0** - Core VFS (read/write/search/links)

## License

MIT
