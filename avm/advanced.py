"""
vfs/advanced.py - Advanced Memory Features

Features:
- Subscription/Notification system
- Memory decay (weight reduction over time)
- Memory compaction (summarize old versions)
- Semantic deduplication
- Derived links (reasoning chains)
- Time-based queries
"""

import fnmatch
import math
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable, Set, Tuple
from enum import Enum

from .store import AVMStore
from .node import AVMNode
from .graph import EdgeType
from .utils import utcnow


# ═══════════════════════════════════════════════════════════════
# Cross-VFS Sync
# ═══════════════════════════════════════════════════════════════

class SyncManager:
    """
    Cross-VFS synchronization
    
    Supports:
    - File-based sync (local directory)
    - S3-compatible sync (with boto3)
    - Conflict resolution: append (default) or last-write-wins
    """
    
    def __init__(self, store: AVMStore):
        self.store = store
    
    def sync_to_directory(self, directory: str, 
                          prefix: str = "/memory") -> Dict[str, int]:
        """
        Sync to local directory
        
        Returns: {"exported": N, "imported": N, "conflicts": N}
        """
        from pathlib import Path
        import json
        
        dir_path = Path(directory)
        dir_path.mkdir(parents=True, exist_ok=True)
        
        stats = {"exported": 0, "imported": 0, "conflicts": 0}
        
        # Export local nodes
        nodes = self.store.list_nodes(prefix, limit=10000)
        local_paths = {}
        
        for node in nodes:
            # Convert path to file path
            rel_path = node.path.lstrip("/").replace("/", "_") + ".json"
            file_path = dir_path / rel_path
            
            # Check for conflict
            if file_path.exists():
                existing = json.loads(file_path.read_text())
                if existing.get("updated_at", "") > node.updated_at.isoformat():
                    # Remote is newer, will import later
                    stats["conflicts"] += 1
                    continue
            
            # Write
            data = {
                "path": node.path,
                "content": node.content,
                "meta": node.meta,
                "updated_at": node.updated_at.isoformat(),
                "version": node.version,
            }
            file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            local_paths[node.path] = True
            stats["exported"] += 1
        
        # Import remote nodes
        for file_path in dir_path.glob("*.json"):
            try:
                data = json.loads(file_path.read_text())
                path = data.get("path")
                
                if path and path not in local_paths:
                    node = AVMNode(
                        path=path,
                        content=data.get("content", ""),
                        meta=data.get("meta", {}),
                    )
                    self.store.put_node(node)
                    stats["imported"] += 1
            except Exception as e:
                print(f"Import error {file_path}: {e}")
        
        return stats
    
    def sync_to_s3(self, bucket: str, prefix: str = "vfs/",
                   memory_prefix: str = "/memory") -> Dict[str, int]:
        """
        Sync to S3-compatible storage
        
        Requires: pip install boto3
        """
        try:
            import boto3
        except ImportError:
            raise RuntimeError("boto3 required: pip install boto3")
        
        import json
        
        s3 = boto3.client("s3")
        stats = {"exported": 0, "imported": 0, "conflicts": 0}
        
        # Get local nodes
        nodes = self.store.list_nodes(memory_prefix, limit=10000)
        local_paths = {}
        
        for node in nodes:
            key = prefix + node.path.lstrip("/").replace("/", "_") + ".json"
            
            # Check if exists in S3
            try:
                response = s3.get_object(Bucket=bucket, Key=key)
                existing = json.loads(response["Body"].read())
                
                if existing.get("updated_at", "") > node.updated_at.isoformat():
                    stats["conflicts"] += 1
                    continue
            except s3.exceptions.NoSuchKey:
                pass
            except Exception:
                pass
            
            # Upload
            data = {
                "path": node.path,
                "content": node.content,
                "meta": node.meta,
                "updated_at": node.updated_at.isoformat(),
                "version": node.version,
            }
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(data, ensure_ascii=False),
                ContentType="application/json",
            )
            local_paths[node.path] = True
            stats["exported"] += 1
        
        # Import from S3
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                try:
                    response = s3.get_object(Bucket=bucket, Key=obj["Key"])
                    data = json.loads(response["Body"].read())
                    path = data.get("path")
                    
                    if path and path not in local_paths:
                        node = AVMNode(
                            path=path,
                            content=data.get("content", ""),
                            meta=data.get("meta", {}),
                        )
                        self.store.put_node(node)
                        stats["imported"] += 1
                except Exception as e:
                    print(f"S3 import error: {e}")
        
        return stats


