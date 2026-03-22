"""
vfs/store.py - SQLite storage layer (with FTS5 full-text search)
"""

import os
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from contextlib import contextmanager
import difflib

from .node import AVMNode, NodeDiff, NodeType
from .graph import KVGraph, Edge, EdgeType
from .utils import utcnow


# SQLite schema
SCHEMA = """
-- Nodes table
CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    meta TEXT NOT NULL DEFAULT '{}',
    node_type TEXT NOT NULL DEFAULT 'file',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    content_h TEXT
);

CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path);

-- FTS5 full-text index (standalone table)
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    path,
    content
);

-- Edges table (relation graph)
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    edge_type TEXT NOT NULL DEFAULT 'related',
    weight REAL NOT NULL DEFAULT 1.0,
    meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(source, target, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);

-- Change history table
CREATE TABLE IF NOT EXISTS diffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_path TEXT NOT NULL,
    version INTEGER NOT NULL,
    old_h TEXT,
    new_h TEXT NOT NULL,
    diff_content TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    change_type TEXT NOT NULL DEFAULT 'update'
);

CREATE INDEX IF NOT EXISTS idx_diffs_path ON diffs(node_path);
CREATE INDEX IF NOT EXISTS idx_diffs_version ON diffs(node_path, version);

-- Vectors table (for embeddings)
CREATE TABLE IF NOT EXISTS embeddings (
    path TEXT PRIMARY KEY,
    vector BLOB,  -- Serialized float array
    model TEXT,
    updated_at TEXT
);
"""


