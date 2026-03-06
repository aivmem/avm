# Configuration

AVM can be configured via YAML file or Python code.

## Config File Location

AVM looks for config in order:
1. `./avm.yaml` (current directory)
2. `~/.avm/config.yaml`
3. `$XDG_CONFIG_HOME/avm/config.yaml`

## Basic Configuration

```yaml
# ~/.avm/config.yaml

# Database location
db_path: ~/.local/share/avm/avm.db

# Default permissions
permissions:
  - pattern: "/memory/*"
    access: rw
  - pattern: "/live/*"
    access: ro

default_access: ro
```

## Provider Configuration

Providers handle different path patterns:

```yaml
providers:
  # HTTP API provider
  - pattern: "/live/prices/{symbol}"
    handler: http
    config:
      url: "https://api.example.com/prices/${symbol}"
      headers:
        Authorization: "Bearer ${API_KEY}"
    ttl: 60  # Cache for 60 seconds

  # Script provider
  - pattern: "/system/status"
    handler: script
    config:
      command: "uptime"
    ttl: 30

  # SQLite provider
  - pattern: "/data/users/{id}"
    handler: sqlite
    config:
      db: "~/data/users.db"
      query: "SELECT * FROM users WHERE id = ${id}"

  # Plugin provider
  - pattern: "/live/indicators/*"
    handler: plugin
    config:
      plugin: "my_plugins.technical"
      function: "get_indicators"
```

## Agent Configuration

```yaml
agents:
  trader:
    namespaces:
      - market
      - signals
    quota:
      max_memories: 1000
      max_bytes: 10485760  # 10MB
    
  analyst:
    namespaces:
      - market
      - research
    quota:
      max_memories: 500

  readonly_bot:
    namespaces:
      - market: ro
```

## Memory Settings

```yaml
memory:
  # Token estimation
  chars_per_token: 4
  
  # Recall defaults
  default_max_tokens: 4000
  default_strategy: balanced  # balanced, importance, recency, relevance
  
  # Compression
  max_chars_per_node: 300
  
  # Versioning
  append_only: true
  max_versions: 10
```

## Python Configuration

```python
from avm import AVM
from avm.config import AVMConfig, PermissionRule, ProviderSpec

config = AVMConfig(
    db_path="~/.local/share/avm/avm.db",
    permissions=[
        PermissionRule(pattern="/memory/*", access="rw"),
        PermissionRule(pattern="/live/*", access="ro"),
    ],
    default_access="ro"
)

avm = AVM(config=config)
```

## Environment Variables

```bash
# Database path
export AVM_DB_PATH=~/.local/share/avm/avm.db

# API keys for providers
export API_KEY=your_api_key

# Config file path
export AVM_CONFIG=~/custom/config.yaml
```

Variables are expanded in config:
```yaml
providers:
  - pattern: "/api/*"
    handler: http
    config:
      headers:
        Authorization: "Bearer ${API_KEY}"  # Expanded from env
```

## Custom Handlers

Register custom handlers:

```python
from avm import BaseHandler, register_handler

class RedisHandler(BaseHandler):
    def __init__(self, store, spec):
        super().__init__(store, spec)
        self.redis = redis.Redis(host=spec.config.get('host', 'localhost'))
    
    def read(self, path, context):
        key = self.extract_vars(path)['key']
        return self.redis.get(key)
    
    def write(self, path, content, context):
        key = self.extract_vars(path)['key']
        self.redis.set(key, content)

register_handler('redis', RedisHandler)
```

Then use in config:
```yaml
providers:
  - pattern: "/cache/{key}"
    handler: redis
    config:
      host: localhost
      port: 6379
```

## Permissions

```yaml
permissions:
  # Wildcard patterns
  - pattern: "/memory/*"
    access: rw
  
  # Specific paths
  - pattern: "/memory/system/*"
    access: ro
  
  # With agent restrictions
  - pattern: "/memory/private/{agent}/*"
    access: rw
    owner_only: true  # Only the owning agent
```

Access levels:
- `ro` - Read only
- `rw` - Read and write
- `none` - No access

## Logging

```yaml
logging:
  level: INFO  # DEBUG, INFO, WARNING, ERROR
  file: ~/.avm/avm.log
  
  # Audit logging
  audit:
    enabled: true
    file: ~/.avm/audit.log
```

## Full Example

```yaml
# ~/.avm/config.yaml

db_path: ~/.local/share/avm/avm.db

providers:
  - pattern: "/live/prices/{symbol}"
    handler: http
    config:
      url: "https://api.polygon.io/v2/aggs/ticker/${symbol}/prev"
      headers:
        Authorization: "Bearer ${POLYGON_API_KEY}"
    ttl: 60

permissions:
  - pattern: "/memory/*"
    access: rw
  - pattern: "/live/*"
    access: ro
  - pattern: "/system/*"
    access: ro

default_access: ro

agents:
  trader:
    namespaces: [market, signals]
    quota:
      max_memories: 1000
  analyst:
    namespaces: [market, research]
    quota:
      max_memories: 500

memory:
  default_max_tokens: 4000
  default_strategy: balanced
  append_only: true

logging:
  level: INFO
  audit:
    enabled: true
```
