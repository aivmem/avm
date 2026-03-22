# AVM 架构深度分析

> 作者：Kearsarge
> 日期：2026-03-22

---

## 一、当前检索流程

```
Query "NVDA analysis"
       │
       ▼
┌─────────────────────────────────┐
│  1. Embedding Search (k=50)    │  ← 向量检索，返回 50 candidates
│     • all-MiniLM-L6-v2         │     需要 load 整个 embedding index
│     • 768-dim vectors          │
└─────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│  2. FTS5 Full-text Search      │  ← 关键词补充
│     • SQLite FTS5              │     对中文支持差
└─────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│  3. Graph Expansion (depth=1)  │  ← 关系扩展
│     • edges table lookup       │     几乎没人用 link
└─────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│  4. Scoring                    │  ← 综合打分
│     • importance (meta)        │     从 meta 读，可能没设
│     • recency (updated_at)     │
│     • relevance (embedding)    │
└─────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│  5. Token Budget Selection     │  ← 截断到 4000 tokens
│     • chars_per_token ≈ 4      │
└─────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│  6. Compact Synthesis          │  ← 生成 markdown
│     • 每节点最多 300 chars     │
└─────────────────────────────────┘
```

---

## 二、问题诊断

### 2.1 Token 浪费点

| 位置 | 问题 | 影响 |
|------|------|------|
| 检索阶段 | k=50 过大，大部分被丢弃 | 浪费 embedding 计算 |
| 存储阶段 | 每条记忆独立存储，无聚合 | 相似内容重复存 |
| 输出阶段 | 300 chars/node 可能截断关键信息 | 质量下降 |
| 路径浪费 | `/memory/private/agent/topic-YYYYMMDD-HHMMSS.md` 太长 | 浪费 ~50 tokens/路径 |

### 2.2 Hop 瓶颈

| 操作 | 当前 hop 数 | 理想 |
|------|------------|------|
| recall 查询 | 4 (embed→fts→graph→db) | 1-2 |
| 读取节点 | 2 (cache miss → sqlite) | 1 |
| 写入 | 3 (sqlite + embedding + subscription) | 1 (async 其余) |

### 2.3 多 Agent 问题

| 问题 | 现状 | 影响 |
|------|------|------|
| 私有/共享隔离 | 路径前缀 `/memory/private/{id}` | 路径长 |
| 跨 agent 订阅 | 持久化但推送延迟不确定 | 实时性差 |
| 权限检查 | 每次 read/write 都检查 | 开销 |

---

## 三、优化方案

### 3.1 两级缓存架构

```
┌─────────────────────────────────────────────────┐
│                  L1: Hot Cache                   │
│  • In-memory LRU (100 nodes)                    │
│  • 读取: 0.002ms                                 │
│  • 已实现 ✅                                     │
└─────────────────────────────────────────────────┘
                       │
                       ▼ miss
┌─────────────────────────────────────────────────┐
│              L2: Topic Index (新)               │
│  • 按 topic 聚合的摘要索引                       │
│  • 结构: {topic: {summary, paths[], updated}}   │
│  • 一次读取整个 topic 上下文                     │
└─────────────────────────────────────────────────┘
                       │
                       ▼ miss
┌─────────────────────────────────────────────────┐
│               L3: SQLite + Embedding            │
│  • 完整内容 + 向量                               │
│  • 只在深度查询时访问                            │
└─────────────────────────────────────────────────┘
```

### 3.2 Topic Clustering（核心优化）

**现状**：100 条记忆 → 100 次查询

**优化**：100 条记忆 → 10 个 topic → 1 次查询

```python
# 自动聚类
topics = {
    "market-nvda": {
        "summary": "NVDA 技术分析...",  # 300 tokens
        "paths": ["/memory/nvda-1.md", "/memory/nvda-2.md", ...],
        "importance": 0.8,
        "updated": "2026-03-22T20:00"
    },
    "trading-lessons": {
        "summary": "止损经验...",
        "paths": [...],
        ...
    }
}
```

**省 token**：只返回 topic summaries，不返回全文
**减 hop**：直接从 topic index 读，不走 embedding

### 3.3 路径压缩

**现状**：
```
/memory/private/kearsarge/market-analysis-20260322-203045.md
```
~70 chars = ~17 tokens

**优化**：
```
/m/k/market-20260322.md
```
~25 chars = ~6 tokens

**节省**：每条记忆节省 11 tokens

### 3.4 单次查询优化

**现状**：
```python
# 多次 SQLite 查询
embedding_search()  # 1 次
fts_search()        # 1 次
graph_expand()      # N 次
get_node()          # M 次
```

**优化**：
```python
# 合并为 1-2 次
combined_search(query, k=20)  # embedding + FTS 合并
batch_get_nodes(paths)        # 批量读取
```

### 3.5 延迟 Embedding

**现状**：写入同步等 embedding（虽然已改成 async thread）

