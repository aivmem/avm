# Changelog

All notable changes to AVM will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-03-09

### Added
- **Tell System**: Cross-agent messaging for important notifications
  - Priority levels: `urgent` (inject into next read), `normal`, `low`
  - Broadcast to all agents via `@all`
  - Automatic injection of urgent messages into file reads
  - `/:inbox` virtual file to view all messages
  - `/tell/<agent>` path for sending messages
  - Expiration support and read tracking
- **Hook System**: Notifications when tells are sent
  - Shell hooks: Execute command on tell
  - HTTP hooks: POST to webhook URL
  - OpenClaw hooks: Send via sessions_send
  - Config-driven via `hooks.yaml`
- **Virtual Hook Files**: Configure hooks via filesystem
  - `/hooks/<agent>` - Read/write hook configuration
  - `/hooks/:list` - List all registered hooks
  - `rm /hooks/<agent>` - Delete a hook
  - Format: `type:target?enabled=true&timeout=10`
- 35 new tests for tell + hook functionality (227 total)

### Usage
```bash
# Send a tell (as akashi)
echo "DB schema changed" > avm/tell/kearsarge?priority=urgent
echo "Team meeting" > avm/tell/@all

# Read inbox
cat avm/:inbox

# Mark all as read
cat avm/:inbox?mark=read
```

### Hook Config Example
```yaml
hooks:
  kearsarge:
    on_tell:
      type: shell
      target: "openclaw notify kearsarge"
  yuze:
    on_tell:
      type: http
      target: "http://localhost:3000/webhook"
```

## [1.0.0] - 2026-03-06

### Added
- **Index Handler**: Structured project indexing with status tracking
  - Code signature extraction (Python, JS, Go, Rust)
  - Watch mode for auto-updates
  - Status tracking: clean/dirty/missing
- **Config Handler**: Agent-writable configuration
  - Layered config: defaults → user → runtime
  - `/.config/` for settings, `/.meta/` for system info
- **Duplicate Detection**: Write-time similarity check
  - `RememberResult` with `similar` field
  - Jaccard word overlap with FTS candidate retrieval
- **Mount Daemon**: Background FUSE mount management
  - `avm-mount --daemon`, `stop`, `status`, `restart`

### Changed
- 69 tests (13 new handler tests)
- Benchmark results: 89% token savings

## [0.9.0] - 2026-03-05

### Added
- **FUSE Mount**: Mount AVM as a filesystem with `avm-mount`
- **Virtual Nodes**: Access metadata via `:meta`, `:links`, `:tags`, `:search`, `:recall`
- **Renamed**: Project renamed from VFS to AVM
- **CLI**: New commands `avm`, `avm-mcp`, `avm-mount`

### Changed
- Package renamed from `vfs` to `avm`
- Default DB path: `~/.local/share/avm/avm.db` (XDG standard)

## [0.8.0] - 2026-03-05

### Added
- **Two-pe retrieval**: `avm_browse` + `avm_fetch` for token efficiency
- 75% token savings on large result sets

## [0.7.0] - 2026-03-05

### Added
- **MCP Server**: 10 tools for AI agent integration
- **Linux-style permissions**: rwx bits, ownership, capabilities
- **API key authentication** for skills

## [0.6.0] - 2026-03-05

### Added
- Advanced features: subscriptions, decay, compaction
- Semantic deduplication
- Derived links
- Time queries
- Tag system
- Access statistics
- Export/import (JSONL, Markdown)
- Snapshots
- Sync to directory

## [0.5.0] - 2026-03-05

### Added
- Multi-agent support
- Append-only versioning
- Audit logging
- Quota enforcement
- Namespace permissions

## [0.4.0] - 2026-03-05

### Added
- Agent Memory with token-aware recall
- Scoring strategies (balanced, importance, recency, relevance)
- Compact markdown synthesis

## [0.3.0] - 2026-03-05

### Added
- Linked retrieval
- Document synthesis
- Semantic + FTS + graph expansion

## [0.2.0] - 2026-03-05

### Added
- Config-driven architecture
- YAML configuration
- Pluggable handlers

## [0.1.0] - 2026-03-05

### Added
- Core AVM functionality
- SQLite storage with FTS5
- Knowledge graph (edges)
- Read/write/search/link operations