# ═══════════════════════════════════════════════════════════════
# Subscription System
# ═══════════════════════════════════════════════════════════════

class EventType(Enum):
    WRITE = "write"
    DELETE = "delete"
    LINK = "link"


@dataclass
class MemoryEvent:
    """Memory change event"""
    event_type: EventType
    path: str
    agent_id: str
    timestamp: datetime = field(default_factory=utcnow)
    data: Dict = field(default_factory=dict)


Callback = Callable[[MemoryEvent], None]


class SubscriptionManager:
    """
    Subscription system for memory changes
    
    Usage:
        sub_mgr = SubscriptionManager()
        
        def on_market_update(event):
            print(f"Market update: {event.path}")
        
        sub_mgr.subscribe("/memory/shared/market/*", on_market_update)
        
        # Later, when write happens:
        sub_mgr.notify(MemoryEvent(
            event_type=EventType.WRITE,
            path="/memory/shared/market/BTC.md",
            agent_id="akashi"
        ))
    """
    
    def __init__(self):
        self._subscriptions: Dict[str, List[Tuple[str, Callback]]] = {}
        # pattern -> [(subscriber_id, callback), ...]
        self._subscriber_count = 0
    
    def subscribe(self, pattern: str, callback: Callback, 
                  subscriber_id: str = None) -> str:
        """
        Subscribe to path pattern
        
        Args:
            pattern: Glob pattern (e.g., "/memory/shared/market/*")
            callback: Function to call on match
            subscriber_id: Optional ID (auto-generated if not provided)
        
        Returns:
            Subscriber ID for unsubscribe
        """
        if subscriber_id is None:
            self._subscriber_count += 1
            subscriber_id = f"sub_{self._subscriber_count}"
        
        if pattern not in self._subscriptions:
            self._subscriptions[pattern] = []
        
        self._subscriptions[pattern].append((subscriber_id, callback))
        return subscriber_id
    
    def unsubscribe(self, subscriber_id: str, pattern: str = None):
        """Unsubscribe by ID"""
        patterns = [pattern] if pattern else list(self._subscriptions.keys())
        
        for p in patterns:
            if p in self._subscriptions:
                self._subscriptions[p] = [
                    (sid, cb) for sid, cb in self._subscriptions[p]
                    if sid != subscriber_id
                ]
    
    def notify(self, event: MemoryEvent):
        """Notify all matching subscribers"""
        for pattern, subscribers in self._subscriptions.items():
            if fnmatch.fnmatch(event.path, pattern):
                for subscriber_id, callback in subscribers:
                    try:
                        callback(event)
                    except Exception as e:
                        # Log but don't crash
                        print(f"Subscription callback error: {e}")
    
    def list_subscriptions(self) -> Dict[str, int]:
        """List patterns and subscriber counts"""
        return {p: len(subs) for p, subs in self._subscriptions.items()}


# ═══════════════════════════════════════════════════════════════
# Memory Decay
# ═══════════════════════════════════════════════════════════════

