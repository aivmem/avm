"""
vfs/providers.py - Pluggable Provider System

Generic handler-based providers for VFS.

Handler Types:
- file: Local filesystem
- http: REST API calls
- script: Execute commands
- plugin: Python plugins
- sqlite: SQLite queries
- redis: Redis key-value
- s3: S3-compatible storage

Usage:
    providers:
      - pattern: "/live/prices/*"
        handler: http
        config:
          url: "https://api.example.com/prices/${symbol}"
          method: GET
          headers:
            Authorization: "Bearer ${API_KEY}"
          transform: ".price"
          ttl: 60
"""

from __future__ import annotations

import os
import re
import json
import subprocess
import fnmatch
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Type, Callable
from datetime import datetime, timedelta
import importlib


# ─── Provider Protocol ────────────────────────────────────

class Provider(Protocol):
    """Protocol for VFS providers"""
    
    def read(self, path: str, context: Dict[str, Any]) -> Optional[str]:
        """Read content from path"""
        ...
    
    def write(self, path: str, content: str, context: Dict[str, Any]) -> bool:
        """Write content to path"""
        ...
    
    def list(self, prefix: str, context: Dict[str, Any]) -> List[str]:
        """List paths under prefix"""
        ...
    
    def delete(self, path: str, context: Dict[str, Any]) -> bool:
        """Delete path"""
        ...


# ─── Base Handler ─────────────────────────────────────────

@dataclass
class ProviderConfig:
    """Configuration for a provider"""
    pattern: str
    handler: str
    config: Dict[str, Any] = field(default_factory=dict)
    ttl: int = 0  # Cache TTL in seconds (0 = no cache)
    access: str = "ro"  # ro, wo, rw
    
    def matches(self, path: str) -> bool:
        """Check if path matches pattern"""
        return fnmatch.fnmatch(path, self.pattern)
    
    def extract_vars(self, path: str) -> Dict[str, str]:
        """Extract variables from path based on pattern"""
        # Convert pattern to regex
        # /live/prices/* -> /live/prices/(?P<_0>.*)
        # /users/{id}/posts -> /users/(?P<id>[^/]+)/posts
        
        regex_pattern = self.pattern
        vars_found = {}
        
        # Handle {name} style variables
        for match in re.finditer(r'\{(\w+)\}', self.pattern):
            var_name = match.group(1)
            regex_pattern = regex_pattern.replace(
                match.group(0), f'(?P<{var_name}>[^/]+)'
            )
        
        # Handle * wildcards
        wildcard_count = 0
        while '*' in regex_pattern:
            regex_pattern = regex_pattern.replace(
                '*', f'(?P<_w{wildcard_count}>.*)', 1
            )
            wildcard_count += 1
        
        # Match and extract
        match = re.match(f'^{regex_pattern}$', path)
        if match:
            vars_found = {k: v for k, v in match.groupdict().items()}
        
        return vars_found


