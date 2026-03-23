# AVM Multi-Agent Collaboration Benchmark Plan

## 目标

测量真实场景下的：
1. **Agent 效率** — 单 agent 任务完成速度/质量
2. **AVM 效率** — 记忆检索/存储对任务的影响
3. **协作效率** — 多 agent 协作 vs 单 agent 的提升
4. **问题解决速度** — 端到端任务完成时间

## 现有数据集参考

### MARBLE (MultiAgentBench) - ACL 2025
- GitHub: https://github.com/ulab-uiuc/MARBLE
- 场景：狼人杀、研究协作、Web 任务
- 指标：任务分数、里程碑完成率、协作质量
- **适用性**：偏游戏/社交模拟，与 AVM 场景不完全匹配

### AWS Multi-Agent Benchmark
- GitHub: https://github.com/aws-samples/multiagent-collab-scenario-benchmark
- 场景：旅行规划、抵押贷款、软件开发（30 个场景）
- 指标：断言验证（assertions）
- **适用性**：企业场景，数据格式简洁，可借鉴

### AgentBench - ICLR 2024
- GitHub: https://github.com/THUDM/AgentBench
- 场景：代码、游戏、Web、数据库等
- 指标：任务成功率
- **适用性**：单 agent 为主，可作为 baseline

## AVM 专属 Benchmark 设计

### 场景类别

1. **知识检索任务** (Memory Retrieval)
   - 从多 agent 共享记忆中检索信息
   - 测量 recall/precision/latency
   - 对比有/无 AVM 的表现

2. **协作编码任务** (Collaborative Coding)
   - 多 agent 共同完成代码任务
   - Agent A 写框架，Agent B 写测试，Agent C review
   - 测量协作效率、代码质量

3. **信息同步任务** (Information Sync)
   - Agent A 学到新知识，Agent B 需要使用
   - 测量 gossip protocol 传播效率
   - 对比直接通信 vs AVM 共享

4. **上下文累积任务** (Context Accumulation)
   - 长对话中积累的知识点
   - 测量 consolidation 效果
   - memory decay 的影响

### 指标体系

| 指标 | 描述 | 测量方法 |
|------|------|----------|
| **Task Success Rate** | 任务完成率 | 二元判断 + LLM judge |
| **Time to Complete** | 完成时间 | wall-clock time |
| **Token Efficiency** | Token 使用效率 | tokens / task score |
| **Memory Precision** | 记忆检索精度 | retrieved_relevant / retrieved_total |
| **Memory Recall** | 记忆检索召回 | retrieved_relevant / total_relevant |
| **Collaboration Score** | 协作质量 | 专家评分 / LLM judge |
| **Knowledge Transfer** | 知识传递效率 | Agent B 使用 Agent A 知识的成功率 |

### 数据集格式

```json
{
  "scenario_id": "coding-001",
  "category": "collaborative_coding",
  "description": "Implement a REST API with tests",
  "agents": [
    {"id": "coder", "role": "Write implementation"},
    {"id": "tester", "role": "Write tests"},
    {"id": "reviewer", "role": "Code review"}
  ],
  "initial_context": "...",
  "assertions": [
    "API endpoints are functional",
    "Test coverage > 80%",
    "No critical review comments unaddressed"
  ],
  "expected_interactions": 5,
  "time_limit_seconds": 600
}
```

### 实验设计

#### Ablation Study

| 配置 | AVM | Gossip | Consolidation |
|------|-----|--------|---------------|
| Baseline | ❌ | ❌ | ❌ |
| +AVM | ✅ | ❌ | ❌ |
| +Gossip | ✅ | ✅ | ❌ |
| Full | ✅ | ✅ | ✅ |

#### 比较对象

- No memory (baseline)
- Simple key-value store
- AVM (ours)
- RAG-based memory

### 日志格式

```json
{
  "run_id": "uuid",
  "timestamp": "ISO8601",
  "scenario_id": "coding-001",
  "config": {
    "avm_enabled": true,
    "gossip_enabled": true,
    "model": "claude-sonnet-4"
  },
  "events": [
    {
      "timestamp": "...",
      "agent": "coder",
      "action": "memory_write",
      "path": "/shared/code/api.py",
      "tokens_used": 150
    },
    {
      "timestamp": "...",
      "agent": "tester",
      "action": "memory_read",
      "query": "api implementation",
      "results": 3,
      "latency_ms": 45
    }
  ],
  "result": {
    "success": true,
    "assertions_passed": 3,
    "assertions_total": 3,
    "time_seconds": 342,
    "total_tokens": 15000
  }
}
```

## 实现步骤

### Phase 1: 数据集创建 (Week 1)
- [ ] 设计 10 个协作编码场景
- [ ] 设计 10 个知识检索场景
- [ ] 设计 10 个信息同步场景
- [ ] 编写 assertion 验证器

### Phase 2: Benchmark 框架 (Week 2)
- [ ] 实现 scenario runner
- [ ] 实现日志记录器
- [ ] 实现 LLM judge
- [ ] 集成 AVM

### Phase 3: 实验运行 (Week 3)
- [ ] 运行 baseline 实验
- [ ] 运行 ablation study
- [ ] 收集结果

### Phase 4: 分析报告 (Week 4)
- [ ] 统计分析
- [ ] 可视化
- [ ] 撰写技术报告

## 参考资料

- MARBLE: https://arxiv.org/abs/2503.01935
- AWS Multi-Agent: https://arxiv.org/abs/2412.05449
- AgentBench: https://github.com/THUDM/AgentBench
