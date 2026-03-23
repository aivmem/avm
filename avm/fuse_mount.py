#!/usr/bin/env python3
"""
vfs/fuse_mount.py - FUSE Mount for AVM

Mount AVM as a filesystem with virtual nodes for metadata access.

Usage:
    avm-mount /mnt/avm --user akashi
    avm-mount /mnt/avm --db /path/to/vfs.db

Virtual Nodes:
    /path/to/node.md       - File content
    /path/to/node.md:meta  - Metadata (JSON)
    /path/to/node.md:links - Related nodes
    /path/to/node.md:tags  - Tags
    /path/to/node.md:history - Change history
    /path/to/:list         - Directory listing
    /path/to/:search?q=X   - Search results
    /path/to/:recall?q=X   - Token-aware recall
    /path/to/:stats        - Statistics
"""

import os
import stat
import errno
import json
import argparse
import re
import sqlite3
from datetime import datetime

from .utils import utcnow
from typing import Optional, Dict, Any
from pathlib import Path

try:
    import fuse as _fuse_module
    from fuse import FUSE, FuseOSError, Operations
    HAS_FUSE = True
    
    # Monkey-patch fusepy for Python 3.13+ compatibility
    # The original code has `self.__critical_exception = e` in a context
    # where `self` is not defined (inside functools.partial callback)
    import sys
    if sys.version_info >= (3, 13):
        import functools
        _original_wrapper = _fuse_module.FUSE._wrapper
        @functools.wraps(_original_wrapper)
        def _patched_wrapper(self, func, *args, **kwargs):
            try:
                return func(*args, **kwargs) or 0
            except OSError as e:
                if e.errno and e.errno > 0:
                    return -e.errno
                # Silently ignore exceptions without errno (e.g., PermissionError)
                return -errno.EINVAL
            except Exception:
                return -errno.EINVAL
        _fuse_module.FUSE._wrapper = _patched_wrapper
        
except (ImportError, OSError):
    # ImportError: fusepy not installed
    # OSError: libfuse not found (common in CI environments)
    HAS_FUSE = False
    FUSE = None
    # Stub for when fuse is not installed
    class Operations:
        pass
    class FuseOSError(Exception):
        pass