class MemoryDecay:
    """
    Memory decay system
    
    Reduces effective weight of unaccessed memories over time.
    Does NOT delete - just affects recall ranking.
    """
    
    def __init__(self, store: AVMStore, half_life_days: float = 7.0):
        """
        Args:
            store: VFS store
            half_life_days: Time for weight to halve (default 7 days)
        """
        self.store = store
        self.half_life_days = half_life_days
        self._decay_constant = math.log(2) / (half_life_days * 24 * 3600)
    
    def calculate_decay(self, node: AVMNode, 
                        reference_time: datetime = None) -> float:
        """
        Calculate decay factor for a node
        
        Returns: Factor between 0 and 1 (1 = no decay)
        """
        from datetime import timezone
        
        if reference_time is None:
            reference_time = utcnow()
        
        # Use last_accessed if available, else updated_at
        last_access = node.meta.get("last_accessed")
        if last_access:
            try:
                last_time = datetime.fromisoformat(last_access)
            except:
                last_time = node.updated_at
        else:
            last_time = node.updated_at
        
        # Ensure both are timezone-aware for comparison
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        
        # Calculate time since last access
        delta_seconds = (reference_time - last_time).total_seconds()
        
        # Exponential decay
        decay_factor = math.exp(-self._decay_constant * delta_seconds)
        
        return decay_factor
    
    def apply_decay(self, nodes: List[AVMNode]) -> List[Tuple[AVMNode, float]]:
        """
        Apply decay to list of nodes
        
        Returns: [(node, decayed_weight), ...] sorted by decayed weight
        """
        now = utcnow()
        
        decayed = []
        for node in nodes:
            base_importance = node.meta.get("importance", 0.5)
            decay = self.calculate_decay(node, now)
            decayed_weight = base_importance * decay
            decayed.append((node, decayed_weight))
        
        # Sort by decayed weight descending
        decayed.sort(key=lambda x: x[1], reverse=True)
        return decayed
    
    def get_cold_memories(self, prefix: str = "/memory",
                          threshold: float = 0.1,
                          limit: int = 100) -> List[AVMNode]:
        """Get memories that have decayed below threshold"""
        nodes = self.store.list_nodes(prefix, limit=1000)
        
        cold = []
        for node in nodes:
            decay = self.calculate_decay(node)
            importance = node.meta.get("importance", 0.5)
            if importance * decay < threshold:
                cold.append(node)
        
        return cold[:limit]


# ═══════════════════════════════════════════════════════════════
# Memory Compaction
# ═══════════════════════════════════════════════════════════════

@dataclass
class CompactionResult:
    """Result of memory compaction"""
    base_path: str
    versions_before: int
    versions_after: int
    summary_path: str
    removed_paths: List[str]


class MemoryCompactor:
    """
    Compacts old versions into summaries
    
    Keeps recent N versions, summarizes older ones.
    """
    
    def __init__(self, store: AVMStore, summarizer: Callable = None):
        """
        Args:
            store: VFS store
            summarizer: Optional function (List[str]) -> str for custom summarization
        """
        self.store = store
        self.summarizer = summarizer or self._default_summarizer
    
    def _default_summarizer(self, contents: List[str]) -> str:
        """Default summarizer: concatenate with markers"""
        summary_parts = []
        for i, content in enumerate(contents):
            # Extract key lines (non-empty, non-header)
            lines = [l.strip() for l in content.split("\n") 
                    if l.strip() and not l.startswith("#") and not l.startswith("*")]
            if lines:
                summary_parts.append(" | ".join(lines[:3]))
        
        return "**Compacted summary:**\n\n" + "\n\n".join(summary_parts)
    
    def compact(self, base_path: str, keep_recent: int = 3) -> CompactionResult:
        """
        Compact versions of a path
        
        Args:
            base_path: Base path to compact
            keep_recent: Numbeenr of recent versions to keep
        
        Returns:
            CompactionResult
        """
        # Get all versions
        versions = self._get_versions(base_path)
        
        if len(versions) <= keep_recent:
            return CompactionResult(
                base_path=base_path,
                versions_before=len(versions),
                versions_after=len(versions),
                summary_path="",
                removed_paths=[],
            )
        
        # Sort by date (newest first)
        versions.sort(key=lambda n: n.meta.get("created_at", ""), reverse=True)
        
        # Keep recent, compact old
        to_keep = versions[:keep_recent]
        to_compact = versions[keep_recent:]
        
        # Generate summary
        contents = [n.content for n in to_compact]
        summary = self.summarizer(contents)
        
        # Create summary node
        timestamp = utcnow().strftime("%Y%m%d_%H%M%S")
        base_name = base_path.rsplit(".", 1)[0]
        summary_path = f"{base_name}.summary_{timestamp}.md"
        
        summary_node = AVMNode(
            path=summary_path,
            content=summary,
            meta={
                "type": "compaction_summary",
                "base_path": base_path,
                "compacted_versions": len(to_compact),
                "created_at": utcnow().isoformat(),
            }
        )
        self.store.put_node(summary_node)
        
        # Remove old versions (optional - could also just mark as compacted)
        removed = []
        for node in to_compact:
            self.store.delete_node(node.path)
            removed.append(node.path)
        
        return CompactionResult(
            base_path=base_path,
            versions_before=len(versions),
            versions_after=len(to_keep) + 1,  # kept + summary
            summary_path=summary_path,
            removed_paths=removed,
        )
    
    def _get_versions(self, base_path: str) -> List[AVMNode]:
        """Get all versions of a path"""
        # Get base
        base = self.store.get_node(base_path)
        versions = [base] if base else []
        
        # Get version links
        edges = self.store.get_links(base_path, direction="in")
        for edge in edges:
            if edge.edge_type.value == "version_of":
                node = self.store.get_node(edge.source)
                if node:
                    versions.append(node)
        
        return versions


