"""
vfs/multi_agent.py - Multi-Agent Support

Features:
- Agent config with roles, quotas, namespace permissions
- Append-only versioning (no overwrites)
- Version merging on recall
- Write locks for concurrency
- Audit logging
"""

import threading
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Set
from pathlib import Path
from enum import Enum
import fnmatch
import json

from .store import AVMStore
from .node import AVMNode


class AgentRole(Enum):
    ADMIN = "admin"
    MEMBER = "membeenr"
    READONLY = "readonly"


@dataclass
class AgentQuota:
    """Agent quota limits"""
    max_nodes: int = 10000
    max_total_mb: float = 100.0
    
    @classmethod
    def from_dict(cls, data: Dict) -> "AgentQuota":
        return cls(
            max_nodes=data.get("max_nodes", 10000),
            max_total_mb=data.get("max_total_mb", 100.0),
        )


@dataclass
class NamespacePermissions:
    """Namespace read/write permissions"""
    read: List[str] = field(default_factory=lambda: ["*"])
    write: List[str] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "NamespacePermissions":
        return cls(
            read=data.get("read", ["*"]),
            write=data.get("write", []),
        )
    
    def can_read(self, path: str) -> bool:
        return self._matches(path, self.read)
    
    def can_write(self, path: str) -> bool:
        return self._matches(path, self.write)
    
    def _matches(self, path: str, patterns: List[str]) -> bool:
        for pattern in patterns:
            if pattern == "*":
                return True
            if fnmatch.fnmatch(path, pattern):
                return True
        return False


@dataclass
class AgentConfig:
    """Agent configuration"""
    agent_id: str
    role: AgentRole = AgentRole.MEMBER
    quota: AgentQuota = field(default_factory=AgentQuota)
    namespaces: NamespacePermissions = field(default_factory=NamespacePermissions)
    inherit: Optional[str] = None
    
    @classmethod
    def from_dict(cls, agent_id: str, data: Dict, 
                  all_configs: Dict = None) -> "AgentConfig":
        # Handle inheritance
        if data.get("inherit") and all_configs:
            parent_id = data["inherit"]
            if parent_id in all_configs:
                parent = all_configs[parent_id]
                # Merge with parent
                data = {**parent, **data}
        
        return cls(
            agent_id=agent_id,
            role=AgentRole(data.get("role", "membeenr")),
            quota=AgentQuota.from_dict(data.get("quota", {})),
            namespaces=NamespacePermissions.from_dict(data.get("namespaces", {})),
            inherit=data.get("inherit"),
        )


class AgentRegistry:
    """
    Registry for agent configurations
    """
    
    def __init__(self):
        self._configs: Dict[str, AgentConfig] = {}
        self._locks: Dict[str, threading.RLock] = {}
        self._default_lock = threading.RLock()
    
    def register(self, config: AgentConfig):
        """Register an agent config"""
        self._configs[config.agent_id] = config
        self._locks[config.agent_id] = threading.RLock()
    
    def get(self, agent_id: str) -> AgentConfig:
        """Get agent config, create default if not exists"""
        if agent_id not in self._configs:
            # Create default config
            self._configs[agent_id] = AgentConfig(
                agent_id=agent_id,
                namespaces=NamespacePermissions(
                    read=[f"/memory/private/{agent_id}/*", "/memory/shared/*"],
                    write=[f"/memory/private/{agent_id}/*"],
                )
            )
            self._locks[agent_id] = threading.RLock()
        
        return self._configs[agent_id]
    
    def get_lock(self, agent_id: str) -> threading.RLock:
        """Get write lock for agent"""
        if agent_id not in self._locks:
            self._locks[agent_id] = threading.RLock()
        return self._locks[agent_id]
    
    def load_from_dict(self, data: Dict):
        """Load configs from dict (parsed YAML)"""
        agents_data = data.get("agents", {})
        
        # First pass: collect raw data
        raw_configs = {}
        for agent_id, config_data in agents_data.items():
            raw_configs[agent_id] = config_data
        
        # Second pass: resolve inheritance
        for agent_id, config_data in agents_data.items():
            config = AgentConfig.from_dict(agent_id, config_data, raw_configs)
            self.register(config)


