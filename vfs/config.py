"""
vfs/config.py - 配置驱动的 VFS

支持 YAML 配置文件，零硬编码
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
    """Provider 规格"""
    pattern: str                    # glob pattern, e.g. "/trading/positions*"
    type: str                       # provider type name
    ttl: int = 0                    # TTL in seconds (0 = no expiry)
    config: Dict[str, Any] = field(default_factory=dict)  # provider-specific config
    
    def matches(self, path: str) -> bool:
        """检查路径是否匹配此 provider"""
        return fnmatch.fnmatch(path, self.pattern)


@dataclass  
class PermissionRule:
    """权限规则"""
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
class VFSConfig:
    """
    VFS 配置
    
    从 YAML 文件加载，支持环境变量展开
    """
    providers: List[ProviderSpec] = field(default_factory=list)
    permissions: List[PermissionRule] = field(default_factory=list)
    db_path: str = ""
    default_ttl: int = 300
    
    # 默认权限（如果没有匹配的规则）
    default_access: str = "ro"
    
    @classmethod
    def from_yaml(cls, path: str) -> "VFSConfig":
        """从 YAML 文件加载配置"""
        with open(path) as f:
            raw = f.read()
        
        # 展开环境变量 ${VAR} 或 $VAR
        def expand_env(match):
            var = match.group(1) or match.group(2)
            return os.environ.get(var, match.group(0))
        
        raw = re.sub(r'\$\{(\w+)\}|\$(\w+)', expand_env, raw)
        
        data = yaml.safe_load(raw)
        return cls.from_dict(data)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "VFSConfig":
        """从字典创建配置"""
        providers = [
            ProviderSpec(
                pattern=p.get("pattern", "/*"),
                type=p.get("type", "static"),
                ttl=p.get("ttl", 0),
                config=p.get("config", {}),
            )
            for p in data.get("providers", [])
        ]
        
        permissions = [
            PermissionRule(
                pattern=p.get("pattern", "/*"),
                access=p.get("access", "ro"),
            )
            for p in data.get("permissions", [])
        ]
        
        return cls(
            providers=providers,
            permissions=permissions,
            db_path=data.get("db_path", ""),
            default_ttl=data.get("default_ttl", 300),
            default_access=data.get("default_access", "ro"),
        )
    
    def to_dict(self) -> Dict:
        """导出为字典"""
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
        """获取匹配路径的 provider spec"""
        for spec in self.providers:
            if spec.matches(path):
                return spec
        return None
    
    def check_permission(self, path: str, action: str = "read") -> bool:
        """
        检查路径权限
        
        Args:
            path: 路径
            action: "read" | "write"
        """
        for rule in self.permissions:
            if rule.matches(path):
                if action == "read":
                    return rule.can_read
                elif action == "write":
                    return rule.can_write
                return False
        
        # 默认权限
        if action == "read":
            return self.default_access in ("ro", "rw")
        elif action == "write":
            return self.default_access == "rw"
        return False


# 默认配置（向后兼容）
DEFAULT_CONFIG = VFSConfig(
    providers=[
        ProviderSpec(pattern="/live/positions*", type="alpaca_positions", ttl=60),
        ProviderSpec(pattern="/live/orders*", type="alpaca_orders", ttl=30),
        ProviderSpec(pattern="/live/indicators/*", type="technical_indicators", ttl=300),
        ProviderSpec(pattern="/live/news/*", type="news", ttl=600),
        ProviderSpec(pattern="/live/watchlist*", type="watchlist", ttl=300),
    ],
    permissions=[
        PermissionRule(pattern="/memory/*", access="rw"),
        PermissionRule(pattern="/live/*", access="ro"),
        PermissionRule(pattern="/research/*", access="ro"),
    ],
    default_access="ro",
)


def load_config(config_path: str = None) -> VFSConfig:
    """
    加载配置
    
    优先级:
    1. 指定路径
    2. 环境变量 VFS_CONFIG
    3. ~/.vfs/config.yaml
    4. 默认配置
    """
    paths_to_try = []
    
    if config_path:
        paths_to_try.append(config_path)
    
    if os.environ.get("VFS_CONFIG"):
        paths_to_try.append(os.environ["VFS_CONFIG"])
    
    paths_to_try.append(str(Path.home() / ".vfs" / "config.yaml"))
    paths_to_try.append(str(Path.home() / ".openclaw" / "vfs" / "config.yaml"))
    
    for path in paths_to_try:
        if os.path.exists(path):
            return VFSConfig.from_yaml(path)
    
    return DEFAULT_CONFIG