class AVMFuse(Operations):
    """
    FUSE operations for AVM filesystem.
    
    Supports virtual nodes via special suffixes:
    - :meta, :links, :tags, :history (per-file)
    - :list, :search, :recall, :stats (per-directory)
    """
    
    # Virtual node suffixes
    VIRTUAL_SUFFIXES = {':meta', ':links', ':tags', ':history', ':shared', ':data', ':info', ':path', ':ttl', ':delta', ':mark'}
    VIRTUAL_DIR_FILES = {':list', ':stats', ':inbox', ':topics'}
    VIRTUAL_QUERY_PATTERNS = {':search', ':recall', ':changes'}
    
    def __init__(self, vfs, user=None):
        self.vfs = vfs
        self.user = user
        self.fd = 0
        self._open_files: Dict[int, str] = {}
        self._write_buffers: Dict[int, bytes] = {}
        self._tell_store = None  # Lazy init
    
    def _get_tell_store(self):
        """Lazy initialization of TellStore"""
        if self._tell_store is None:
            from .tell import TellStore
            self._tell_store = TellStore(self.vfs.store.db_path)
        return self._tell_store
    
    def _get_hook_manager(self):
        """Get or create HookManager with DB persistence"""
        from .tell import HookManager, get_hook_manager, set_hook_manager
        manager = get_hook_manager()
        # Ensure it has DB path for persistence
        if manager._db_path is None:
            manager = HookManager(db_path=self.vfs.store.db_path)
            set_hook_manager(manager)
        return manager
    
    def _parse_path(self, path: str) -> tuple:
        """
        Parse path into (real_path, virtual_suffix, query_params).
        
        Examples:
            /memory/note.md -> ('/memory/note.md', None, None)
            /memory/note.md:meta -> ('/memory/note.md', ':meta', None)
            /memory/:search?q=RSI -> ('/memory', ':search', {'q': 'RSI'})
            /@abc -> resolved shortcut path
        """
        # Handle shortcut (@xxx) - check if any path component starts with @
        # e.g., /@abc or /memory/private/@abc
        # If path ends with @xxx/, resolve to parent directory
        parts = path.split('/')
        for i, part in enumerate(parts):
            if part.startswith('@') and len(part) > 1:
                shortcut = part[1:]  # Remove @
                # Check for suffix on shortcut (e.g., @abc:meta)
                suffix_part = None
                for suffix in self.VIRTUAL_SUFFIXES:
                    if shortcut.endswith(suffix):
                        suffix_part = suffix
                        shortcut = shortcut[:-len(suffix)]
                        break
                # Resolve shortcut to real path
                real_path = self._resolve_shortcut(shortcut)
                if real_path:
                    return (real_path, suffix_part, None)
                # Shortcut not found - return as-is for error handling
                return (path, None, None)
        
        # Check for query params
        if '?' in path:
            base, query_str = path.split('?', 1)
            params = {}
            for part in query_str.split('&'):
                if '=' in part:
                    k, v = part.split('=', 1)
                    params[k] = v
        else:
            base = path
            params = None
        
        # Check for virtual suffix (colon-prefixed, e.g., :meta)
        for suffix in self.VIRTUAL_SUFFIXES | self.VIRTUAL_DIR_FILES | self.VIRTUAL_QUERY_PATTERNS:
            if base.endswith(suffix):
                real_path = base[:-len(suffix)]
                if real_path.endswith('/'):
                    real_path = real_path[:-1]
                return (real_path or '/', suffix, params)
        
        return (base, None, params)
    
    def _is_virtual(self, path: str) -> bool:
        """Check if path is a virtual node."""
        _, suffix, _ = self._parse_path(path)
        return suffix is not None
    
    def _resolve_shortcut(self, shortcut: str) -> str:
        """Resolve shortcut to real path."""
        # Search for node with this shortcut in meta
        nodes = self.vfs.store.list_nodes("/memory", limit=1000)
        for node in nodes:
            if node.meta.get('shortcut') == shortcut:
                return node.path
        return None
    
    def _generate_shortcut(self, path: str) -> str:
        """Generate a unique shortcut for a path."""
        import hashlib
        # Use hash of path for consistent shortcuts
        h = hashlib.md5(path.encode()).hexdigest()[:3]
        # Check for collision
        existing = self._resolve_shortcut(h)
        if existing and existing != path:
            # Collision - extend hash
            h = hashlib.md5(path.encode()).hexdigest()[:4]
        return h
    
    def _can_see_shared(self, node) -> bool:
        """Check if current agent can see this shared node."""
        if not self.user:
            return True  # Admin mode
        
        # Only filter /memory/shared/ paths
        if not node.path.startswith("/memory/shared/"):
            return True
        
        # Check shared_with in metadata
        shared_with = node.meta.get("shared_with", [])
        
        # Empty or contains "all" = everyone can see
        if not shared_with or "all" in shared_with:
            return True
        
        return self.user in shared_with
    
    def _get_virtual_content(self, real_path: str, suffix: str, params: dict, update_markers: bool = True) -> str:
        """Generate content for virtual nodes."""
        
        if suffix == ':data':
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            return node.content or ''
        
        if suffix == ':path':
            # Return path relative to mount point (without leading /)
            rel_path = real_path.lstrip('/')
            return f"{rel_path}\n"
        
        if suffix == ':delta':
            # Return diff since last read by this agent (read-only, doesn't update marker)
            if not self.user:
                return '(no agent context)\n'
            
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            
            current_version = node.version
            last_read = node.meta.get('last_read', {})
            last_version = last_read.get(self.user, 0)
            
            if last_version == 0:
                # First read - return full content
                if update_markers:
                    last_read[self.user] = current_version
                    node.meta['last_read'] = last_read
                    self.vfs.store.put_node(node, save_diff=False)
                return f'# (first read, full content)\n{node.content or ""}\n'
            
            if last_version >= current_version:
                return '(no changes)\n'  # Already up to date, no marker update needed
            
            # Get diffs from last_version to current
            history = self.vfs.history(real_path, limit=100)
            
            # Collect diffs for versions > last_version
            diffs = []
            for h in reversed(history):  # oldest first
                if h.version > last_version:
                    if h.diff_content and h.change_type == 'update':
                        diffs.append(f"# v{h.version} ({h.changed_at.strftime('%Y-%m-%d %H:%M')})\n{h.diff_content}")
            
            if not diffs:
                result = f'(changed but no diff, v{last_version}→v{current_version})\n'
            else:
                result = '\n'.join(diffs) + '\n'
            
            # Auto-mark as read after showing delta
            if update_markers:
                last_read[self.user] = current_version
                node.meta['last_read'] = last_read
                self.vfs.store.put_node(node, save_diff=False)
            
            return result
        
        if suffix == ':mark':
            # Show current read marker for this agent
            if not self.user:
                return '(no agent context)\n'
            
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            
            last_read = node.meta.get('last_read', {})
            last_version = last_read.get(self.user, 0)
            current_version = node.version
            
            return f'marked: v{last_version}, current: v{current_version}\n'
        
        if suffix == ':ttl':
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            expires_at = node.meta.get('expires_at')
            if not expires_at:
                return 'never\n'
            from datetime import datetime
            try:
                exp_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                remaining = exp_dt - utcnow()
                if remaining.total_seconds() <= 0:
                    return 'expired\n'
                # Format as human readable
                mins = int(remaining.total_seconds() / 60)
                if mins < 60:
                    return f'{mins}m\n'
                hours = mins // 60
                if hours < 24:
                    return f'{hours}h {mins % 60}m\n'
                days = hours // 24
                return f'{days}d {hours % 24}h\n'
            except (ValueError, TypeError):
                return 'invalid\n'
        
        if suffix == ':info':
            # List available virtual suffixes for this file
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            
            suffixes = [':data']
            if node.meta:
                suffixes.append(':meta')
            try:
                links = self.vfs.links(real_path, direction="both")
                if links:
                    suffixes.append(':links')
            except Exception:
                pass
            if node.meta.get('tags'):
                suffixes.append(':tags')
            if 'shared_with' in node.meta:
                suffixes.append(':shared')
            
            return '\n'.join(suffixes) + '\n'
        
        if suffix == ':meta':
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            return json.dumps(node.meta, indent=2, default=str) + '\n'
        
        elif suffix == ':links':
            try:
                edges = self.vfs.links(real_path, direction="both")
                lines = []
                for edge in edges:
                    target = edge.get('target') or edge.get('source', '?')
                    rel_type = edge.get('type', 'related')
                    lines.append(f"{target} ({rel_type})")
                return '\n'.join(lines) + '\n' if lines else '(no links)\n'
            except Exception:
                return '(no links)\n'
        
        elif suffix == ':tags':
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            tags = node.meta.get('tags', [])
            return ','.join(tags) + '\n' if tags else '\n'
        
        elif suffix == ':shared':
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            shared_with = node.meta.get('shared_with', [])
            if not shared_with:
                return 'all\n'
            return ','.join(shared_with) + '\n'
        
        elif suffix == ':history':
            history = self.vfs.history(real_path, limit=10)
            lines = []
            for h in history:
                ts = h.changed_at.strftime('%Y-%m-%d %H:%M') if h.changed_at else '?'
                change = h.change_type or 'update'
                ver = f"v{h.version}" if h.version else ''
                lines.append(f"[{ts}] {change} {ver}")
            return '\n'.join(lines) + '\n' if lines else '(no history)\n'
        
        elif suffix == ':list':
            limit = int(params.get('limit', 50)) if params else 50
            offset = int(params.get('offset', 0)) if params else 0
            query = params.get('q', '') if params else ''
            
            tag_filter = params.get('tag', '') if params else ''
            
            if query:
                # Search mode: use full-text search
                results = self.vfs.search(query, limit=(limit + offset) * 5)
                nodes = [node for node, score in results]
            else:
                # List mode: get nodes from path
                nodes = self.vfs.list(real_path, limit=(limit + offset) * 5)
            
            # Filter by tag if specified
            if tag_filter:
                nodes = [n for n in nodes 
                        if tag_filter in n.meta.get('tags', [])]
            lines = []
            skipped = 0
            for node in nodes:
                # Filter by access permission first
                if not self._can_see_shared(node):
                    continue
                # Then apply offset
                if skipped < offset:
                    skipped += 1
                    continue
                # Stop at limit
                if len(lines) >= limit:
                    break
                # Get or generate shortcut
                shortcut = node.meta.get('shortcut')
                if not shortcut:
                    shortcut = self._generate_shortcut(node.path)
                    # Store shortcut in meta
                    node.meta['shortcut'] = shortcut
                    self.vfs.write(node.path, node.content, meta=node.meta)
                # Get filename (truncate if too long)
                filename = node.path.split('/')[-1]
                if len(filename) > 30:
                    filename = filename[:27] + '...'
                # Generate summary (first line, skip headers)
                content = node.content or ''
                summary = content.lstrip('#').strip()
                first_line = summary.split('\n')[0][:40]
                if len(summary.split('\n')[0]) > 40:
                    first_line += '...'
                lines.append(f"@{shortcut}  {filename}  {first_line}")
            return '\n'.join(lines) + '\n' if lines else '\n'
        
        elif suffix == ':stats':
            stats = self.vfs.stats()
            return json.dumps(stats, indent=2, default=str) + '\n'
        
        elif suffix == ':inbox':
            # Show all tells for this agent
            if not self.user:
                return '(no agent context)\n'
            try:
                tell_store = self._get_tell_store()
                tells = tell_store.get_all(self.user, limit=50)
                
                # Check for mark=read param
                if params and params.get('mark') == 'read':
                    tell_store.mark_all_read(self.user)
                    return f'Marked {len([t for t in tells if not t.read_at])} messages as read.\n'
                
                from .tell import format_inbox
                return format_inbox(tells, show_read=True)
            except Exception as e:
                return f'(tell system error: {e})\n'
        
        elif suffix == ':search':
            query = params.get('q', '') if params else ''
            limit = int(params.get('limit', 10)) if params else 10
            # Use embedding + FTS hybrid when embedding is available
            es = getattr(self.vfs, '_embedding_store', None)
            if es is not None:
                sem_results = es.search(query, k=limit)
                fts_results = self.vfs.search(query, limit=limit)
                # Merge: embedding results first, then FTS results not already seen
                seen = set()
                merged = []
                for node, score in sem_results:
                    seen.add(node.path)
                    merged.append((node, score))
                for node, score in fts_results:
                    if node.path not in seen:
                        merged.append((node, score))
                results = merged[:limit]
            else:
                results = self.vfs.search(query, limit=limit)
            lines = []
            for node, score in results:
                lines.append(f"[{score:.2f}] {node.path}")
            return '\n'.join(lines) + '\n' if lines else '(no results)\n'
        
        elif suffix == ':recall':
            query = params.get('q', '') if params else ''
            max_tokens = int(params.get('max_tokens', 4000)) if params else 4000
            if self.user:
                memory = self.vfs.agent_memory(self.user)
                return memory.recall(query, max_tokens=max_tokens)
            else:
                return '(no user context for recall)\n'
        
        elif suffix == ':cold':
            # Show cold (decayed) memories
            from .advanced import MemoryDecay
            threshold = float(params.get('threshold', 0.3)) if params else 0.3
            half_life = float(params.get('half_life', 7.0)) if params else 7.0
            limit = int(params.get('limit', 20)) if params else 20
            
            decay = MemoryDecay(self.vfs.store, half_life_days=half_life)
            cold = decay.get_cold_memories(prefix=real_path or '/memory', threshold=threshold, limit=limit)
            
            if not cold:
                return '(no cold memories)\n'
            
            lines = [f"# Cold memories (importance × decay < {threshold})", ""]
            for node in cold:
                importance = node.meta.get("importance", 0.5)
                decay_factor = decay.calculate_decay(node)
                score = importance * decay_factor
                lines.append(f"{node.path}")
                lines.append(f"  score={score:.3f} (imp={importance:.2f} × dec={decay_factor:.2f})")
            return '\n'.join(lines) + '\n'
        
        elif suffix == ':archive':
            # Archive cold memories (requires user context)
            if not self.user:
                return '(no agent context - archive requires user)\n'
            
            from .advanced import MemoryDecay
            threshold = float(params.get('threshold', 0.2)) if params else 0.2
            half_life = float(params.get('half_life', 7.0)) if params else 7.0
            limit = int(params.get('limit', 10)) if params else 10
            dry_run = params.get('dry_run', 'true').lower() == 'true' if params else True
            
            decay = MemoryDecay(self.vfs.store, half_life_days=half_life)
            cold = decay.get_cold_memories(prefix=real_path or '/memory', threshold=threshold, limit=limit)
            
            if not cold:
                return '(no cold memories to archive)\n'
            
            if dry_run:
                lines = [f"# Would archive {len(cold)} memories (dry_run=true)", ""]
                for node in cold:
                    archive_path = node.path.replace("/memory/", "/archive/", 1)
                    lines.append(f"{node.path} → {archive_path}")
                return '\n'.join(lines) + '\n'
            
            # Actually archive
            archived = []
            for node in cold:
                archive_path = node.path.replace("/memory/", "/archive/", 1)
                node.meta['archived_by'] = self.user
                node.meta['archived_at'] = utcnow().isoformat()
                self.vfs.write(archive_path, node.content, meta=node.meta)
                self.vfs.store.delete_node(node.path)
                archived.append((node.path, archive_path))
            
            lines = [f"# Archived {len(archived)} memories", ""]
            for src, dst in archived:
                lines.append(f"{src} → {dst}")
            return '\n'.join(lines) + '\n'
        
        elif suffix == ':decay':
            # Show decay status for a specific file
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            
            from .advanced import MemoryDecay
            half_life = float(params.get('half_life', 7.0)) if params else 7.0
            decay = MemoryDecay(self.vfs.store, half_life_days=half_life)
            
            importance = node.meta.get("importance", 0.5)
            decay_factor = decay.calculate_decay(node)
            score = importance * decay_factor
            
            lines = [
                f"path: {node.path}",
                f"importance: {importance:.2f}",
                f"decay_factor: {decay_factor:.3f}",
                f"effective_score: {score:.3f}",
                f"half_life: {half_life} days",
                f"updated_at: {node.updated_at}",
            ]
            return '\n'.join(lines) + '\n'
        
        elif suffix == ':subscriptions':
            # List subscriptions for current agent
            if not self.user:
                return '(no agent context)\n'
            
            from .subscriptions import get_subscription_store
            store = get_subscription_store()
            subs = store.list_subscriptions(agent_id=self.user)
            
            if not subs:
                return '(no subscriptions)\n'
            
            lines = ["# Subscriptions", ""]
            for s in subs:
                mode_info = s.mode.value
                if s.mode.value == "throttled":
                    mode_info += f" ({s.throttle_seconds}s)"
                lines.append(f"{s.pattern} [{mode_info}]")
            return '\n'.join(lines) + '\n'
        
        elif suffix == ':pending':
            # Show pending notifications
            if not self.user:
                return '(no agent context)\n'
            
            from .subscriptions import get_subscription_store
            store = get_subscription_store()
            
            mark = params.get('mark', '') == 'read' if params else False
            pending = store.get_pending(self.user, mark_delivered=mark)
            
            if not pending:
                return '(no pending notifications)\n'
            
            lines = [f"# Pending ({len(pending)})", ""]
            for p in pending:
                lines.append(f"[{p['timestamp'][:16]}] {p['path']}")
            if mark:
                lines.append(f"\n(marked {len(pending)} as delivered)")
            return '\n'.join(lines) + '\n'
        
        elif suffix == ':feed':
            # Show recent activity feed
            from .advanced import AccessStats
            
            limit = int(params.get('limit', 20)) if params else 20
            stats = AccessStats(self.vfs.store)
            
            # Get recent activity across all agents
            with sqlite3.connect(stats.db_path) as conn:
                rows = conn.execute("""
                    SELECT path, agent_id, access_type, timestamp
                    FROM access_log
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,)).fetchall()
            
            if not rows:
                return '(no recent activity)\n'
            
            lines = ["# Activity Feed", ""]
            for path, agent, access_type, ts in rows:
                ts_short = ts[11:16] if len(ts) > 16 else ts
                agent_display = agent or "unknown"
                lines.append(f"[{ts_short}] {agent_display} {access_type} {path}")
            return '\n'.join(lines) + '\n'
        
        elif suffix == ':changes':
            # Return recently modified files
            # :changes?since=ISO_TIMESTAMP or :changes?minutes=N
            since = params.get('since', '') if params else ''
            minutes = int(params.get('minutes', 60)) if params else 60
            limit = int(params.get('limit', 20)) if params else 20
            
            from datetime import datetime, timedelta
            
            if since:
                try:
                    since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
                except ValueError:
                    since_dt = utcnow() - timedelta(minutes=minutes)
            else:
                since_dt = utcnow() - timedelta(minutes=minutes)
            
            # Get all nodes and filter by updated_at
            nodes = self.vfs.list(real_path, limit=500)
            changed = []
            for node in nodes:
                if not self._can_see_shared(node):
                    continue
                try:
                    updated = node.updated_at
                    if updated and updated >= since_dt:
                        changed.append((node, updated))
                except (AttributeError, TypeError):
                    pass
            
            # Sort by update time (newest first)
            changed.sort(key=lambda x: x[1], reverse=True)
            
            lines = []
            for node, updated in changed[:limit]:
                shortcut = node.meta.get('shortcut', '???')
                filename = node.path.split('/')[-1]
                if len(filename) > 25:
                    filename = filename[:22] + '...'
                time_str = updated.strftime('%H:%M')
                lines.append(f"@{shortcut}  {time_str}  {filename}")
            
            if not lines:
                return '(no changes)\n'
            return '\n'.join(lines) + '\n'
        
        return ''
    
    def _set_virtual_content(self, real_path: str, suffix: str, content: str) -> bool:
        """Set content for writable virtual nodes."""
        
        if suffix == ':tags':
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            tags = [t.strip() for t in content.strip().split(',') if t.strip()]
            node.meta['tags'] = tags
            self.vfs.write(real_path, node.content, meta=node.meta)
            return True
        
        elif suffix == ':meta':
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            try:
                new_meta = json.loads(content)
                node.meta.update(new_meta)
                self.vfs.write(real_path, node.content, meta=node.meta)
                return True
            except json.JSONDecodeError:
                raise FuseOSError(errno.EINVAL)
        
        elif suffix == ':links':
            # Format: target_path relation_type
            lines = content.strip().split('\n')
            for line in lines:
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 1:
                    target = parts[0]
                    rel_type = parts[1] if len(parts) > 1 else 'related'
                    self.vfs.link(real_path, target, rel_type)
            return True
        
        elif suffix == ':mark':
            # Update read marker to current version
            if not self.user:
                raise FuseOSError(errno.EACCES)
            
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            
            last_read = node.meta.get('last_read', {})
            last_read[self.user] = node.version
            node.meta['last_read'] = last_read
            
            # Write without triggering diff (content unchanged)
            self.vfs.store.put_node(node, save_diff=False)
            return True
        
        elif suffix == ':ttl':
            # Format: Nm (minutes), Nh (hours), Nd (days), or "never"
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            
            ttl_str = content.strip().lower()
            from datetime import datetime, timedelta
            
            if ttl_str == 'never' or not ttl_str:
                if 'expires_at' in node.meta:
                    del node.meta['expires_at']
            else:
                # Parse duration
                try:
                    if ttl_str.endswith('m'):
                        minutes = int(ttl_str[:-1])
                        delta = timedelta(minutes=minutes)
                    elif ttl_str.endswith('h'):
                        hours = int(ttl_str[:-1])
                        delta = timedelta(hours=hours)
                    elif ttl_str.endswith('d'):
                        days = int(ttl_str[:-1])
                        delta = timedelta(days=days)
                    else:
                        # Assume minutes
                        delta = timedelta(minutes=int(ttl_str))
                    
                    expires_at = utcnow() + delta
                    node.meta['expires_at'] = expires_at.isoformat()
                except ValueError:
                    raise FuseOSError(errno.EINVAL)
            
            self.vfs.write(real_path, node.content, meta=node.meta)
            return True
        
        elif suffix == ':shared':
            # Format: agent1,agent2,... or "all"
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            
            # Only creator can modify shared_with
            creator = node.meta.get('created_by')
            if creator and self.user and creator != self.user:
                raise FuseOSError(errno.EACCES)
            
            agents = content.strip()
            if agents == 'all' or not agents:
                node.meta['shared_with'] = []
            else:
                node.meta['shared_with'] = [a.strip() for a in agents.split(',')]
            
            # Record creator if not set
            if not creator and self.user:
                node.meta['created_by'] = self.user
            
            self.vfs.write(real_path, node.content, meta=node.meta)
            return True
        
        return False
    
    # ─── FUSE Operations ─────────────────────────────────
    
    def getattr(self, path, fh=None):
        """Get file attributes."""
        now = datetime.now().timestamp()
        
        # Skip macOS special files
        basename = os.path.basename(path)
        if basename.startswith('._') or basename in ('.DS_Store', '.localized'):
            raise FuseOSError(errno.ENOENT)
        
        real_path, suffix, params = self._parse_path(path)
        
        # Root directory
        if path == '/':
            return {
                'st_mode': stat.S_IFDIR | 0o755,
                'st_nlink': 2,
                'st_uid': os.getuid(),
                'st_gid': os.getgid(),
                'st_atime': now,
                'st_mtime': now,
                'st_ctime': now,
            }
        
        # Virtual node
        if suffix:
            try:
                # Don't update markers in getattr (only in read)
                content = self._get_virtual_content(real_path, suffix, params, update_markers=False)
                return {
                    'st_mode': stat.S_IFREG | 0o644,
                    'st_nlink': 1,
                    'st_size': len(content.encode('utf-8')),
                    'st_uid': os.getuid(),
                    'st_gid': os.getgid(),
                    'st_atime': now,
                    'st_mtime': now,
                    'st_ctime': now,
                }
            except Exception:
                raise FuseOSError(errno.ENOENT)
        
        # Real node
        node = self.vfs.read(real_path)
        if node:
            size = len(node.content.encode('utf-8')) if node.content else 0
            mtime = now
            if 'updated_at' in node.meta:
                try:
                    mtime = datetime.fromisoformat(node.meta['updated_at'].replace('Z', '+00:00')).timestamp()
                except (ValueError, AttributeError):
                    pass
            
            return {
                'st_mode': stat.S_IFREG | 0o644,
                'st_nlink': 1,
                'st_size': size,
                'st_uid': os.getuid(),
                'st_gid': os.getgid(),
                'st_atime': now,
                'st_mtime': mtime,
                'st_ctime': mtime,
            }
        
        # Handle /tell/ paths for cross-agent messaging
        if real_path.startswith('/tell/'):
            # /tell/<agent> - writable file for sending messages
            return {
                'st_mode': stat.S_IFREG | 0o644,
                'st_nlink': 1,
                'st_size': 0,
                'st_uid': os.getuid(),
                'st_gid': os.getgid(),
                'st_atime': now,
                'st_mtime': now,
                'st_ctime': now,
            }
        
        if real_path == '/tell':
            # /tell directory
            return {
                'st_mode': stat.S_IFDIR | 0o755,
                'st_nlink': 2,
                'st_uid': os.getuid(),
                'st_gid': os.getgid(),
                'st_atime': now,
                'st_mtime': now,
                'st_ctime': now,
            }
        
        # Handle /hooks/ paths for hook configuration
        if real_path.startswith('/hooks/'):
            agent_id = real_path.split('/')[-1]
            if agent_id and agent_id != ':list':
                # /hooks/<agent> - readable/writable hook config
                manager = self._get_hook_manager()
                content = manager.format_hook(agent_id)
                return {
                    'st_mode': stat.S_IFREG | 0o644,
                    'st_nlink': 1,
                    'st_size': len(content.encode('utf-8')) if content else 0,
                    'st_uid': os.getuid(),
                    'st_gid': os.getgid(),
                    'st_atime': now,
                    'st_mtime': now,
                    'st_ctime': now,
                }
        
        if real_path == '/hooks':
            # /hooks directory
            return {
                'st_mode': stat.S_IFDIR | 0o755,
                'st_nlink': 2,
                'st_uid': os.getuid(),
                'st_gid': os.getgid(),
                'st_atime': now,
                'st_mtime': now,
                'st_ctime': now,
            }
        
        # Check if it's a directory (prefix with children)
        children = self.vfs.list(real_path, limit=1)
        if children or real_path in ('/', '/memory', '/memory/private', '/memory/shared'):
            return {
                'st_mode': stat.S_IFDIR | 0o755,
                'st_nlink': 2,
                'st_uid': os.getuid(),
                'st_gid': os.getgid(),
                'st_atime': now,
                'st_mtime': now,
                'st_ctime': now,
            }
        
        raise FuseOSError(errno.ENOENT)
    
    def opendir(self, path):
        """Open directory."""
        return 0
    
    def releasedir(self, path, fh):
        """Release directory."""
        return 0
    
    def readdir(self, path, fh):
        """List directory contents."""
        real_path, _, _ = self._parse_path(path)
        
        entries = ['.', '..']
        
        # Add virtual directory files
        entries.extend([':list', ':stats', ':inbox'])
        
        # Add /tell and /hooks directories at root
        if real_path == '/':
            entries.append('tell')
            entries.append('hooks')
        
        # List hooks in /hooks directory
        if real_path == '/hooks':
            try:
                manager = self._get_hook_manager()
                for agent_id in manager.list_hooks().keys():
                    entries.append(agent_id)
            except Exception:
                pass
        
        # Add real children
        nodes = self.vfs.list(real_path)
        seen = set()
        
        for node in nodes:
            # Filter by shared_with permission
            if not self._can_see_shared(node):
                continue
            
            # Get relative name
            if node.path.startswith(real_path):
                rel = node.path[len(real_path):].lstrip('/')
                # Only first component (immediate children)
                name = rel.split('/')[0]
                if name and name not in seen:
                    seen.add(name)
                    entries.append(name)
                    # Add virtual suffixes for files (on-demand)
                    if '.' in name:  # Likely a file
                        # :meta only if has metadata beyond system fields
                        if node.meta:
                            entries.append(f"{name}:meta")
                        # :links only if has links
                        try:
                            links = self.vfs.links(node.path, direction="both")
                            if links:
                                entries.append(f"{name}:links")
                        except Exception:
                            pass
                        # :tags only if has tags
                        if node.meta.get('tags'):
                            entries.append(f"{name}:tags")
                        # :shared only if shared_with set
                        if 'shared_with' in node.meta:
                            entries.append(f"{name}:shared")
        
        return entries
    
    def read(self, path, size, offset, fh):
        """Read file content."""
        real_path, suffix, params = self._parse_path(path)
        
        # Handle /hooks/<agent> reads
        if real_path.startswith('/hooks/'):
            agent_id = real_path.split('/')[-1]
            if agent_id == ':list':
                # List all hooks
                manager = self._get_hook_manager()
                hooks = manager.list_hooks()
                lines = ["# Registered Hooks", ""]
                for aid, hook in hooks.items():
                    lines.append(f"- {aid}: {manager.format_hook(aid)}")
                content = "\n".join(lines) + "\n" if hooks else "# No hooks registered\n"
            else:
                manager = self._get_hook_manager()
                content = manager.format_hook(agent_id)
                if not content:
                    content = "# No hook configured\n"
            encoded = content.encode('utf-8')
            return encoded[offset:offset + size]
        
        if suffix:
            content = self._get_virtual_content(real_path, suffix, params)
        else:
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            # Check shared permission
            if not self._can_see_shared(node):
                raise FuseOSError(errno.EACCES)
            # Check TTL expiration
            expires_at = node.meta.get('expires_at')
            if expires_at:
                from datetime import datetime
                try:
                    exp_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    if utcnow() >= exp_dt:
                        raise FuseOSError(errno.ENOENT)  # Expired = not found
                except (ValueError, TypeError):
                    pass
            
            # Auto-mark as read for shared files
            if self.user and '/shared/' in real_path:
                last_read = node.meta.get('last_read', {})
                if last_read.get(self.user) != node.version:
                    last_read[self.user] = node.version
                    node.meta['last_read'] = last_read
                    self.vfs.store.put_node(node, save_diff=False)
            
            content = node.content or ''
            
            # Inject urgent tells at the beginning (only on first read, offset=0)
            if offset == 0 and self.user:
                content = self._inject_urgent_tells(content)
        
        encoded = content.encode('utf-8')
        return encoded[offset:offset + size]
    
    def _inject_urgent_tells(self, content: str) -> str:
        """Inject urgent unread tells at the beginning of content"""
        try:
            tell_store = self._get_tell_store()
            urgent_tells = tell_store.get_urgent_unread(self.user)
            
            if urgent_tells:
                from .tell import format_tells_for_injection
                header = format_tells_for_injection(urgent_tells)
                
                # Mark as read after injection
                tell_store.mark_read([t.id for t in urgent_tells])
                
                return header + content
        except Exception:
            # Don't break reads if tell system fails
            pass
        
        return content
    
    def write(self, path, data, offset, fh):
        """Write to file."""
        real_path, suffix, _ = self._parse_path(path)
        
        # Buffer writes - load existing content if not already buffered
        if fh not in self._write_buffers:
            if not suffix:
                node = self.vfs.read(real_path)
                if node and node.content:
                    self._write_buffers[fh] = node.content.encode('utf-8')
                else:
                    self._write_buffers[fh] = b''
            else:
                self._write_buffers[fh] = b''
        
        # Handle offset
        buf = self._write_buffers[fh]
        if offset < len(buf):
            # Insert/overwrite at position
            buf = buf[:offset] + data + buf[offset + len(data):]
        elif offset == len(buf):
            # Append at end
            buf = buf + data
        else:
            # Gap - fill with spaces (not nulls)
            buf = buf + b' ' * (offset - len(buf)) + data
        
        self._write_buffers[fh] = buf
        return len(data)
    
    def create(self, path, mode, fi=None):
        """Create a new file."""
        # Check for reserved @ prefix
        filename = path.split('/')[-1]
        if filename.startswith('@'):
            raise FuseOSError(errno.EINVAL)  # Invalid argument - @ is reserved
        
        real_path, suffix, _ = self._parse_path(path)
        
        self.fd += 1
        self._open_files[self.fd] = path
        self._write_buffers[self.fd] = b''
        
        if not suffix:
            # Create empty node with creator metadata
            meta = {}
            if self.user:
                meta['created_by'] = self.user
            self.vfs.write(real_path, '', meta=meta)
        
        return self.fd
    
    def open(self, path, flags):
        """Open a file."""
        import os as _os
        self.fd += 1
        self._open_files[self.fd] = path
        
        # Handle O_APPEND: pre-load existing content to buffer
        if flags & _os.O_APPEND:
            real_path, suffix, _ = self._parse_path(path)
            if not suffix:
                node = self.vfs.read(real_path)
                if node and node.content:
                    self._write_buffers[self.fd] = node.content.encode('utf-8')
        
        return self.fd
    
    def release(self, path, fh):
        """Close a file and flush writes."""
        if fh in self._write_buffers and self._write_buffers[fh]:
            real_path, suffix, params = self._parse_path(path)
            content = self._write_buffers[fh].decode('utf-8', errors='replace')
            
            # Handle /tell/<agent> paths for cross-agent messaging
            if real_path.startswith('/tell/'):
                self._handle_tell_write(real_path, content, params)
            # Handle /hooks/<agent> paths for hook configuration
            elif real_path.startswith('/hooks/'):
                self._handle_hook_write(real_path, content)
            elif suffix:
                self._set_virtual_content(real_path, suffix, content)
            else:
                # Preserve existing meta or create new with creator
                existing = self.vfs.read(real_path)
                if existing:
                    meta = existing.meta
                else:
                    meta = {}
                    if self.user:
                        meta['created_by'] = self.user
                self.vfs.write(real_path, content, meta=meta)
        
        self._write_buffers.pop(fh, None)
        self._open_files.pop(fh, None)
        return 0
    
    def _handle_tell_write(self, path: str, content: str, params: dict):
        """Handle writes to /tell/<agent> paths"""
        if not self.user:
            return  # No sender context
        
        # Parse path: /tell/agentname or /tell/@all
        parts = path.strip('/').split('/')
        if len(parts) < 2:
            return
        
        to_agent = parts[1]
        
        # Parse priority from params or path
        from .tell import TellPriority
        priority_str = 'normal'
        if params:
            priority_str = params.get('priority', 'normal')
        
        try:
            priority = TellPriority(priority_str)
        except ValueError:
            priority = TellPriority.NORMAL
        
        # Parse optional expiration
        expires_at = params.get('expires') if params else None
        
        # Send the tell
        try:
            tell_store = self._get_tell_store()
            tell_store.send(
                from_agent=self.user,
                to_agent=to_agent,
                content=content.strip(),
                priority=priority,
                expires_at=expires_at
            )
        except Exception:
            pass  # Don't break writes if tell fails
    
    def _handle_hook_write(self, path: str, content: str):
        """Handle writes to /hooks/<agent> paths"""
        # Parse path: /hooks/agentname
        parts = path.strip('/').split('/')
        if len(parts) < 2:
            return
        
        agent_id = parts[1]
        content = content.strip()
        
        manager = self._get_hook_manager()
        
        if not content:
            # Empty content = delete hook
            manager.unregister(agent_id)
            return
        
        # Parse hook string
        hook = manager.parse_hook_string(content)
        if hook:
            manager.register(agent_id, hook)
    
    def truncate(self, path, length, fh=None):
        """Truncate file."""
        real_path, suffix, _ = self._parse_path(path)
        
        if suffix:
            return 0  # Virtual files don't really truncate
        
        node = self.vfs.read(real_path)
        if node:
            content = node.content[:length] if node.content else ''
            self.vfs.write(real_path, content)
        
        return 0
    
    def unlink(self, path):
        """Delete a file."""
        real_path, suffix, _ = self._parse_path(path)
        
        if suffix:
            raise FuseOSError(errno.EPERM)  # Can't delete virtual files
        
        # Handle /hooks/<agent> deletion
        if real_path.startswith('/hooks/'):
            agent_id = real_path.split('/')[-1]
            manager = self._get_hook_manager()
            manager.unregister(agent_id)
            return
        
        if not self.vfs.delete(real_path):
            raise FuseOSError(errno.ENOENT)
    
    def mkdir(self, path, mode):
        """Create directory (no-op for VFS)."""
        # VFS doesn't have real directories
        return 0
    
    def rmdir(self, path):
        """Remove directory."""
        # Check if empty
        nodes = self.vfs.list(path, limit=1)
        if nodes:
            raise FuseOSError(errno.ENOTEMPTY)
        return 0
    
    def rename(self, old, new):
        """Rename/move a file."""
        old_path, old_suffix, _ = self._parse_path(old)
        new_path, new_suffix, _ = self._parse_path(new)
        
        if old_suffix or new_suffix:
            raise FuseOSError(errno.EPERM)
        
        node = self.vfs.read(old_path)
        if not node:
            raise FuseOSError(errno.ENOENT)
        
        self.vfs.write(new_path, node.content, meta=node.meta)
        self.vfs.delete(old_path)
        return 0
    
    def chmod(self, path, mode):
        """Change permissions (no-op)."""
        return 0
    
    def chown(self, path, uid, gid):
        """Change ownership (no-op)."""
        return 0
    
    def utimens(self, path, times=None):
        """Update timestamps (no-op)."""
        return 0


import signal
import subprocess
import sys

# PID file location
def _pid_file(mountpoint: str) -> Path:
    """Get PID file path for a mountpoint."""
    safe_name = mountpoint.replace('/', '_').strip('_')
    return Path.home() / '.local' / 'share' / 'avm' / 'mounts' / f'{safe_name}.pid'


def _is_mounted(mountpoint: str) -> bool:
    """Check if mountpoint is currently mounted."""
    try:
        # Use /sbin/mount for macOS compatibility
        mount_cmd = '/sbin/mount' if os.path.exists('/sbin/mount') else 'mount'
        result = subprocess.run([mount_cmd], capture_output=True, text=True)
        # Handle /tmp -> /private/tmp symlink on macOS
        return mountpoint in result.stdout or mountpoint.replace('/tmp/', '/private/tmp/') in result.stdout
    except Exception:
        return False


def _get_pid(mountpoint: str) -> Optional[int]:
    """Get PID of mount process."""
    pid_file = _pid_file(mountpoint)
    if pid_file.exists():
        try:
            return int(pid_file.read_text().strip())
        except (ValueError, IOError):
            pass
    return None


def _write_pid(mountpoint: str, pid: int):
    """Write PID file."""
    pid_file = _pid_file(mountpoint)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(pid))


def _remove_pid(mountpoint: str):
    """Remove PID file."""
    pid_file = _pid_file(mountpoint)
    if pid_file.exists():
        pid_file.unlink()


def cmd_mount(args):
    """Mount AVM filesystem."""
    if not HAS_FUSE:
        print("Error: fusepy not installed. Run: pip install fusepy")
        print("Also ensure FUSE is installed:")
        print("  macOS: brew install macfuse")
        print("  Linux: apt install fuse3")
        return 1
    
    mountpoint = Path(args.mountpoint).resolve()
    mountpoint.mkdir(parents=True, exist_ok=True)
    
    if _is_mounted(str(mountpoint)):
        print(f"Already mounted: {mountpoint}")
        return 1
    
    from . import AVM
    from .config import AVMConfig
    
    config = AVMConfig(db_path=args.db) if args.db else None
    
    if args.daemon:
        # Fork to background
        pid = os.fork()
        if pid > 0:
            # Parent
            _write_pid(str(mountpoint), pid)
            print(f"Mounted: {mountpoint} (pid={pid})")
            return 0
        
        # Child - detach
        os.setsid()
        
        # Redirect stdio
        sys.stdin = open(os.devnull, 'r')
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')
    
    # Create AVM AFTER fork (SQLite connections can't cross fork)
    avm = AVM(config=config, agent_id=args.agent)
    
    if not args.daemon:
        print(f"Mounting AVM at {mountpoint}")
        print(f"Agent: {args.agent or '(none)'}")
        print(f"Database: {avm.store.db_path}")
        print("Press Ctrl+C to unmount")
    
    try:
        FUSE(
            AVMFuse(avm, args.agent),
            str(mountpoint),
            foreground=not args.daemon,
            allow_other=False,
            nothreads=True,
        )
    finally:
        if args.daemon:
            _remove_pid(str(mountpoint))
    
    return 0


def cmd_stop(args):
    """Stop mounted AVM filesystem."""
    mountpoint = Path(args.mountpoint).resolve()
    
    if not _is_mounted(str(mountpoint)):
        print(f"Not mounted: {mountpoint}")
        _remove_pid(str(mountpoint))
        return 1
    
    pid = _get_pid(str(mountpoint))
    
    # Try umount first
    try:
        if sys.platform == 'darwin':
            subprocess.run(['umount', str(mountpoint)], check=True)
        else:
            subprocess.run(['fusermount', '-u', str(mountpoint)], check=True)
        _remove_pid(str(mountpoint))
        print(f"Stopped: {mountpoint}")
        return 0
    except subprocess.CalledProcessError:
        pass
    
    # Kill process if umount failed
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            _remove_pid(str(mountpoint))
            print(f"Stopped: {mountpoint} (killed pid={pid})")
            return 0
        except ProcessLookupError:
            _remove_pid(str(mountpoint))
    
    print(f"Failed to stop: {mountpoint}")
    return 1


def cmd_status(args):
    """Show mount status."""
    pid_dir = Path.home() / '.local' / 'share' / 'avm' / 'mounts'
    
    if not pid_dir.exists():
        print("No mounts.")
        return 0
    
    found = False
    for pid_file in pid_dir.glob('*.pid'):
        mountpoint = '/' + pid_file.stem.replace('_', '/')
        pid = None
        try:
            pid = int(pid_file.read_text().strip())
        except (ValueError, IOError):
            pass
        
        mounted = _is_mounted(mountpoint)
        running = False
        if pid:
            try:
                os.kill(pid, 0)
                running = True
            except ProcessLookupError:
                pass
        
        status = "mounted" if mounted else ("running" if running else "stale")
        print(f"{mountpoint}: {status} (pid={pid})")
        found = True
    
    if not found:
        print("No mounts.")
    
    return 0


def cmd_restart(args):
    """Restart mounted AVM filesystem."""
    # Get current settings from pid file or args
    mountpoint = Path(args.mountpoint).resolve()
    
    # Stop if running
    if _is_mounted(str(mountpoint)) or _get_pid(str(mountpoint)):
        cmd_stop(args)
        import time
        time.sleep(0.5)  # Wait for cleanup
    
    # Start again
    args.daemon = True
    return cmd_mount(args)
