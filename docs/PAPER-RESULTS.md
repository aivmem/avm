# AVM Paper Benchmark Results

> Experimental evaluation of AVM (AI Virtual Memory) performance characteristics
> 
> Date: 2026-03-22
> Configuration: M1 Mac, SQLite WAL, LRU cache (100), all-MiniLM-L6-v2 embedding

---

## 1. Latency Distribution

### 1.1 Read Latency (Hot vs Cold)

| Percentile | Cold Read | Hot Read |
|------------|-----------|----------|
| p50 | 0.032ms | 0.001ms |
| p90 | 0.049ms | 0.001ms |
| p95 | 0.063ms | 0.001ms |
| p99 | 0.103ms | 0.002ms |

**Observation**: Hot cache reduces latency by **32x** at p50.

### 1.2 Write Latency

| Percentile | Latency |
|------------|---------|
| p50 | 0.72ms |
| p90 | 1.01ms |
| p95 | 1.13ms |
| p99 | 1.78ms |

**Observation**: Consistent write latency with async embedding.

### 1.3 Search Latency (FTS5)

| Percentile | Latency |
|------------|---------|
| p50 | 0.38ms |
| p90 | 0.55ms |
| p95 | 0.67ms |
| p99 | 0.91ms |

---

## 2. Scalability

### 2.1 Throughput vs. Memory Count

| Memory Count | Write (ops/s) | Read (ops/s) | Search (ops/s) |
|--------------|---------------|--------------|----------------|
| 10 | 1,317 | 1,247,000 | 3,025 |
| 50 | 1,327 | 1,672,000 | 2,479 |
| 100 | 1,283 | 1,691,000 | 2,209 |
| 200 | 1,250 | 1,580,000 | 1,850 |
| 500 | 1,180 | 1,420,000 | 1,200 |
| 1000 | 1,050 | 1,350,000 | 850 |

**Observations**:
- Write throughput degrades gracefully (20% at 1000 memories)
- Read throughput peaks at ~100 memories (cache warming effect)
- Search throughput inversely proportional to dataset size

### 2.2 Scalability Plot Data

```
Memory Count vs. Throughput (log-log scale recommended)

Write: Nearly horizontal (O(1) amortized)
Read: Increases then plateaus (cache effect)
Search: Decreases sub-linearly (FTS5 index scales)
```

---

## 3. Cache Analysis

### 3.1 Cache Size Sensitivity (200 memories, Zipf α=1.5)

| Cache Size | Hit Rate | Avg Latency (ms) | p99 Latency (ms) |
|------------|----------|------------------|------------------|
| 10 | 95.4% | 0.015 | 0.35 |
| 25 | 96.8% | 0.010 | 0.32 |
| 50 | 97.7% | 0.008 | 0.30 |
| 100 | 97.1% | 0.010 | 0.32 |
| 200 | 97.5% | 0.009 | 0.31 |

**Observation**: Diminishing returns beyond cache_size=50 for Zipf-distributed access.

### 3.2 Hit Rate by Access Pattern

| Pattern | Description | Hit Rate |
|---------|-------------|----------|
| Zipf | Power-law (realistic) | 94.8% |
| Working Set | Hot 20 + cold tail | 78.8% |
| Temporal | Prefer recent | 67.2% |
| Uniform | Random | 64.0% |

**Observation**: Real agent workloads (Zipf-like) benefit most from caching.

---

## 4. Multi-Agent Contention

### 4.1 Concurrent Write Throughput

| Agents | Total Throughput | Per-Agent Throughput | p99 Latency (ms) |
|--------|------------------|----------------------|------------------|
| 1 | 454 | 454 | 4.3 |
| 2 | 421 | 211 | 47.7 |
| 4 | 362 | 90 | 120.6 |
| 8 | 298 | 37 | 245.2 |
| 16 | 210 | 13 | 512.8 |

**Observation**: SQLite write lock causes linear degradation per agent.

### 4.2 Contention Analysis

- **Lock contention**: SQLite serializes writes at the database level
- **WAL benefit**: Concurrent reads unaffected
- **Recommendation**: Batch writes per agent to reduce lock frequency

---

## 5. Token Efficiency

### 5.1 Recall Quality vs. Token Budget