class BaseHandler(ABC):
    """Base class for handlers"""
    
    # Override these in subclasses to provide skill info for agents
    name: str = "base"
    description: str = "Base handler"
    usage: str = ""
    examples: List[str] = []
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._cache: Dict[str, tuple] = {}  # path -> (content, expires_at)
    
    @classmethod
    def skill_info(cls) -> str:
        """
        Generate skill documentation for agents.
        Override to customize, or set class attributes.
        """
        lines = [f"# {cls.name} Handler", ""]
        
        if cls.description:
            lines.append(cls.description)
            lines.append("")
        
        if cls.usage:
            lines.append("## Usage")
            lines.append("```")
            lines.append(cls.usage)
            lines.append("```")
            lines.append("")
        
        if cls.examples:
            lines.append("## Examples")
            for ex in cls.examples:
                lines.append(f"- `{ex}`")
            lines.append("")
        
        return "\n".join(lines)
    
    def _expand_vars(self, template: str, context: Dict[str, Any]) -> str:
        """Expand ${VAR} in template"""
        result = template
        
        # Expand environment variables
        for match in re.finditer(r'\$\{(\w+)\}', template):
            var_name = match.group(1)
            value = context.get(var_name) or os.environ.get(var_name, '')
            result = result.replace(match.group(0), str(value))
        
        return result
    
    def _get_cached(self, path: str) -> Optional[str]:
        """Get cached content if not expired"""
        if path in self._cache:
            content, expires_at = self._cache[path]
            if datetime.utcnow() < expires_at:
                return content
            del self._cache[path]
        return None
    
    def _set_cached(self, path: str, content: str, ttl: int):
        """Cache content with TTL"""
        if ttl > 0:
            expires_at = datetime.utcnow() + timedelta(seconds=ttl)
            self._cache[path] = (content, expires_at)
    
    @abstractmethod
    def read(self, path: str, context: Dict[str, Any]) -> Optional[str]:
        pass
    
    def write(self, path: str, content: str, context: Dict[str, Any]) -> bool:
        return False  # Default: read-only
    
    def list(self, prefix: str, context: Dict[str, Any]) -> List[str]:
        return []  # Default: no listing
    
    def delete(self, path: str, context: Dict[str, Any]) -> bool:
        return False  # Default: no delete


# ─── File Handler ─────────────────────────────────────────

class FileHandler(BaseHandler):
    """
    Local filesystem handler
    
    Config:
        root: Base directory path
        create_dirs: Auto-create directories (default: true)
    """
    name = "file"
    description = "Read/write local filesystem files."
    usage = """pattern: "/data/{filename}"
handler: file
config:
  root: ~/data
  create_dirs: true"""
    examples = [
        "cat /data/notes.md",
        "echo 'content' > /data/new.md"
    ]
    
    def read(self, path: str, context: Dict[str, Any]) -> Optional[str]:
        root = self._expand_vars(self.config.get('root', '.'), context)
        file_path = os.path.join(root, path.lstrip('/'))
        
        try:
            with open(file_path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            return None
    
    def write(self, path: str, content: str, context: Dict[str, Any]) -> bool:
        root = self._expand_vars(self.config.get('root', '.'), context)
        file_path = os.path.join(root, path.lstrip('/'))
        
        if self.config.get('create_dirs', True):
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'w') as f:
            f.write(content)
        return True
    
    def list(self, prefix: str, context: Dict[str, Any]) -> List[str]:
        root = self._expand_vars(self.config.get('root', '.'), context)
        dir_path = os.path.join(root, prefix.lstrip('/'))
        
        if not os.path.isdir(dir_path):
            return []
        
        results = []
        for entry in os.listdir(dir_path):
            full_path = os.path.join(prefix, entry)
            results.append(full_path)
        return results
    
    def delete(self, path: str, context: Dict[str, Any]) -> bool:
        root = self._expand_vars(self.config.get('root', '.'), context)
        file_path = os.path.join(root, path.lstrip('/'))
        
        try:
            os.remove(file_path)
            return True
        except FileNotFoundError:
            return False


# ─── HTTP Handler ─────────────────────────────────────────