# ═══════════════════════════════════════════════════════════════
# Semantic Deduplication
# ═══════════════════════════════════════════════════════════════

@dataclass
class DedupeResult:
    """Result of deduplication check"""
    is_duplicate: bool
    similar_path: Optional[str] = None
    similarity: float = 0.0
    action: str = "write"  # "write" | "skip" | "merge"


class SemanticDeduplicator:
    """
    Checks for semantically similar memories before writing
    
    Uses either:
    - Embedding similarity (if available)
    - Text fingerprinting (fallback)
    """
    
    def __init__(self, store: AVMStore, embedding_store = None):
        self.store = store
        self.embedding_store = embedding_store
    
    def check_duplicate(self, content: str, 
                        prefix: str = "/memory",
                        threshold: float = 0.85) -> DedupeResult:
        """
        Check if content is similar to existing memories
        
        Args:
            content: New content to check
            prefix: Path prefix to search
            threshold: Similarity threshold (0-1)
        
        Returns:
            DedupeResult
        """
        # Try embedding-based similarity first
        if self.embedding_store:
            return self._check_embedding(content, prefix, threshold)
        
        # Fallback to text fingerprinting
        return self._check_fingerprint(content, prefix, threshold)
    
    def _check_embedding(self, content: str, prefix: str, 
                         threshold: float) -> DedupeResult:
        """Check using embedding similarity"""
        results = self.embedding_store.search(content, k=3, prefix=prefix)
        
        for node, similarity in results:
            if similarity >= threshold:
                return DedupeResult(
                    is_duplicate=True,
                    similar_path=node.path,
                    similarity=similarity,
                    action="skip",
                )
        
        return DedupeResult(is_duplicate=False, action="write")
    
    def _check_fingerprint(self, content: str, prefix: str,
                           threshold: float) -> DedupeResult:
        """Check using text fingerprinting (simh-like)"""
        new_shingles = self._get_shingles(content)
        
        nodes = self.store.list_nodes(prefix, limit=500)
        
        for node in nodes:
            existing_shingles = self._get_shingles(node.content)
            similarity = self._jaccard_similarity(new_shingles, existing_shingles)
            
            if similarity >= threshold:
                return DedupeResult(
                    is_duplicate=True,
                    similar_path=node.path,
                    similarity=similarity,
                    action="skip",
                )
        
        return DedupeResult(is_duplicate=False, action="write")
    
    def _get_shingles(self, text: str, k: int = 3) -> Set[str]:
        """Get k-shingles from text"""
        # Normalize
        text = text.lower()
        words = text.split()
        
        shingles = set()
        for i in range(len(words) - k + 1):
            shingle = " ".join(words[i:i+k])
            shingles.add(shingle)
        
        return shingles
    
    def _jaccard_similarity(self, a: Set[str], b: Set[str]) -> float:
        """Calculate Jaccard similarity"""
        if not a or not b:
            return 0.0
        
        intersection = len(a & b)
        union = len(a | b)
        
        return intersection / union if union > 0 else 0.0


