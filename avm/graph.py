"""
vfs/graph.py - knowledge graph（adjacency list implementation）
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from enum import Enum


class EdgeType(Enum):
    """edge type"""
    PEER = "peer"           # peer relation (e.g., stocks in same sector)
    PARENT = "parent"       # parent-child relation (e.g., sector→individual stock)
    CITATION = "citation"   # citation relation (e.g., research report reference)
    DERIVED = "derived"     # derived relation (e.g., signal derived from indicator)
    RELATED = "related"     # general relation
    VERSION_OF = "version_of"  # versionrelation（append-only memory）


@dataclass
class Edge:
    """
    graph edge
    """
    source: str         # source node path
    target: str         # targetnodepath
    edge_type: EdgeType = EdgeType.RELATED
    weight: float = 1.0
    meta: Dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_tuple(self) -> Tuple[str, str, str, float]:
        return (self.source, self.target, self.edge_type.value, self.weight)
    
    def __repr__(self) -> str:
        return f"Edge({self.source} --[{self.edge_type.value}]--> {self.target})"


class KVGraph:
    """
    knowledge graph
    
    simple adjacency list implementation, supports：
    - add/delete edge
    - Query all related to a node
    - Filter by edge type
    - Path finding (BFS)
    """
    
    def __init__(self):
        # adjacency list: {source: [Edge, ...]}
        self._outgoing: Dict[str, List[Edge]] = {}
        # Reverse index: {target: [Edge, ...]}
        self._incoming: Dict[str, List[Edge]] = {}
    
    def add_edge(self, source: str, target: str, 
                 edge_type: EdgeType = EdgeType.RELATED,
                 weight: float = 1.0,
                 meta: Dict = None) -> Edge:
        """addedge"""
        edge = Edge(
            source=source,
            target=target,
            edge_type=edge_type,
            weight=weight,
            meta=meta or {},
        )
        
        if source not in self._outgoing:
            self._outgoing[source] = []
        self._outgoing[source].append(edge)
        
        if target not in self._incoming:
            self._incoming[target] = []
        self._incoming[target].append(edge)
        
        return edge
    
    def remove_edge(self, source: str, target: str, 
                    edge_type: EdgeType = None) -> int:
        """delete edge，returndeletecount"""
        removed = 0
        
        if source in self._outgoing:
            before = len(self._outgoing[source])
            self._outgoing[source] = [
                e for e in self._outgoing[source]
                if not (e.target == target and 
                       (edge_type is None or e.edge_type == edge_type))
            ]
            removed = before - len(self._outgoing[source])
        
        if target in self._incoming:
            self._incoming[target] = [
                e for e in self._incoming[target]
                if not (e.source == source and
                       (edge_type is None or e.edge_type == edge_type))
            ]
        
        return removed
    
    def get_outgoing(self, node: str, 
                     edge_type: EdgeType = None) -> List[Edge]:
        """get outgoing edges"""
        edges = self._outgoing.get(node, [])
        if edge_type:
            edges = [e for e in edges if e.edge_type == edge_type]
        return edges
    
    def get_incoming(self, node: str,
                     edge_type: EdgeType = None) -> List[Edge]:
        """get incoming edges"""
        edges = self._incoming.get(node, [])
        if edge_type:
            edges = [e for e in edges if e.edge_type == edge_type]
        return edges
    
    def get_neighbors(self, node: str,
                      edge_type: EdgeType = None) -> Set[str]:
        """Get all neighbor nodes"""
        neighbors = set()
        for e in self.get_outgoing(node, edge_type):
            neighbors.add(e.target)
        for e in self.get_incoming(node, edge_type):
            neighbors.add(e.source)
        return neighbors
    
    def find_path(self, source: str, target: str, 
                  max_depth: int = 5) -> Optional[List[str]]:
        """BFS path finding"""
        if source == target:
            return [source]
        
        visited = {source}
        queue = [(source, [source])]
        
        while queue and len(queue[0][1]) <= max_depth:
            current, path = queue.pop(0)
            
            for neighbor in self.get_neighbors(current):
                if neighbor == target:
                    return path + [neighbor]
                
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        
        return None
    
    def get_subgraph(self, center: str, depth: int = 1) -> "KVGraph":
        """Get subgraph centered on a node"""
        subgraph = KVGraph()
        visited = set()
        queue = [(center, 0)]
        
        while queue:
            node, d = queue.pop(0)
            if node in visited or d > depth:
                continue
            visited.add(node)
            
            for edge in self.get_outgoing(node):
                subgraph.add_edge(
                    edge.source, edge.target,
                    edge.edge_type, edge.weight, edge.meta
                )
                if d < depth:
                    queue.append((edge.target, d + 1))
            
            for edge in self.get_incoming(node):
                subgraph.add_edge(
                    edge.source, edge.target,
                    edge.edge_type, edge.weight, edge.meta
                )
                if d < depth:
                    queue.append((edge.source, d + 1))
        
        return subgraph
    
    def to_adjacency_list(self) -> Dict[str, List[Dict]]:
        """exportadjacency list"""
        result = {}
        for source, edges in self._outgoing.items():
            result[source] = [
                {"target": e.target, "type": e.edge_type.value, "weight": e.weight}
                for e in edges
            ]
        return result
    
    @property
    def node_count(self) -> int:
        """node count"""
        nodes = set(self._outgoing.keys()) | set(self._incoming.keys())
        return len(nodes)
    
    @property
    def edge_count(self) -> int:
        """edge count"""
        return sum(len(edges) for edges in self._outgoing.values())
    
    def __repr__(self) -> str:
        return f"KVGraph({self.node_count} nodes, {self.edge_count} edges)"
