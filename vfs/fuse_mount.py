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
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

try:
    from fuse import FUSE, FuseOSError, Operations
    HAS_FUSE = True
except ImportError:
    HAS_FUSE = False
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
    VIRTUAL_SUFFIXES = {':meta', ':links', ':tags', ':history'}
    VIRTUAL_DIR_FILES = {':list', ':stats'}
    VIRTUAL_QUERY_PATTERNS = {':search', ':recall'}
    
    def __init__(self, vfs, user=None):
        self.vfs = vfs
        self.user = user
        self.fd = 0
        self._open_files: Dict[int, str] = {}
        self._write_buffers: Dict[int, bytes] = {}
    
    def _parse_path(self, path: str) -> tuple:
        """
        Parse path into (real_path, virtual_suffix, query_params).
        
        Examples:
            /memory/note.md -> ('/memory/note.md', None, None)
            /memory/note.md:meta -> ('/memory/note.md', ':meta', None)
            /memory/:search?q=RSI -> ('/memory', ':search', {'q': 'RSI'})
        """
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
        
        # Check for virtual suffix
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
    
    def _get_virtual_content(self, real_path: str, suffix: str, params: dict) -> str:
        """Generate content for virtual nodes."""
        
        if suffix == ':meta':
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            return json.dumps(node.meta, indent=2, default=str) + '\n'
        
        elif suffix == ':links':
            edges = self.vfs.store.get_edges(real_path)
            lines = []
            for edge in edges:
                target = edge.target if edge.source == real_path else edge.source
                lines.append(f"{target} ({edge.edge_type})")
            return '\n'.join(lines) + '\n' if lines else '(no links)\n'
        
        elif suffix == ':tags':
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            tags = node.meta.get('tags', [])
            return ','.join(tags) + '\n' if tags else '\n'
        
        elif suffix == ':history':
            history = self.vfs.history(real_path, limit=10)
            lines = []
            for h in history:
                ts = h.get('timestamp', '')[:19]
                change = h.get('change_type', 'update')
                lines.append(f"[{ts}] {change}")
            return '\n'.join(lines) + '\n' if lines else '(no history)\n'
        
        elif suffix == ':list':
            nodes = self.vfs.list(real_path)
            lines = []
            for node in nodes:
                name = node.path.split('/')[-1]
                lines.append(name)
            return '\n'.join(sorted(lines)) + '\n' if lines else '\n'
        
        elif suffix == ':stats':
            stats = self.vfs.stats()
            return json.dumps(stats, indent=2, default=str) + '\n'
        
        elif suffix == ':search':
            query = params.get('q', '') if params else ''
            limit = int(params.get('limit', 10)) if params else 10
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
        
        return False
    
    # ─── FUSE Operations ─────────────────────────────────
    
    def getattr(self, path, fh=None):
        """Get file attributes."""
        real_path, suffix, params = self._parse_path(path)
        
        now = datetime.now().timestamp()
        
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
                content = self._get_virtual_content(real_path, suffix, params)
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
    
    def readdir(self, path, fh):
        """List directory contents."""
        real_path, _, _ = self._parse_path(path)
        
        entries = ['.', '..']
        
        # Add virtual directory files
        entries.extend([':list', ':stats'])
        
        # Add real children
        nodes = self.vfs.list(real_path)
        seen = set()
        
        for node in nodes:
            # Get relative name
            if node.path.startswith(real_path):
                rel = node.path[len(real_path):].lstrip('/')
                # Only first component (immediate children)
                name = rel.split('/')[0]
                if name and name not in seen:
                    seen.add(name)
                    entries.append(name)
                    # Add virtual suffixes for files
                    if '.' in name:  # Likely a file
                        entries.append(f"{name}:meta")
                        entries.append(f"{name}:links")
                        entries.append(f"{name}:tags")
        
        return entries
    
    def read(self, path, size, offset, fh):
        """Read file content."""
        real_path, suffix, params = self._parse_path(path)
        
        if suffix:
            content = self._get_virtual_content(real_path, suffix, params)
        else:
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            content = node.content or ''
        
        encoded = content.encode('utf-8')
        return encoded[offset:offset + size]
    
    def write(self, path, data, offset, fh):
        """Write to file."""
        real_path, suffix, _ = self._parse_path(path)
        
        # Buffer writes
        if fh not in self._write_buffers:
            self._write_buffers[fh] = b''
        
        # Handle offset
        buf = self._write_buffers[fh]
        if offset < len(buf):
            buf = buf[:offset] + data
        else:
            buf = buf + b'\x00' * (offset - len(buf)) + data
        
        self._write_buffers[fh] = buf
        return len(data)
    
    def create(self, path, mode, fi=None):
        """Create a new file."""
        real_path, suffix, _ = self._parse_path(path)
        
        self.fd += 1
        self._open_files[self.fd] = path
        self._write_buffers[self.fd] = b''
        
        if not suffix:
            # Create empty node
            self.vfs.write(real_path, '')
        
        return self.fd
    
    def open(self, path, flags):
        """Open a file."""
        self.fd += 1
        self._open_files[self.fd] = path
        return self.fd
    
    def release(self, path, fh):
        """Close a file and flush writes."""
        if fh in self._write_buffers and self._write_buffers[fh]:
            real_path, suffix, _ = self._parse_path(path)
            content = self._write_buffers[fh].decode('utf-8', errors='replace')
            
            if suffix:
                self._set_virtual_content(real_path, suffix, content)
            else:
                self.vfs.write(real_path, content)
        
        self._write_buffers.pop(fh, None)
        self._open_files.pop(fh, None)
        return 0
    
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


def main():
    """Main entry point for avm-mount."""
    if not HAS_FUSE:
        print("Error: fusepy not installed. Run: pip install fusepy")
        print("Also ensure FUSE is installed on your system:")
        print("  macOS: brew install macfuse")
        print("  Linux: apt install fuse3")
        return 1
    
    parser = argparse.ArgumentParser(
        description="Mount AVM as a FUSE filesystem",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Virtual Nodes:
  /path/file.md:meta    Metadata (JSON)
  /path/file.md:links   Related nodes
  /path/file.md:tags    Tags (comma-separated)
  /path/:list           Directory listing
  /path/:search?q=X     Search results
  /path/:recall?q=X     Token-aware recall

Examples:
  avm-mount /mnt/avm
  avm-mount /mnt/avm --user akashi
  cat /mnt/avm/memory/note.md:meta
  cat "/mnt/avm/memory/:search?q=RSI"
        """
    )
    parser.add_argument("mountpoint", help="Mount point path")
    parser.add_argument("--user", "-u", help="User name for recall")
    parser.add_argument("--db", "-d", help="Database path")
    parser.add_argument("--foreground", "-f", action="store_true", help="Run in foreground")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    
    args = parser.parse_args()
    
    # Ensure mount point exists
    mountpoint = Path(args.mountpoint)
    mountpoint.mkdir(parents=True, exist_ok=True)
    
    # Initialize VFS
    from . import VFS
    from .config import VFSConfig
    
    config = VFSConfig(db_path=args.db) if args.db else None
    vfs = VFS(config=config)
    
    print(f"Mounting AVM at {args.mountpoint}")
    print(f"User: {args.user or '(none)'}")
    print(f"Database: {vfs.store.db_path}")
    print("Press Ctrl+C to unmount")
    
    # Mount
    FUSE(
        AVMFuse(vfs, args.user),
        str(mountpoint),
        foreground=args.foreground or True,
        allow_other=False,
        nothreads=True,
    )


if __name__ == "__main__":
    main()
