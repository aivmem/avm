# Changelog

All notable changes to AVM will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
