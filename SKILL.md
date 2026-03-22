# AVM Memory Skill

> AI Virtual Memory — 多 Agent 共享记忆系统

## 核心能力

- **语义搜索**：embedding + FTS5 混合检索
- **Token 感知**：自动截断到 token 预算
- **多 Agent**：私有/共享空间隔离 + 订阅通知
- **生命周期**：自动衰减、归档、垃圾清理

## 快速开始

### CLI 方式

```bash
# 记忆
avm remember "NVDA RSI at 72" --importance 0.8

# 回忆（token 限制）
avm recall "NVDA analysis" --max-tokens 2000

# 语义搜索
avm semantic "technical indicators"

# 时间旅行
avm read /memory/notes.md --as-of 2026-03-20
```

### FUSE 方式

```bash
# 挂载
avm-mount ~/avm --agent myagent

# 读写
cat ~/avm/memory/notes.md
echo "New insight" > ~/avm/memory/insight.md

# 虚拟文件
cat ~/avm/:search?q=analysis
cat ~/avm/:recall?q=trading&max_tokens=1000
cat ~/avm/:cold
cat ~/avm/:feed
cat ~/avm/:pending
```

### Python API

```python
from avm import AVM
from avm.agent_memory import AgentMemory

avm = AVM(agent_id="myagent")
mem = AgentMemory(avm, "myagent")

# 记忆
mem.remember("RSI at 72", importance=0.8, tags=["market", "nvda"])

# 回忆
context = mem.recall("technical analysis", max_tokens=2000)
```

## 订阅协作

```bash
# 订阅共享空间（节流模式）
avm subscribe "/shared/market/*" --agent kearsarge --mode throttled --throttle 60

# 查看待处理通知
avm pending --agent kearsarge

# 跨 agent 消息
echo "DB changed" > ~/avm/tell/akashi?priority=urgent
```

**订阅模式：**
- `realtime`：立即推送（紧急）
- `throttled`：窗口内聚合（频繁更新）
- `batched`：不推送，等查询（低优先级）
- `digest`：定时汇总

## 生命周期管理

```bash
# 查看冷记忆（衰减低于阈值）
avm cold --threshold 0.3

# 归档冷记忆
avm archive --threshold 0.2 --dry-run
avm archive --threshold 0.2

# 软删除（移到 /trash/）
avm delete /memory/old.md

# 恢复
avm restore /trash/memory/old.md

# 清空垃圾桶
avm trash --empty
```

## 导出/打包

```bash
# 压缩导出
avm export /memory --format tar.gz -o backup.tar.gz

# 任务交接
avm bundle /task/project-x --since 7d > handoff.md

# 知识图谱
avm graph /task/project-x --format mermaid
```

## MCP Server

```bash
# 启动
avm-mcp --user akashi

# 或带认证
avm-mcp --api-key $AVM_API_KEY
```

### MCP 配置

```yaml
# mcp_servers.yaml
avm-memory:
  command: avm-mcp
  args: ["--user", "${AVM_USER:-default}"]
```

### MCP Tools

| Tool | 描述 |
|------|------|
| `avm_recall` | Token 感知记忆检索 |
| `avm_remember` | 存储新记忆 |
| `avm_search` | 语义搜索 |
| `avm_list` | 列出记忆 |
| `avm_read` | 读取特定记忆 |
| `avm_write` | 写入记忆 |
| `avm_delete` | 删除记忆 |

## 最佳实践

### Importance 设置

| 值 | 适用 |
|----|------|
| 0.9+ | 关键决策、重大错误 |
| 0.7-0.8 | 日常发现 |
| 0.5 | 默认/临时 |
| <0.3 | 会被自动归档 |

### 命名规范

```
✅ market-nvda.md
✅ trading-lesson-stoploss.md
❌ notes-20260322-123456.md  # 避免时间戳在文件名
```

### Token 节省

1. 用 `recall` 代替 `read`（自动截断）
2. 设置合理的 `max_tokens`
3. 让冷记忆自动归档
4. 用 topic 前缀组织

## 配置

```yaml
# ~/.avm/config.yaml

embedding:
  enabled: true
  backend: local
  model: all-MiniLM-L6-v2

decay:
  half_life_days: 14.0
  archive_threshold: 0.15
  archive_interval_hours: 6

cache:
  max_size: 100
```

## 性能数据

| 操作 | 吞吐量 | 延迟 |
|------|--------|------|
| Write | 468 ops/s | 2.1ms |
| Read (cached) | 724k ops/s | 0.001ms |
| Search | 2k ops/s | 1.6ms |
| Recall | 54 ops/s | 18ms |

## 更多信息

- [技术报告](docs/TECHNICAL-REPORT-2026-03-22.md)
- [架构分析](docs/ARCHITECTURE-ANALYSIS.md)
- [源码](https://github.com/aivmem/avm)
