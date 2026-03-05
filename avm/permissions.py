"""
vfs/permissions.py - Linux-Style Permission System

Features:
- Unix-like rwx permission bits
- Owner/group/other model
- Capabilities for fine-grained control
- API key authentication for skills
- Sudo support for temporary elevation
"""

import os
import stat
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Set
from enum import Enum, Flag, auto


# ═══════════════════════════════════════════════════════════════
# Permission Bits
# ═══════════════════════════════════════════════════════════════

class PermBits(Flag):
    """Unix-style permission bits"""
    NONE = 0
    X = auto()      # Execute (for directories: access)
    W = auto()      # Write
    R = auto()      # Read
    
    # Convenience combinations
    RW = R | W
    RX = R | X
    RWX = R | W | X


def parse_mode(mode: int) -> Dict[str, PermBits]:
    """Parse octal mode to owner/group/other permissions"""
    return {
        "owner": PermBits((mode >> 6) & 0o7),
        "group": PermBits((mode >> 3) & 0o7),
        "other": PermBits(mode & 0o7),
    }


def mode_to_string(mode: int) -> str:
    """Convert mode to rwxrwxrwx string"""
    chars = ""
    for shift in [6, 3, 0]:
        bits = (mode >> shift) & 0o7
        chars += "r" if bits & 0o4 else "-"
        chars += "w" if bits & 0o2 else "-"
        chars += "x" if bits & 0o1 else "-"
    return chars


