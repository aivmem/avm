"""
avm/subscriptions.py - Persistent subscriptions with throttling/batching

Subscription modes:
- realtime: Push immediately via tell/hook
- throttled: Aggregate within window, push at end
- batched: No push, accumulate for /:inbox
- digest: Scheduled summaries (e.g., every 2h)

Usage:
    # FUSE
    echo "pattern=/memory/shared/*;mode=throttled;throttle=60" > avm/:subscribe
    cat avm/:subscriptions
    
    # CLI
    avm subscribe /memory/shared/* --mode throttled --throttle 60
    avm subscriptions list
"""

import json
import time
import threading
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Enum
import fnmatch

from .utils import utcnow


class SubscriptionMode(Enum):
    REALTIME = "realtime"    # Push immediately
    THROTTLED = "throttled"  # Aggregate within window
    BATCHED = "batched"      # No push, wait for poll
    DIGEST = "digest"        # Scheduled summary


@dataclass
class Subscription:
    """A subscription to path pattern changes"""
    id: int
    agent_id: str
    pattern: str
    mode: SubscriptionMode
    throttle_seconds: int = 60
    digest_cron: Optional[str] = None
    enabled: bool = True
    created_at: str = ""
    
    def __post_init__(self):
        if isinstance(self.mode, str):
            self.mode = SubscriptionMode(self.mode)
        if not self.created_at:
            self.created_at = utcnow().isoformat()


@dataclass
class PendingNotification:
    """Accumulated notifications waiting to be sent"""
    subscription_id: int
    agent_id: str
    paths: List[str] = field(default_factory=list)
    first_event: str = ""
    last_event: str = ""
    count: int = 0


