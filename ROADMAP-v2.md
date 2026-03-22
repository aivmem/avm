# AVM v2 Roadmap — 效能提升计划

> Created: 2026-03-22
> Target: 完整的多 agent 协作 + 性能优化 + 通用 benchmark

---

## Phase 1: 核心优化（今日完成）

### 1.1 热记忆缓存 ✅ → 待实现
- LRU 缓存最近访问的 100 个节点
- 写入时 invalidate
- 配置: `cache.max_size`, `cache.ttl`

### 1.2 持久化订阅 ✅
- `avm/subscriptions.py` — 完成
- 四种模式: realtime/throttled/batched/digest
- CLI + FUSE 支持

### 1.3 Activity Feed ✅
- `/:feed` 虚拟文件 — 完成
- 显示全局活动流

---

## Phase 2: 多 Agent 协作

### 2.1 任务上下文打包
```bash
avm bundle /task/project-x --since 7d > handoff.md
```
- 收集相关记忆 + 时间线 + 依赖
- 输出 markdown 或 JSON

### 2.2 知识图谱可视化
```bash
avm graph /task/project-x --depth 2 --format mermaid
```
- 输出 Mermaid/DOT 格式
- 显示节点关系

### 2.3 软删除 + 垃圾桶
- 删除移到 `/trash/`
- 30 天后自动清理
- `avm restore /trash/file.md`

---

## Phase 3: Benchmark 框架

### 3.1 场景定义
1. **单 Agent 持续工作**
   - 1000 条记忆写入
   - 100 次 recall
   - 测量: 延迟、token 节省

2. **多 Agent 协作**
   - 5 个 agent 并发读写
   - 订阅通知延迟
   - 冲突检测

3. **冷启动**
   - 大量历史记忆（10k 条）
   - recall 首次查询延迟

### 3.2 对比基线
- **无 AVM**: 直接文件读写 + grep 搜索
- **有 AVM**: SQLite + embedding + 衰减

### 3.3 指标
- ops/sec (读/写/搜索/recall)
- token 节省率 (recall vs 全量读取)
- 通知延迟 (订阅 → 收到)
- 内存占用

---

## 实现顺序

| 优先级 | 功能 | 预计时间 |
|--------|------|----------|
| 1 | 热记忆缓存 | 30min |
| 2 | 软删除/垃圾桶 | 20min |
| 3 | 任务打包 | 40min |
| 4 | 知识图谱 | 30min |
| 5 | Benchmark 重构 | 60min |
| 6 | 测试 + 文档 | 30min |

---

## 开始！
