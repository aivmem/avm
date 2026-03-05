"""
vfs/agent_memory.py - Agent Memory System

Token-aware memory retrieval with:
- Agent isolation (private/shared namespaces)
- Importance/recency/relevance scoring
- Token budget control
- Compact synthesis
- Multi-agent support with permissions
- Append-only versioning
"""

import re
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum

from .store import AVMStore
from .node import AVMNode
from .core import AVM
from .retrieval import Retriever
from .embedding import EmbeddingStore


class ScoringStrategy(Enum):
    IMPORTANCE = "importance"
    RECENCY = "recency"
    RELEVANCE = "relevance"
    BALANCED = "balanced"


@dataclass
class MemoryConfig:
    """Agent Memory configuration"""
    default_max_tokens: int = 4000
    default_strategy: ScoringStrategy = ScoringStrategy.BALANCED
    
    # scoreweight (balanced strategy)
    importance_weight: float = 0.3
    recency_weight: float = 0.2
    relevance_weight: float = 0.5
    
    # compresssettings
    max_chars_per_node: int = 300
    include_path: bool = True
    include_metadata: bool = False
    
    # Token estimate
    chars_per_token: float = 4.0  # roughestimate
    
    @classmethod
    def from_dict(cls, data: Dict) -> "MemoryConfig":
        return cls(
            default_max_tokens=data.get("default_max_tokens", 4000),
            default_strategy=ScoringStrategy(data.get("default_strategy", "balanced")),
            importance_weight=data.get("scoring_weights", {}).get("importance", 0.3),
            recency_weight=data.get("scoring_weights", {}).get("recency", 0.2),
            relevance_weight=data.get("scoring_weights", {}).get("relevance", 0.5),
            max_chars_per_node=data.get("compression", {}).get("max_chars_per_node", 300),
        )


@dataclass
class ScoredNode:
    """Node with score"""
    node: AVMNode
    relevance_score: float = 0.0
    importance_score: float = 0.5
    recency_score: float = 0.5
    final_score: float = 0.0
    estimated_tokens: int = 0
    summary: str = ""


