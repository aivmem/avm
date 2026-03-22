"""
vfs/config.py - Config-driven VFS

Supports YAML configuration files with zero hardcoding.
"""

import os
import re
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Type, Callable
import yaml


@dataclass
class ProviderSpec:
    """Provider specification"""
    pattern: str                    # glob pattern, e.g. "/trading/positions*"
    type: str                       # provider type name
    ttl: int = 0                    # TTL in seconds (0 = no expiry)
    config: Dict[str, Any] = field(default_factory=dict)  # provider-specific config
    
    def matches(self, path: str) -> bool:
        """Check if path matches this provider pattern"""
        return fnmatch.fnmatch(path, self.pattern)


@dataclass  
class PermissionRule:
    """Permission rule"""
    pattern: str                    # glob pattern
    access: str = "ro"              # "ro" | "rw" | "none"
    
    def matches(self, path: str) -> bool:
        return fnmatch.fnmatch(path, self.pattern)
    
    @property
    def can_read(self) -> bool:
        return self.access in ("ro", "rw")
    
    @property
    def can_write(self) -> bool:
        return self.access == "rw"


@dataclass
class AVMConfig:
    """
    VFS Configuration
    
    Loads from YAML file with environment variable expansion.
    """
    providers: List[ProviderSpec] = field(default_factory=list)
    permissions: List[PermissionRule] = field(default_factory=list)
    db_path: str = ""
    default_ttl: int = 300
    
    # Default access if no matching rule
    default_access: str = "ro"

    # Embedding config (optional)
    embedding: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_yaml(cls, path: str) -> "AVMConfig":
        """Load configuration from YAML file"""
        with open(path) as f:
            raw = f.read()
        
        # Expand env vars ${VAR} or $VAR
        def expand_env(match):
            var = match.group(1) or match.group(2)
            return os.environ.get(var, match.group(0))
        
        raw = re.sub(r'\$\{(\w+)\}|\$(\w+)', expand_env, raw)
        
        data = yaml.safe_load(raw)
        return cls.from_dict(data)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "AVMConfig":
        """Create configuration from dictionary"""
        providers = [
            ProviderSpec(
                pattern=p.get("pattern", "/*"),
                type=p.get("type", "static"),
                ttl=p.get("ttl", 0),
                config=p.get("config", {}),
            )
            for p in data.get("providers", [])
        ]
        
        # Use default permissions if not specified in config
        raw_permissions = data.get("permissions")
        if raw_permissions is None:
            # Default permissions for memory paths
            permissions = [
                PermissionRule(pattern="/memory/private/*", access="rw"),
                PermissionRule(pattern="/memory/shared/*", access="rw"),
                PermissionRule(pattern="/memory/*", access="rw"),
                PermissionRule(pattern="/snapshots/*", access="rw"),
                PermissionRule(pattern="/live/*", access="ro"),
                PermissionRule(pattern="/research/*", access="ro"),
            ]
        else:
            permissions = [
                PermissionRule(
                    pattern=p.get("pattern", "/*"),
                    access=p.get("access", "ro"),
                )
                for p in raw_permissions
            ]
        
        return cls(
            providers=providers,
            permissions=permissions,
            db_path=data.get("db_path", ""),
            default_ttl=data.get("default_ttl", 300),
            default_access=data.get("default_access", "ro"),
            embedding=data.get("embedding", {}),
        )
    
    def to_dict(self) -> Dict:
        """Export as dictionary"""
        return {
            "providers": [
                {"pattern": p.pattern, "type": p.type, "ttl": p.ttl, "config": p.config}
                for p in self.providers
            ],
            "permissions": [
                {"pattern": p.pattern, "access": p.access}
                for p in self.permissions
            ],
            "db_path": self.db_path,
            "default_ttl": self.default_ttl,
            "default_access": self.default_access,
        }
    
    def get_provider_spec(self, path: str) -> Optional[ProviderSpec]:
        """Get provider spec matching path"""
        for spec in self.providers:
            if spec.matches(path):
                return spec
        return None
    
    def check_permission(self, path: str, action: str = "read") -> bool:
        """
        Check path permission
        
        Args:
            path: path
            action: "read" | "write"
        """
        for rule in self.permissions:
            if rule.matches(path):
                if action == "read":
                    return rule.can_read
                elif action == "write":
                    return rule.can_write
                return False
        
        # Default permission
        if action == "read":
            return self.default_access in ("ro", "rw")
        elif action == "write":
            return self.default_access == "rw"
        return False


# Default configuration (backward compatible)
DEFAULT_CONFIG = AVMConfig(
    providers=[
        ProviderSpec(pattern="/live/positions*", type="alpaca_positions", ttl=60),
        ProviderSpec(pattern="/live/orders*", type="alpaca_orders", ttl=30),
        ProviderSpec(pattern="/live/indicators/*", type="technical_indicators", ttl=300),
        ProviderSpec(pattern="/live/news/*", type="news", ttl=600),
        ProviderSpec(pattern="/live/watchlist*", type="watchlist", ttl=300),
    ],
    permissions=[
        PermissionRule(pattern="/memory/private/*", access="rw"),
        PermissionRule(pattern="/memory/shared/*", access="rw"),
        PermissionRule(pattern="/memory/*", access="rw"),
        PermissionRule(pattern="/snapshots/*", access="rw"),
        PermissionRule(pattern="/live/*", access="ro"),
        PermissionRule(pattern="/research/*", access="ro"),
    ],
    default_access="ro",
)


def load_config(config_path: str = None) -> AVMConfig:
    """
    Load configuration
    
    Priority:
    1. Specified path
    2. Environment variable VFS_CONFIG
    3. ~/.avm/config.yaml
    4. Default configuration
    """
    paths_to_try = []
    
    if config_path:
        paths_to_try.append(config_path)
    
    if os.environ.get("VFS_CONFIG"):
        paths_to_try.append(os.environ["VFS_CONFIG"])
    
    paths_to_try.append(str(Path.home() / ".avm" / "config.yaml"))
    paths_to_try.append(str(Path.home() / ".openclaw" / "vfs" / "config.yaml"))
    
    for path in paths_to_try:
        if os.path.exists(path):
            return AVMConfig.from_yaml(path)
    
    return DEFAULT_CONFIG
