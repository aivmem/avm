"""
AI Virtual Filesystem (VFS)

让 AI Bot 通过文件路径读写结构化知识。
配置驱动，支持自定义 provider 和权限规则。
"""

__version__ = "0.2.0"

from .node import VFSNode
from .graph import KVGraph
from .store import VFSStore
from .config import VFSConfig, ProviderSpec, PermissionRule, load_config
from .core import VFS, register_provider_type

__all__ = [
    # Core
    "VFS",
    "VFSConfig",
    "VFSStore",
    "VFSNode",
    "KVGraph",
    # Config
    "ProviderSpec",
    "PermissionRule",
    "load_config",
    "register_provider_type",
]