# ═══════════════════════════════════════════════════════════════
# Derived Links (Reasoning Chains)
# ═══════════════════════════════════════════════════════════════

class DerivedLinkManager:
    """
    Manages derived/reasoning chain links
    
    When an agent writes a conclusion, link it to source memories.
    """
    
    def __init__(self, store: AVMStore):
        self.store = store
    
    def link_derived(self, derived_path: str, 
                     source_paths: List[str],
                     reasoning: str = None):
        """
        Link a derived memory to its sources
        
        Args:
            derived_path: Path of the derived/conclusion memory
            source_paths: Paths of source memories
            reasoning: Optional reasoning description
        """
        for source_path in source_paths:
            self.store.add_edge(
                derived_path,
                source_path,
                EdgeType.DERIVED,
                weight=1.0,
                meta={"reasoning": reasoning} if reasoning else {},
            )
    
    def get_derivation_chain(self, path: str, 
                             max_depth: int = 5) -> List[List[str]]:
        """
        Get the derivation chain for a memory
        
        Returns: List of paths from conclusion back to sources
        """
        chains = []
        self._trace_chain(path, [], chains, max_depth)
        return chains
    
    def _trace_chain(self, path: str, current_chain: List[str],
                     all_chains: List[List[str]], max_depth: int):
        """Recursively trace derivation chain"""
        current_chain = current_chain + [path]
        
        if len(current_chain) > max_depth:
            all_chains.append(current_chain)
            return
        
        # Get sources
        edges = self.store.get_links(path, direction="out")
        derived_edges = [e for e in edges if e.edge_type == EdgeType.DERIVED]
        
        if not derived_edges:
            # End of chain
            all_chains.append(current_chain)
            return
        
        for edge in derived_edges:
            self._trace_chain(edge.target, current_chain, all_chains, max_depth)
    
    def get_derived_from(self, source_path: str) -> List[AVMNode]:
        """Get all memories derived from a source"""
        edges = self.store.get_links(source_path, direction="in")
        derived_edges = [e for e in edges if e.edge_type == EdgeType.DERIVED]
        
        nodes = []
        for edge in derived_edges:
            node = self.store.get_node(edge.source)
            if node:
                nodes.append(node)
        
        return nodes


# ═══════════════════════════════════════════════════════════════
# Time-Based Queries
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# Tag System
# ═══════════════════════════════════════════════════════════════

