"""
AVM Unified Daemon - Single process, multiple mount points

Usage:
    avm-daemon start [--config CONFIG]
    avm-daemon stop
    avm-daemon status
    avm-daemon add MOUNTPOINT --agent AGENT_ID
    avm-daemon remove MOUNTPOINT
"""

import os
import sys
import json
import signal
import threading
import argparse
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass, field, asdict

# Lazy imports to avoid circular dependencies
FUSE = None
AVMFuse = None
AVM = None


def _lazy_imports():
    global FUSE, AVMFuse, AVM
    if FUSE is None:
        from fuse import FUSE as _FUSE
        from .fuse_mount import AVMFuse as _AVMFuse
        from .core import AVM as _AVM
        FUSE = _FUSE
        AVMFuse = _AVMFuse
        AVM = _AVM


# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════

DATA_DIR = Path.home() / ".local" / "share" / "avm"
CONFIG_DIR = Path.home() / ".config" / "avm"
MOUNTS_CONFIG = CONFIG_DIR / "mounts.yaml"
DAEMON_PID = DATA_DIR / "daemon.pid"


@dataclass
class MountConfig:
    """Configuration for a single mount point"""
    path: str
    agent: str
    enabled: bool = True


@dataclass
class DaemonConfig:
    """Daemon configuration"""
    mounts: list = field(default_factory=list)
    
    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        import yaml
        data = {
            "mounts": [
                {"path": m.path, "agent": m.agent, "enabled": m.enabled}
                for m in self.mounts
            ]
        }
        MOUNTS_CONFIG.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
    
    @classmethod
    def load(cls) -> "DaemonConfig":
        if not MOUNTS_CONFIG.exists():
            return cls()
        try:
            import yaml
            data = yaml.safe_load(MOUNTS_CONFIG.read_text())
            mounts = [
                MountConfig(
                    path=str(Path(m["path"]).expanduser()),
                    agent=m["agent"],
                    enabled=m.get("enabled", True)
                )
                for m in data.get("mounts", [])
            ]
            return cls(mounts=mounts)
        except Exception:
            return cls()


# ═══════════════════════════════════════════════════════════════
# Mount Thread
# ═══════════════════════════════════════════════════════════════