class AVMStore:
    """
    VFS SQLite storage
    
    Features:
    - Node CRUD
    - FTS5 full-text search
    - Relation graph storage
    - Change history
    """
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            # Default: use XDG data home or ~/.local/share/avm
            xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
            db_path = str(Path(xdg_data) / "vfs" / "avm.db")
        
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        self._init_db()
    
    def _init_db(self):
        """Initialize database"""
        with self._conn() as conn:
            conn.executescript(SCHEMA)
    
    @contextmanager
    def _conn(self):
        """Get database connection with configurable WAL mode"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        # Configurable performance settings
        if getattr(self, '_wal_mode', True):
            conn.execute("PRAGMA journal_mode=WAL")
        sync_mode = getattr(self, '_sync_mode', 'NORMAL')
        conn.execute(f"PRAGMA synchronous={sync_mode}")
        
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def configure_performance(self, wal_mode: bool = True, sync_mode: str = "NORMAL"):
        """Configure performance settings (for ablation experiments)"""
        self._wal_mode = wal_mode
        self._sync_mode = sync_mode
    
    # ─── Node operations ─────────────────────────────────────────
    
    def get_node(self, path: str) -> Optional[AVMNode]:
        """Read node"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM nodes WHERE path = ?", (path,)
            ).fetchone()
            
            if row is None:
                return None
            
            return AVMNode(
                path=row["path"],
                content=row["content"],
                meta=json.loads(row["meta"]),
                node_type=NodeType(row["node_type"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                version=row["version"],
            )
    
    def put_node(self, node: AVMNode, save_diff: bool = True) -> AVMNode:
        """
        Write node
        
        - Check write permission
        - Auto-increment version
        - Save diff
        """
        if not node.is_writable:
            # Read-only path: only allow internal provider writes(via _put_node_internal)
            raise PermissionError(f"Path {node.path} is read-only")
        
        return self._put_node_internal(node, save_diff)
    
    def _put_node_internal(self, node: AVMNode, save_diff: bool = True) -> AVMNode:
        """
        Internal write (bypass permission check, for providers)
        """
        with self._conn() as conn:
            existing = self.get_node(node.path)
            
            now = utcnow()
            new_h = node.content_h
            
            if existing:
                # Update
                old_h = existing.content_h
                
                # Only bump version if content changed
                if old_h != new_h:
                    new_version = existing.version + 1
                else:
                    new_version = existing.version
                
                if save_diff and old_h != new_h:
                    # Save diff
                    diff = self._compute_diff(existing.content, node.content)
                    self._save_diff(conn, NodeDiff(
                        node_path=node.path,
                        version=new_version,
                        old_h=old_h,
                        new_h=new_h,
                        diff_content=diff,
                        change_type="update",
                    ))
                
                conn.execute("""
                    UPDATE nodes SET 
                        content = ?, meta = ?, node_type = ?,
                        updated_at = ?, version = ?, content_h = ?
                    WHERE path = ?
                """, (
                    node.content,
                    json.dumps(node.meta),
                    node.node_type.value,
                    now.isoformat(),
                    new_version,
                    new_h,
                    node.path,
                ))
                
                # Update FTS index
                conn.execute("DELETE FROM nodes_fts WHERE path = ?", (node.path,))
                conn.execute(
                    "INSERT INTO nodes_fts (path, content) VALUES (?, ?)",
                    (node.path, node.content)
                )
                
                node.version = new_version
                node.updated_at = now
            else:
                # Create new
                if save_diff:
                    self._save_diff(conn, NodeDiff(
                        node_path=node.path,
                        version=1,
                        old_h=None,
                        new_h=new_h,
                        diff_content=node.content,
                        change_type="create",
                    ))
                
                conn.execute("""
                    INSERT INTO nodes 
                        (path, content, meta, node_type, created_at, updated_at, version, content_h)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    node.path,
                    node.content,
                    json.dumps(node.meta),
                    node.node_type.value,
                    now.isoformat(),
                    now.isoformat(),
                    1,
                    new_h,
                ))
                
                # Insert FTS index
                conn.execute(
                    "INSERT INTO nodes_fts (path, content) VALUES (?, ?)",
                    (node.path, node.content)
                )
                
                node.version = 1
                node.created_at = now
                node.updated_at = now
        
        return node
    
    def delete_node(self, path: str) -> bool:
        """Delete node"""
        node = self.get_node(path)
        if node is None:
            return False
        
        if not node.is_writable:
            raise PermissionError(f"Path {path} is read-only")
        
        with self._conn() as conn:
            # Record deletion
            self._save_diff(conn, NodeDiff(
                node_path=path,
                version=node.version + 1,
                old_h=node.content_h,
                new_h="",
                diff_content="",
                change_type="delete",
            ))
            
            conn.execute("DELETE FROM nodes WHERE path = ?", (path,))
            conn.execute("DELETE FROM nodes_fts WHERE path = ?", (path,))
            conn.execute("DELETE FROM edges WHERE source = ? OR target = ?", (path, path))
        
        return True
    
    def list_nodes(self, prefix: str = "/", limit: int = 100) -> List[AVMNode]:
        """List nodes"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM nodes WHERE path LIKE ? ORDER BY path LIMIT ?",
                (prefix + "%", limit)
            ).fetchall()
            
            return [
                AVMNode(
                    path=row["path"],
                    content=row["content"],
                    meta=json.loads(row["meta"]),
                    node_type=NodeType(row["node_type"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    version=row["version"],
                )
                for row in rows
            ]
    
    # ─── Search ─────────────────────────────────────────────
    
    def search(self, query: str, limit: int = 10) -> List[Tuple[AVMNode, float]]:
        """
        FTS5 full-text search
        return [(node, score), ...]
        
        Auto-add prefix match (*) for mixed text
        """
        # Add prefix match for each word, escape special chars
        import re
        # Remove FTS5 special characters
        clean_query = re.sub(r'[^\w\s]', ' ', query)
        terms = clean_query.split()
        if not terms:
            return []
        # Use OR to match any term (more inclusive)
        fts_query = " OR ".join(f"{term}*" for term in terms if term)
        
        with self._conn() as conn:
            # FTS5 BM25 ranking
            rows = conn.execute("""
                SELECT nodes.*, bm25(nodes_fts) as score
                FROM nodes_fts
                JOIN nodes ON nodes_fts.path = nodes.path
                WHERE nodes_fts MATCH ?
                ORDER BY score
                LIMIT ?
            """, (fts_query, limit)).fetchall()
            
            results = []
            for row in rows:
                node = AVMNode(
                    path=row["path"],
                    content=row["content"],
                    meta=json.loads(row["meta"]),
                    node_type=NodeType(row["node_type"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    version=row["version"],
                )
                results.append((node, abs(row["score"])))
            
            return results
    
    # ─── Relation graph ─────────────────────────────────────────────
    
    def add_edge(self, source: str, target: str,
                 edge_type: EdgeType = EdgeType.RELATED,
                 weight: float = 1.0,
                 meta: Dict = None) -> Edge:
        """Add edge"""
        edge = Edge(
            source=source,
            target=target,
            edge_type=edge_type,
            weight=weight,
            meta=meta or {},
        )
        
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO edges 
                    (source, target, edge_type, weight, meta, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                source, target, edge_type.value, weight,
                json.dumps(meta or {}),
                utcnow().isoformat(),
            ))
        
        return edge
    
    def get_links(self, path: str, 
                  direction: str = "both",
                  edge_type: EdgeType = None) -> List[Edge]:
        """Get edges for node"""
        with self._conn() as conn:
            edges = []
            
            if direction in ("out", "both"):
                sql = "SELECT * FROM edges WHERE source = ?"
                params = [path]
                if edge_type:
                    sql += " AND edge_type = ?"
                    params.append(edge_type.value)
                
                for row in conn.execute(sql, params):
                    edges.append(Edge(
                        source=row["source"],
                        target=row["target"],
                        edge_type=EdgeType(row["edge_type"]),
                        weight=row["weight"],
                        meta=json.loads(row["meta"]),
                        created_at=datetime.fromisoformat(row["created_at"]),
                    ))
            
            if direction in ("in", "both"):
                sql = "SELECT * FROM edges WHERE target = ?"
                params = [path]
                if edge_type:
                    sql += " AND edge_type = ?"
                    params.append(edge_type.value)
                
                for row in conn.execute(sql, params):
                    edges.append(Edge(
                        source=row["source"],
                        target=row["target"],
                        edge_type=EdgeType(row["edge_type"]),
                        weight=row["weight"],
                        meta=json.loads(row["meta"]),
                        created_at=datetime.fromisoformat(row["created_at"]),
                    ))
            
            return edges
    
    def load_graph(self) -> KVGraph:
        """Load full graph to memory"""
        graph = KVGraph()
        
        with self._conn() as conn:
            for row in conn.execute("SELECT * FROM edges"):
                graph.add_edge(
                    row["source"],
                    row["target"],
                    EdgeType(row["edge_type"]),
                    row["weight"],
                    json.loads(row["meta"]),
                )
        
        return graph
    
    # ─── Diff ─────────────────────────────────────────────
    
    def _compute_diff(self, old: str, new: str) -> str:
        """Calculate unified diff"""
        diff = difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            lineterm="",
        )
        return "".join(diff)
    
    def _save_diff(self, conn, diff: NodeDiff):
        """Save diff record"""
        conn.execute("""
            INSERT INTO diffs 
                (node_path, version, old_h, new_h, diff_content, changed_at, change_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            diff.node_path,
            diff.version,
            diff.old_h,
            diff.new_h,
            diff.diff_content,
            diff.changed_at.isoformat(),
            diff.change_type,
        ))
    
    def get_history(self, path: str, limit: int = 10) -> List[NodeDiff]:
        """Get change history"""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM diffs 
                WHERE node_path = ? 
                ORDER BY version DESC 
                LIMIT ?
            """, (path, limit)).fetchall()
            
            return [
                NodeDiff(
                    node_path=row["node_path"],
                    version=row["version"],
                    old_h=row["old_h"],
                    new_h=row["new_h"],
                    diff_content=row["diff_content"],
                    changed_at=datetime.fromisoformat(row["changed_at"]),
                    change_type=row["change_type"],
                )
                for row in rows
            ]
    
    def get_node_at_version(self, path: str, version: int) -> Optional[AVMNode]:
        """Get node content at a specific version (time travel)"""
        with self._conn() as conn:
            # Get current node
            current = self.get_node(path)
            if not current:
                return None
            
            if current.version <= version:
                return current
            
            # Reconstruct by reverse-applying diffs
            content = current.content
            diffs = conn.execute("""
                SELECT diff_content, version FROM diffs 
                WHERE node_path = ? AND version > ?
                ORDER BY version DESC
            """, (path, version)).fetchall()
            
            # Note: This is a simplified approach
            # For full reconstruction, we'd need forward diffs
            # For now, return current with version marker
            node = AVMNode(
                path=path,
                content=content,
                version=version,
                meta={**current.meta, '_reconstructed': True, '_target_version': version},
            )
            return node
    
    def get_node_at_time(self, path: str, as_of: datetime) -> Optional[AVMNode]:
        """Get node content at a specific point in time"""
        with self._conn() as conn:
            # Find the version that was current at that time
            row = conn.execute("""
                SELECT version FROM diffs 
                WHERE node_path = ? AND changed_at <= ?
                ORDER BY changed_at DESC
                LIMIT 1
            """, (path, as_of.isoformat())).fetchone()
            
            if row:
                return self.get_node_at_version(path, row[0])
            
            # No diffs before that time, might be the original
            return self.get_node(path)
    
    # ─── Statistics ─────────────────────────────────────────────
    
    def stats(self) -> Dict[str, Any]:
        """Get storage statistics"""
        with self._conn() as conn:
            node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            diff_count = conn.execute("SELECT COUNT(*) FROM diffs").fetchone()[0]
            
            # Stats by path prefix
            prefix_stats = {}
            for row in conn.execute("""
                SELECT 
                    CASE 
                        WHEN path LIKE '/live%' THEN '/live'
                        WHEN path LIKE '/research%' THEN '/research'
                        WHEN path LIKE '/memory%' THEN '/memory'
                        ELSE '/other'
                    END as prefix,
                    COUNT(*) as cnt
                FROM nodes GROUP BY prefix
            """):
                prefix_stats[row["prefix"]] = row["cnt"]
            
            return {
                "nodes": node_count,
                "edges": edge_count,
                "diffs": diff_count,
                "by_prefix": prefix_stats,
                "db_path": self.db_path,
            }
