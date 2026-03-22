"""
vfs/node.py - VFS node data structure
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum
import hashlib
import json

from .utils import utcnow


class NodeType(Enum):
    """node type"""
    FILE = "file"
    DIRECTORY = "dir"
    LINK = "link"  # Soft link


class Permission(Enum):
    """permission"""
    READ_ONLY = "ro"
    READ_WRITE = "rw"


@dataclass
class AVMNode:
    """
    VFSnode
    
    eachnode：
    - path: Virtual path (e.g., /research/MSFT.md)
    - content: filecontent
    - meta: Metadata (TTL, source, update time, etc.)
    - node_type: File/directory/link
    """
    path: str
    content: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    node_type: NodeType = NodeType.FILE
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    version: int = 1
    
    # Permission determined by path prefix
    WRITABLE_PREFIXES = ("/memory", "/trash", "/archive", "/shared", "/task")
    READONLY_PREFIXES = ("/research", "/live", "/links")
    
    @property
    def is_writable(self) -> bool:
        """checknodewhetherwritable"""
        for prefix in self.WRITABLE_PREFIXES:
            if self.path.startswith(prefix):
                return True
        return False
    
    @property
    def is_live(self) -> bool:
        """checkwhetherlive datanode"""
        return self.path.startswith("/live")
    
    @property
    def ttl_seconds(self) -> Optional[int]:
        """getTTL（onlylivenode）"""
        return self.meta.get("ttl_seconds") if self.is_live else None
    
    @property
    def is_expired(self) -> bool:
        """checklivenodewhetherexpired"""
        if not self.is_live:
            return False
        ttl = self.ttl_seconds
        if ttl is None:
            return False
        age = (utcnow() - self.updated_at).total_seconds()
        return age > ttl
    
    @property
    def content_h(self) -> str:
        """Content hash (for diff detection)"""
        return hashlib.sha256(self.content.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """To dict"""
        return {
            "path": self.path,
            "content": self.content,
            "meta": self.meta,
            "node_type": self.node_type.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AVMNode":
        """fromdictcreate"""
        return cls(
            path=data["path"],
            content=data.get("content", ""),
            meta=data.get("meta", {}),
            node_type=NodeType(data.get("node_type", "file")),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else utcnow(),
            version=data.get("version", 1),
        )
    
    def __repr__(self) -> str:
        return f"AVMNode({self.path}, v{self.version}, {len(self.content)} bytes)"


@dataclass
class NodeDiff:
    """
    nodechangerecord
    """
    node_path: str
    version: int
    old_h: Optional[str]
    new_h: str
    diff_content: str  # Unified diff or complete new content
    changed_at: datetime = field(default_factory=utcnow)
    change_type: str = "update"  # create/update/delete
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_path": self.node_path,
            "version": self.version,
            "old_h": self.old_h,
            "new_h": self.new_h,
            "diff_content": self.diff_content,
            "changed_at": self.changed_at.isoformat(),
            "change_type": self.change_type,
        }