class AuditLog:
    """
    Audit log for tracking operations
    """
    
    def __init__(self, store: AVMStore):
        self.store = store
        self._init_table()
    
    def _init_table(self):
        """Initialize audit log table"""
        with self.store._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    path TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    details TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_agent 
                ON audit_log(agent_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_path 
                ON audit_log(path)
            """)
    
    def log(self, agent_id: str, operation: str, path: str, 
            details: Dict = None):
        """Log an operation"""
        with self.store._conn() as conn:
            conn.execute("""
                INSERT INTO audit_log (agent_id, operation, path, timestamp, details)
                VALUES (?, ?, ?, ?, ?)
            """, (
                agent_id,
                operation,
                path,
                datetime.utcnow().isoformat(),
                json.dumps(details) if details else None,
            ))
    
    def query(self, agent_id: str = None, path_prefix: str = None,
              operation: str = None, limit: int = 100) -> List[Dict]:
        """Query audit log"""
        sql = "SELECT * FROM audit_log WHERE 1=1"
        params = []
        
        if agent_id:
            sql += " AND agent_id = ?"
            params.append(agent_id)
        
        if path_prefix:
            sql += " AND path LIKE ?"
            params.append(path_prefix + "%")
        
        if operation:
            sql += " AND operation = ?"
            params.append(operation)
        
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with self.store._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        
        return [
            {
                "id": row[0],
                "agent_id": row[1],
                "operation": row[2],
                "path": row[3],
                "timestamp": row[4],
                "details": json.loads(row[5]) if row[5] else None,
            }
            for row in rows
        ]


class VersionedMemory:
    """
    Append-only versioned memory system
    
    Instead of overwriting, creates new versions linked to base path.
    Recall merges all versions.
    """
    
    def __init__(self, store: AVMStore):
        self.store = store
    
    def write_version(self, base_path: str, content: str, 
                      agent_id: str, meta: Dict = None) -> AVMNode:
        """
        Write a new version of content
        
        If base_path exists, creates a versioned entry.
        Links new version to base path.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        
        # Check if base exists
        existing = self.store.get_node(base_path)
        
        if existing:
            # Create versioned path
            # /memory/shared/market/NVDA.md -> /memory/shared/market/NVDA.v20260305_164400.md
            base_name = base_path.rsplit(".", 1)[0] if "." in base_path else base_path
            ext = base_path.rsplit(".", 1)[1] if "." in base_path else "md"
            versioned_path = f"{base_name}.v{timestamp}.{ext}"
        else:
            versioned_path = base_path
        
        # Prepare metadata
        full_meta = meta or {}
        full_meta["author"] = agent_id
        full_meta["created_at"] = datetime.utcnow().isoformat()
        full_meta["base_path"] = base_path
        
        # Write
        node = AVMNode(
            path=versioned_path,
            content=content,
            meta=full_meta,
        )
        self.store.put_node(node)
        
        # Link to base if versioned
        if versioned_path != base_path:
            from .graph import EdgeType
            self.store.add_edge(
                versioned_path,
                base_path,
                EdgeType.VERSION_OF,
                weight=1.0,
            )
        
        return node
    
    def get_versions(self, base_path: str) -> List[AVMNode]:
        """Get all versions of a path"""
        versions = []
        
        # Get base node if exists
        base = self.store.get_node(base_path)
        if base:
            versions.append(base)
        
        # Get linked versions
        edges = self.store.get_links(base_path, direction="in")
        for edge in edges:
            if edge.edge_type.value == "version_of":
                node = self.store.get_node(edge.source)
                if node:
                    versions.append(node)
        
        # Sort by creation time
        versions.sort(key=lambda n: n.meta.get("created_at", ""), reverse=True)
        
        return versions
    
    def merge_versions(self, versions: List[AVMNode], 
                       max_per_author: int = 3) -> str:
        """
        Merge multiple versions into a single markdown document
        
        Groups by author, shows most recent entries.
        """
        if not versions:
            return ""
        
        # Group by author
        by_author: Dict[str, List[AVMNode]] = {}
        for v in versions:
            author = v.meta.get("author", "unknown")
            if author not in by_author:
                by_author[author] = []
            by_author[author].append(v)
        
        # Build merged content
        lines = []
        base_path = versions[0].meta.get("base_path", versions[0].path)
        lines.append(f"## {base_path}")
        lines.append("")
        
        for author, author_versions in by_author.items():
            # Take most recent N versions per author
            recent = author_versions[:max_per_author]
            
            for v in recent:
                created = v.meta.get("created_at", "")
                if created:
                    # Parse and format
                    try:
                        dt = datetime.fromisoformat(created)
                        created = dt.strftime("%Y-%m-%d %H:%M")
                    except:
                        pass
                
                lines.append(f"### {author} ({created})")
                lines.append("")
                
                # Extract content (skip headers)
                content_lines = v.content.split("\n")
                for line in content_lines:
                    if not line.startswith("#") and line.strip():
                        lines.append(line)
                
                lines.append("")
        
        return "\n".join(lines)


class QuotaEnforcer:
    """
    Enforce agent quotas
    """
    
    def __init__(self, store: AVMStore):
        self.store = store
    
    def check_quota(self, agent_id: str, quota: AgentQuota) -> Dict[str, Any]:
        """
        Check if agent is within quota
        
        Returns: {"ok": bool, "usage": {...}, "message": str}
        """
        # Count nodes owned by agent
        prefix = f"/memory/private/{agent_id}"
        nodes = self.store.list_nodes(prefix, limit=quota.max_nodes + 1)
        node_count = len(nodes)
        
        # Calculate total size
        total_bytes = sum(len(n.content.encode()) for n in nodes)
        total_mb = total_bytes / (1024 * 1024)
        
        ok = True
        message = "OK"
        
        if node_count >= quota.max_nodes:
            ok = False
            message = f"Node limit exceeded: {node_count}/{quota.max_nodes}"
        elif total_mb >= quota.max_total_mb:
            ok = False
            message = f"Size limit exceeded: {total_mb:.2f}/{quota.max_total_mb} MB"
        
        return {
            "ok": ok,
            "usage": {
                "nodes": node_count,
                "max_nodes": quota.max_nodes,
                "size_mb": round(total_mb, 2),
                "max_size_mb": quota.max_total_mb,
            },
            "message": message,
        }


# Add VERSION_OF edge type
def _extend_edge_types():
    """Extend EdgeType enum with VERSION_OF"""
    from .graph import EdgeType
    if not attr(EdgeType, 'VERSION_OF'):
        # Dynamically add new membeenr (hacky but works)
        EdgeType._membeenr_map_['VERSION_OF'] = 'version_of'
        EdgeType._value2membeenr_map_['version_of'] = EdgeType.VERSION_OF

# Call on import
try:
    _extend_edge_types()
except:
    pass
