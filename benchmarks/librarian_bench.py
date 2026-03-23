#!/usr/bin/env python3
"""
Librarian Benchmark

Measures:
1. Query routing accuracy
2. Cross-agent discovery precision/recall
3. Privacy policy effectiveness
4. Latency at different scales
"""

import os
import sys
import time
import json
import random
import tempfile
import argparse
from typing import List, Dict, Tuple
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from avm.store import AVMStore
from avm.node import AVMNode
from avm.librarian import Librarian, LibrarianResponse, PrivacyPolicy, AgentInfo
from avm.topic_index import TopicIndex
from avm.embedding import EmbeddingStore, LocalEmbedding


@dataclass
class BenchmarkConfig:
    """Benchmark configuration"""
    num_agents: int = 10
    memories_per_agent: int = 100
    topics: List[str] = field(default_factory=lambda: [
        "trading", "market", "crypto", "ai", "research",
        "personal", "code", "bugs", "features", "meetings"
    ])
    query_count: int = 100
    seed: int = 42
    use_embedding: bool = False  # Enable semantic search


@dataclass
class BenchmarkResult:
    """Benchmark results"""
    # Routing accuracy
    precision: float = 0.0  # Correct accessible / total accessible
    recall: float = 0.0     # Correct accessible / should be accessible
    
    # Discovery
    suggestion_accuracy: float = 0.0  # Correct suggestions / total suggestions
    
    # Latency (ms)
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    
    # Scale
    total_memories: int = 0
    total_agents: int = 0
    queries_run: int = 0
    
    def to_dict(self) -> Dict:
        return {
            "routing": {
                "precision": round(self.precision, 4),
                "recall": round(self.recall, 4),
                "f1": round(2 * self.precision * self.recall / (self.precision + self.recall + 0.001), 4),
            },
            "discovery": {
                "suggestion_accuracy": round(self.suggestion_accuracy, 4),
            },
            "latency_ms": {
                "avg": round(self.avg_latency_ms, 2),
                "p50": round(self.p50_latency_ms, 2),
                "p99": round(self.p99_latency_ms, 2),
            },
            "scale": {
                "total_memories": self.total_memories,
                "total_agents": self.total_agents,
                "queries_run": self.queries_run,
            }
        }