class MountProcess:
    """Child process managing a single FUSE mount (fork-based).

    Uses os.fork() for isolation — each mount is a separate process so
    macFUSE device slots are claimed sequentially and never race.
    GPU/MPS is disabled in the child via AVM_FUSE_WORKER=1 so XPC issues
    after fork() do not occur.
    """

    def __init__(self, mountpoint: str, agent_id: str,
                 embed_server=None, child_conn=None):
        self.mountpoint = mountpoint
        self.agent_id = agent_id
        self.embed_server = embed_server  # legacy / unused in fork mode
        self.child_conn = child_conn      # multiprocessing.Pipe child end
        self.pid: Optional[int] = None

    def start(self) -> bool:
        """Fork and block until the mount is live (st_dev changes) or 12 s."""
        import time

        normal_dev = Path(self.mountpoint).parent.stat().st_dev
        pid = os.fork()
        if pid == 0:
            self._run_fuse()
            os._exit(0)

        self.pid = pid
        mp = Path(self.mountpoint)
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            try:
                rc = os.waitpid(pid, os.WNOHANG)
                if rc[0] != 0:          # child exited early → mount failed
                    self.pid = None
                    return False
            except ChildProcessError:
                self.pid = None
                return False
            try:
                if mp.stat().st_dev != normal_dev:
                    return True         # mount is live
            except OSError:
                pass
            time.sleep(0.3)

        # 12 s elapsed — check one last time
        try:
            rc = os.waitpid(pid, os.WNOHANG)
            if rc[0] != 0:
                self.pid = None
                return False
        except ChildProcessError:
            self.pid = None
            return False
        # Child alive but mount didn't appear — proceed anyway
        return mp.stat().st_dev != normal_dev

    def _run_fuse(self):
        """Run FUSE in forked child.

        If a child_conn Pipe was provided, GPU embedding is routed through
        the parent process (MPS-safe).  Otherwise falls back to CPU.
        """
        _lazy_imports()
        import os as _os
        _os.environ["TOKENIZERS_PARALLELISM"] = "false"

        if self.child_conn is None:
            # No GPU proxy — force CPU embedding in this fork
            _os.environ["AVM_FUSE_WORKER"] = "1"

        try:
            agent_avm = AVM(agent_id=self.agent_id)

            if self.child_conn is not None:
                # Inject GPU proxy backed by the parent's embedding server
                from .embedding import EmbeddingStore, PipeEmbeddingProxy
                proxy = PipeEmbeddingProxy(self.child_conn)
                agent_avm._embedding_store = EmbeddingStore(agent_avm.store, proxy)
                agent_avm._auto_index_embedding = True

            Path(self.mountpoint).mkdir(parents=True, exist_ok=True)
            FUSE(
                AVMFuse(agent_avm, self.agent_id),
                self.mountpoint,
                nothreads=True,
                foreground=True,
                allow_other=False,
                attr_timeout=0,
                entry_timeout=0,
                direct_io=True,
            )
        except Exception as e:
            print(f"FUSE error for {self.mountpoint}: {e}", file=sys.stderr)
        finally:
            if self.child_conn is not None:
                self.child_conn.close()

    def stop(self):
        """Kill child and force-unmount."""
        import subprocess, platform, time as _t

        if self.pid:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.kill(self.pid, sig)
                    _t.sleep(0.5)
                    os.waitpid(self.pid, os.WNOHANG)
                except (ProcessLookupError, ChildProcessError):
                    break

        mp = self.mountpoint
        try:
            if platform.system() == "Darwin":
                r = subprocess.run(
                    ["/usr/sbin/diskutil", "unmount", "force", mp],
                    capture_output=True, timeout=10,
                )
                if r.returncode != 0:
                    subprocess.run(["/sbin/umount", "-f", mp],
                                   capture_output=True, timeout=5)
            else:
                for cmd in (["fusermount3", "-u", mp],
                            ["fusermount", "-u", mp],
                            ["/sbin/umount", "-f", mp]):
                    r = subprocess.run(cmd, capture_output=True, timeout=5)
                    if r.returncode == 0:
                        break
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# Daemon
# ═══════════════════════════════════════════════════════════════

