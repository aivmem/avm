"""
Librarian: Global Knowledge Router for Multi-Agent Systems

The Librarian is a privileged service that:
1. Has global visibility (ignores permissions for metadata)
2. Routes queries to appropriate content or agents
3. Respects permissions when returning actual content
4. Suggests collaboration when content is inaccessible

Usage:
    librarian = Librarian(store)
    response = librarian.query("agent_a", "NVDA analysis")
    
    if response.accessible:
        # Direct access
        for node in response.accessible:
            print(node.content)
    else:
        # Need collaboration
        for suggestion in response.suggestions:
            print(f"Ask {suggestion.agent} about {suggestion.topic}")
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
import re

from .node import AVMNode
from .store import AVMStore
from .config import AVMConfig


@dataclass
class AgentInfo:
    """Agent registry entry"""
    id: str
    display_name: str = ""
    capabilities: List[str] = field(default_factory=list)
    description: str = ""
    last_active: Optional[datetime] = None
    memory_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name or self.id,
            "capabilities": self.capabilities,
            "description": self.description,
            "last_active": self.last_active.isoformat() if self.last_active else None,
            "memory_count": self.memory_count,
        }


@dataclass
class SearchMatch:
    """A search match with metadata"""
    path: str
    score: float
    owner: Optional[str] = None
    topic: Optional[str] = None
    snippet: str = ""
    accessible: bool = False


@dataclass
class CollaborationSuggestion:
    """Suggestion to ask another agent"""
    agent: str
    topic: str
    relevance: float
    reason: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "topic": self.topic,
            "relevance": self.relevance,
            "reason": self.reason,
        }


@dataclass
class LibrarianResponse:
    """Response from a Librarian query"""
    query: str
    requester: str
    accessible: List[AVMNode] = field(default_factory=list)
    suggestions: List[CollaborationSuggestion] = field(default_factory=list)
    directory: List[AgentInfo] = field(default_factory=list)
    total_matches: int = 0
    accessible_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "requester": self.requester,
            "accessible_count": self.accessible_count,
            "total_matches": self.total_matches,
            "accessible": [n.to_dict() for n in self.accessible],
            "suggestions": [s.to_dict() for s in self.suggestions],
            "directory": [a.to_dict() for a in self.directory],
        }


class PrivacyPolicy:
    """Controls what metadata can be revealed"""
    
    FULL = "full"           # Reveal existence + owner + topic
    OWNER_ONLY = "owner"    # Only reveal who to ask
    EXISTENCE = "existence" # Only reveal "someone knows"
    NONE = "none"           # Don't reveal anything
    
    def __init__(self, level: str = "owner"):
        self.level = level
    
    def can_reveal_existence(self) -> bool:
        return self.level in (self.FULL, self.OWNER_ONLY, self.EXISTENCE)
    
    def can_reveal_owner(self) -> bool:
        return self.level in (self.FULL, self.OWNER_ONLY)
    
    def can_reveal_topic(self) -> bool:
        return self.level == self.FULL


class Librarian:
    """
    Global Knowledge Router
    
    The Librarian has privileged access to all memory metadata,
    but respects permissions when returning content.
    """
    
    def __init__(self, store: AVMStore, config: AVMConfig = None,
                 privacy_policy: PrivacyPolicy = None):
        self.store = store
        self.config = config
        self.privacy = privacy_policy or PrivacyPolicy("owner")
        self._agent_registry: Dict[str, AgentInfo] = {}
        self._rebuild_registry()
    
    def _rebuild_registry(self):
        """Build agent registry from existing memory paths"""
        # Scan /memory/private/* for agent IDs
        try:
            nodes = self.store.list_nodes("/memory/private/", limit=1000)
            agent_paths: Dict[str, List[str]] = {}
            
            for node in nodes:
                # Extract agent ID from path
                parts = node.path.split("/")
                if len(parts) >= 4:
                    agent_id = parts[3]  # /memory/private/{agent_id}/...
                    if agent_id not in agent_paths:
                        agent_paths[agent_id] = []
                    agent_paths[agent_id].append(node.path)
            
            # Build registry
            for agent_id, paths in agent_paths.items():
                # Infer capabilities from path/content keywords
                capabilities = self._infer_capabilities(paths)
                
                self._agent_registry[agent_id] = AgentInfo(
                    id=agent_id,
                    capabilities=capabilities,
                    memory_count=len(paths),
                )
        except Exception:
            pass  # Registry building is best-effort
    
    def _infer_capabilities(self, paths: List[str]) -> List[str]:
        """Infer agent capabilities from their memory paths"""
        capabilities = set()
        
        keywords = {
            "market": ["market", "trading", "stock", "nvda", "btc"],
            "code": ["code", "programming", "bug", "feature", "test"],
            "research": ["paper", "research", "analysis", "study"],
            "personal": ["preference", "setting", "config"],
        }
        
        for path in paths:
            path_lower = path.lower()
            for capability, kws in keywords.items():
                if any(kw in path_lower for kw in kws):
                    capabilities.add(capability)
        
        return list(capabilities)
    
    def _get_owner(self, path: str) -> Optional[str]:
        """Extract owner agent ID from path"""
        if path.startswith("/memory/private/"):
            parts = path.split("/")
            if len(parts) >= 4:
                return parts[3]
        return None
    
    def _extract_topic(self, path: str) -> str:
        """Extract topic from path"""
        # /memory/private/agent/market/nvda.md → "market/nvda"
        parts = path.split("/")
        if len(parts) >= 5:
            return "/".join(parts[4:]).replace(".md", "")
        return path.split("/")[-1].replace(".md", "")
    
    def _can_access(self, requester: str, path: str) -> bool:
        """Check if requester can access this path"""
        # Shared memory is accessible to all
        if path.startswith("/memory/shared/"):
            return True
        
        # Private memory only to owner
        if path.startswith("/memory/private/"):
            owner = self._get_owner(path)
            return owner == requester
        
        # Check config permissions
        if self.config:
            return self.config.check_permission(path, "read")
        
        return False
    
    def register_agent(self, agent_id: str, info: AgentInfo = None):
        """Register an agent with capabilities"""
        if info is None:
            info = AgentInfo(id=agent_id)
        self._agent_registry[agent_id] = info
    
    def query(self, requester: str, question: str, 
              limit: int = 20) -> LibrarianResponse:
        """
        Query the Librarian for information.
        
        Args:
            requester: The agent making the request
            question: Natural language query
            limit: Max results
        
        Returns:
            LibrarianResponse with accessible content and/or suggestions
        """
        response = LibrarianResponse(query=question, requester=requester)
        
        # 1. Global search (privileged - ignores permissions for discovery)
        all_matches = self._privileged_search(question, limit * 2)
        response.total_matches = len(all_matches)
        
        # 2. Separate by accessibility
        accessible = []
        inaccessible_by_owner: Dict[str, List[SearchMatch]] = {}
        
        for match in all_matches:
            if self._can_access(requester, match.path):
                match.accessible = True
                accessible.append(match)
            else:
                owner = match.owner or "unknown"
                if owner not in inaccessible_by_owner:
                    inaccessible_by_owner[owner] = []
                inaccessible_by_owner[owner].append(match)
        
        # 3. Return accessible content
        for match in accessible[:limit]:
            node = self.store.get_node(match.path)
            if node:
                response.accessible.append(node)
        response.accessible_count = len(response.accessible)
        
        # 4. Generate collaboration suggestions
        if self.privacy.can_reveal_existence():
            for owner, matches in inaccessible_by_owner.items():
                if owner == requester:
                    continue
                
                best_match = max(matches, key=lambda m: m.score)
                
                suggestion = CollaborationSuggestion(
                    agent=owner if self.privacy.can_reveal_owner() else "another agent",
                    topic=best_match.topic if self.privacy.can_reveal_topic() else "related information",
                    relevance=best_match.score,
                    reason=f"Has {len(matches)} relevant memories" if self.privacy.can_reveal_topic() else "",
                )
                response.suggestions.append(suggestion)
        
        # Sort suggestions by relevance
        response.suggestions.sort(key=lambda s: s.relevance, reverse=True)
        
        return response
    
    def _privileged_search(self, query: str, limit: int) -> List[SearchMatch]:
        """Search all content (privileged, ignores permissions)"""
        matches = []
        
        # Use FTS search
        try:
            results = self.store.search(query, limit=limit)
            for node, score in results:
                owner = self._get_owner(node.path)
                topic = self._extract_topic(node.path)
                
                # Get snippet
                content = node.content or ""
                snippet = content[:200] + "..." if len(content) > 200 else content
                
                matches.append(SearchMatch(
                    path=node.path,
                    score=score,
                    owner=owner,
                    topic=topic,
                    snippet=snippet,
                ))
        except Exception:
            pass
        
        return matches
    
    def who_knows(self, topic: str, limit: int = 10) -> List[AgentInfo]:
        """Find agents who might know about a topic"""
        matches = self._privileged_search(topic, limit * 3)
        
        # Collect unique owners
        owner_scores: Dict[str, float] = {}
        for match in matches:
            if match.owner:
                if match.owner not in owner_scores:
                    owner_scores[match.owner] = 0
                owner_scores[match.owner] = max(owner_scores[match.owner], match.score)
        
        # Return agent infos sorted by relevance
        result = []
        for owner, score in sorted(owner_scores.items(), key=lambda x: x[1], reverse=True)[:limit]:
            info = self._agent_registry.get(owner, AgentInfo(id=owner))
            result.append(info)
        
        return result
    
    def agents(self) -> List[AgentInfo]:
        """List all registered agents"""
        return list(self._agent_registry.values())
    
    def agent(self, agent_id: str) -> Optional[AgentInfo]:
        """Get info about a specific agent"""
        return self._agent_registry.get(agent_id)
    
    def directory(self) -> Dict[str, Any]:
        """Get full directory of agents and their capabilities"""
        agents_by_capability: Dict[str, List[str]] = {}
        
        for agent_id, info in self._agent_registry.items():
            for cap in info.capabilities:
                if cap not in agents_by_capability:
                    agents_by_capability[cap] = []
                agents_by_capability[cap].append(agent_id)
        
        return {
            "agents": [a.to_dict() for a in self._agent_registry.values()],
            "by_capability": agents_by_capability,
            "total_agents": len(self._agent_registry),
        }


def get_librarian(store: AVMStore = None, config: AVMConfig = None) -> Librarian:
    """Get or create a Librarian instance"""
    if store is None:
        from .core import AVM
        avm = AVM(config=config)
        store = avm.store
    
    return Librarian(store, config)