class SubscriptionStore:
    """SQLite-backed subscription storage"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(Path.home() / ".local" / "share" / "avm" / "subscriptions.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_tables()
        
        # In-memory state for throttling
        self._pending: Dict[int, PendingNotification] = {}
        self._throttle_timers: Dict[int, threading.Timer] = {}
        self._lock = threading.Lock()
        
        # Callback for sending notifications
        self._notify_callback: Optional[Callable] = None
    
    def _init_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'batched',
                    throttle_seconds INTEGER DEFAULT 60,
                    digest_cron TEXT,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(agent_id, pattern)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_events (
                    id INTEGER PRIMARY KEY,
                    subscription_id INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    delivered INTEGER DEFAULT 0,
                    FOREIGN KEY(subscription_id) REFERENCES subscriptions(id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_sub ON pending_events(subscription_id, delivered)")
    
    def set_notify_callback(self, callback: Callable):
        """Set callback for sending notifications"""
        self._notify_callback = callback
    
    def subscribe(self, agent_id: str, pattern: str, 
                  mode: SubscriptionMode = SubscriptionMode.BATCHED,
                  throttle_seconds: int = 60,
                  digest_cron: str = None) -> Subscription:
        """Create or update a subscription"""
        now = utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO subscriptions (agent_id, pattern, mode, throttle_seconds, digest_cron, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id, pattern) DO UPDATE SET
                    mode = excluded.mode,
                    throttle_seconds = excluded.throttle_seconds,
                    digest_cron = excluded.digest_cron,
                    enabled = 1
            """, (agent_id, pattern, mode.value, throttle_seconds, digest_cron, now))
            
            row = conn.execute(
                "SELECT id, agent_id, pattern, mode, throttle_seconds, digest_cron, enabled, created_at FROM subscriptions WHERE agent_id = ? AND pattern = ?",
                (agent_id, pattern)
            ).fetchone()
        
        return Subscription(
            id=row[0], agent_id=row[1], pattern=row[2],
            mode=row[3], throttle_seconds=row[4],
            digest_cron=row[5], enabled=bool(row[6]), created_at=row[7]
        )
    
    def unsubscribe(self, agent_id: str, pattern: str):
        """Remove a subscription"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM subscriptions WHERE agent_id = ? AND pattern = ?",
                (agent_id, pattern)
            )
    
    def list_subscriptions(self, agent_id: str = None) -> List[Subscription]:
        """List subscriptions, optionally filtered by agent"""
        with sqlite3.connect(self.db_path) as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT id, agent_id, pattern, mode, throttle_seconds, digest_cron, enabled, created_at FROM subscriptions WHERE agent_id = ? AND enabled = 1",
                    (agent_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, agent_id, pattern, mode, throttle_seconds, digest_cron, enabled, created_at FROM subscriptions WHERE enabled = 1"
                ).fetchall()
        
        return [
            Subscription(id=r[0], agent_id=r[1], pattern=r[2], mode=r[3],
                        throttle_seconds=r[4], digest_cron=r[5], 
                        enabled=bool(r[6]), created_at=r[7])
            for r in rows
        ]
    
    def get_matching_subscriptions(self, path: str) -> List[Subscription]:
        """Find all subscriptions that match a given path"""
        all_subs = self.list_subscriptions()
        matching = []
        for sub in all_subs:
            if fnmatch.fnmatch(path, sub.pattern):
                matching.append(sub)
        return matching
    
    def on_write(self, path: str, author: str = None):
        """Called when a path is written - triggers subscription notifications"""
        subs = self.get_matching_subscriptions(path)
        now = utcnow().isoformat()
        
        for sub in subs:
            # Don't notify the author
            if author and sub.agent_id == author:
                continue
            
            if sub.mode == SubscriptionMode.REALTIME:
                self._send_immediate(sub, path)
            
            elif sub.mode == SubscriptionMode.THROTTLED:
                self._add_to_throttle(sub, path, now)
            
            elif sub.mode == SubscriptionMode.BATCHED:
                self._store_pending(sub.id, path, now)
            
            elif sub.mode == SubscriptionMode.DIGEST:
                self._store_pending(sub.id, path, now)
    
    def _send_immediate(self, sub: Subscription, path: str):
        """Send notification immediately"""
        if self._notify_callback:
            self._notify_callback(sub.agent_id, f"[update] {path}")
    
    def _add_to_throttle(self, sub: Subscription, path: str, timestamp: str):
        """Add to throttle buffer, schedule flush"""
        with self._lock:
            if sub.id not in self._pending:
                self._pending[sub.id] = PendingNotification(
                    subscription_id=sub.id,
                    agent_id=sub.agent_id,
                    paths=[path],
                    first_event=timestamp,
                    last_event=timestamp,
                    count=1
                )
                # Schedule flush
                timer = threading.Timer(sub.throttle_seconds, self._flush_throttle, args=[sub.id])
                timer.daemon = True
                timer.start()
                self._throttle_timers[sub.id] = timer
            else:
                pending = self._pending[sub.id]
                if path not in pending.paths:
                    pending.paths.append(path)
                pending.last_event = timestamp
                pending.count += 1
    
    def _flush_throttle(self, sub_id: int):
        """Flush throttled notifications"""
        with self._lock:
            pending = self._pending.pop(sub_id, None)
            self._throttle_timers.pop(sub_id, None)
        
        if pending and self._notify_callback:
            if pending.count == 1:
                msg = f"[update] {pending.paths[0]}"
            else:
                msg = f"[{pending.count} updates] {', '.join(pending.paths[:3])}"
                if len(pending.paths) > 3:
                    msg += f" +{len(pending.paths) - 3} more"
            self._notify_callback(pending.agent_id, msg)
    
    def _store_pending(self, sub_id: int, path: str, timestamp: str):
        """Store for later retrieval (batched/digest)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO pending_events (subscription_id, path, event_type, timestamp) VALUES (?, ?, ?, ?)",
                (sub_id, path, "write", timestamp)
            )
    
    def get_pending(self, agent_id: str, mark_delivered: bool = False) -> List[Dict]:
        """Get pending notifications for an agent"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT e.id, e.path, e.event_type, e.timestamp, s.pattern
                FROM pending_events e
                JOIN subscriptions s ON e.subscription_id = s.id
                WHERE s.agent_id = ? AND e.delivered = 0
                ORDER BY e.timestamp DESC
            """, (agent_id,)).fetchall()
            
            if mark_delivered and rows:
                ids = [r[0] for r in rows]
                placeholders = ','.join('?' * len(ids))
                conn.execute(f"UPDATE pending_events SET delivered = 1 WHERE id IN ({placeholders})", ids)
        
        return [
            {"path": r[1], "event_type": r[2], "timestamp": r[3], "pattern": r[4]}
            for r in rows
        ]
    
    def clear_pending(self, agent_id: str):
        """Clear all pending notifications for an agent"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE pending_events SET delivered = 1
                WHERE subscription_id IN (SELECT id FROM subscriptions WHERE agent_id = ?)
            """, (agent_id,))


# Singleton instance
_subscription_store: Optional[SubscriptionStore] = None

def get_subscription_store() -> SubscriptionStore:
    global _subscription_store
    if _subscription_store is None:
        _subscription_store = SubscriptionStore()
    return _subscription_store