class AVMDaemon:
    """Unified AVM daemon managing multiple mounts"""
    
    def __init__(self):
        _lazy_imports()
        self.config = DaemonConfig.load()
        self.mounts: Dict[str, MountProcess] = {}
        self._running = False
        self._embed_backend = None   # shared LocalEmbedding (GPU/MPS, parent only)
        self._pipe_servers: list = []  # EmbeddingPipeServer instances

    def start(self):
        """Start the daemon and all configured mounts"""
        if DAEMON_PID.exists():
            try:
                pid = int(DAEMON_PID.read_text().strip())
                os.kill(pid, 0)  # Check if process exists
                # Also verify it's actually an AVM daemon (not a recycled PID)
                try:
                    import subprocess
                    cmdline = subprocess.check_output(
                        ["ps", "-p", str(pid), "-o", "command="],
                        timeout=3, text=True
                    ).strip()
                    if "avm" in cmdline.lower() or "AVMDaemon" in cmdline:
                        print(f"Daemon already running (pid={pid})")
                        return False
                    else:
                        print(f"  Stale pid file (pid={pid} is '{cmdline[:40]}'), ignoring")
                except Exception:
                    # Can't verify cmdline — trust the pid
                    print(f"Daemon already running (pid={pid})")
                    return False
            except (ProcessLookupError, ValueError):
                pass  # Stale pid file — process gone
        
        # Write PID
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DAEMON_PID.write_text(str(os.getpid()))
        
        self._running = True

        # Start mounts one at a time.  macFUSE allocates /dev/macfuseN slots
        # sequentially; launching multiple FUSE threads simultaneously causes
        # "Resource temporarily unavailable" on all but the first device.
        # _start_mount now blocks until the mount is accessible before returning.
        for mount_config in self.config.mounts:
            if mount_config.enabled:
                self._start_mount(mount_config)
        
        print(f"Daemon started (pid={os.getpid()})")
        print(f"Mounts: {len(self.mounts)}")
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGHUP, self._handle_reload)
        
        # Start auto-archive thread
        self._archive_thread = threading.Thread(target=self._auto_archive_loop, daemon=True)
        self._archive_thread.start()
        print("  Auto-archive enabled (every 6h, threshold=0.15)")
        
        # Start trash cleanup thread
        self._trash_thread = threading.Thread(target=self._auto_trash_cleanup, daemon=True)
        self._trash_thread.start()
        print("  Trash cleanup enabled (daily, 30d retention)")

        # Start mount watchdog thread — checks every 30s, remounts dead mounts
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()
        print("  Mount watchdog enabled (every 30s)")

        # Wait for stop
        try:
            while self._running:
                signal.pause()
        except Exception:
            pass
        
        return True

    def _watchdog_loop(self):
        """Periodically verify mounts are alive, remount if dead."""
        import time, subprocess, platform
        while self._running:
            time.sleep(30)
            for mp, proc in list(self.mounts.items()):
                try:
                    entries = os.listdir(mp)
                    if not entries:
                        raise OSError("empty mount — likely stale")
                except OSError:
                    # Mount is dead — try to recover
                    print(f"  [watchdog] Dead mount detected: {mp}, remounting...", flush=True)
                    # Kill stale FUSE process
                    if proc.pid:
                        try:
                            os.kill(proc.pid, 9)
                        except ProcessLookupError:
                            pass
                    # Force unmount
                    if platform.system() == "Darwin":
                        subprocess.run(["/usr/sbin/diskutil", "unmount", "force", mp],
                                       capture_output=True, timeout=5)
                    else:
                        for cmd in (["fusermount3", "-u", mp],
                                    ["fusermount", "-u", mp],
                                    ["/sbin/umount", "-f", mp]):
                            r = subprocess.run(cmd, capture_output=True, timeout=5)
                            if r.returncode == 0:
                                break
                    # Find config for this mount and remount
                    for mc in self.config.mounts:
                        if mc.path == mp and mc.enabled:
                            self._start_mount(mc)
                            break
    
    def _auto_archive_loop(self):
        """Background thread that archives cold memories periodically"""
        import time
        from .advanced import MemoryDecay
        from .core import AVM as _AVM
        from .config import load_config
        
        # Load settings from config
        config = load_config()
        decay_cfg = getattr(config, 'decay', None) or {}
        if isinstance(decay_cfg, dict):
            ARCHIVE_INTERVAL = int(decay_cfg.get('archive_interval_hours', 6)) * 60 * 60
            ARCHIVE_THRESHOLD = float(decay_cfg.get('archive_threshold', 0.15))
            ARCHIVE_HALF_LIFE = float(decay_cfg.get('half_life_days', 14.0))
            ARCHIVE_LIMIT = int(decay_cfg.get('archive_limit', 50))
        else:
            ARCHIVE_INTERVAL = 6 * 60 * 60
            ARCHIVE_THRESHOLD = 0.15
            ARCHIVE_HALF_LIFE = 14.0
            ARCHIVE_LIMIT = 50
        
        # Initial delay to let system settle
        time.sleep(60)
        
        while self._running:
            try:
                vfs = _AVM()
                decay = MemoryDecay(vfs.store, half_life_days=ARCHIVE_HALF_LIFE)
                cold = decay.get_cold_memories(
                    prefix="/memory",
                    threshold=ARCHIVE_THRESHOLD,
                    limit=ARCHIVE_LIMIT
                )
                
                if cold:
                    from .utils import utcnow
                    archived = []
                    for node in cold:
                        archive_path = node.path.replace("/memory/", "/archive/", 1)
                        node.meta['archived_by'] = 'daemon'
                        node.meta['archived_at'] = utcnow().isoformat()
                        vfs.write(archive_path, node.content, meta=node.meta)
                        vfs.store.delete_node(node.path)
                        archived.append(node.path)
                    
                    print(f"[auto-archive] Archived {len(archived)} cold memories")
            except Exception as e:
                print(f"[auto-archive] Error: {e}")
            
            # Sleep in small chunks to check _running flag
            for _ in range(ARCHIVE_INTERVAL // 60):
                if not self._running:
                    break
                time.sleep(60)
    
    def _wait_for_mount(self, mountpoint: str, timeout: float = 10.0):
        """Block until the mountpoint is actually serving FUSE requests.

        Exits early if:
        - iterdir() succeeds (mount is live)
        - the MountProcess thread has died (mount failed)
        - timeout is reached
        """
        import time as _time
        deadline = _time.monotonic() + timeout
        path = Path(mountpoint)
        proc = self.mounts.get(mountpoint)

        while _time.monotonic() < deadline:
            # If the thread died, don't wait any longer
            if proc is not None and proc._thread is not None and not proc._thread.is_alive():
                print(f"  ⚠ Mount thread for {mountpoint} exited early", file=sys.stderr)
                return
            try:
                list(path.iterdir())
                return   # mount is live
            except OSError:
                pass
            _time.sleep(0.5)

        print(f"  ⚠ Mount {mountpoint} did not become ready within {timeout}s",
              file=sys.stderr)

    def _start_mount(self, mount_config: MountConfig):
        """Start a single mount, with zombie cleanup on failure."""
        import subprocess, platform

        mp = mount_config.path
        Path(mp).mkdir(parents=True, exist_ok=True)

        # Set up GPU embedding pipe (fork-safe: Pipe created before fork,
        # each child gets its own fd pair → no cross-agent access).
        child_conn = None
        from .config import load_config as _lc
        _cfg = _lc()
        _emb_cfg = getattr(_cfg, 'embedding', None) or {}
        if isinstance(_emb_cfg, dict) and _emb_cfg.get('enabled'):
            import multiprocessing as _mp
            from .embedding import EmbeddingPipeServer, LocalEmbedding

            # Load the shared GPU backend once (lazy)
            if self._embed_backend is None:
                _model = _emb_cfg.get('model', 'all-MiniLM-L6-v2')
                print(f"  Loading embedding model ({_model}, MPS)...")
                self._embed_backend = LocalEmbedding(_model)
                self._embed_backend._load_model()
                print(f"  Embedding model ready (dim={self._embed_backend.dimension})")

            parent_conn, child_conn = _mp.Pipe()
            server = EmbeddingPipeServer(parent_conn, backend=self._embed_backend)
            server.start()
            self._pipe_servers.append(server)

        proc = MountProcess(mp, mount_config.agent, child_conn=child_conn)
        ok = proc.start()

        # Close parent's copy of child_conn (child has its own fd)
        if child_conn is not None:
            child_conn.close()

        if not ok:
            # Mount failed — clean up any partial macFUSE state immediately
            print(f"  ⚠ Mount failed for {mp}, cleaning up...", file=sys.stderr)
            if platform.system() == "Darwin":
                subprocess.run(["/usr/sbin/diskutil", "unmount", "force", mp],
                               capture_output=True, timeout=5)
            else:
                for cmd in (["fusermount3", "-u", mp],
                            ["fusermount", "-u", mp],
                            ["/sbin/umount", "-f", mp]):
                    r = subprocess.run(cmd, capture_output=True, timeout=5)
                    if r.returncode == 0:
                        break
            return

        self.mounts[mp] = proc
        print(f"  Mounted: {mp} (agent={mount_config.agent}, pid={proc.pid})")

        # Wait for this mount to become accessible before starting the next one.
        # Note: start() already blocked until the mount was live (st_dev check),
        # so by the time we reach here macFUSE has fully registered the device.
    
    def _auto_trash_cleanup(self):
        """Background thread that cleans up old trash items"""
        import time
        from datetime import datetime, timedelta, timezone
        from .core import AVM as _AVM
        
        CLEANUP_INTERVAL = 24 * 60 * 60  # Daily
        RETENTION_DAYS = 30
        
        # Initial delay
        time.sleep(120)
        
        while self._running:
            try:
                vfs = _AVM()
                trash_items = vfs.list("/trash", limit=500)
                
                cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
                deleted = 0
                
                for item in trash_items:
                    deleted_at = item.meta.get('deleted_at')
                    if deleted_at:
                        try:
                            dt = datetime.fromisoformat(deleted_at.replace('Z', '+00:00'))
                            if dt < cutoff:
                                vfs.delete(item.path, hard=True)
                                deleted += 1
                        except (ValueError, TypeError):
                            pass
                
                if deleted:
                    print(f"[trash-cleanup] Removed {deleted} items older than {RETENTION_DAYS}d")
            except Exception as e:
                print(f"[trash-cleanup] Error: {e}")
            
            # Sleep in chunks
            for _ in range(CLEANUP_INTERVAL // 60):
                if not self._running:
                    break
                time.sleep(60)
    
    def _handle_signal(self, signum, frame):
        """Handle shutdown signals"""
        print("\nShutting down...")
        self._running = False
        
        # Stop all mounts
        for mount in self.mounts.values():
            mount.stop()

        # Stop the embedding server
        # Remove PID file
        if DAEMON_PID.exists():
            DAEMON_PID.unlink()
    
    def _handle_reload(self, signum, frame):
        """Handle reload signal (SIGHUP)"""
        print("\nReloading configuration...")
        
        # Reload config
        new_config = DaemonConfig.load()
        
        # Find what changed
        current_paths = set(self.mounts.keys())
        new_paths = set(m.path for m in new_config.mounts if m.enabled)
        
        # Stop removed mounts
        for path in current_paths - new_paths:
            print(f"  Stopping: {path}")
            self.mounts[path].stop()
            del self.mounts[path]
        
        # Start new mounts
        for m in new_config.mounts:
            if m.enabled and m.path not in current_paths:
                print(f"  Starting: {m.path}")
                self._start_mount(m)
        
        self.config = new_config
        print(f"Reload complete. Mounts: {len(self.mounts)}")
    
    def add_mount(self, path: str, agent: str):
        """Add a mount configuration"""
        path = str(Path(path).expanduser().resolve())
        # Check if already exists
        for m in self.config.mounts:
            if m.path == path:
                m.agent = agent
                self.config.save()
                print(f"Updated: {path} (agent={agent})")
                return
        self.config.mounts.append(MountConfig(path=path, agent=agent))
        self.config.save()
        print(f"Added: {path} (agent={agent})")
    
    def remove_mount(self, path: str):
        """Remove a mount configuration"""
        path = str(Path(path).expanduser().resolve())
        for i, m in enumerate(self.config.mounts):
            if m.path == path:
                del self.config.mounts[i]
                self.config.save()
                print(f"Removed: {path}")
                return
        print(f"Not found: {path}")
    
    def list_mounts(self):
        """List configured mounts"""
        if not self.config.mounts:
            print("No mounts configured")
            return
        
        print("Configured mounts:")
        for m in self.config.mounts:
            status = "✓" if m.enabled else "○"
            short_path = m.path.replace(str(Path.home()), "~")
            print(f"  {status} {short_path} → {m.agent}")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def cmd_start(args):
    """Start the daemon"""
    daemon = AVMDaemon()
    
    if args.daemon:
        # Fork to background
        pid = os.fork()
        if pid > 0:
            print(f"Daemon started in background (pid={pid})")
            return 0
        
        # Child process
        os.setsid()
        
        # Redirect stdout/stderr
        log_file = CONFIG_DIR / "daemon.log"
        sys.stdout = open(log_file, "a")
        sys.stderr = sys.stdout
    
    daemon.start()
    return 0


def cmd_stop(args):
    """Stop the daemon and wait for clean shutdown"""
    import time

    if not DAEMON_PID.exists():
        print("Daemon not running")
        return 1

    pid = int(DAEMON_PID.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        DAEMON_PID.unlink(missing_ok=True)
        print("Daemon not running (stale pid file removed)")
        return 1

    # Wait for the process to exit (up to 8s)
    for _ in range(16):
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
    else:
        # Still alive — SIGKILL
        try:
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
        except ProcessLookupError:
            pass

    DAEMON_PID.unlink(missing_ok=True)
    print(f"Stopped daemon (pid={pid})")
    return 0


def cmd_status(args):
    """Show daemon status"""
    print("╭─────────────────────────────────────────╮")
    print("│         🧠 AVM Daemon Status            │")
    print("╰─────────────────────────────────────────╯")
    
    if not DAEMON_PID.exists():
        print("  Status: ⭘ not running")
    else:
        pid = int(DAEMON_PID.read_text().strip())
        try:
            os.kill(pid, 0)
            print(f"  Status: ● running (pid={pid})")
        except ProcessLookupError:
            print("  Status: ⭘ not running (stale pid)")
    
    daemon = AVMDaemon()
    config = daemon.config
    
    if not config.mounts:
        print("\n  No mounts configured")
    else:
        print(f"\n  Mounts: {len(config.mounts)}")
        print("  ─────────────────────────────────────")
        for m in config.mounts:
            status = "●" if m.enabled else "○"
            short_path = m.path.replace(str(Path.home()), "~")
            print(f"  {status} {m.agent:<12} → {short_path}")
    
    print()
    return 0


def cmd_inspect(args):
    """Inspect daemon and mounts in detail"""
    _lazy_imports()
    
    print("╭─────────────────────────────────────────╮")
    print("│         🔍 AVM Daemon Inspect           │")
    print("╰─────────────────────────────────────────╯")
    
    # Daemon info
    print("\n📋 Daemon")
    print("  ─────────────────────────────────────")
    if DAEMON_PID.exists():
        pid = int(DAEMON_PID.read_text().strip())
        try:
            os.kill(pid, 0)
            print(f"  PID:     {pid}")
            print(f"  Status:  ● running")
        except ProcessLookupError:
            print(f"  Status:  ⭘ not running (stale pid={pid})")
    else:
        print("  Status:  ⭘ not running")
    
    print(f"  Config:  {MOUNTS_CONFIG}")
    print(f"  PID file: {DAEMON_PID}")
    
    # Database info
    print("\n💾 Database")
    print("  ─────────────────────────────────────")
    avm = AVM()
    db_path = avm.store.db_path
    print(f"  Path:    {db_path}")
    if Path(db_path).exists():
        size = Path(db_path).stat().st_size
        if size > 1024 * 1024:
            print(f"  Size:    {size / 1024 / 1024:.1f} MB")
        else:
            print(f"  Size:    {size / 1024:.1f} KB")
        
        # Node count
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            conn.close()
            print(f"  Nodes:   {count}")
        except Exception:
            pass
    
    # Mount details
    daemon = AVMDaemon()
    config = daemon.config
    
    print("\n📂 Mounts")
    print("  ─────────────────────────────────────")
    
    if not config.mounts:
        print("  (none configured)")
    else:
        # Check actual mount status
        import subprocess
        result = subprocess.run(["/sbin/mount"], capture_output=True, text=True)
        mounted = result.stdout
        
        for m in config.mounts:
            short_path = m.path.replace(str(Path.home()), "~")
            is_mounted = m.path in mounted or m.path.replace("/Users/", "/private/var/") in mounted
            
            status_icon = "●" if is_mounted else "○"
            status_text = "mounted" if is_mounted else "not mounted"
            
            print(f"\n  {status_icon} {m.agent}")
            print(f"    Path:   {short_path}")
            print(f"    Status: {status_text}")
            
            # Check if accessible
            if is_mounted:
                try:
                    list_path = Path(m.path) / ":stats"
                    if list_path.exists():
                        stats = json.loads(list_path.read_text())
                        print(f"    Nodes:  {stats.get('nodes', '?')}")
                except Exception:
                    pass
    
    # Process tree
    print("\n🌳 Processes")
    print("  ─────────────────────────────────────")
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True
        )
        procs = [l for l in result.stdout.split("\n") if "avm-daemon" in l and "grep" not in l]
        if procs:
            for p in procs:
                parts = p.split()
                pid = parts[1]
                mem = parts[3]
                print(f"  pid={pid} mem={mem}%")
        else:
            print("  (no daemon processes)")
    except Exception:
        print("  (unable to check)")
    
    print()
    return 0


def cmd_add(args):
    """Add a mount"""
    daemon = AVMDaemon()
    daemon.add_mount(args.mountpoint, args.agent)
    return 0


def cmd_remove(args):
    """Remove a mount"""
    daemon = AVMDaemon()
    daemon.remove_mount(args.mountpoint)
    return 0


def cmd_check(args):
    """Check configuration validity"""
    print("Checking configuration...")
    
    if not MOUNTS_CONFIG.exists():
        print(f"  ✗ Config not found: {MOUNTS_CONFIG}")
        return 1
    
    try:
        import yaml
        data = yaml.safe_load(MOUNTS_CONFIG.read_text())
    except Exception as e:
        print(f"  ✗ YAML parse error: {e}")
        return 1
    
    if not isinstance(data, dict) or "mounts" not in data:
        print("  ✗ Missing 'mounts' key")
        return 1
    
    mounts = data.get("mounts", [])
    if not isinstance(mounts, list):
        print("  ✗ 'mounts' must be a list")
        return 1
    
    errors = []
    for i, m in enumerate(mounts):
        if not isinstance(m, dict):
            errors.append(f"  ✗ Mount {i}: must be a dict")
            continue
        if "path" not in m:
            errors.append(f"  ✗ Mount {i}: missing 'path'")
        if "agent" not in m:
            errors.append(f"  ✗ Mount {i}: missing 'agent'")
        
        # Check path exists or can be created
        if "path" in m:
            path = Path(m["path"]).expanduser()
            parent = path.parent
            if not parent.exists():
                errors.append(f"  ✗ Mount {i}: parent dir not found: {parent}")
    
    if errors:
        for e in errors:
            print(e)
        return 1
    
    print(f"  ✓ Config valid ({len(mounts)} mounts)")
    return 0


def cmd_reload(args):
    """Reload configuration (send SIGHUP to daemon)"""
    # Check config first
    print("Pre-reload check...")
    if cmd_check(argparse.Namespace()) != 0:
        print("\n✗ Reload aborted: invalid config")
        return 1
    
    if not DAEMON_PID.exists():
        print("Daemon not running")
        return 1
    
    pid = int(DAEMON_PID.read_text().strip())
    try:
        os.kill(pid, signal.SIGHUP)
        print(f"\n✓ Sent reload signal to daemon (pid={pid})")
        return 0
    except ProcessLookupError:
        print("Daemon not running (stale pid)")
        DAEMON_PID.unlink()
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="AVM Unified Daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # start
    start_parser = subparsers.add_parser("start", help="Start daemon")
    start_parser.add_argument("--daemon", "-d", action="store_true",
                              help="Run in background")
    start_parser.set_defaults(func=cmd_start)
    
    # stop
    stop_parser = subparsers.add_parser("stop", help="Stop daemon")
    stop_parser.set_defaults(func=cmd_stop)
    
    # reload
    reload_parser = subparsers.add_parser("reload", help="Reload configuration")
    reload_parser.set_defaults(func=cmd_reload)
    
    # check
    check_parser = subparsers.add_parser("check", help="Check config validity")
    check_parser.set_defaults(func=cmd_check)
    
    # status
    status_parser = subparsers.add_parser("status", help="Show status")
    status_parser.set_defaults(func=cmd_status)
    
    # inspect
    inspect_parser = subparsers.add_parser("inspect", help="Detailed inspection")
    inspect_parser.set_defaults(func=cmd_inspect)
    
    # add
    add_parser = subparsers.add_parser("add", help="Add mount")
    add_parser.add_argument("mountpoint", help="Mount point path")
    add_parser.add_argument("--agent", "-a", required=True,
                           help="Agent ID")
    add_parser.set_defaults(func=cmd_add)
    
    # remove
    remove_parser = subparsers.add_parser("remove", help="Remove mount")
    remove_parser.add_argument("mountpoint", help="Mount point path")
    remove_parser.set_defaults(func=cmd_remove)
    
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