class TagManager:
    """
    Enhanced tag system
    
    - Query by tag
    - Tag cloud/frequency
    - Auto-tagging suggestions
    """
    
    def __init__(self, store: AVMStore):
        self.store = store
    
    def by_tag(self, tag: str, prefix: str = "/memory",
               limit: int = 100) -> List[AVMNode]:
        """Get all memories with a specific tag"""
        nodes = self.store.list_nodes(prefix, limit=limit * 2)
        
        matched = []
        for node in nodes:
            tags = node.meta.get("tags", [])
            if tag.lower() in [t.lower() for t in tags]:
                matched.append(node)
        
        return matched[:limit]
    
    def tag_cloud(self, prefix: str = "/memory",
                  limit: int = 50) -> Dict[str, int]:
        """Get tag frequency distribution"""
        nodes = self.store.list_nodes(prefix, limit=1000)
        
        tag_counts: Dict[str, int] = {}
        for node in nodes:
            tags = node.meta.get("tags", [])
            for tag in tags:
                tag_lower = tag.lower()
                tag_counts[tag_lower] = tag_counts.get(tag_lower, 0) + 1
        
        # Sort by frequency
        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_tags[:limit])
    
    def find_related_tags(self, tag: str, prefix: str = "/memory") -> Dict[str, int]:
        """Find tags that co-occur with given tag"""
        nodes = self.by_tag(tag, prefix)
        
        co_tags: Dict[str, int] = {}
        for node in nodes:
            tags = node.meta.get("tags", [])
            for t in tags:
                t_lower = t.lower()
                if t_lower != tag.lower():
                    co_tags[t_lower] = co_tags.get(t_lower, 0) + 1
        
        return dict(sorted(co_tags.items(), key=lambda x: x[1], reverse=True))
    
    def suggest_tags(self, content: str, top_k: int = 5) -> List[str]:
        """Suggest tags based on content keywords"""
        # Simple keyword extraction
        words = content.lower().split()
        
        # Filter common words
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "been", "beenen",
                    "have", "", "had", "do", "does", "did", "will", "would",
                    "could", "should", "may", "might", "must", "shall", "can",
                    "to", "of", "in", "for", "on", "with", "at", "by", "from",
                    "as", "into", "through", "during", "before", "after", "above",
                    "below", "between", "under", "again", "further", "then", "once",
                    "and", "but", "or", "nor", "so", "yet", "both", "either",
                    "neither", "not", "only", "own", "same", "than", "too", "very",
                    "just", "also", "now", "here", "there", "when", "where", "why",
                    "how", "all", "each", "every", "both", "few", "more", "most",
                    "other", "some", "such", "no", "any", "this", "that", "these",
                    "those", "i", "you", "he", "she", "it", "we", "they", "me",
                    "him", "her", "us", "them", "my", "your", "his", "its", "our",
                    "their", "what", "which", "who", "whom", "whose"}
        
        # Count words
        word_counts: Dict[str, int] = {}
        for word in words:
            word = ''.join(c for c in word if c.isalnum())
            if word and len(word) > 2 and word not in stopwords:
                word_counts[word] = word_counts.get(word, 0) + 1
        
        # Return top words as suggested tags
        sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in sorted_words[:top_k]]


# ═══════════════════════════════════════════════════════════════
# Access Statistics
# ═══════════════════════════════════════════════════════════════

class AccessStats:
    """
    Track and analyze memory access patterns
    """
    
    def __init__(self, store: AVMStore):
        self.store = store
        self._init_table()
    
    def _init_table(self):
        """Initialize access log table"""
        with self.store._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS access_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    agent_id TEXT,
                    access_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_access_path 
                ON access_log(path)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_access_time 
                ON access_log(timestamp)
            """)
    
    def log_access(self, path: str, agent_id: str = None, 
                   access_type: str = "read"):
        """Log an access event"""
        with self.store._conn() as conn:
            conn.execute("""
                INSERT INTO access_log (path, agent_id, access_type, timestamp)
                VALUES (?, ?, ?, ?)
            """, (path, agent_id, access_type, utcnow().isoformat()))
    
    def hot_paths(self, days: int = 7, limit: int = 10) -> List[Tuple[str, int]]:
        """Get most accessed paths in recent days"""
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        
        with self.store._conn() as conn:
            rows = conn.execute("""
                SELECT path, COUNT(*) as count
                FROM access_log
                WHERE timestamp > ?
                GROUP BY path
                ORDER BY count DESC
                LIMIT ?
            """, (cutoff, limit)).fetchall()
        
        return [(row[0], row[1]) for row in rows]
    
    def cold_paths(self, days: int = 30, prefix: str = "/memory",
                   limit: int = 20) -> List[AVMNode]:
        """Get paths not accessed in recent days"""
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        
        # Get recently accessed paths
        with self.store._conn() as conn:
            rows = conn.execute("""
                SELECT DISTINCT path FROM access_log
                WHERE timestamp > ?
            """, (cutoff,)).fetchall()
        
        recent_paths = {row[0] for row in rows}
        
        # Get all nodes and filter
        nodes = self.store.list_nodes(prefix, limit=limit * 3)
        cold = [n for n in nodes if n.path not in recent_paths]
        
        return cold[:limit]
    
    def access_history(self, path: str, limit: int = 50) -> List[Dict]:
        """Get access history for a path"""
        with self.store._conn() as conn:
            rows = conn.execute("""
                SELECT agent_id, access_type, timestamp
                FROM access_log
                WHERE path = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (path, limit)).fetchall()
        
        return [
            {"agent_id": row[0], "access_type": row[1], "timestamp": row[2]}
            for row in rows
        ]
    
    def agent_activity(self, agent_id: str, days: int = 7) -> Dict[str, int]:
        """Get activity summary for an agent"""
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        
        with self.store._conn() as conn:
            rows = conn.execute("""
                SELECT access_type, COUNT(*) as count
                FROM access_log
                WHERE agent_id = ? AND timestamp > ?
                GROUP BY access_type
            """, (agent_id, cutoff)).fetchall()
        
        return {row[0]: row[1] for row in rows}


