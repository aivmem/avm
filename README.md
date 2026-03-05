# AVM - AI Virtual Memory

A config-driven virtual filesystem for AI agents to read/write structured knowledge.

## Features

- **FUSE Mount** - Mount as filesystem, use `ls`, `cat`, `echo`
- **Virtual Nodes** - Access metadata via `:meta`, `:links`, `:tags`
- **MCP Server** - Integrate with AI agents via MCP protocol
- **Agent Memory** - Token-aware recall with scoring strategies
- **Multi-Agent** - Permissions, quotas, audit logging
- **Full-Text Search** - FTS5 with semantic search support

## Install

```bash
pip install -e .

# For FUSE mount (optional)
pip install fusepy
# macOS: brew install macfuse
# Linux: apt install fuse3
```

## Quick Start

### Python API

```python
from vfs import VFS

vfs = VFS()

# Read/Write
vfs.write("/memory/lesson.md", "# Trading Lesson\n\nRSI > 70 = overbought")
node = vfs.read("/memory/lesson.md")

# Search
results = vfs.search("RSI")

# Agent Memory
mem = vfs.agent_memory("akashi")
mem.remember("NVDA showing weakness", tags=["market", "nvda"])
context = mem.recall("NVDA risk", max_tokens=4000)
```

### CLI

```bash
# Read/Write
avm read /memory/lesson.md
avm write /memory/lesson.md --content "New lesson"

# Search
avm search "RSI"

# Agent Memory
avm recall "NVDA risk" --agent akashi --max-tokens 4000
```

### FUSE Mount

```bash
# Mount
avm-mount /mnt/avm --user akashi

# Use standard shell commands
ls /mnt/avm/memory/
cat /mnt/avm/memory/lesson.md
echo "New insight" >> /mnt/avm/memory/log.md

# Virtual nodes
cat /mnt/avm/memory/lesson.md:meta      # Metadata (JSON)
cat /mnt/avm/memory/lesson.md:links     # Related nodes
cat /mnt/avm/memory/lesson.md:tags      # Tags
cat /mnt/avm/memory/:list               # Directory listing
cat "/mnt/avm/memory/:search?q=RSI"     # Search
cat "/mnt/avm/memory/:recall?q=NVDA"    # Token-aware recall

# Write metadata
echo "market,trading" > /mnt/avm/memory/lesson.md:tags
```

### MCP Server

```bash
# Start MCP server
avm-mcp --user akashi
```

```yaml
# mcp_servers.yaml
avm-memory:
  command: avm-mcp
  args: ["--user", "akashi"]
```

**MCP Tools:**

| Tool | Description |
|------|-------------|
| `vfs_recall` | Token-controlled memory retrieval |
| `vfs_browse` | Get paths + summaries (two-phase) |
| `vfs_fetch` | Get full content of selected paths |
| `vfs_remember` | Store memory with tags/importance |
| `vfs_search` | Full-text search |
| `vfs_list` | List by prefix |
| `vfs_read` | Read specific path |
| `vfs_tags` | Tag cloud |
| `vfs_recent` | Time-based queries |
| `vfs_stats` | Statistics |

## Configuration

```yaml
# config.yaml
providers:
  # HTTP API
  - pattern: "/live/prices/{symbol}"
    handler: http
    config:
      url: "https://api.example.com/prices/${symbol}"
      headers:
        Authorization: "Bearer ${API_KEY}"
    ttl: 60

  # Script
  - pattern: "/system/status"
    handler: script
    config:
      command: "uptime"

  # Plugin
  - pattern: "/live/indicators/*"
    handler: plugin
    config:
      plugin: "my_plugins.talib"

permissions:
  - pattern: "/memory/*"
    access: rw
  - pattern: "/live/*"
    access: ro

default_access: ro
```

### Handlers

| Handler | Description |
|---------|-------------|
| `file` | Local filesystem |
| `http` | REST API calls |
| `script` | Execute commands |
| `plugin` | Python plugins |
| `sqlite` | Database queries |

### Custom Handlers

```python
from vfs import BaseHandler, register_handler

class RedisHandler(BaseHandler):
    def read(self, path, context):
        return self.redis.get(path)

register_handler('redis', RedisHandler)
```

## Virtual Nodes

Access metadata via special suffixes:

| Suffix | Read | Write |
|--------|------|-------|
| `:meta` | JSON metadata | Update metadata |
| `:links` | Related nodes | Add links |
| `:tags` | Tags | Set tags |
| `:history` | Change history | - |
| `:list` | Directory listing | - |
| `:stats` | Statistics | - |
| `:search?q=` | Search results | - |
| `:recall?q=` | Token-aware recall | - |

## Two-Phase Retrieval

For large result sets, use two-phase retrieval to save tokens:

```bash
# Phase 1: Get paths + summaries (~200 tokens)
cat "/mnt/avm/memory/:search?q=NVDA"
# → [0.85] /memory/market/NVDA.md
# →     RSI超买警告...
# → [0.72] /memory/lessons/nvda_q4.md
# →     Q4财报后跌15%...

# Phase 2: Get selected content (~300 tokens)
cat /mnt/avm/memory/market/NVDA.md

# Total: 500 tokens vs 2000 tokens (75% saved)
```

## Linux-Style Permissions

```python
vfs.init_permissions({
    "users": {
        "akashi": {
            "groups": ["trading", "admin"],
            "capabilities": ["search_all", "write", "sudo"]
        },
        "guest": {
            "groups": [],
            "capabilities": []
        }
    }
})

# Check permissions
user = vfs.get_user("akashi")
vfs.check_permission(user, "/memory/private/akashi/note.md", "write")

# API keys for skills
key = vfs.create_api_key(user, paths=["/memory/*"], actions=["read"])
```

## Multi-Bot Architecture

```
┌─────────────────────────────────────────┐
│           Application                   │
├─────────────────────────────────────────┤
│ Akashi → avm-mcp --user akashi ─┐       │
│ Yuze   → avm-mcp --user yuze   ─┼─→ DB  │
│ Laffey → avm-mcp --user laffey ─┘       │
└─────────────────────────────────────────┘
```

- Each bot has its own MCP process
- Shared database for cross-bot memory
- Auth at startup, no token per request

## Database

Default location: `~/.local/share/vfs/vfs.db`

Override:
```bash
avm --db /path/to/custom.db read /memory/note.md
XDG_DATA_HOME=/custom/path avm read /memory/note.md
```

## Versions

- **v0.9.0** - Rename to AVM, FUSE mount with virtual nodes
- **v0.8.0** - Two-phase retrieval (browse + fetch)
- **v0.7.0** - Linux-style permissions, MCP server
- **v0.6.0** - Advanced features (sync, tags, export)
- **v0.5.0** - Multi-agent support
- **v0.4.0** - Agent Memory (token-aware recall)
- **v0.3.0** - Linked Retrieval + Document Synthesis
- **v0.2.0** - Config-driven providers/permissions
- **v0.1.0** - Core VFS

## License

MIT