class AgentMemory:
    """
    Agent Memory System
    
    Provide token-aware memory retrieval and management
    Supports multi-agent permission control and append-only versioning
    """
    
    def __init__(self, avm: AVM, agent_id: str, 
                 config: MemoryConfig = None):
        """
        Args:
            avm: AVM instance
            agent_id: Agent identifier
            config: configuration
        """
        self.avm = avm
        self.agent_id = agent_id
        self.config = config or MemoryConfig()
        
        # pathprefix
        self.private_prefix = f"/memory/private/{agent_id}"
        self.shared_prefix = "/memory/shared"
        
        # Get agent config (permissions, quotas)
        self._agent_config = avm.get_agent_config(agent_id)
    
    # ─── retrieve ─────────────────────────────────────────────
    
    def recall(self, query: str,
               max_tokens: int = None,
               strategy: ScoringStrategy = None,
               include_shared: bool = True,
               namespaces: List[str] = None,
               merge_versions: bool = True) -> str:
        """
        Retrieve related memories, return token-controlled context
        
        Args:
            query: Query text
            max_tokens: Max token count
            strategy: scorestrategy
            include_shared: whetherincludesharedmemory
            namespaces: Restricted shared namespaces
            merge_versions: Whether to merge multiple versions of same path
        
        Returns:
            Compact Markdown formatted context
        """
        max_tokens = max_tokens or self.config.default_max_tokens
        strategy = strategy or self.config.default_strategy
        
        # 1. Determine search range
        prefixes = [self.private_prefix]
        if include_shared:
            if namespaces:
                prefixes.extend([f"{self.shared_prefix}/{ns}" for ns in namespaces])
            else:
                prefixes.append(self.shared_prefix)
        
        # 2. Retrieve candidate nodes
        candidates = self._retrieve_candidates(query, prefixes, k=50)
        
        # 3. permissionfilter
        candidates = [(n, s) for n, s in candidates if self._can_read(n.path)]
        
        # 4. score
        scored = self._score_nodes(candidates, query, strategy)
        
        # 5. Select within token budget
        selected = self._select_within_budget(scored, max_tokens)
        
        # 6. versionmerge（ifenable）
        if merge_versions and hasattr(self.avm, '_versioned_memory'):
            selected = self._merge_versions_in_results(selected)
        
        # 7. Generate compact output
        return self._compact_synthesis(selected, query, max_tokens, strategy)
    
    def _merge_versions_in_results(self, scored: List[ScoredNode]) -> List[ScoredNode]:
        """Merge multiple versions of same base_path"""
        # Group by base_path
        by_base: Dict[str, List[ScoredNode]] = {}
        no_base: List[ScoredNode] = []
        
        for sn in scored:
            base = sn.node.meta.get("base_path")
            if base:
                if base not in by_base:
                    by_base[base] = []
                by_base[base].append(sn)
            else:
                no_base.append(sn)
        
        # Merge each group
        merged = []
        for base_path, versions in by_base.items():
            if len(versions) == 1:
                merged.append(versions[0])
            else:
                # Merge multiple versions
                merged_content = self.avm._versioned_memory.merge_versions(
                    [sn.node for sn in versions]
                )
                # Use highest score node as representative
                best = max(versions, key=lambda x: x.final_score)
                best.summary = self._extract_summary(
                    AVMNode(path=base_path, content=merged_content)
                )
                merged.append(best)
        
        return merged + no_base
    
    def _retrieve_candidates(self, query: str, 
                            prefixes: List[str],
                            k: int = 50) -> List[Tuple[AVMNode, float]]:
        """Retrieve candidate nodes"""
        candidates = []
        seen = set()
        
        # Use VFS retrieval features (single retrieval)
        result = self.avm.retrieve(query, k=k)
        
        for node in result.nodes:
            # Check if under allowed prefix
            if any(node.path.startswith(p) for p in prefixes):
                if node.path not in seen:
                    seen.add(node.path)
                    score = result.scores.get(node.path, 0.0)
                    candidates.append((node, score))
        
        return candidates
    
    def _score_nodes(self, candidates: List[Tuple[AVMNode, float]],
                     query: str,
                     strategy: ScoringStrategy) -> List[ScoredNode]:
        """nodescore"""
        scored = []
        now = datetime.utcnow()
        
        for node, relevance in candidates:
            sn = ScoredNode(node=node, relevance_score=relevance)
            
            # Importance score (from metadata)
            sn.importance_score = node.meta.get("importance", 0.5)
            
            # Recency score (exponential decay)
            age_hours = (now - node.updated_at).total_seconds() / 3600
            sn.recency_score = math.exp(-age_hours / 168)  # half-life 1 week
            
            # Calculate final score
            if strategy == ScoringStrategy.IMPORTANCE:
                sn.final_score = sn.importance_score
            elif strategy == ScoringStrategy.RECENCY:
                sn.final_score = sn.recency_score
            elif strategy == ScoringStrategy.RELEVANCE:
                sn.final_score = sn.relevance_score
            else:  # BALANCED
                sn.final_score = (
                    self.config.importance_weight * sn.importance_score +
                    self.config.recency_weight * sn.recency_score +
                    self.config.relevance_weight * sn.relevance_score
                )
            
            # Generate summary and estimate tokens
            sn.summary = self._extract_summary(node)
            sn.estimated_tokens = self._estimate_tokens(sn.summary)
            
            scored.append(sn)
        
        # Sort by score
        scored.sort(key=lambda x: x.final_score, reverse=True)
        return scored
    
    def _select_within_budget(self, scored: List[ScoredNode],
                              max_tokens: int) -> List[ScoredNode]:
        """Select within token budgetnode"""
        selected = []
        used_tokens = 100  # reserved header
        
        for sn in scored:
            if used_tokens + sn.estimated_tokens <= max_tokens:
                selected.append(sn)
                used_tokens += sn.estimated_tokens
            
            # Keep at least one
            if not selected and sn == scored[0]:
                selected.append(sn)
                break
        
        return selected
    
    def _extract_summary(self, node: AVMNode) -> str:
        """extractnodesummary"""
        content = node.content
        max_chars = self.config.max_chars_per_node
        
        # remove Markdown format
        # removetitle
        content = re.sub(r'^#+\s+.*$', '', content, flags=re.MULTILINE)
        # removeupdatetime
        content = re.sub(r'\*Updated:.*\*', '', content)
        # removeemptyline
        content = re.sub(r'\n{2,}', '\n', content)
        
        # Extract key lines
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        
        # Prioritize lines with numbers (likely key data)
        key_lines = [l for l in lines if re.search(r'\d', l)]
        other_lines = [l for l in lines if l not in key_lines]
        
        # combine
        result_lines = key_lines[:3] + other_lines
        result = ' '.join(result_lines)
        
        if len(result) > max_chars:
            result = result[:max_chars-3] + "..."
        
        return result
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count"""
        return int(len(text) / self.config.chars_per_token) + 10  # +10 for formatting
    
    def _compact_synthesis(self, selected: List[ScoredNode],
                          query: str,
                          max_tokens: int,
                          strategy: ScoringStrategy) -> str:
        """Generate compact Markdown output"""
        if not selected:
            return f"## Memory Recall\n\nNo relevant memories found for: \"{query}\""
        
        total_tokens = sum(sn.estimated_tokens for sn in selected)
        
        lines = [
            f"## Relevant Memory ({len(selected)} items, ~{total_tokens} tokens)",
            "",
        ]
        
        for sn in selected:
            # format: [path] summary
            score_str = f"{sn.final_score:.2f}"
            lines.append(f"[{sn.node.path}] ({score_str}) {sn.summary}")
            lines.append("")
        
        lines.append("---")
        lines.append(f"*Tokens: ~{total_tokens}/{max_tokens} | Strategy: {strategy.value} | Query: \"{query}\"*")
        
        return "\n".join(lines)
    
    # ─── write ─────────────────────────────────────────────
    
    def remember(self, content: str,
                 title: str = None,
                 importance: float = 0.5,
                 tags: List[str] = None,
                 source: str = "agent",
                 namespace: str = None,
                 path: str = None) -> AVMNode:
        """
        writememory（supports append-only version）
        
        Args:
            content: memorycontent
            title: title（forgeneratepath）
            importance: importance (0-1)
            tags: tag
            source: source
            namespace: shared namespace (e.g., "market", "projects")
            path: specifiedpath（for append-only update）
        """
        # Determine target path
        if path:
            target_path = path
        elif namespace:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")  # add microseconds
            slug = self._make_slug(title) if title else timestamp
            target_path = f"{self.shared_prefix}/{namespace}/{slug}.md"
        else:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")  # add microseconds
            slug = self._make_slug(title) if title else ""
            filename = f"{timestamp}_{slug}.md" if slug else f"{timestamp}.md"
            target_path = f"{self.private_prefix}/{filename}"
        
        # Check write permission
        if not self._can_write(target_path):
            raise PermissionError(f"Agent {self.agent_id} cannot write to {target_path}")
        
        # Check quota
        self._check_quota()
        
        # Format content
        full_content = self._format_content(content, title, tags)
        
        meta = {
            "importance": importance,
            "tags": tags or [],
            "source": source,
            "author": self.agent_id,
        }
        
        # Use versioned write (if updating existing path)
        if path and hasattr(self.avm, '_versioned_memory'):
            node = self.avm._versioned_memory.write_version(
                path, full_content, self.agent_id, meta
            )
        else:
            node = self.avm.write(target_path, full_content, meta)
        
        # recordauditlog
        self._log_operation("write", node.path)
        
        return node
    
    def _make_slug(self, title: str) -> str:
        """generate URL-safe slug"""
        if not title:
            return ""
        slug = re.sub(r'[^\w\s-]', '', title.lower())
        slug = re.sub(r'[\s_]+', '_', slug)
        return slug[:30]
    
    def _format_content(self, content: str, title: str = None, 
                        tags: List[str] = None) -> str:
        """Format memory content"""
        lines = []
        if title:
            lines.append(f"# {title}")
            lines.append("")
        lines.append(f"*Created: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*")
        if tags:
            lines.append(f"*Tags: {', '.join(tags)}*")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(content)
        return "\n".join(lines)
    
    def _can_write(self, path: str) -> bool:
        """Check write permission"""
        if self._agent_config:
            return self._agent_config.namespaces.can_write(path)
        # Default: can only write to private namespace
        return path.startswith(self.private_prefix)
    
    def _can_read(self, path: str) -> bool:
        """Check read permission"""
        if self._agent_config:
            return self._agent_config.namespaces.can_read(path)
        # default：Can read private and shared
        return path.startswith(self.private_prefix) or path.startswith(self.shared_prefix)
    
    def _check_quota(self):
        """Check quota"""
        if hasattr(self.avm, '_agent_registry') and self._agent_config:
            from .multi_agent import QuotaEnforcer
            enforcer = QuotaEnforcer(self.avm.store)
            result = enforcer.check_quota(self.agent_id, self._agent_config.quota)
            if not result["ok"]:
                raise RuntimeError(f"Quota exceeded: {result['message']}")
    
    def _log_operation(self, operation: str, path: str, details: Dict = None):
        """recordauditlog"""
        if hasattr(self.avm, '_audit_log'):
            self.avm._audit_log.log(self.agent_id, operation, path, details)
    
    def share(self, path: str, namespace: str,
              new_name: str = None) -> AVMNode:
        """
        Share memory to shared namespace
        
        Args:
            path: Original path (private memory)
            namespace: targetnamednamespace
            new_name: New filename (optional)
        """
        # Read original node
        node = self.avm.read(path)
        if not node:
            raise ValueError(f"Node not found: {path}")
        
        # Generate new path
        if new_name:
            new_path = f"{self.shared_prefix}/{namespace}/{new_name}"
        else:
            filename = path.split("/")[-1]
            new_path = f"{self.shared_prefix}/{namespace}/{filename}"
        
        # Update metadata
        meta = node.meta.copy()
        meta["shared_from"] = path
        meta["shared_by"] = self.agent_id
        meta["shared_at"] = datetime.utcnow().isoformat()
        
        return self.avm.write(new_path, node.content, meta)
    
    # ─── update ─────────────────────────────────────────────
    
    def update_importance(self, path: str, importance: float):
        """Update memory importance"""
        node = self.avm.read(path)
        if not node:
            raise ValueError(f"Node not found: {path}")
        
        # checkpermission
        if not path.startswith(self.private_prefix):
            if node.meta.get("agent") != self.agent_id:
                raise PermissionError(f"Cannot modify: {path}")
        
        meta = node.meta.copy()
        meta["importance"] = max(0.0, min(1.0, importance))
        
        return self.avm.write(path, node.content, meta)
    
    def mark_accessed(self, path: str):
        """Mark memory as accessed (for recency calculation)"""
        node = self.avm.read(path)
        if node:
            meta = node.meta.copy()
            meta["last_accessed"] = datetime.utcnow().isoformat()
            # Update meta only, not content
            self.avm.store._put_node_internal(
                AVMNode(path=path, content=node.content, meta=meta),
                save_diff=False
            )
    
    # ─── columntable ─────────────────────────────────────────────
    
    def list_private(self, limit: int = 100) -> List[AVMNode]:
        """List private memories"""
        return self.avm.list(self.private_prefix, limit)
    
    def list_shared(self, namespace: str = None, 
                    limit: int = 100) -> List[AVMNode]:
        """listsharedmemory"""
        prefix = f"{self.shared_prefix}/{namespace}" if namespace else self.shared_prefix
        return self.avm.list(prefix, limit)
    
    def stats(self) -> Dict[str, Any]:
        """statisticsinfo"""
        private = self.list_private()
        shared = self.list_shared()
        
        return {
            "agent_id": self.agent_id,
            "private_count": len(private),
            "shared_accessible": len(shared),
            "private_prefix": self.private_prefix,
            "config": {
                "max_tokens": self.config.default_max_tokens,
                "strategy": self.config.default_strategy.value,
            }
        }
    
    # ─── Advanced Features ─────────────────────────────────────────
    
    def subscribe(self, pattern: str, callback) -> str:
        """
        Subscribe to path changes
        
        Args:
            pattern: Glob mode (e.g., "/memory/shared/market/*")
            callback: callbackfunction (event) -> None
        
        Returns:
            subscribe ID（forcancelledsubscribe）
        """
        from .advanced import SubscriptionManager
        
        if not hasattr(self.avm, '_subscription_manager'):
            self.avm._subscription_manager = SubscriptionManager()
        
        return self.avm._subscription_manager.subscribe(
            pattern, callback, subscriber_id=self.agent_id
        )
    
    def unsubscribe(self, pattern: str = None):
        """cancelledsubscribe"""
        if hasattr(self.avm, '_subscription_manager'):
            self.avm._subscription_manager.unsubscribe(self.agent_id, pattern)
    
    def recall_recent(self, query: str, 
                      time_range: str = "last_7d",
                      max_tokens: int = None) -> str:
        """
        Retrieve memories within time range
        
        Args:
            query: Query text
            time_range: timerange ("last_24h", "last_7d", "last_30d", "today")
            max_tokens: Max token count
        """
        from .advanced import TimeQuery
        
        time_query = TimeQuery(self.avm.store)
        recent_nodes = time_query.query(
            prefix="/memory",
            time_range=time_range,
            limit=50
        )
        
        # filterpermission
        recent_nodes = [n for n in recent_nodes if self._can_read(n.path)]
        
        # Convert to scored nodes and synthesize
        max_tokens = max_tokens or self.config.default_max_tokens
        scored = []
        
        for node in recent_nodes:
            sn = ScoredNode(node=node)
            sn.importance_score = node.meta.get("importance", 0.5)
            sn.recency_score = 1.0  # Already recent
            sn.relevance_score = 0.5  # Time query ignores relevance
            sn.final_score = sn.importance_score
            sn.summary = self._extract_summary(node)
            sn.estimated_tokens = self._estimate_tokens(sn.summary)
            scored.append(sn)
        
        selected = self._select_within_budget(scored, max_tokens)
        return self._compact_synthesis(selected, f"{query} (time: {time_range})", 
                                       max_tokens, ScoringStrategy.IMPORTANCE)
    
    def remember_derived(self, content: str,
                         derived_from: List[str],
                         title: str = None,
                         reasoning: str = None,
                         **kwargs) -> AVMNode:
        """
        Write derived memory, auto-establish source links
        
        Args:
            content: derived/conclusioncontent
            derived_from: sourcepathcolumntable
            title: title
            reasoning: Reasoning description
        """
        from .advanced import DerivedLinkManager
        
        # writememory
        node = self.remember(content, title=title, **kwargs)
        
        # Establish derived links
        link_mgr = DerivedLinkManager(self.avm.store)
        link_mgr.link_derived(node.path, derived_from, reasoning)
        
        return node
    
    def check_duplicate(self, content: str, 
                        threshold: float = 0.85) -> "DedupeResult":
        """
        Check if duplicate with existing memory
        
        Args:
            content: content
            threshold: Similarity threshold (0.85 conservative, 0.95 strict)
        
        Returns:
            DedupeResult
        """
        from .advanced import SemanticDeduplicator, DedupeResult
        
        embedding_store = getattr(self.avm, '_embedding_store', None)
        deduper = SemanticDeduplicator(self.avm.store, embedding_store)
        
        return deduper.check_duplicate(
            content, 
            prefix=self.private_prefix,
            threshold=threshold
        )
    
    def remember_if_new(self, content: str, 
                        threshold: float = 0.85,
                        **kwargs) -> Optional[AVMNode]:
        """
        Write only if content not duplicate
        
        Returns:
            AVMNode if written, None if duplicate
        """
        result = self.check_duplicate(content, threshold)
        
        if result.is_duplicate:
            return None
        
        return self.remember(content, **kwargs)
    
    def get_cold_memories(self, threshold: float = 0.1,
                          limit: int = 20) -> List[AVMNode]:
        """
        Get decayed cold memories
        
        Args:
            threshold: Weight threshold after decay
            limit: maxcount
        """
        from .advanced import MemoryDecay
        
        decay = MemoryDecay(self.avm.store)
        return decay.get_cold_memories(
            prefix=self.private_prefix,
            threshold=threshold,
            limit=limit
        )
    
    def compact_versions(self, path: str, 
                         keep_recent: int = 3) -> "CompactionResult":
        """
        Compress path history versions
        
        Args:
            path: Path to compress
            keep_recent: Keep recent N versions
        """
        from .advanced import MemoryCompactor
        
        compactor = MemoryCompactor(self.avm.store)
        return compactor.compact(path, keep_recent)
    
    # ─── Tag System ─────────────────────────────────────────
    
    def by_tag(self, tag: str, limit: int = 100) -> List[AVMNode]:
        """Get memories by tag"""
        from .advanced import TagManager
        
        tag_mgr = TagManager(self.avm.store)
        
        # Search private and shared namespaces
        private_nodes = tag_mgr.by_tag(tag, prefix=self.private_prefix, limit=limit)
        shared_nodes = tag_mgr.by_tag(tag, prefix=self.shared_prefix, limit=limit)
        
        all_nodes = private_nodes + shared_nodes
        
        # Filter by permission and dedupe
        seen = set()
        result = []
        for n in all_nodes:
            if n.path not in seen and self._can_read(n.path):
                seen.add(n.path)
                result.append(n)
        
        return result[:limit]
    
    def tag_cloud(self) -> Dict[str, int]:
        """Get tag cloud (frequency distribution)"""
        from .advanced import TagManager
        
        tag_mgr = TagManager(self.avm.store)
        
        # Merge tags from private and shared namespaces
        private_cloud = tag_mgr.tag_cloud(prefix=self.private_prefix)
        shared_cloud = tag_mgr.tag_cloud(prefix=self.shared_prefix)
        
        # Merge counts
        combined = {}
        for tag, count in private_cloud.items():
            combined[tag] = combined.get(tag, 0) + count
        for tag, count in shared_cloud.items():
            combined[tag] = combined.get(tag, 0) + count
        
        return dict(sorted(combined.items(), key=lambda x: x[1], reverse=True))
    
    def suggest_tags(self, content: str, top_k: int = 5) -> List[str]:
        """contentrecommendationtag"""
        from .advanced import TagManager
        
        tag_mgr = TagManager(self.avm.store)
        return tag_mgr.suggest_tags(content, top_k)
    
    # ─── Access Statistics ─────────────────────────────────────────
    
    def hot_memories(self, days: int = 7, limit: int = 10) -> List[Tuple[str, int]]:
        """Get hot memories (high access)"""
        from .advanced import AccessStats
        
        stats = AccessStats(self.avm.store)
        return stats.hot_paths(days, limit)
    
    def cold_memories(self, days: int = 30, limit: int = 20) -> List[AVMNode]:
        """Get cold memories (rarely accessed)"""
        from .advanced import AccessStats
        
        stats = AccessStats(self.avm.store)
        nodes = stats.cold_paths(days, prefix="/memory", limit=limit)
        return [n for n in nodes if self._can_read(n.path)]
    
    def my_activity(self, days: int = 7) -> Dict[str, int]:
        """Get my activity stats"""
        from .advanced import AccessStats
        
        stats = AccessStats(self.avm.store)
        return stats.agent_activity(self.agent_id, days)
    
    # ─── export/snapshot ─────────────────────────────────────────
    
    def export(self, format: str = "jsonl") -> str:
        """
        Export my memories
        
        Args:
            format: "jsonl" or "markdown"
        """
        from .advanced import ExportManager
        
        export_mgr = ExportManager(self.avm.store)
        
        if format == "markdown":
            return export_mgr.export_markdown(
                prefix=self.private_prefix,
                agent_id=self.agent_id
            )
        else:
            return export_mgr.export_jsonl(
                prefix=self.private_prefix,
                agent_id=self.agent_id
            )
    
    def import_memories(self, jsonl: str) -> int:
        """
        importmemory
        
        Args:
            jsonl: Memory data in JSONL format
        
        Returns:
            importcount
        """
        from .advanced import ExportManager
        
        export_mgr = ExportManager(self.avm.store)
        return export_mgr.import_jsonl(jsonl)
    
    # ─── Navigation & Discovery ─────────────────────────────────────────
    
    def browse(self, path: str = "/memory", depth: int = 2) -> Dict[str, Any]:
        """
        Browse memory structure like a directory tree.
        Helps agent discover memories without knowing exact keywords.
        
        Args:
            path: Starting path (default: /memory)
            depth: How deep to traverse (default: 2)
            
        Returns:
            Tree structure with paths and summaries
        """
        nodes = self.avm.list(path, limit=100)
        
        # Build tree structure
        tree = {"path": path, "children": {}, "count": 0}
        
        for node in nodes:
            if not self._can_read(node.path):
                continue
                
            # Get relative path parts
            rel_path = node.path[len(path):].lstrip("/")
            parts = rel_path.split("/")
            
            # Only include up to depth levels
            if len(parts) > depth:
                parts = parts[:depth]
            
            # Build nested structure
            current = tree
            for i, part in enumerate(parts):
                if part not in current["children"]:
                    current["children"][part] = {
                        "path": path + "/" + "/".join(parts[:i+1]),
                        "children": {},
                        "count": 0
                    }
                current = current["children"][part]
                current["count"] += 1
        
        return self._format_tree(tree, depth=0)
    
    def _format_tree(self, tree: Dict, depth: int = 0) -> str:
        """Format tree as readable string"""
        lines = []
        indent = "  " * depth
        
        for name, subtree in sorted(tree.get("children", {}).items()):
            count = subtree.get("count", 0)
            icon = "📁" if subtree.get("children") else "📄"
            lines.append(f"{indent}{icon} {name} ({count})")
            
            if subtree.get("children"):
                lines.append(self._format_tree(subtree, depth + 1))
        
        return "\n".join(lines)
    
    def explore(self, path: str, depth: int = 2) -> str:
        """
        Explore from a memory node via knowledge graph.
        Follows links to discover related memories.
        
        Args:
            path: Starting node path
            depth: How many hops to follow (default: 2)
            
        Returns:
            Related memories with relationship types
        """
        if not self._can_read(path):
            return f"Cannot access: {path}"
        
        # Get the starting node
        node = self.avm.read(path)
        if not node:
            return f"Not found: {path}"
        
        # BFS to explore graph
        visited = {path}
        current_level = [path]
        results = [f"## Starting from: {path}\n{node.content[:200]}...\n"]
        
        for d in range(depth):
            next_level = []
            level_results = []
            
            for p in current_level:
                edges = self.avm.links(p)
                for edge in edges:
                    target = edge.source if edge.source != p else edge.target
                    if target not in visited and self._can_read(target):
                        visited.add(target)
                        next_level.append(target)
                        
                        target_node = self.avm.read(target)
                        if target_node:
                            rel_type = edge.edge_type.value if hasattr(edge.edge_type, 'value') else str(edge.edge_type)
                            preview = target_node.content[:100].replace("\n", " ")
                            level_results.append(f"  [{rel_type}] {target}\n    {preview}...")
            
            if level_results:
                results.append(f"\n### Hop {d + 1}:")
                results.extend(level_results)
            
            current_level = next_level
            if not current_level:
                break
        
        if len(results) == 1:
            results.append("\nNo linked memories found. Try creating links with avm.link()")
        
        return "\n".join(results)
    
    def topics(self, limit: int = 10) -> str:
        """
        Get high-level topic overview based on tags and paths.
        Helps agent understand what's in memory without keywords.
        
        Args:
            limit: Max topics to return
            
        Returns:
            Topic summary with counts
        """
        # Get tag cloud
        cloud = self.tag_cloud()
        
        # Get path prefixes
        nodes = self.avm.list("/memory", limit=200)
        prefix_counts = {}
        
        for node in nodes:
            if not self._can_read(node.path):
                continue
            # Extract second-level path as category
            parts = node.path.split("/")
            if len(parts) >= 3:
                category = parts[2]  # e.g., "private", "shared", "market", etc.
                prefix_counts[category] = prefix_counts.get(category, 0) + 1
        
        # Format output
        lines = ["## Memory Topics\n"]
        
        lines.append("### By Category:")
        for cat, count in sorted(prefix_counts.items(), key=lambda x: x[1], reverse=True)[:limit]:
            lines.append(f"  📁 {cat}: {count} memories")
        
        lines.append("\n### By Tag:")
        for tag, count in list(cloud.items())[:limit]:
            lines.append(f"  🏷️ {tag}: {count} occurrences")
        
        return "\n".join(lines)
    
    def timeline(self, days: int = 7, limit: int = 20) -> str:
        """
        View memories by time.
        Helps recall "what did I observe/learn recently?"
        
        Args:
            days: How many days back to look
            limit: Max memories to return
            
        Returns:
            Timeline of recent memories
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        nodes = self.avm.query_time(
            prefix="/memory",
            time_range=f"last_{days}d"
        )
        
        # Filter by permission
        accessible = [n for n in nodes if self._can_read(n.path)][:limit]
        
        if not accessible:
            return f"No memories in the last {days} days."
        
        # Group by date
        by_date = {}
        for node in accessible:
            date_str = node.created_at.strftime("%Y-%m-%d")
            if date_str not in by_date:
                by_date[date_str] = []
            by_date[date_str].append(node)
        
        # Format output
        lines = [f"## Timeline (last {days} days)\n"]
        
        for date_str in sorted(by_date.keys(), reverse=True):
            lines.append(f"### {date_str}")
            for node in by_date[date_str]:
                time_str = node.created_at.strftime("%H:%M")
                title = node.meta.get("title", node.path.split("/")[-1])
                preview = node.content[:60].replace("\n", " ")
                lines.append(f"  [{time_str}] {title}: {preview}...")
            lines.append("")
        
        return "\n".join(lines)