# ═══════════════════════════════════════════════════════════════
# Export/Snapshot
# ═══════════════════════════════════════════════════════════════

import json

class ExportManager:
    """
    Export and snapshot functionality
    """
    
    def __init__(self, store: AVMStore):
        self.store = store
    
    def export_jsonl(self, prefix: str = "/memory",
                     agent_id: str = None,
                     limit: int = 10000) -> str:
        """
        Export memories as JSONL
        
        Returns: JSONL string (one JSON object per line)
        """
        nodes = self.store.list_nodes(prefix, limit=limit)
        
        if agent_id:
            nodes = [n for n in nodes 
                    if n.meta.get("author") == agent_id or 
                       n.meta.get("agent") == agent_id]
        
        lines = []
        for node in nodes:
            obj = {
                "path": node.path,
                "content": node.content,
                "meta": node.meta,
                "created_at": node.created_at.isoformat(),
                "updated_at": node.updated_at.isoformat(),
                "version": node.version,
            }
            lines.append(json.dumps(obj, ensure_ascii=False))
        
        return "\n".join(lines)
    
    def export_markdown(self, prefix: str = "/memory",
                        agent_id: str = None) -> str:
        """Export as single markdown document"""
        nodes = self.store.list_nodes(prefix, limit=1000)
        
        if agent_id:
            nodes = [n for n in nodes 
                    if n.meta.get("author") == agent_id or 
                       n.meta.get("agent") == agent_id]
        
        # Sort by path
        nodes.sort(key=lambda n: n.path)
        
        lines = [
            f"# Memory Export",
            f"",
            f"*Exported: {utcnow().isoformat()}*",
            f"*Prefix: {prefix}*",
            f"*Count: {len(nodes)}*",
            "",
            "---",
            "",
        ]
        
        for node in nodes:
            lines.append(f"## {node.path}")
            lines.append("")
            lines.append(f"*Updated: {node.updated_at.isoformat()}*")
            if node.meta.get("tags"):
                lines.append(f"*Tags: {', '.join(node.meta['tags'])}*")
            lines.append("")
            lines.append(node.content)
            lines.append("")
            lines.append("---")
            lines.append("")
        
        return "\n".join(lines)
    
    def import_jsonl(self, jsonl: str) -> int:
        """
        Import memories from JSONL
        
        Returns: Numbeenr of imported nodes
        """
        count = 0
        
        for line in jsonl.strip().split("\n"):
            if not line.strip():
                continue
            
            try:
                obj = json.loads(line)
                node = AVMNode(
                    path=obj["path"],
                    content=obj["content"],
                    meta=obj.get("meta", {}),
                )
                self.store.put_node(node)
                count += 1
            except Exception as e:
                print(f"Import error: {e}")
        
        return count
    
    def snapshot(self, name: str = None) -> str:
        """
        Create a named snapshot
        
        Returns: Snapshot path
        """
        if name is None:
            name = utcnow().strftime("%Y%m%d_%H%M%S")
        
        snapshot_path = f"/snapshots/{name}"
        
        # Get all nodes (exclude snapshots themselves)
        all_nodes = self.store.list_nodes("/", limit=100000)
        nodes = [n for n in all_nodes if not n.path.startswith("/snapshots")]
        
        # Create snapshot metadata
        snapshot_meta = {
            "type": "snapshot",
            "name": name,
            "created_at": utcnow().isoformat(),
            "node_count": len(nodes),
            "paths": [n.path for n in nodes],
        }
        
        snapshot_node = AVMNode(
            path=f"{snapshot_path}/meta.json",
            content=json.dumps(snapshot_meta, indent=2),
            meta={"type": "snapshot_meta"},
        )
        # Use internal method to bypass permission check
        self.store._put_node_internal(snapshot_node)
        
        # Store content
        content_node = AVMNode(
            path=f"{snapshot_path}/content.jsonl",
            content=self.export_jsonl("/"),
            meta={"type": "snapshot_content"},
        )
        self.store._put_node_internal(content_node)
        
        return snapshot_path
    
    def list_snapshots(self) -> List[Dict]:
        """List all snapshots"""
        nodes = self.store.list_nodes("/snapshots", limit=100)
        
        snapshots = []
        for node in nodes:
            if node.path.endswith("/meta.json"):
                try:
                    meta = json.loads(node.content)
                    snapshots.append(meta)
                except:
                    pass
        
        return sorted(snapshots, key=lambda x: x.get("created_at", ""), reverse=True)
    
    def restore_snapshot(self, name: str) -> int:
        """
        Restore from snapshot
        
        Returns: Numbeenr of restored nodes
        """
        content_path = f"/snapshots/{name}/content.jsonl"
        node = self.store.get_node(content_path)
        
        if not node:
            raise ValueError(f"Snapshot not found: {name}")
        
        return self.import_jsonl(node.content)