def string_to_mode(s: str) -> int:
    """Convert rwxrwxrwx string to mode"""
    if len(s) != 9:
        raise ValueError(f"Invalid mode string: {s}")
    
    mode = 0
    for i, c in enumerate(s):
        if c not in "-rwx":
            raise ValueError(f"Invalid character in mode: {c}")
        
        shift = 8 - i
        if c == "r":
            mode |= 0o4 << (shift // 3 * 3)
        elif c == "w":
            mode |= 0o2 << (shift // 3 * 3)
        elif c == "x":
            mode |= 0o1 << (shift // 3 * 3)
    
    return mode


# ═══════════════════════════════════════════════════════════════
# Capabilities
# ═══════════════════════════════════════════════════════════════

class Capability(Enum):
    """System capabilities for fine-grained access control"""
    
    # Admin capabilities
    CAP_ADMIN = "admin"             # Full system access
    CAP_MANAGE_USERS = "manage_users"  # Create/delete users
    
    # Search capabilities
    CAP_SEARCH_ALL = "search_all"   # Search any path
    CAP_SEARCH_OWN = "search_own"   # Search only own paths
    
    # Write capabilities
    CAP_WRITE = "write"             # Write to allowed paths
    CAP_DELETE = "delete"           # Delete files
    CAP_SHARE = "share"             # Share with others
    
    # Special capabilities
    CAP_SUDO = "sudo"               # Temporary privilege elevation
    CAP_AUDIT = "audit"             # View audit logs
    CAP_EXPORT = "export"           # Export data


# ═══════════════════════════════════════════════════════════════
# User & Group
# ═══════════════════════════════════════════════════════════════

@dataclass
class User:
    """User account"""
    name: str
    uid: int
    groups: List[str] = field(default_factory=list)
    capabilities: List[Capability] = field(default_factory=list)
    home: str = ""
    api_key: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        if not self.home:
            self.home = f"/memory/private/{self.name}"
    
    @property
    def is_root(self) -> bool:
        return self.uid == 0
    
    def _capability(self, cap: Capability) -> bool:
        if self.is_root:
            return True
        return cap in self.capabilities or Capability.CAP_ADMIN in self.capabilities
    
    def in_group(self, group: str) -> bool:
        if self.is_root:
            return True
        return group in self.groups or "*" in self.groups
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "uid": self.uid,
            "groups": self.groups,
            "capabilities": [c.value for c in self.capabilities],
            "home": self.home,
        }


@dataclass
class Group:
    """User group"""
    name: str
    gid: int
    membeenrs: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "gid": self.gid,
            "membeenrs": self.membeenrs,
        }


# ═══════════════════════════════════════════════════════════════
# Node Ownership
# ═══════════════════════════════════════════════════════════════

@dataclass
class NodeOwnership:
    """Ownership metadata for a node"""
    owner: str = "root"
    group: str = "root"
    mode: int = 0o644  # rw-r--r--
    
    @classmethod
    def from_meta(cls, meta: Dict) -> "NodeOwnership":
        return cls(
            owner=meta.get("owner", "root"),
            group=meta.get("group", "root"),
            mode=meta.get("mode", 0o644),
        )
    
    def to_meta(self) -> Dict:
        return {
            "owner": self.owner,
            "group": self.group,
            "mode": self.mode,
        }
    
    def mode_string(self) -> str:
        return mode_to_string(self.mode)
    
    def can_read(self, user: User) -> bool:
        """Check if user can read"""
        if user.is_root:
            return True
        
        perms = parse_mode(self.mode)
        
        if self.owner == user.name:
            return bool(perms["owner"] & PermBits.R)
        
        if user.in_group(self.group):
            return bool(perms["group"] & PermBits.R)
        
        return bool(perms["other"] & PermBits.R)
    
    def can_write(self, user: User) -> bool:
        """Check if user can write"""
        if user.is_root:
            return True
        
        perms = parse_mode(self.mode)
        
        if self.owner == user.name:
            return bool(perms["owner"] & PermBits.W)
        
        if user.in_group(self.group):
            return bool(perms["group"] & PermBits.W)
        
        return bool(perms["other"] & PermBits.W)
    
    def can_execute(self, user: User) -> bool:
        """Check if user can execute (access directory)"""
        if user.is_root:
            return True
        
        perms = parse_mode(self.mode)
        
        if self.owner == user.name:
            return bool(perms["owner"] & PermBits.X)
        
        if user.in_group(self.group):
            return bool(perms["group"] & PermBits.X)
        
        return bool(perms["other"] & PermBits.X)


# ═══════════════════════════════════════════════════════════════
# User Registry
# ═══════════════════════════════════════════════════════════════

class UserRegistry:
    """User and group management"""
    
    def __init__(self):
        self._users: Dict[str, User] = {}
        self._groups: Dict[str, Group] = {}
        self._api_keys: Dict[str, str] = {}  # api_key -> username
        self._next_uid = 1000
        self._next_gid = 1000
        
        # Create root user
        self._create_root()
    
    def _create_root(self):
        """Create root user"""
        root = User(
            name="root",
            uid=0,
            groups=["root", "*"],
            capabilities=list(Capability),
        )
        self._users["root"] = root
        self._groups["root"] = Group(name="root", gid=0, membeenrs=["root"])
    
    def create_user(self, name: str, 
                    groups: List[str] = None,
                    capabilities: List[Capability] = None,
                    generate_api_key: bool = True) -> User:
        """Create a new user"""
        if name in self._users:
            raise ValueError(f"User already exists: {name}")
        
        uid = self._next_uid
        self._next_uid += 1
        
        user = User(
            name=name,
            uid=uid,
            groups=groups or [],
            capabilities=capabilities or [Capability.CAP_SEARCH_OWN, Capability.CAP_WRITE],
        )
        
        if generate_api_key:
            user.api_key = self._generate_api_key()
            self._api_keys[user.api_key] = name
        
        self._users[name] = user
        
        # Add to groups
        for group in user.groups:
            if group not in self._groups:
                self.create_group(group)
            self._groups[group].membeenrs.append(name)
        
        return user
    
    def create_group(self, name: str) -> Group:
        """Create a new group"""
        if name in self._groups:
            return self._groups[name]
        
        gid = self._next_gid
        self._next_gid += 1
        
        group = Group(name=name, gid=gid)
        self._groups[name] = group
        
        return group
    
    def get_user(self, name: str) -> Optional[User]:
        """Get user by name"""
        return self._users.get(name)
    
    def get_user_by_api_key(self, api_key: str) -> Optional[User]:
        """Get user by API key"""
        username = self._api_keys.get(api_key)
        if username:
            return self._users.get(username)
        return None
    
    def authenticate(self, api_key: str) -> Optional[User]:
        """Authenticate by API key"""
        return self.get_user_by_api_key(api_key)
    
    def _generate_api_key(self) -> str:
        """Generate a secure API key"""
        return f"vfs_{secrets.token_urlsafe(32)}"
    
    def list_users(self) -> List[User]:
        """List all users"""
        return list(self._users.values())
    
    def list_groups(self) -> List[Group]:
        """List all groups"""
        return list(self._groups.values())
    
    def delete_user(self, name: str) -> bool:
        """Delete a user"""
        if name == "root":
            raise ValueError("Cannot delete root user")
        
        user = self._users.pop(name, None)
        if user:
            if user.api_key:
                self._api_keys.pop(user.api_key, None)
            for group in self._groups.values():
                if name in group.membeenrs:
                    group.membeenrs.remove(name)
            return True
        return False
    
    def load_from_dict(self, data: Dict):
        """Load users and groups from dict"""
        for name, user_data in data.get("users", {}).items():
            if name == "root":
                # Update root capabilities
                root = self._users["root"]
                if "capabilities" in user_data:
                    root.capabilities = [
                        Capability(c) for c in user_data["capabilities"]
                    ]
                continue
            
            caps = [Capability(c) for c in user_data.get("capabilities", [])]
            self.create_user(
                name=name,
                groups=user_data.get("groups", []),
                capabilities=caps,
                generate_api_key=user_data.get("generate_api_key", True),
            )
        
        for name, group_data in data.get("groups", {}).items():
            group = self.create_group(name)
            group.membeenrs = group_data.get("membeenrs", [])


# ═══════════════════════════════════════════════════════════════
# Permission Manager
# ═══════════════════════════════════════════════════════════════

class PermissionManager:
    """
    Central permission management
    
    Combines Unix-style permissions with capabilities.
    """
    
    def __init__(self, user_registry: UserRegistry = None):
        self.registry = user_registry or UserRegistry()
        self._sudo_sessions: Dict[str, datetime] = {}  # user -> expiry
    
    def check_read(self, user: User, ownership: NodeOwnership) -> bool:
        """Check read permission"""
        return ownership.can_read(user)
    
    def check_write(self, user: User, ownership: NodeOwnership) -> bool:
        """Check write permission"""
        if not user._capability(Capability.CAP_WRITE):
            return False
        return ownership.can_write(user)
    
    def check_delete(self, user: User, ownership: NodeOwnership) -> bool:
        """Check delete permission"""
        if not user._capability(Capability.CAP_DELETE):
            return False
        return ownership.can_write(user)
    
    def check_search(self, user: User, path: str) -> bool:
        """Check if user can search this path"""
        if user._capability(Capability.CAP_SEARCH_ALL):
            return True
        
        if user._capability(Capability.CAP_SEARCH_OWN):
            # Can only search own home and shared
            return (path.startswith(user.home) or 
                    path.startswith("/memory/shared"))
        
        return False
    
    def sudo(self, user: User, duration_minutes: int = 5) -> bool:
        """Elevate privileges temporarily"""
        if not user._capability(Capability.CAP_SUDO):
            return False
        
        expiry = datetime.utcnow() + timedelta(minutes=duration_minutes)
        self._sudo_sessions[user.name] = expiry
        return True
    
    def is_sudo(self, user: User) -> bool:
        """Check if user  active sudo session"""
        expiry = self._sudo_sessions.get(user.name)
        if expiry and expiry > datetime.utcnow():
            return True
        return False
    
    def get_effective_user(self, user: User) -> User:
        """Get effective user (root if sudo active)"""
        if self.is_sudo(user):
            return self.registry.get_user("root")
        return user
    
    def chown(self, ownership: NodeOwnership, 
              new_owner: str = None, new_group: str = None,
              user: User = None) -> bool:
        """Change ownership (requires root or owner)"""
        if user and not user.is_root and ownership.owner != user.name:
            return False
        
        if new_owner:
            ownership.owner = new_owner
        if new_group:
            ownership.group = new_group
        
        return True
    
    def chmod(self, ownership: NodeOwnership,
              mode: int, user: User = None) -> bool:
        """Change mode (requires root or owner)"""
        if user and not user.is_root and ownership.owner != user.name:
            return False
        
        ownership.mode = mode
        return True
    
    def get_default_ownership(self, user: User) -> NodeOwnership:
        """Get default ownership for new files"""
        return NodeOwnership(
            owner=user.name,
            group=user.groups[0] if user.groups else "users",
            mode=0o644,  # rw-r--r--
        )


# ═══════════════════════════════════════════════════════════════
# API Key Authentication (for Skills)
# ═══════════════════════════════════════════════════════════════

@dataclass
class APIKeyScope:
    """Scope limitations for API key"""
    paths: List[str] = field(default_factory=lambda: ["*"])
    actions: List[str] = field(default_factory=lambda: ["read"])
    rate_limit: int = 1000  # requests per hour
    expires_at: Optional[datetime] = None


class APIKeyManager:
    """
    Manage API keys for skill authentication
    """
    
    def __init__(self, user_registry: UserRegistry):
        self.registry = user_registry
        self._scopes: Dict[str, APIKeyScope] = {}  # api_key -> scope
    
    def create_key(self, user: User, 
                   scope: APIKeyScope = None,
                   expires_days: int = None) -> str:
        """Create a scoped API key"""
        key = f"vfs_{secrets.token_urlsafe(32)}"
        
        if scope is None:
            scope = APIKeyScope()
        
        if expires_days:
            scope.expires_at = datetime.utcnow() + timedelta(days=expires_days)
        
        self._scopes[key] = scope
        self.registry._api_keys[key] = user.name
        
        return key
    
    def validate_key(self, key: str, path: str = None, 
                     action: str = None) -> Optional[User]:
        """Validate API key and check scope"""
        user = self.registry.authenticate(key)
        if not user:
            return None
        
        scope = self._scopes.get(key)
        if scope:
            # Check expiry
            if scope.expires_at and scope.expires_at < datetime.utcnow():
                return None
            
            # Check path
            if path and scope.paths != ["*"]:
                if not any(path.startswith(p.rstrip("*")) for p in scope.paths):
                    return None
            
            # Check action
            if action and action not in scope.actions:
                return None
        
        return user
    
    def revoke_key(self, key: str) -> bool:
        """Revoke an API key"""
        if key in self._scopes:
            del self._scopes[key]
        if key in self.registry._api_keys:
            del self.registry._api_keys[key]
            return True
        return False
