"""
AI Virtual Filesystem (VFS)

A config-driven virtual filesystem for AI agents to read/write structured knowledge via file paths.
Supports custom providers, permissions, and multi-agent collaboration.
"""

__version__ = "1.0.0"

from .node import AVMNode
from .graph import KVGraph
from .store import AVMStore
from .config import AVMConfig, ProviderSpec, PermissionRule, load_config
from .core import AVM, register_provider_type

# Backward compatibility alias
VFS = AVM
from .retrieval import Retriever, DocumentSynthesizer, RetrievalResult
from .multi_agent import (
    AgentConfig, AgentRegistry, AgentRole, AgentQuota,
    NamespacePermissions, AuditLog, VersionedMemory, QuotaEnforcer
)
from .advanced import (
    SubscriptionManager, MemoryEvent, EventType,
    MemoryDecay, MemoryCompactor, CompactionResult,
    SemanticDeduplicator, DedupeResult,
    DerivedLinkManager, TimeQuery,
    TagManager, AccessStats, ExportManager, SyncManager
)
from .handlers import (
    ProviderConfig,
    ProviderManager,
    BaseHandler,
    FileHandler,
    HTTPHandler,
    ScriptHandler,
    PluginHandler,
    SQLiteHandler,
    register_handler,
    handler,  # Decorator for registering handlers with skill info
    HANDLERS,
)
from .index_handler import (
    IndexHandler,
    IndexStore,
    IndexEntry,
    FileEntry,
    ScanHook,
    ProjectScanHook,
    register_scan_hook,
    SCAN_HOOKS,
)
from .config_handler import (
    ConfigHandler,
    ConfigStore,
    MetaHandler,
    DEFAULT_SETTINGS,
    deep_merge,
)
from .permissions import (
    User, Group, Capability, PermBits,
    NodeOwnership, UserRegistry, PermissionManager,
    APIKeyScope, APIKeyManager,
    mode_to_string, string_to_mode
)

__all__ = [
    # Core
    "VFS",
    "AVMConfig",
    "AVMStore",
    "AVMNode",
    "KVGraph",
    # Config
    "ProviderSpec",
    "PermissionRule",
    "load_config",
    "register_provider_type",
    # Retrieval
    "Retriever",
    "DocumentSynthesizer",
    "RetrievalResult",
    # Multi-Agent
    "AgentConfig",
    "AgentRegistry",
    "AgentRole",
    "AgentQuota",
    "NamespacePermissions",
    "AuditLog",
    "VersionedMemory",
    "QuotaEnforcer",
    # Advanced
    "SubscriptionManager",
    "MemoryEvent",
    "EventType",
    "MemoryDecay",
    "MemoryCompactor",
    "CompactionResult",
    "SemanticDeduplicator",
    "DedupeResult",
    "DerivedLinkManager",
    "TimeQuery",
    "TagManager",
    "AccessStats",
    "ExportManager",
    "SyncManager",
    # Permissions
    "User",
    "Group", 
    "Capability",
    "PermBits",
    "NodeOwnership",
    "UserRegistry",
    "PermissionManager",
    "APIKeyScope",
    "APIKeyManager",
    "mode_to_string",
    "string_to_mode",
]