# ═══════════════════════════════════════════════════════════════
# Time-Based Queries
# ═══════════════════════════════════════════════════════════════

class TimeQuery:
    """
    Time-based memory queries
    """
    
    def __init__(self, store: AVMStore):
        self.store = store
    
    def query(self, prefix: str = "/memory",
              after: datetime = None,
              before: datetime = None,
              time_range: str = None,
              limit: int = 100) -> List[AVMNode]:
        """
        Query memories by time
        
        Args:
            prefix: Path prefix
            after: Only memories after this time
            before: Only memories before this time
            time_range: Shorthand ("last_24h", "last_7d", "last_30d", "today")
            limit: Max results
        
        Returns:
            List of matching nodes, sorted by time (newest first)
        """
        # Parse time_range shorthand
        if time_range:
            after, before = self._parse_time_range(time_range)
        
        # Get all nodes
        nodes = self.store.list_nodes(prefix, limit=limit * 2)
        
        # Filter by time
        filtered = []
        for node in nodes:
            created = node.meta.get("created_at") or node.updated_at.isoformat()
            try:
                node_time = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except:
                node_time = node.updated_at
            
            if after and node_time < after:
                continue
            if before and node_time > before:
                continue
            
            filtered.append((node, node_time))
        
        # Sort by time descending
        filtered.sort(key=lambda x: x[1], reverse=True)
        
        return [n for n, _ in filtered[:limit]]
    
    def _parse_time_range(self, time_range: str) -> Tuple[datetime, datetime]:
        """Parse time range shorthand"""
        now = utcnow()
        
        ranges = {
            "last_1h": timedelta(hours=1),
            "last_24h": timedelta(hours=24),
            "last_7d": timedelta(days=7),
            "last_30d": timedelta(days=30),
            "last_90d": timedelta(days=90),
        }
        
        if time_range in ranges:
            return now - ranges[time_range], now
        
        if time_range == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, now
        
        if time_range == "terday":
            end = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start = end - timedelta(days=1)
            return start, end
        
        # Default: last 7 days
        return now - timedelta(days=7), now
    
    def group_by_date(self, nodes: List[AVMNode]) -> Dict[str, List[AVMNode]]:
        """Group nodes by date"""
        grouped: Dict[str, List[AVMNode]] = {}
        
        for node in nodes:
            created = node.meta.get("created_at") or node.updated_at.isoformat()
            try:
                date_str = created[:10]  # YYYY-MM-DD
            except:
                date_str = "unknown"
            
            if date_str not in grouped:
                grouped[date_str] = []
            grouped[date_str].append(node)
        
        return grouped
