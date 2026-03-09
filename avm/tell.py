"""
avm/tell.py - Cross-agent messaging system

Allows agents to send important messages to each other that get
injected into the recipient's next read operation.

Priority levels:
- urgent: Injected into next read of ANY file
- normal: Shown when reading /:inbox or /tell/@me
- low: Only shown when explicitly reading /:inbox

Hooks:
- Shell: Execute command when tell is sent
- HTTP: POST to webhook URL
- OpenClaw: Send via sessions_send

Usage:
    # Write a tell
    echo "important message" > avm/tell/kearsarge?priority=urgent
    echo "fyi" > avm/tell/kearsarge
    echo "message" > avm/tell/@all  # Broadcast

    # Read tells
    cat avm/:inbox              # All unread tells
    cat avm/tell/@me            # Same as /:inbox
    cat avm/tell/@me?mark=read  # Mark all as read
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum


class TellPriority(Enum):
    URGENT = "urgent"   # Inject into next read
    NORMAL = "normal"   # Show in inbox
    LOW = "low"         # Only explicit inbox read


@dataclass
class Tell:
    """A message from one agent to another"""
    id: int
    from_agent: str
    to_agent: str  # Can be specific agent or "@all"
    content: str
    priority: TellPriority
    created_at: str
    read_at: Optional[str] = None
    expires_at: Optional[str] = None
    ack_required: bool = False
    meta: Dict[str, Any] = None
    
    def __post_init__(self):
        if isinstance(self.priority, str):
            self.priority = TellPriority(self.priority)
        if self.meta is None:
            self.meta = {}
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        d['priority'] = self.priority.value
        return d
    
    def format_header(self) -> str:
        """Format as markdown header for injection"""
        priority_emoji = {
            TellPriority.URGENT: "🔴",
            TellPriority.NORMAL: "🟡", 
            TellPriority.LOW: "⚪"
        }
        emoji = priority_emoji.get(self.priority, "")
        return f"## {emoji} From: {self.from_agent} @ {self.created_at}\n{self.content}"


class TellStore:
    """SQLite storage for tells"""
    
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS tells (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_agent TEXT NOT NULL,
        to_agent TEXT NOT NULL,
        content TEXT NOT NULL,
        priority TEXT NOT NULL DEFAULT 'normal',
        created_at TEXT NOT NULL,
        read_at TEXT,
        expires_at TEXT,
        ack_required INTEGER DEFAULT 0,
        meta TEXT DEFAULT '{}'
    );
    
    CREATE INDEX IF NOT EXISTS idx_tells_to_agent ON tells(to_agent);
    CREATE INDEX IF NOT EXISTS idx_tells_read_at ON tells(read_at);
    CREATE INDEX IF NOT EXISTS idx_tells_priority ON tells(priority);
    """
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize tell tables"""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(self.SCHEMA)
    
    def _row_to_tell(self, row: tuple) -> Tell:
        """Convert database row to Tell object"""
        return Tell(
            id=row[0],
            from_agent=row[1],
            to_agent=row[2],
            content=row[3],
            priority=TellPriority(row[4]),
            created_at=row[5],
            read_at=row[6],
            expires_at=row[7],
            ack_required=bool(row[8]),
            meta=json.loads(row[9]) if row[9] else {}
        )
    
    def send(self, from_agent: str, to_agent: str, content: str,
             priority: TellPriority = TellPriority.NORMAL,
             expires_at: str = None, ack_required: bool = False,
             meta: Dict = None) -> Tell:
        """Send a tell to an agent"""
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(meta or {})
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO tells 
                (from_agent, to_agent, content, priority, created_at, expires_at, ack_required, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (from_agent, to_agent, content, priority.value, now, expires_at, int(ack_required), meta_json))
            
            tell_id = cursor.lastrowid
            
            tell = Tell(
                id=tell_id,
                from_agent=from_agent,
                to_agent=to_agent,
                content=content,
                priority=priority,
                created_at=now,
                expires_at=expires_at,
                ack_required=ack_required,
                meta=meta or {}
            )
        
        # Trigger hooks (outside transaction)
        try:
            hook_manager = get_hook_manager()
            hook_manager.trigger(tell)
        except Exception:
            pass  # Don't fail send if hook fails
        
        return tell
    
    def get_unread(self, agent_id: str, priority: TellPriority = None,
                   include_broadcast: bool = True) -> List[Tell]:
        """Get unread tells for an agent"""
        now = datetime.now(timezone.utc).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Build query
            conditions = ["read_at IS NULL"]
            params = []
            
            # Agent filter (including @all broadcasts)
            if include_broadcast:
                conditions.append("(to_agent = ? OR to_agent = '@all')")
            else:
                conditions.append("to_agent = ?")
            params.append(agent_id)
            
            # Priority filter
            if priority:
                conditions.append("priority = ?")
                params.append(priority.value)
            
            # Expiration filter
            conditions.append("(expires_at IS NULL OR expires_at > ?)")
            params.append(now)
            
            query = f"""
                SELECT id, from_agent, to_agent, content, priority, 
                       created_at, read_at, expires_at, ack_required, meta
                FROM tells 
                WHERE {' AND '.join(conditions)}
                ORDER BY 
                    CASE priority 
                        WHEN 'urgent' THEN 0 
                        WHEN 'normal' THEN 1 
                        ELSE 2 
                    END,
                    created_at DESC
            """
            
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_tell(tuple(row)) for row in rows]
    
    def get_urgent_unread(self, agent_id: str) -> List[Tell]:
        """Get only urgent unread tells"""
        return self.get_unread(agent_id, priority=TellPriority.URGENT)
    
    def mark_read(self, tell_ids: List[int]) -> int:
        """Mark tells as read"""
        if not tell_ids:
            return 0
        
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ','.join('?' * len(tell_ids))
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(f"""
                UPDATE tells SET read_at = ?
                WHERE id IN ({placeholders}) AND read_at IS NULL
            """, [now] + tell_ids)
            return cursor.rowcount
    
    def mark_all_read(self, agent_id: str) -> int:
        """Mark all tells for an agent as read"""
        now = datetime.now(timezone.utc).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE tells SET read_at = ?
                WHERE (to_agent = ? OR to_agent = '@all') AND read_at IS NULL
            """, (now, agent_id))
            return cursor.rowcount
    
    def get_all(self, agent_id: str, limit: int = 50) -> List[Tell]:
        """Get all tells for an agent (read and unread)"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT id, from_agent, to_agent, content, priority,
                       created_at, read_at, expires_at, ack_required, meta
                FROM tells
                WHERE to_agent = ? OR to_agent = '@all'
                ORDER BY created_at DESC
                LIMIT ?
            """, (agent_id, limit)).fetchall()
            return [self._row_to_tell(row) for row in rows]
    
    def delete_expired(self) -> int:
        """Delete expired tells"""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                DELETE FROM tells WHERE expires_at IS NOT NULL AND expires_at < ?
            """, (now,))
            return cursor.rowcount
    
    def stats(self, agent_id: str = None) -> Dict:
        """Get tell statistics"""
        with sqlite3.connect(self.db_path) as conn:
            if agent_id:
                total = conn.execute("""
                    SELECT COUNT(*) FROM tells WHERE to_agent = ? OR to_agent = '@all'
                """, (agent_id,)).fetchone()[0]
                unread = conn.execute("""
                    SELECT COUNT(*) FROM tells 
                    WHERE (to_agent = ? OR to_agent = '@all') AND read_at IS NULL
                """, (agent_id,)).fetchone()[0]
            else:
                total = conn.execute("SELECT COUNT(*) FROM tells").fetchone()[0]
                unread = conn.execute("SELECT COUNT(*) FROM tells WHERE read_at IS NULL").fetchone()[0]
            
            return {
                "total": total,
                "unread": unread,
                "read": total - unread
            }


def format_tells_for_injection(tells: List[Tell]) -> str:
    """Format tells as a header block for file injection"""
    if not tells:
        return ""
    
    lines = [
        "# ⚠️ UNREAD MESSAGES",
        ""
    ]
    
    for tell in tells:
        lines.append(tell.format_header())
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    return "\n".join(lines)


def format_inbox(tells: List[Tell], show_read: bool = False) -> str:
    """Format tells for inbox view"""
    if not tells:
        return "# 📬 Inbox\n\nNo messages.\n"
    
    lines = ["# 📬 Inbox", ""]
    
    unread = [t for t in tells if not t.read_at]
    read = [t for t in tells if t.read_at]
    
    if unread:
        lines.append(f"## Unread ({len(unread)})")
        lines.append("")
        for tell in unread:
            lines.append(tell.format_header())
            lines.append("")
    
    if show_read and read:
        lines.append(f"## Read ({len(read)})")
        lines.append("")
        for tell in read[:10]:  # Limit read messages
            lines.append(tell.format_header())
            lines.append("")
    
    return "\n".join(lines)


# ============================================================
# Hook System
# ============================================================

class HookType(Enum):
    """Types of hooks that can be triggered"""
    SHELL = "shell"     # Execute shell command
    HTTP = "http"       # POST to webhook URL
    OPENCLAW = "openclaw"  # Send via OpenClaw sessions_send


@dataclass
class HookConfig:
    """Configuration for a single hook"""
    type: HookType
    target: str  # Command, URL, or session key
    enabled: bool = True
    timeout: int = 10  # seconds
    
    def __post_init__(self):
        if isinstance(self.type, str):
            self.type = HookType(self.type)


class HookManager:
    """
    Manages hooks for tell notifications.
    
    Config example (in avm.yaml or hooks.yaml):
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
      akashi:
        on_tell:
          type: openclaw
          target: "agent:akashi"
    ```
    
    Or via virtual files:
    ```bash
    echo "shell:openclaw notify kearsarge" > avm/hooks/kearsarge
    echo "http:http://localhost:3000/webhook" > avm/hooks/yuze
    ```
    """
    
    def __init__(self, config: Dict[str, Dict] = None, db_path: str = None):
        self._hooks: Dict[str, HookConfig] = {}
        self._db_path = db_path
        if db_path:
            self._init_db()
            self._load_from_db()
        if config:
            self._load_config(config)
    
    def _init_db(self):
        """Initialize hooks table"""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hooks (
                    agent_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    target TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    timeout INTEGER DEFAULT 10,
                    created_at TEXT
                )
            """)
    
    def _load_from_db(self):
        """Load hooks from database"""
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT agent_id, type, target, enabled, timeout FROM hooks"
                ).fetchall()
                for row in rows:
                    self._hooks[row[0]] = HookConfig(
                        type=HookType(row[1]),
                        target=row[2],
                        enabled=bool(row[3]),
                        timeout=row[4]
                    )
        except Exception:
            pass  # Table might not exist yet
    
    def _save_to_db(self, agent_id: str, hook: HookConfig):
        """Save hook to database"""
        if not self._db_path:
            return
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO hooks (agent_id, type, target, enabled, timeout, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (agent_id, hook.type.value, hook.target, int(hook.enabled), hook.timeout, now))
    
    def _delete_from_db(self, agent_id: str):
        """Delete hook from database"""
        if not self._db_path:
            return
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM hooks WHERE agent_id = ?", (agent_id,))
    
    def _load_config(self, config: Dict):
        """Load hooks from config dict"""
        hooks_config = config.get('hooks', {})
        for agent_id, agent_hooks in hooks_config.items():
            if 'on_tell' in agent_hooks:
                hook_data = agent_hooks['on_tell']
                if isinstance(hook_data, str):
                    # Simple format: just a command
                    self._hooks[agent_id] = HookConfig(
                        type=HookType.SHELL,
                        target=hook_data
                    )
                elif isinstance(hook_data, dict):
                    self._hooks[agent_id] = HookConfig(
                        type=HookType(hook_data.get('type', 'shell')),
                        target=hook_data['target'],
                        enabled=hook_data.get('enabled', True),
                        timeout=hook_data.get('timeout', 10)
                    )
    
    def register(self, agent_id: str, hook: HookConfig):
        """Register a hook for an agent"""
        self._hooks[agent_id] = hook
        self._save_to_db(agent_id, hook)
    
    def unregister(self, agent_id: str):
        """Unregister a hook"""
        self._hooks.pop(agent_id, None)
        self._delete_from_db(agent_id)
    
    def list_hooks(self) -> Dict[str, HookConfig]:
        """List all registered hooks"""
        return dict(self._hooks)
    
    @staticmethod
    def parse_hook_string(s: str) -> Optional[HookConfig]:
        """
        Parse hook from string format.
        
        Formats:
            type:target
            type:target?enabled=true&timeout=10
        
        Examples:
            shell:echo hello
            http:http://localhost:3000/webhook
            openclaw:agent:akashi
        """
        s = s.strip()
        if not s or ':' not in s:
            return None
        
        # Parse query params if present
        params = {}
        if '?' in s:
            s, query = s.split('?', 1)
            for part in query.split('&'):
                if '=' in part:
                    k, v = part.split('=', 1)
                    params[k] = v
        
        # Parse type:target
        type_str, target = s.split(':', 1)
        
        try:
            hook_type = HookType(type_str.lower())
        except ValueError:
            return None
        
        return HookConfig(
            type=hook_type,
            target=target,
            enabled=params.get('enabled', 'true').lower() == 'true',
            timeout=int(params.get('timeout', 10))
        )
    
    def format_hook(self, agent_id: str) -> str:
        """Format hook config as string"""
        hook = self._hooks.get(agent_id)
        if not hook:
            return ""
        
        params = []
        if not hook.enabled:
            params.append("enabled=false")
        if hook.timeout != 10:
            params.append(f"timeout={hook.timeout}")
        
        base = f"{hook.type.value}:{hook.target}"
        if params:
            base += "?" + "&".join(params)
        return base
    
    def get_hook(self, agent_id: str) -> Optional[HookConfig]:
        """Get hook config for an agent"""
        return self._hooks.get(agent_id)
    
    def trigger(self, tell: Tell) -> Dict[str, Any]:
        """
        Trigger hooks for a tell.
        Returns results for each triggered hook.
        """
        results = {}
        
        # Get agents to notify
        agents_to_notify = []
        if tell.to_agent == '@all':
            # Trigger all registered hooks
            agents_to_notify = list(self._hooks.keys())
        elif tell.to_agent in self._hooks:
            agents_to_notify = [tell.to_agent]
        
        for agent_id in agents_to_notify:
            hook = self._hooks.get(agent_id)
            if not hook or not hook.enabled:
                continue
            
            try:
                result = self._execute_hook(hook, tell, agent_id)
                results[agent_id] = {"success": True, "result": result}
            except Exception as e:
                results[agent_id] = {"success": False, "error": str(e)}
        
        return results
    
    def _execute_hook(self, hook: HookConfig, tell: Tell, agent_id: str) -> Any:
        """Execute a single hook"""
        if hook.type == HookType.SHELL:
            return self._execute_shell(hook, tell, agent_id)
        elif hook.type == HookType.HTTP:
            return self._execute_http(hook, tell)
        elif hook.type == HookType.OPENCLAW:
            return self._execute_openclaw(hook, tell, agent_id)
        else:
            raise ValueError(f"Unknown hook type: {hook.type}")
    
    def _execute_shell(self, hook: HookConfig, tell: Tell, agent_id: str) -> str:
        """Execute shell command"""
        import subprocess
        import shlex
        
        # Expand variables in command
        cmd = hook.target
        cmd = cmd.replace('${from}', tell.from_agent)
        cmd = cmd.replace('${to}', agent_id)
        cmd = cmd.replace('${priority}', tell.priority.value)
        cmd = cmd.replace('${content}', shlex.quote(tell.content[:100]))
        
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            timeout=hook.timeout,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Command failed: {result.stderr}")
        
        return result.stdout.strip()
    
    def _execute_http(self, hook: HookConfig, tell: Tell) -> Dict:
        """POST to webhook URL"""
        import urllib.request
        import urllib.error
        
        payload = json.dumps({
            "type": "tell",
            "from": tell.from_agent,
            "to": tell.to_agent,
            "content": tell.content,
            "priority": tell.priority.value,
            "created_at": tell.created_at
        }).encode('utf-8')
        
        req = urllib.request.Request(
            hook.target,
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        
        try:
            with urllib.request.urlopen(req, timeout=hook.timeout) as resp:
                return {"status": resp.status, "body": resp.read().decode()}
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"URL error: {e.reason}")
    
    def _execute_openclaw(self, hook: HookConfig, tell: Tell, agent_id: str) -> str:
        """
        Send notification via OpenClaw.
        Requires openclaw CLI to be available.
        """
        import subprocess
        
        message = f"📬 New message from {tell.from_agent}:\n{tell.content}"
        
        # Use openclaw CLI to send
        cmd = [
            "openclaw", "send",
            "--to", hook.target,
            "--message", message
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=hook.timeout,
            text=True
        )
        
        if result.returncode != 0:
            # Fallback: try sessions_send via API if available
            raise RuntimeError(f"OpenClaw send failed: {result.stderr}")
        
        return "sent"


# Global hook manager (can be configured at startup)
_hook_manager: Optional[HookManager] = None


def get_hook_manager() -> HookManager:
    """Get or create the global hook manager"""
    global _hook_manager
    if _hook_manager is None:
        _hook_manager = HookManager()
    return _hook_manager


def set_hook_manager(manager: HookManager):
    """Set the global hook manager"""
    global _hook_manager
    _hook_manager = manager


def configure_hooks(config: Dict):
    """Configure hooks from a config dict"""
    global _hook_manager
    _hook_manager = HookManager(config)