**优化**：
- 写入只存 SQLite
- 后台批量 embedding（每分钟）
- 查询时如果没 embedding，fallback 到 FTS

---

## 四、文件系统组织优化

### 4.1 当前结构

```
/memory/
  private/
    kearsarge/
      topic-20260322-123456.md
      topic-20260322-123457.md
      ...
  shared/
    namespace1/
      ...
```

### 4.2 优化结构

```
/m/                          # 短前缀
  k/                         # agent 首字母缩写
    20260322.md              # 按天聚合
  _topic/                    # topic 索引（自动维护）
    nvda.idx                 # topic: paths[]
    trading.idx
  _summary/                  # 摘要层
    k-20260322.summary       # 每日摘要
  _hot/                      # 热数据快照（定期更新）
    top100.json              # 最常访问的 100 条
```

### 4.3 Agent 交互简化

**现状**：
```python
mem.remember("content", title="...", importance=0.8, tags=[...])
mem.recall("query", max_tokens=4000)
```

**优化**：
```python
# 自动 topic 检测，自动 importance
mem.note("NVDA RSI at 72")  
# → 自动归入 topic:nvda, importance=0.7

# 智能 recall，先查 topic index
mem.ask("what about NVDA?")
# → 直接返回 topic:nvda 的 summary，不遍历所有
```

---

## 五、多步查询优化

### 5.1 当前流程

```
User Query → Embedding Search → FTS → Graph → Score → Select → Synthesize
              ↑                   ↑     ↑
              50 candidates       +20   +10
              = 80 candidates total
              丢弃 75，只用 5
```

### 5.2 优化流程

```
User Query
    │
    ▼
┌─────────────┐
│ Topic Match │ ← 先查 topic index（10 topics）
│   O(1)      │   
└─────────────┘
    │ 命中 topic?
    ├─ Yes → 直接返回 topic summary（1 hop）
    │
    ▼ No
┌─────────────┐
│ Hybrid Search│ ← embedding + FTS 合并
│   k=20       │   减少候选数
└─────────────┘
    │
    ▼
┌─────────────┐
│ Batch Read  │ ← 批量读取节点
│   1 SQL     │
└─────────────┘
    │
    ▼
│ Synthesize  │
```

**优化效果**：
- 热查询：1 hop（topic hit）
- 冷查询：2 hops（search + batch read）

---

## 六、性能提升记录

### Phase 1（今日完成）

| 优化 | 之前 | 之后 | 提升 |
|------|------|------|------|
| Write throughput | 23 ops/s | 468 ops/s | **20x** |
| Write latency | 43ms | 2.1ms | **20x** |
| Read (cached) | 417k ops/s | 724k ops/s | **1.7x** |
| Search vs grep | 2k ops/s | N/A | **14x** |

### Phase 2（计划）

| 优化 | 预期提升 |
|------|----------|
| Topic index | recall 延迟 -80% |
| 路径压缩 | token 使用 -15% |
| 批量查询 | hop 数 -50% |
| 延迟 embedding | 写入延迟 -50% |

---

## 七、实现优先级

| 优先级 | 功能 | 价值 | 难度 |
|--------|------|------|------|
| P0 | Topic index + auto-clustering | 极高 | 高 |
| P1 | 路径压缩 | 中 | 低 |
| P1 | 批量查询 API | 高 | 中 |
| P2 | 按天聚合存储 | 中 | 中 |
| P2 | 智能 importance | 中 | 中 |
| P3 | Prometheus metrics | 低 | 低 |

---

## 八、Agent 操作指南（更新版）

### 8.1 基本操作

```bash
# 记忆
avm remember "NVDA RSI at 72" --importance 0.8
# 或通过 FUSE
echo "NVDA RSI at 72" > avm/memory/market/nvda.md

# 回忆
avm recall "NVDA analysis" --max-tokens 2000

# 时间旅行
avm read /memory/nvda.md --as-of 2026-03-20
```

### 8.2 订阅协作

```bash
# 订阅共享空间（节流模式，60秒聚合）
avm subscribe "/shared/market/*" --agent kearsarge --mode throttled --throttle 60

# 查看待处理通知
avm pending --agent kearsarge

# 发送跨 agent 消息
echo "DB schema changed" > avm/tell/akashi?priority=urgent
```

### 8.3 最佳实践

1. **importance 设置**
   - 0.9+: 关键决策、重大错误
   - 0.7-0.8: 日常发现
   - 0.5: 默认/临时

2. **命名规范**
   - 用 topic 前缀：`market-nvda`, `trading-lesson`
   - 避免时间戳在文件名中（用 meta）

3. **定期维护**
   - `avm cold` 查看冷记忆
   - `avm archive` 归档
   - `avm trash --empty` 清理（30天后自动）

---

## 九、下一步行动

1. 实现 Topic Index
2. 实现路径压缩
3. 实现批量查询 API
4. 更新 benchmark
5. 生成技术报告
