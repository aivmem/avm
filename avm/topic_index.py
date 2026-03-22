"""
avm/topic_index.py - Topic-Level Index for Fast Recall

Reduces recall hops from 4 to 1 by pre-computing topic→path mappings.

Architecture:
- Topic extraction happens on write (async)
- Topics stored in separate table with path references
- Recall first checks topic index, then falls back to FTS

This enables:
- 1-hop recall for known topics
- Instant "what do I know about X?" queries
- Topic clustering for discovery
"""

import re
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Set, Optional, Tuple
from collections import defaultdict

from .store import AVMStore
from .node import AVMNode


# Common stop words to filter out
STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
    "be", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "shall", "can", "need",
    "this", "that", "these", "those", "i", "you", "he", "she", "it",
    "we", "they", "what", "which", "who", "whom", "when", "where", "why",
    "how", "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "just", "also", "now", "here", "there",
}


@dataclass
class TopicEntry:
    """A topic with associated paths"""
    topic: str
    paths: Set[str] = field(default_factory=set)
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    def add_path(self, path: str):
        self.paths.add(path)
        self.last_updated = datetime.utcnow()
    
    def remove_path(self, path: str):
        self.paths.discard(path)
        self.last_updated = datetime.utcnow()


class TopicIndex:
    """
    In-memory topic index backed by SQLite.
    
    Schema:
        topics(topic TEXT PRIMARY KEY, paths TEXT, updated_at INTEGER)
    """
    
    def __init__(self, store: AVMStore):
        self.store = store
        self._cache: Dict[str, TopicEntry] = {}
        self._path_to_topics: Dict[str, Set[str]] = defaultdict(set)
        self._ensure_table()
        self._load_index()
    
    def _ensure_table(self):
        """Create topics table if not exists"""
        with self.store._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS topics (
                    topic TEXT PRIMARY KEY,
                    paths TEXT,
                    updated_at INTEGER
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_topics_updated 
                ON topics(updated_at)
            """)
    
    def _load_index(self):
        """Load index from SQLite into memory"""
        with self.store._conn() as conn:
            rows = conn.execute("SELECT topic, paths, updated_at FROM topics").fetchall()
            for topic, paths_str, updated_at in rows:
                paths = set(paths_str.split("|")) if paths_str else set()
                entry = TopicEntry(
                    topic=topic,
                    paths=paths,
                    last_updated=datetime.fromtimestamp(updated_at / 1000) if updated_at else datetime.utcnow()
                )
                self._cache[topic] = entry
                for path in paths:
                    self._path_to_topics[path].add(topic)
    
    def _save_topic(self, topic: str):
        """Save a single topic to SQLite"""
        entry = self._cache.get(topic)
        if not entry:
            return
        
        paths_str = "|".join(entry.paths) if entry.paths else ""
        updated_at = int(entry.last_updated.timestamp() * 1000)
        
        with self.store._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO topics (topic, paths, updated_at)
                VALUES (?, ?, ?)
            """, (topic, paths_str, updated_at))
    
    def extract_topics(self, content: str, title: str = "") -> List[str]:
        """
        Extract topics from content using simple NLP.
        
        Strategy:
        1. Split into words
        2. Filter stop words
        3. Extract noun phrases (simple: capitalized words)
        4. Extract hashtags
        5. Use title words as high-weight topics
        """
        topics = set()
        
        # Title words are important topics
        if title:
            title_words = re.findall(r'\b[a-zA-Z]{3,}\b', title.lower())
            topics.update(w for w in title_words if w not in STOP_WORDS)
        
        # Extract hashtags
        hashtags = re.findall(r'#(\w+)', content)
        topics.update(h.lower() for h in hashtags)
        
        # Extract capitalized words (likely proper nouns)
        proper_nouns = re.findall(r'\b[A-Z][a-z]+\b', content)
        topics.update(w.lower() for w in proper_nouns if len(w) > 2 and w.lower() not in STOP_WORDS)
        
        # Extract significant words (frequency-based)
        words = re.findall(r'\b[a-zA-Z]{4,}\b', content.lower())
        word_freq = defaultdict(int)
        for w in words:
            if w not in STOP_WORDS:
                word_freq[w] += 1
        
        # Top words by frequency
        sorted_words = sorted(word_freq.items(), key=lambda x: -x[1])
        topics.update(w for w, _ in sorted_words[:10])
        
        return list(topics)[:20]  # Max 20 topics per document
    
    def index_path(self, path: str, content: str, title: str = ""):
        """
        Index a path's topics.
        
        Called on write operations.
        """
        # Remove old topics for this path
        old_topics = self._path_to_topics.get(path, set()).copy()
        for topic in old_topics:
            if topic in self._cache:
                self._cache[topic].remove_path(path)
                if not self._cache[topic].paths:
                    del self._cache[topic]
        self._path_to_topics[path] = set()
        
        # Extract new topics
        topics = self.extract_topics(content, title)
        
        # Update index
        for topic in topics:
            if topic not in self._cache:
                self._cache[topic] = TopicEntry(topic=topic)
            self._cache[topic].add_path(path)
            self._path_to_topics[path].add(topic)
            self._save_topic(topic)
    
    def remove_path(self, path: str):
        """Remove a path from the index"""
        topics = self._path_to_topics.get(path, set()).copy()
        for topic in topics:
            if topic in self._cache:
                self._cache[topic].remove_path(path)
                if not self._cache[topic].paths:
                    del self._cache[topic]
                else:
                    self._save_topic(topic)
        del self._path_to_topics[path]
    
    def query(self, query: str, limit: int = 50) -> List[Tuple[str, float]]:
        """
        Query the topic index.
        
        Returns: List of (path, score) tuples
        """
        # Extract query topics
        query_topics = set(self.extract_topics(query, ""))
        
        if not query_topics:
            return []
        
        # Score paths by topic overlap
        path_scores: Dict[str, float] = defaultdict(float)
        
        for topic in query_topics:
            if topic in self._cache:
                entry = self._cache[topic]
                # Score based on topic specificity (fewer paths = more specific)
                specificity = 1.0 / (len(entry.paths) + 1)
                for path in entry.paths:
                    path_scores[path] += specificity
        
        # Normalize and sort
        if path_scores:
            max_score = max(path_scores.values())
            path_scores = {p: s / max_score for p, s in path_scores.items()}
        
        sorted_paths = sorted(path_scores.items(), key=lambda x: -x[1])
        return sorted_paths[:limit]
    
    def topics_for_path(self, path: str) -> List[str]:
        """Get topics associated with a path"""
        return list(self._path_to_topics.get(path, set()))
    
    def paths_for_topic(self, topic: str) -> List[str]:
        """Get paths associated with a topic"""
        entry = self._cache.get(topic.lower())
        return list(entry.paths) if entry else []
    
    def all_topics(self) -> Dict[str, int]:
        """Get all topics with path counts"""
        return {topic: len(entry.paths) for topic, entry in self._cache.items()}
    
    def similar_topics(self, topic: str, limit: int = 10) -> List[Tuple[str, float]]:
        """
        Find topics that often co-occur with the given topic.
        
        Uses Jaccard similarity on path sets.
        """
        topic = topic.lower()
        if topic not in self._cache:
            return []
        
        target_paths = self._cache[topic].paths
        if not target_paths:
            return []
        
        similarities = []
        for other_topic, entry in self._cache.items():
            if other_topic == topic:
                continue
            
            intersection = len(target_paths & entry.paths)
            if intersection > 0:
                union = len(target_paths | entry.paths)
                jaccard = intersection / union
                similarities.append((other_topic, jaccard))
        
        similarities.sort(key=lambda x: -x[1])
        return similarities[:limit]
    
    def stats(self) -> Dict[str, int]:
        """Get index statistics"""
        return {
            "total_topics": len(self._cache),
            "total_paths": len(self._path_to_topics),
            "avg_paths_per_topic": sum(len(e.paths) for e in self._cache.values()) / max(len(self._cache), 1),
            "avg_topics_per_path": sum(len(t) for t in self._path_to_topics.values()) / max(len(self._path_to_topics), 1),
        }


def integrate_with_recall(topic_index: TopicIndex, avm_store: AVMStore):
    """
    Hook to integrate topic index with recall.
    
    Call this in agent_memory.recall() before FTS:
    
    1. Query topic index (O(1) lookup)
    2. If topics found → use those paths directly
    3. Else → fall back to FTS
    
    This reduces hop count from 4 to 1 for known topics.
    """
    pass  # Integration point - see agent_memory.py