class HTTPHandler(BaseHandler):
    """
    HTTP/REST API handler
    
    Config:
        url: URL template with ${var} placeholders
        method: HTTP method (default: GET)
        headers: Request headers
        body: Request body template
        transform: jq-style transform (optional)
        timeout: Request timeout in seconds
    """
    name = "http"
    description = "Fetch data from HTTP/REST APIs."
    usage = """pattern: "/api/prices/{symbol}"
handler: http
config:
  url: "https://api.example.com/prices/${symbol}"
  headers:
    Authorization: "Bearer ${API_KEY}"
  ttl: 60"""
    examples = [
        "cat /api/prices/AAPL",
        "cat /api/weather/london"
    ]
    
    def read(self, path: str, context: Dict[str, Any]) -> Optional[str]:
        import urllib.request
        import urllib.error
        
        # Check cache
        cached = self._get_cached(path)
        if cached is not None:
            return cached
        
        url = self._expand_vars(self.config.get('url', ''), context)
        method = self.config.get('method', 'GET')
        headers = {
            k: self._expand_vars(v, context)
            for k, v in self.config.get('headers', {}).items()
        }
        timeout = self.config.get('timeout', 30)
        
        try:
            req = urllib.request.Request(url, method=method, headers=headers)
            
            if method in ('POST', 'PUT', 'PATCH') and 'body' in self.config:
                body = self._expand_vars(self.config['body'], context)
                req.data = body.encode('utf-8')
            
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read().decode('utf-8')
            
            # Apply transform if specified
            if 'transform' in self.config:
                content = self._transform(content, self.config['transform'])
            
            # Cache if TTL specified
            ttl = self.config.get('ttl', 0)
            self._set_cached(path, content, ttl)
            
            return content
            
        except urllib.error.URLError as e:
            return None
    
    def write(self, path: str, content: str, context: Dict[str, Any]) -> bool:
        import urllib.request
        import urllib.error
        
        url = self._expand_vars(self.config.get('url', ''), context)
        method = self.config.get('write_method', 'POST')
        headers = {
            k: self._expand_vars(v, context)
            for k, v in self.config.get('headers', {}).items()
        }
        
        try:
            req = urllib.request.Request(url, method=method, headers=headers)
            req.data = content.encode('utf-8')
            
            with urllib.request.urlopen(req) as resp:
                return resp.status < 400
        except urllib.error.URLError:
            return False
    
    def _transform(self, content: str, transform: str) -> str:
        """Apply jq-style transform to JSON content"""
        try:
            data = json.loads(content)
            
            # Simple jq-like transforms
            if transform.startswith('.'):
                keys = transform[1:].split('.')
                for key in keys:
                    if key and isinstance(data, dict):
                        data = data.get(key, {})
                    elif key.isdigit() and isinstance(data, list):
                        data = data[int(key)] if int(key) < len(data) else None
                
                return json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)
            
            return content
        except json.JSONDecodeError:
            return content


# ─── Script Handler ───────────────────────────────────────

