"""
vfs/core.py - VFS 核心类

配置驱动的虚拟文件系统
"""

from typing import Dict, List, Optional, Type, Callable, Any, Tuple
from pathlib import Path

from .config import VFSConfig, ProviderSpec, load_config
from .store import VFSStore
from .node import VFSNode, NodeType
from .graph import EdgeType


class ProviderRegistry:
    """
    Provider 注册表
    
    管理 provider type name -> provider class 的映射
    """
    
    def __init__(self):
        self._types: Dict[str, Type] = {}
        self._factories: Dict[str, Callable] = {}
    
    def register(self, name: str, provider_class: Type = None, 
                 factory: Callable = None):
        """
        注册 provider 类型
        
        Args:
            name: 类型名称
            provider_class: Provider 类
            factory: 工厂函数 (store, spec) -> Provider
        """
        if provider_class:
            self._types[name] = provider_class
        if factory:
            self._factories[name] = factory
    
    def create(self, name: str, store: VFSStore, 
               spec: ProviderSpec) -> Optional[Any]:
        """创建 provider 实例"""
        if name in self._factories:
            return self._factories[name](store, spec)
        
        if name in self._types:
            cls = self._types[name]
            return cls(store, spec.pattern, spec.ttl, **spec.config)
        
        return None
    
    def list_types(self) -> List[str]:
        """列出所有已注册的类型"""
        return list(set(self._types.keys()) | set(self._factories.keys()))


# 全局注册表
_registry = ProviderRegistry()


def register_provider_type(name: str, provider_class: Type = None,
                           factory: Callable = None):
    """注册 provider 类型（全局）"""
    _registry.register(name, provider_class, factory)