class LibrarianBenchmark:
    """Benchmark harness for Librarian"""
    
    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.tmpdir = tempfile.mkdtemp()
        self.store = AVMStore(os.path.join(self.tmpdir, "bench.db"))
        self.topic_index = TopicIndex(self.store)
        
        # Embedding store (optional)
        self.embedding_store = None
        if config.use_embedding:
            try:
                backend = LocalEmbedding("all-MiniLM-L6-v2")
                self.embedding_store = EmbeddingStore(self.store, backend)
                print("Embedding enabled (all-MiniLM-L6-v2)")
            except ImportError:
                print("Warning: sentence-transformers not installed, using FTS only")
        
        self.librarian = Librarian(
            self.store, 
            privacy_policy=PrivacyPolicy("full"),
            embedding_store=self.embedding_store,
        )
        
        # Ground truth
        self.agent_topics: Dict[str, List[str]] = {}
        self.memory_topics: Dict[str, str] = {}  # path -> topic
        
        random.seed(config.seed)
    
    def setup(self):
        """Generate synthetic memories"""
        print(f"Generating {self.config.num_agents} agents × {self.config.memories_per_agent} memories...")
        
        for agent_idx in range(self.config.num_agents):
            agent_id = f"agent_{agent_idx:03d}"
            
            # Each agent specializes in 2-3 topics
            agent_topics = random.sample(self.config.topics, random.randint(2, 3))
            self.agent_topics[agent_id] = agent_topics
            
            for mem_idx in range(self.config.memories_per_agent):
                # 80% on-topic, 20% random
                if random.random() < 0.8:
                    topic = random.choice(agent_topics)
                else:
                    topic = random.choice(self.config.topics)
                
                path = f"/memory/private/{agent_id}/{topic}/{mem_idx:04d}.md"
                content = self._generate_content(topic, mem_idx)
                
                node = AVMNode(
                    path=path,
                    content=content,
                    meta={"topic": topic, "importance": random.random()}
                )
                self.store.put_node(node)
                self.topic_index.index_path(path, content, topic)
                self.memory_topics[path] = topic
                
                # Generate embedding if enabled
                if self.embedding_store:
                    self.embedding_store.embeend_node(node)
        
        # Register agents
        for agent_id, topics in self.agent_topics.items():
            self.librarian.register_agent(agent_id, AgentInfo(
                id=agent_id,
                capabilities=topics,
                memory_count=self.config.memories_per_agent,
            ))
        
        print(f"Setup complete: {len(self.memory_topics)} memories indexed")
    
    def _generate_content(self, topic: str, idx: int) -> str:
        """Generate synthetic content for a topic"""
        templates = {
            "trading": f"Market analysis #{idx}: BTC showing bullish patterns. RSI at {random.randint(30, 70)}.",
            "market": f"Stock update #{idx}: NVDA up {random.randint(1, 10)}%. Volume {random.randint(10, 100)}M.",
            "crypto": f"Crypto news #{idx}: ETH gas fees at {random.randint(5, 50)} gwei. DEX volume rising.",
            "ai": f"AI research #{idx}: New transformer architecture with {random.randint(1, 100)}B params.",
            "research": f"Paper summary #{idx}: Novel approach to {random.choice(['NLP', 'CV', 'RL', 'ML'])}.",
            "personal": f"Personal note #{idx}: Remember to {random.choice(['call', 'email', 'meet'])} about project.",
            "code": f"Code review #{idx}: Fixed bug in {random.choice(['auth', 'api', 'db'])} module.",
            "bugs": f"Bug report #{idx}: Issue in {random.choice(['login', 'checkout', 'search'])} flow.",
            "features": f"Feature request #{idx}: Add {random.choice(['dark mode', 'export', 'filters'])}.",
            "meetings": f"Meeting notes #{idx}: Discussed Q{random.randint(1, 4)} roadmap with team.",
        }
        return templates.get(topic, f"Generic content #{idx} about {topic}")
    
    def run_benchmark(self) -> BenchmarkResult:
        """Run the benchmark"""
        result = BenchmarkResult()
        result.total_memories = len(self.memory_topics)
        result.total_agents = len(self.agent_topics)
        
        latencies = []
        correct_accessible = 0
        total_accessible = 0
        should_be_accessible = 0
        correct_suggestions = 0
        total_suggestions = 0
        
        # Generate queries
        queries = self._generate_queries()
        result.queries_run = len(queries)
        
        for query, expected_topic, requester in queries:
            # Time the query
            start = time.perf_counter()
            response = self.librarian.query(requester, query, limit=10)
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)
            
            # Check routing accuracy
            total_accessible += len(response.accessible)
            
            # Calculate expected accessible count
            expected_paths = [
                p for p, t in self.memory_topics.items()
                if t == expected_topic and p.startswith(f"/memory/private/{requester}/")
            ]
            should_be_accessible += len(expected_paths)
            
            # Count correct accessible
            for node in response.accessible:
                actual_topic = self.memory_topics.get(node.path, "")
                if actual_topic == expected_topic:
                    correct_accessible += 1
            
            # Check suggestion accuracy
            for suggestion in response.suggestions:
                total_suggestions += 1
                # Check if suggested agent actually has this topic
                if suggestion.agent in self.agent_topics:
                    if expected_topic in self.agent_topics[suggestion.agent]:
                        correct_suggestions += 1
        
        # Calculate metrics
        result.precision = correct_accessible / max(total_accessible, 1)
        result.recall = correct_accessible / max(should_be_accessible, 1)
        result.suggestion_accuracy = correct_suggestions / max(total_suggestions, 1)
        
        # Latency percentiles
        latencies.sort()
        result.avg_latency_ms = sum(latencies) / len(latencies)
        result.p50_latency_ms = latencies[len(latencies) // 2]
        result.p99_latency_ms = latencies[int(len(latencies) * 0.99)]
        
        return result
    
    def _generate_queries(self) -> List[Tuple[str, str, str]]:
        """Generate test queries: (query, expected_topic, requester)"""
        queries = []
        
        # Direct keyword queries (FTS-friendly)
        topic_keywords = {
            "trading": ["market analysis", "bullish", "RSI", "trading strategy"],
            "market": ["stock", "NVDA", "volume", "earnings"],
            "crypto": ["BTC", "ETH", "gas fees", "DEX"],
            "ai": ["transformer", "neural network", "GPT", "LLM"],
            "research": ["paper", "novel approach", "study", "findings"],
            "personal": ["remember", "call", "email", "meeting"],
            "code": ["code review", "bug fix", "refactor", "module"],
            "bugs": ["bug report", "issue", "error", "crash"],
            "features": ["feature request", "enhancement", "add support"],
            "meetings": ["meeting notes", "roadmap", "discussion", "team"],
        }
        
        # Semantic queries (embedding-friendly, no exact keywords)
        topic_semantic = {
            "trading": ["how should I invest", "what's the best strategy", "market timing"],
            "market": ["how are tech stocks doing", "latest equity news", "share price changes"],
            "crypto": ["blockchain developments", "digital currency trends", "decentralized finance"],
            "ai": ["machine learning progress", "artificial intelligence advances", "deep learning models"],
            "research": ["academic work", "scientific studies", "published findings"],
            "personal": ["things I need to do", "my schedule", "reminders"],
            "code": ["programming improvements", "software changes", "development work"],
            "bugs": ["problems in the system", "things that broke", "errors to fix"],
            "features": ["new functionality", "product improvements", "user requests"],
            "meetings": ["team discussions", "planning sessions", "group conversations"],
        }
        
        agents = list(self.agent_topics.keys())
        
        for i in range(self.config.query_count):
            topic = random.choice(self.config.topics)
            requester = random.choice(agents)
            
            # Mix: 50% keyword queries, 50% semantic queries
            if i % 2 == 0:
                query = random.choice(topic_keywords[topic])
            else:
                query = random.choice(topic_semantic[topic])
            
            queries.append((query, topic, requester))
        
        return queries
    
    def cleanup(self):
        """Cleanup temporary files"""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def run_scale_benchmark(max_agents: int = 50, step: int = 10):
    """Run benchmark at different scales"""
    results = []
    
    for num_agents in range(10, max_agents + 1, step):
        config = BenchmarkConfig(
            num_agents=num_agents,
            memories_per_agent=100,
            query_count=100,
        )
        
        bench = LibrarianBenchmark(config)
        bench.setup()
        result = bench.run_benchmark()
        bench.cleanup()
        
        results.append({
            "agents": num_agents,
            "memories": num_agents * 100,
            **result.to_dict()
        })
        
        print(f"[{num_agents} agents] Precision: {result.precision:.3f}, "
              f"Recall: {result.recall:.3f}, Latency: {result.avg_latency_ms:.2f}ms")
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Librarian Benchmark")
    parser.add_argument("--agents", "-a", type=int, default=10, help="Number of agents")
    parser.add_argument("--memories", "-m", type=int, default=100, help="Memories per agent")
    parser.add_argument("--queries", "-q", type=int, default=100, help="Number of queries")
    parser.add_argument("--scale", action="store_true", help="Run scale benchmark")
    parser.add_argument("--max-agents", type=int, default=50, help="Max agents for scale test")
    parser.add_argument("--embedding", "-e", action="store_true", help="Enable semantic search")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    if args.scale:
        results = run_scale_benchmark(args.max_agents)
        if args.json:
            print(json.dumps(results, indent=2))
        return
    
    config = BenchmarkConfig(
        num_agents=args.agents,
        memories_per_agent=args.memories,
        query_count=args.queries,
        use_embedding=args.embedding,
    )
    
    bench = LibrarianBenchmark(config)
    bench.setup()
    result = bench.run_benchmark()
    bench.cleanup()
    
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("\n" + "=" * 50)
        print("LIBRARIAN BENCHMARK RESULTS")
        print("=" * 50)
        print(f"\nScale: {result.total_agents} agents, {result.total_memories} memories")
        print(f"Queries: {result.queries_run}")
        print(f"\nRouting Accuracy:")
        print(f"  Precision: {result.precision:.4f}")
        print(f"  Recall:    {result.recall:.4f}")
        f1 = 2 * result.precision * result.recall / (result.precision + result.recall + 0.001)
        print(f"  F1 Score:  {f1:.4f}")
        print(f"\nDiscovery:")
        print(f"  Suggestion Accuracy: {result.suggestion_accuracy:.4f}")
        print(f"\nLatency:")
        print(f"  Average: {result.avg_latency_ms:.2f}ms")
        print(f"  P50:     {result.p50_latency_ms:.2f}ms")
        print(f"  P99:     {result.p99_latency_ms:.2f}ms")


if __name__ == "__main__":
    main()