class ScriptHandler(BaseHandler):
    """
    Execute scripts/commands handler
    
    Config:
        command: Command template with ${var} placeholders
        shell: Use shell (default: true)
        timeout: Execution timeout in seconds
        cwd: Working directory
        env: Additional environment variables
    """
    name = "script"
    description = "Execute shell commands and return output."
    usage = """pattern: "/system/status"
handler: script
config:
  command: "uptime"
  timeout: 10"""
    examples = [
        "cat /system/status",
        "cat /system/disk"
    ]
    
    def read(self, path: str, context: Dict[str, Any]) -> Optional[str]:
        command = self._expand_vars(self.config.get('command', ''), context)
        shell = self.config.get('shell', True)
        timeout = self.config.get('timeout', 30)
        cwd = self.config.get('cwd')
        
        env = os.environ.copy()
        for k, v in self.config.get('env', {}).items():
            env[k] = self._expand_vars(v, context)
        
        try:
            result = subprocess.run(
                command if shell else command.split(),
                shell=shell,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=env
            )
            return result.stdout
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None
    
    def write(self, path: str, content: str, context: Dict[str, Any]) -> bool:
        command = self._expand_vars(self.config.get('write_command', ''), context)
        if not command:
            return False
        
        shell = self.config.get('shell', True)
        timeout = self.config.get('timeout', 30)
        
        try:
            result = subprocess.run(
                command if shell else command.split(),
                shell=shell,
                input=content,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode == 0
        except Exception:
            return False


# ─── Plugin Handler ───────────────────────────────────────

class PluginHandler(BaseHandler):
    """
    Python plugin handler
    
    Config:
        plugin: Module path (e.g., "vfs_plugins.talib")
        class: Class name (default: "Provider")
        init: Initialization arguments
    """
    name = "plugin"
    description = "Load and call Python plugins."
    usage = """pattern: "/indicators/{symbol}"
handler: plugin
config:
  plugin: "my_plugins.technical"
  class: "IndicatorProvider"
  init:
    api_key: "${API_KEY}" """
    examples = [
        "cat /indicators/AAPL",
        "cat /indicators/NVDA"
    ]
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._plugin = None
    
    def _get_plugin(self) -> Optional[Provider]:
        if self._plugin is None:
            try:
                module_path = self.config.get('plugin', '')
                class_name = self.config.get('class', 'Provider')
                init_args = self.config.get('init', {})
                
                module = importlib.import_module(module_path)
                cls = getattr(module, class_name)
                self._plugin = cls(**init_args)
            except (ImportError, AttributeError):
                return None
        return self._plugin
    
    def read(self, path: str, context: Dict[str, Any]) -> Optional[str]:
        plugin = self._get_plugin()
        if plugin:
            return plugin.read(path, context)
        return None
    
    def write(self, path: str, content: str, context: Dict[str, Any]) -> bool:
        plugin = self._get_plugin()
        if plugin:
            return plugin.write(path, content, context)
        return False
    
    def list(self, prefix: str, context: Dict[str, Any]) -> List[str]:
        plugin = self._get_plugin()
        if plugin:
            return plugin.list(prefix, context)
        return []


# ─── SQLite Handler ───────────────────────────────────────

class SQLiteHandler(BaseHandler):
    """
    SQLite query handler
    
    Config:
        db: Database path
        read_query: SELECT query template
        write_query: INSERT/UPDATE query template
        list_query: List query template
    """
    name = "sqlite"
    description = "Query SQLite databases."
    usage = """pattern: "/db/users/{id}"
handler: sqlite
config:
  db: "~/data/app.db"
  read_query: "SELECT * FROM users WHERE id = ${id}" """
    examples = [
        "cat /db/users/123",
        "cat /db/orders/recent"
    ]
    
    def read(self, path: str, context: Dict[str, Any]) -> Optional[str]:
        import sqlite3
        
        db_path = self._expand_vars(self.config.get('db', ':memory:'), context)
        query = self._expand_vars(self.config.get('read_query', ''), context)
        
        if not query:
            return None
        
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query)
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return json.dumps(rows, indent=2, default=str)
        except sqlite3.Error:
            return None
    
    def write(self, path: str, content: str, context: Dict[str, Any]) -> bool:
        import sqlite3
        
        db_path = self._expand_vars(self.config.get('db', ':memory:'), context)
        query = self._expand_vars(self.config.get('write_query', ''), context)
        
        if not query:
            return False
        
        try:
            conn = sqlite3.connect(db_path)
            context['_content'] = content
            conn.execute(query, context)
            conn.commit()
            conn.close()
            return True
        except sqlite3.Error:
            return False


# ─── Handler Registry ─────────────────────────────────────

HANDLERS: Dict[str, Type[BaseHandler]] = {
    'file': FileHandler,
    'http': HTTPHandler,
    'script': ScriptHandler,
    'plugin': PluginHandler,
    'sqlite': SQLiteHandler,
}


def register_handler(name: str, handler_class: Type[BaseHandler]):
    """Register a custom handler"""
    HANDLERS[name] = handler_class


def handler(name: str, description: str = "", usage: str = "", examples: List[str] = None):
    """
    Decorator to register a handler with auto-generated skill info.
    
    Usage:
        @handler("redis", 
                 description="Redis key-value store",
                 usage="pattern: /cache/{key}\\nhandler: redis",
                 examples=["cat /cache/session"])
        class RedisHandler(BaseHandler):
            def read(self, path, context):
                ...
    
    Or minimal:
        @handler("redis")
        class RedisHandler(BaseHandler):
            '''Redis key-value store for caching.'''
            ...
    """
    def decorator(cls: Type[BaseHandler]) -> Type[BaseHandler]:
        # Auto-extract from docstring if not provided
        cls.name = name
        cls.description = description or (cls.__doc__ or "").strip().split('\n')[0]
        cls.usage = usage
        cls.examples = examples or []
        
        # Auto-generate usage from __init__ signature if not provided
        if not usage and hasattr(cls, '__init__'):
            import inspect
            sig = inspect.signature(cls.__init__)
            params = [p for p in sig.parameters.keys() if p not in ('self', 'config')]
            if params:
                cls.usage = f"# Config params: {', '.join(params)}"
        
        # Register
        HANDLERS[name] = cls
        return cls
    
    return decorator