class VFS:
    """
    虚拟文件系统
    
    配置驱动，支持：
    - 动态 provider 注册
    - 可配置的权限规则
    - TTL 缓存
    - 关系图
    """
    
    def __init__(self, config: VFSConfig = None, config_path: str = None):
        """
        Args:
            config: VFSConfig 实例
            config_path: 配置文件路径
        """
        if config:
            self.config = config
        else:
            self.config = load_config(config_path)
        
        # 初始化存储
        db_path = self.config.db_path or None
        self.store = VFSStore(db_path)
        
        # Provider 实例缓存
        self._providers: Dict[str, Any] = {}
        
        # 使用全局注册表
        self._registry = _registry
        
        # 注册内置 provider 类型
        self._register_builtin_providers()
    
    def _register_builtin_providers(self):
        """注册内置 provider"""
        from .providers import (
            AlpacaPositionsProvider, AlpacaOrdersProvider,
            TechnicalIndicatorsProvider, NewsProvider,
            WatchlistProvider, MemoryProvider,
        )
        
        # Alpaca (需要配置)
        def create_alpaca_positions(store, spec):
            config = spec.config
            if not config.get("api_key"):
                # 尝试从 env_file 加载
                env_file = config.get("env_file", "")
                if env_file:
                    env_path = Path(env_file).expanduser()
                    if env_path.exists():
                        env = dict(
                            line.split("=", 1)
                            for line in env_path.read_text().splitlines()
                            if "=" in line and not line.startswith("#")
                        )
                        config = {**config, **{
                            "api_key": env.get("ALPACA_API_KEY", ""),
                            "secret_key": env.get("ALPACA_SECRET_KEY", ""),
                            "base_url": env.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
                        }}
            
            return AlpacaPositionsProvider(
                store,
                api_key=config.get("api_key", ""),
                secret_key=config.get("secret_key", ""),
                base_url=config.get("base_url", "https://paper-api.alpaca.markets"),
                ttl_seconds=spec.ttl or 60,
            )
        
        def create_alpaca_orders(store, spec):
            config = spec.config
            env_file = config.get("env_file", "")
            if env_file and not config.get("api_key"):
                env_path = Path(env_file).expanduser()
                if env_path.exists():
                    env = dict(
                        line.split("=", 1)
                        for line in env_path.read_text().splitlines()
                        if "=" in line and not line.startswith("#")
                    )
                    config = {**config, **{
                        "api_key": env.get("ALPACA_API_KEY", ""),
                        "secret_key": env.get("ALPACA_SECRET_KEY", ""),
                        "base_url": env.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
                    }}
            
            return AlpacaOrdersProvider(
                store,
                api_key=config.get("api_key", ""),
                secret_key=config.get("secret_key", ""),
                base_url=config.get("base_url", "https://paper-api.alpaca.markets"),
                ttl_seconds=spec.ttl or 30,
            )
        
        self._registry.register("alpaca_positions", factory=create_alpaca_positions)
        self._registry.register("alpaca_orders", factory=create_alpaca_orders)
        
        # 无需配置的 providers
        self._registry.register("technical_indicators", TechnicalIndicatorsProvider)
        self._registry.register("news", NewsProvider)
        self._registry.register("watchlist", WatchlistProvider)
        self._registry.register("memory", MemoryProvider)
    
    def register_provider_type(self, name: str, provider_class: Type = None,
                               factory: Callable = None):
        """注册自定义 provider 类型"""
        self._registry.register(name, provider_class, factory)
    
    def _get_provider(self, path: str) -> Optional[Any]:
        """获取或创建路径对应的 provider"""
        spec = self.config.get_provider_spec(path)
        if not spec:
            return None
        
        # 缓存 key
        cache_key = f"{spec.type}:{spec.pattern}"
        
        if cache_key not in self._providers:
            provider = self._registry.create(spec.type, self.store, spec)
            if provider:
                self._providers[cache_key] = provider
        
        return self._providers.get(cache_key)
    
    # ─── 读写接口 ─────────────────────────────────────────
    
    def read(self, path: str, force_refresh: bool = False) -> Optional[VFSNode]:
        """
        读取节点
        
        1. 检查读权限
        2. 查找 provider
        3. 通过 provider 获取（带 TTL 缓存）
        4. 或直接从 store 读取
        """
        if not self.config.check_permission(path, "read"):
            raise PermissionError(f"No read permission for {path}")
        
        provider = self._get_provider(path)
        if provider:
            return provider.get(path, force_refresh=force_refresh)
        
        return self.store.get_node(path)
    
    def write(self, path: str, content: str, 
              meta: Dict = None) -> VFSNode:
        """
        写入节点
        
        1. 检查写权限
        2. 创建或更新节点
        """
        if not self.config.check_permission(path, "write"):
            raise PermissionError(f"No write permission for {path}")
        
        node = VFSNode(
            path=path,
            content=content,
            meta=meta or {},
            node_type=NodeType.FILE,
        )
        
        return self.store.put_node(node)
    
    def delete(self, path: str) -> bool:
        """删除节点"""
        if not self.config.check_permission(path, "write"):
            raise PermissionError(f"No write permission for {path}")
        
        return self.store.delete_node(path)
    
    def list(self, prefix: str = "/", limit: int = 100) -> List[VFSNode]:
        """列出节点"""
        return self.store.list_nodes(prefix, limit)
    
    # ─── 搜索 ─────────────────────────────────────────────
    
    def search(self, query: str, limit: int = 10) -> List[Tuple[VFSNode, float]]:
        """全文搜索"""
        return self.store.search(query, limit)
    
    # ─── 关系图 ─────────────────────────────────────────────
    
    def link(self, source: str, target: str,
             edge_type: EdgeType = EdgeType.RELATED,
             weight: float = 1.0):
        """添加关系"""
        return self.store.add_edge(source, target, edge_type, weight)
    
    def links(self, path: str, direction: str = "both") -> List:
        """获取关系"""
        return self.store.get_links(path, direction)
    
    # ─── 历史 ─────────────────────────────────────────────
    
    def history(self, path: str, limit: int = 10):
        """获取变更历史"""
        return self.store.get_history(path, limit)
    
    # ─── 统计 ─────────────────────────────────────────────
    
    def stats(self) -> Dict:
        """存储统计"""
        return self.store.stats()
