"""
avm/consolidation.py - Memory Consolidation

Like human sleep consolidation:
- Merge similar memories
- Extract common themes into summaries
- Decay old memory importance
- Can run as scheduled cron job

Usage:
    consolidator = MemoryConsolidator(avm)
    consolidator.run()  # Full consolidation
    consolidator.decay_importance()  # Just decay
    consolidator.merge_similar()  # Just merge
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Set, Optional, Tuple
from collections import defaultdict

from .store import AVMStore
from .node import AVMNode
from .topic_index import TopicIndex


@dataclass
class ConsolidationConfig:
    """Configuration for memory consolidation"""
    # Importance decay
    decay_half_life_days: float = 30.0  # Importance halves every 30 days
    min_importance: float = 0.1  # Floor for importance decay
    
    # Similarity merging
    similarity_threshold: float = 0.8  # Jaccard threshold for merging
    min_age_for_merge_days: float = 7.0  # Don't merge recent memories
    
    # Summary extraction
    min_cluster_size: int = 3  # Minimum memories to form a cluster
    max_summary_length: int = 500  # Characters per summary


@dataclass
class ConsolidationResult:
    """Result of a consolidation run"""
    memories_processed: int = 0
    importance_decayed: int = 0
    memories_merged: int = 0
    summaries_created: int = 0
    duration_ms: float = 0.0


class MemoryConsolidator:
    """
    Consolidates agent memories to reduce noise and extract patterns.
    
    Inspired by sleep consolidation in biological memory systems.
    """
    
    def __init__(self, store: AVMStore, topic_index: TopicIndex = None,
                 config: ConsolidationConfig = None):
        self.store = store
        self.topic_index = topic_index or TopicIndex(store)
        self.config = config or ConsolidationConfig()
    
    def run(self, agent_id: str = None, dry_run: bool = False) -> ConsolidationResult:
        """
        Run full consolidation.
        
        Args:
            agent_id: Consolidate specific agent, or all if None
            dry_run: If True, don't actually modify anything
        
        Returns:
            ConsolidationResult with stats
        """
        import time
        start = time.perf_counter()
        
        result = ConsolidationResult()
        
        # Get memories to process
        prefix = f"/memory/private/{agent_id}" if agent_id else "/memory"
        memories = self._get_memories(prefix)
        result.memories_processed = len(memories)
        
        if not dry_run:
            # Step 1: Decay importance
            decayed = self.decay_importance(memories)
            result.importance_decayed = decayed
            
            # Step 2: Merge similar memories
            merged = self.merge_similar(memories)
            result.memories_merged = merged
            
            # Step 3: Extract summaries from clusters
            summaries = self.extract_summaries(memories)
            result.summaries_created = summaries
        
        result.duration_ms = (time.perf_counter() - start) * 1000
        return result
    
    def _get_memories(self, prefix: str) -> List[AVMNode]:
        """Get all memories under a prefix"""
        return self.store.list_nodes(prefix, limit=10000)
    
    def decay_importance(self, memories: List[AVMNode] = None) -> int:
        """
        Apply time-based importance decay.
        
        Importance decays exponentially: I(t) = I(0) * 0.5^(t/half_life)
        """
        if memories is None:
            memories = self._get_memories("/memory")
        
        now = datetime.utcnow()
        decayed_count = 0
        
        for mem in memories:
            age_days = (now - mem.updated_at).total_seconds() / 86400
            current_importance = mem.meta.get("importance", 0.5)
            
            # Calculate decayed importance
            decay_factor = 0.5 ** (age_days / self.config.decay_half_life_days)
            new_importance = max(
                current_importance * decay_factor,
                self.config.min_importance
            )
            
            # Only update if significant change
            if abs(new_importance - current_importance) > 0.01:
                mem.meta["importance"] = round(new_importance, 3)
                mem.meta["last_decay"] = now.isoformat()
                self.store.put_node(mem)
                decayed_count += 1
        
        return decayed_count
    
    def merge_similar(self, memories: List[AVMNode] = None) -> int:
        """
        Merge similar memories into consolidated versions.
        
        Uses topic overlap (Jaccard similarity) to find candidates.
        """
        if memories is None:
            memories = self._get_memories("/memory")
        
        now = datetime.utcnow()
        min_age = timedelta(days=self.config.min_age_for_merge_days)
        merged_count = 0
        
        # Filter to old enough memories
        eligible = [m for m in memories 
                   if (now - m.updated_at) > min_age]
        
        # Build topic sets for each memory
        mem_topics: Dict[str, Set[str]] = {}
        for mem in eligible:
            topics = set(self.topic_index.topics_for_path(mem.path))
            if topics:
                mem_topics[mem.path] = topics
        
        # Find similar pairs
        merged_paths: Set[str] = set()
        
        for path1, topics1 in mem_topics.items():
            if path1 in merged_paths:
                continue
            
            similar = []
            for path2, topics2 in mem_topics.items():
                if path2 == path1 or path2 in merged_paths:
                    continue
                
                # Jaccard similarity
                intersection = len(topics1 & topics2)
                union = len(topics1 | topics2)
                if union > 0:
                    similarity = intersection / union
                    if similarity >= self.config.similarity_threshold:
                        similar.append(path2)
            
            if similar:
                # Merge similar memories into path1
                mem1 = self.store.get_node(path1)
                if mem1:
                    merged_content = [mem1.content or ""]
                    merged_importance = mem1.meta.get("importance", 0.5)
                    
                    for path2 in similar:
                        mem2 = self.store.get_node(path2)
                        if mem2:
                            merged_content.append(mem2.content or "")
                            merged_importance = max(
                                merged_importance,
                                mem2.meta.get("importance", 0.5)
                            )
                            # Mark as merged (soft delete)
                            mem2.meta["merged_into"] = path1
                            mem2.meta["merged_at"] = now.isoformat()
                            self.store.put_node(mem2)
                            merged_paths.add(path2)
                    
                    # Update consolidated memory
                    mem1.content = "\n\n---\n\n".join(merged_content)
                    mem1.meta["importance"] = merged_importance
                    mem1.meta["consolidated_from"] = list(similar)
                    mem1.meta["consolidated_at"] = now.isoformat()
                    self.store.put_node(mem1)
                    
                    # Re-index topics
                    self.topic_index.index_path(path1, mem1.content)
                    
                    merged_count += len(similar)
        
        return merged_count
    
    def extract_summaries(self, memories: List[AVMNode] = None) -> int:
        """
        Extract topic summaries from memory clusters.
        
        Groups memories by topic and creates summary nodes.
        """
        if memories is None:
            memories = self._get_memories("/memory")
        
        # Group by topic
        topic_memories: Dict[str, List[AVMNode]] = defaultdict(list)
        
        for mem in memories:
            topics = self.topic_index.topics_for_path(mem.path)
            for topic in topics:
                topic_memories[topic].append(mem)
        
        summaries_created = 0
        now = datetime.utcnow()
        
        for topic, mems in topic_memories.items():
            if len(mems) < self.config.min_cluster_size:
                continue
            
            # Check if summary already exists and is recent
            summary_path = f"/memory/summaries/{topic}.md"
            existing = self.store.get_node(summary_path)
            if existing:
                age = (now - existing.updated_at).total_seconds() / 86400
                if age < 7:  # Don't re-summarize within a week
                    continue
            
            # Create summary
            summary_content = self._create_summary(topic, mems)
            
            summary_node = AVMNode(
                path=summary_path,
                content=summary_content,
                meta={
                    "type": "summary",
                    "topic": topic,
                    "source_count": len(mems),
                    "generated_at": now.isoformat(),
                    "importance": 0.8,  # Summaries are important
                }
            )
            self.store.put_node(summary_node)
            self.topic_index.index_path(summary_path, summary_content, topic)
            summaries_created += 1
        
        return summaries_created
    
    def _create_summary(self, topic: str, memories: List[AVMNode]) -> str:
        """Create a summary from a list of memories"""
        # Simple extractive summary: first sentence of each memory
        lines = [f"# Summary: {topic.title()}\n"]
        lines.append(f"*Generated from {len(memories)} memories*\n")
        
        for mem in sorted(memories, 
                         key=lambda m: m.meta.get("importance", 0.5),
                         reverse=True)[:10]:
            content = mem.content or ""
            # First sentence or first 100 chars
            first_sentence = content.split(".")[0][:100]
            if first_sentence:
                lines.append(f"- {first_sentence.strip()}")
        
        return "\n".join(lines)[:self.config.max_summary_length]


def schedule_consolidation(store: AVMStore, interval_hours: int = 24):
    """
    Schedule periodic consolidation.
    
    Can be called from a cron job or background thread.
    """
    import threading
    import time
    
    def _consolidation_loop():
        consolidator = MemoryConsolidator(store)
        while True:
            try:
                result = consolidator.run()
                print(f"[Consolidation] Processed {result.memories_processed}, "
                      f"decayed {result.importance_decayed}, "
                      f"merged {result.memories_merged}, "
                      f"summaries {result.summaries_created}")
            except Exception as e:
                print(f"[Consolidation] Error: {e}")
            
            time.sleep(interval_hours * 3600)
    
    thread = threading.Thread(target=_consolidation_loop, daemon=True)
    thread.start()
    return thread