def get_handlers_skill_info() -> str:
    """
    Get skill info for all registered handlers.
    Agents can read this to learn how to use handlers.
    """
    lines = ["# Available Handlers", ""]
    lines.append("These handlers are available for custom providers.")
    lines.append("")
    
    for name, handler_class in HANDLERS.items():
        lines.append(f"## {name}")
        lines.append("")
        if hasattr(handler_class, 'description'):
            lines.append(handler_class.description)
            lines.append("")
        if hasattr(handler_class, 'usage') and handler_class.usage:
            lines.append("```yaml")
            lines.append(handler_class.usage)
            lines.append("```")
            lines.append("")
        if hasattr(handler_class, 'examples') and handler_class.examples:
            lines.append("Examples:")
            for ex in handler_class.examples:
                lines.append(f"- `{ex}`")
            lines.append("")
    
    return "\n".join(lines)


# ─── Provider Manager ─────────────────────────────────────

class ProviderManager:
    """Manages multiple providers and routes requests"""
    
    def __init__(self, configs: List[Dict[str, Any]] = None):
        self.providers: List[tuple] = []  # (ProviderConfig, BaseHandler)
        
        if configs:
            for cfg in configs:
                self.add_provider(cfg)
    
    def add_provider(self, config: Dict[str, Any]):
        """Add a provider from config dict"""
        provider_config = ProviderConfig(
            pattern=config.get('pattern', '/*'),
            handler=config.get('handler', 'file'),
            config=config.get('config', {}),
            ttl=config.get('ttl', 0),
            access=config.get('access', 'ro'),
        )
        
        handler_class = HANDLERS.get(provider_config.handler)
        if handler_class:
            handler = handler_class(provider_config.config)
            self.providers.append((provider_config, handler))
    
    def _find_handler(self, path: str) -> Optional[tuple]:
        """Find matching handler for path"""
        for config, handler in self.providers:
            if config.matches(path):
                return config, handler
        return None
    
    def read(self, path: str, context: Dict[str, Any] = None) -> Optional[str]:
        """Read from matching provider"""
        result = self._find_handler(path)
        if not result:
            return None
        
        config, handler = result
        ctx = context or {}
        ctx.update(config.extract_vars(path))
        
        return handler.read(path, ctx)
    
    def write(self, path: str, content: str, context: Dict[str, Any] = None) -> bool:
        """Write to matching provider"""
        result = self._find_handler(path)
        if not result:
            return False
        
        config, handler = result
        
        # Check access
        if 'w' not in config.access:
            return False
        
        ctx = context or {}
        ctx.update(config.extract_vars(path))
        
        return handler.write(path, content, ctx)
    
    def list(self, prefix: str, context: Dict[str, Any] = None) -> List[str]:
        """List from matching provider"""
        result = self._find_handler(prefix)
        if not result:
            return []
        
        config, handler = result
        ctx = context or {}
        ctx.update(config.extract_vars(prefix))
        
        return handler.list(prefix, ctx)
    
    def delete(self, path: str, context: Dict[str, Any] = None) -> bool:
        """Delete from matching provider"""
        result = self._find_handler(path)
        if not result:
            return False
        
        config, handler = result
        
        if 'w' not in config.access:
            return False
        
        ctx = context or {}
        ctx.update(config.extract_vars(path))
        
        return handler.delete(path, ctx)