| Budget (tokens) | Returned | Utilization | Relevant Mentions |
|-----------------|----------|-------------|-------------------|
| 100 | 98 | 98% | 3/50 |
| 250 | 245 | 98% | 8/50 |
| 500 | 490 | 98% | 15/50 |
| 1000 | 980 | 98% | 28/50 |
| 2000 | 1950 | 97.5% | 42/50 |
| 4000 | 3900 | 97.5% | 50/50 |

**Observation**: ~1000 tokens sufficient for 50%+ recall on typical queries.

### 5.2 Token Savings

| Scenario | Total Available | Budget | Savings |
|----------|-----------------|--------|---------|
| 100 memories × 300 tokens | 30,000 | 2,000 | 93.3% |
| 500 memories × 300 tokens | 150,000 | 4,000 | 97.3% |
| 1000 memories × 300 tokens | 300,000 | 4,000 | 98.7% |

---

## 6. Cold Start Analysis

### 6.1 First Query Latency by History Size

| History Size | Cold (ms) | Warm (ms) | Warmup Factor |
|--------------|-----------|-----------|---------------|
| 10 | 2.5 | 1.2 | 2.1x |
| 50 | 5.8 | 1.8 | 3.2x |
| 100 | 12.4 | 2.3 | 5.4x |
| 500 | 45.2 | 8.5 | 5.3x |
| 1000 | 89.6 | 15.2 | 5.9x |

**Observation**: Cold start overhead ~6x, dominated by embedding model initialization.

---

## 7. Write Batch Analysis

### 7.1 Batch Size vs. Throughput

| Batch Size | Throughput (ops/s) | Per-Op Latency (ms) |
|------------|--------------------|--------------------|
| 1 | 1,310 | 0.76 |
| 5 | 1,250 | 0.80 |
| 10 | 1,186 | 0.84 |
| 25 | 1,150 | 0.87 |
| 50 | 1,129 | 0.89 |
| 100 | 1,080 | 0.93 |

**Observation**: Batching does not improve throughput (async embedding already decouples).

---

## 8. Content Size Impact

### 8.1 Latency by Content Size

| Size (chars) | Tokens | Write (ms) | Read (ms) |
|--------------|--------|------------|-----------|
| 100 | 25 | 0.79 | 0.0008 |
| 500 | 125 | 0.80 | 0.0007 |
| 1000 | 250 | 0.80 | 0.0007 |
| 2000 | 500 | 0.85 | 0.0007 |
| 5000 | 1250 | 0.92 | 0.0007 |
| 10000 | 2500 | 1.05 | 0.0008 |

**Observation**: 
- Write latency grows sub-linearly with content size
- Read latency constant (cache hit returns reference)

---

## 9. Operation Hop Count

| Operation | Hops | Breakdown |
|-----------|------|-----------|
| read_hot | 1 | cache_check |
| read_cold | 2 | cache_check → sqlite_read |
| write | 1 | sqlite_write (embedding async) |
| search | 2 | fts_search → batch_read |
| recall_cold | 4 | embed → fts → graph → batch_read |
| recall_hot | 1 | topic_index (future) |

---

## 10. Ablation Study Summary

| Configuration | Write (ops/s) | Read (ops/s) | Delta |
|---------------|---------------|--------------|-------|
| baseline (all OFF) | 1,293 | 3,339 | — |
| +WAL | 1,354 | 3,256 | +5% write |
| +cache | 1,281 | 1,318,704 | +39,000% read |
| +async_embed | 1,300 | 3,135 | — |
| all ON | 1,327 | 1,401,896 | +42,000% read |

**Key Finding**: LRU cache provides 420x read performance improvement.

---

## Appendix: Test Environment

- **Hardware**: Apple M1 Pro, 16GB RAM
- **OS**: macOS 24.6.0
- **Python**: 3.13.12
- **SQLite**: 3.45.0 (WAL mode)
- **Embedding**: all-MiniLM-L6-v2 (384-dim)
- **Cache**: LRU, max_size=100

---

## Appendix: Reproducibility

```bash
# Run all experiments
python benchmarks/bench_paper.py --all --output results/

# Run specific experiment
python benchmarks/bench_paper.py --exp scalability

# Quick test
python benchmarks/bench_paper.py --small
```

---

*Generated: 2026-03-22 22:45 UTC*
