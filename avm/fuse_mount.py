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
    VIRTUAL_SUFFIXES = {':meta', ':links', ':tags', ':history', ':shared', ':data', ':info', ':path'}
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
    
    def _get_virtual_content(self, real_path: str, suffix: str, params: dict) -> str:
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
                ts = h.get('timestamp', '')[:19]
                change = h.get('change_type', 'update')
                lines.append(f"[{ts}] {change}")
            return '\n'.join(lines) + '\n' if lines else '(no history)\n'
        
        elif suffix == ':list':
            limit = int(params.get('limit', 50)) if params else 50
            nodes = self.vfs.list(real_path, limit=limit)
            lines = []
            for node in nodes:
                # Filter by access permission
                if not self._can_see_shared(node):
                    continue
                # Get or generate shortcut
                shortcut = node.meta.get('shortcut')
                if not shortcut:
                    shortcut = self._generate_shortcut(node.path)
                    # Store shortcut in meta
                    node.meta['shortcut'] = shortcut
                    self.vfs.write(node.path, node.content, meta=node.meta)
                # Get filename
                filename = node.path.split('/')[-1]
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
        entries.extend([':list', ':stats'])
        
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
        
        if suffix:
            content = self._get_virtual_content(real_path, suffix, params)
        else:
            node = self.vfs.read(real_path)
            if not node:
                raise FuseOSError(errno.ENOENT)
            # Check shared permission
            if not self._can_see_shared(node):
                raise FuseOSError(errno.EACCES)
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


def main():
    """Main entry point for avm-mount."""
    parser = argparse.ArgumentParser(
        description="AVM FUSE Mount Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # mount command (default)
    mount_parser = subparsers.add_parser('mount', help='Mount AVM filesystem')
    mount_parser.add_argument("mountpoint", help="Mount point path")
    mount_parser.add_argument("--agent", "-a", help="Agent ID for recall")
    mount_parser.add_argument("--db", "-d", help="Database path")
    mount_parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    mount_parser.add_argument("--foreground", "-f", action="store_true", help="Run in foreground (default)")
    
    # stop command
    stop_parser = subparsers.add_parser('stop', help='Stop mounted filesystem')
    stop_parser.add_argument("mountpoint", help="Mount point path")
    
    # status command
    subparsers.add_parser('status', help='Show mount status')
    
    # restart command
    restart_parser = subparsers.add_parser('restart', help='Restart mounted filesystem')
    restart_parser.add_argument("mountpoint", help="Mount point path")
    restart_parser.add_argument("--agent", "-a", help="Agent ID for recall")
    restart_parser.add_argument("--db", "-d", help="Database path")
    
    args = parser.parse_args()
    
    # Default to mount if no command and mountpoint-like arg
    if not args.command:
        if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
            # Legacy: avm-mount /path
            args.command = 'mount'
            args.mountpoint = sys.argv[1]
            args.agent = None
            args.db = None
            args.daemon = False
            args.foreground = True
            # Re-parse with mount defaults
            for i, arg in enumerate(sys.argv[2:], 2):
                if arg in ('--agent', '-a') and i + 1 < len(sys.argv):
                    args.agent = sys.argv[i + 1]
                elif arg in ('--db', '-d') and i + 1 < len(sys.argv):
                    args.db = sys.argv[i + 1]
                elif arg == '--daemon':
                    args.daemon = True
                elif arg in ('--foreground', '-f'):
                    args.foreground = True
        else:
            parser.print_help()
            return 1
    
    if args.command == 'mount':
        return cmd_mount(args)
    elif args.command == 'stop':
        return cmd_stop(args)
    elif args.command == 'status':
        return cmd_status(args)
    elif args.command == 'restart':
        return cmd_restart(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
