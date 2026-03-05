#!/usr/bin/env python3
"""
AVM Playground - Interactive Demo

Run this script to experience AVM's core features:
    python playground.py

This demo shows:
1. Basic read/write operations
2. Full-text search
3. Knowledge graph (linking)
4. Agent Memory with token-aware recall
5. Multi-agent collaboration
6. Virtual nodes (metadata, tags, links)
"""

import os
import tempfile
from datetime import datetime

# Use a temp database for the demo
os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()

from avm import VFS
from avm.graph import EdgeType


def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def print_result(label: str, value):
    print(f"\n📌 {label}:")
    if isinstance(value, str):
        for line in value.split('\n')[:15]:
            print(f"   {line}")
    else:
        print(f"   {value}")


def main():
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║     █████╗ ██╗   ██╗███╗   ███╗                          ║
    ║    ██╔══██╗██║   ██║████╗ ████║                          ║
    ║    ███████║██║   ██║██╔████╔██║                          ║
    ║    ██╔══██║╚██╗ ██╔╝██║╚██╔╝██║                          ║
    ║    ██║  ██║ ╚████╔╝ ██║ ╚═╝ ██║                          ║
    ║    ╚═╝  ╚═╝  ╚═══╝  ╚═╝     ╚═╝                          ║
    ║                                                           ║
    ║    AI Virtual Memory - Playground                         ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Initialize VFS
    vfs = VFS()
    print(f"✓ AVM initialized (DB: {vfs.store.db_path})")
    
    # ─────────────────────────────────────────────────────────
    print_section("1. BASIC READ/WRITE")
    # ─────────────────────────────────────────────────────────
    
    # Write some memories
    vfs.write("/memory/lessons/risk_management.md", """# Risk Management Rules

## Position Sizing
- Never risk more than 2% of portfolio on a single trade
- Use stop-loss orders religiously
- Scale into positions, don't go all-in

## Market Conditions
- Reduce position size in high volatility
- RSI > 70 indicates overbought conditions
- RSI < 30 indicates oversold conditions

## Emotional Control
- Never revenge trade after a loss
- Take breaks after 3 consecutive losses
- Stick to the plan, ignore FOMO
""")
    print("✓ Written: /memory/lessons/risk_management.md")
    
    vfs.write("/memory/market/NVDA_analysis.md", """# NVDA Technical Analysis

**Date**: 2026-03-05
**Price**: $892.50
**RSI**: 72.3 (Overbought)

## Signals
- MACD showing bearish divergence
- Volume declining on recent highs
- Approaching resistance at $900

## Recommendation
Reduce position size by 50%. Set stop-loss at $850.
Watch for break below 20-day MA as exit signal.
""")
    print("✓ Written: /memory/market/NVDA_analysis.md")
    
    vfs.write("/memory/market/BTC_update.md", """# BTC Market Update

**Price**: $67,250
**Trend**: Bullish continuation

## Key Levels
- Support: $65,000
- Resistance: $70,000
- RSI: 58 (Neutral)

## Notes
ETF inflows remain strong. Halving in 45 days.
Accumulate on dips to $65K support.
""")
    print("✓ Written: /memory/market/BTC_update.md")
    
    # Read back
    node = vfs.read("/memory/lessons/risk_management.md")
    print_result("Read content (first 200 chars)", node.content[:200] + "...")
    
    # ─────────────────────────────────────────────────────────
    print_section("2. FULL-TEXT SEARCH")
    # ─────────────────────────────────────────────────────────
    
    results = vfs.search("RSI overbought", limit=5)
    print_result("Search: 'RSI overbought'", 
                 "\n".join([f"[{score:.2f}] {node.path}" for node, score in results]))
    
    results = vfs.search("position sizing", limit=5)
    print_result("Search: 'position sizing'",
                 "\n".join([f"[{score:.2f}] {node.path}" for node, score in results]))
    
    # ─────────────────────────────────────────────────────────
    print_section("3. KNOWLEDGE GRAPH (LINKING)")
    # ─────────────────────────────────────────────────────────
    
    # Create relationships
    vfs.link("/memory/market/NVDA_analysis.md", 
             "/memory/lessons/risk_management.md", 
             EdgeType.RELATED)
    print("✓ Linked: NVDA_analysis → risk_management (related)")
    
    vfs.link("/memory/market/BTC_update.md",
             "/memory/lessons/risk_management.md",
             EdgeType.RELATED)
    print("✓ Linked: BTC_update → risk_management (related)")
    
    # Query links
    edges = vfs.links("/memory/lessons/risk_management.md")
    print_result("Links from risk_management.md",
                 "\n".join([f"→ {e.source} ({e.edge_type})" for e in edges]))
    
    # ─────────────────────────────────────────────────────────
    print_section("4. AGENT MEMORY (TOKEN-AWARE RECALL)")
    # ─────────────────────────────────────────────────────────
    
    # Create agent memory for "trader" agent
    mem = vfs.agent_memory("trader")
    
    # Store some insights
    mem.remember(
        "NVDA showing weakness. RSI at 72, reduce exposure.",
        title="nvda_warning",
        importance=0.9,
        tags=["market", "nvda", "warning"]
    )
    print("✓ Remembered: NVDA warning (importance: 0.9)")
    
    mem.remember(
        "BTC holding above $65K support. Bullish structure intact.",
        title="btc_observation",
        importance=0.7,
        tags=["market", "btc", "bullish"]
    )
    print("✓ Remembered: BTC observation (importance: 0.7)")
    
    mem.remember(
        "General market sentiment turning cautious. Fed minutes tomorrow.",
        title="macro_note",
        importance=0.6,
        tags=["macro", "fed"]
    )
    print("✓ Remembered: Macro note (importance: 0.6)")
    
    # Recall with token budget
    print_result("Recall: 'NVDA risk' (max 500 tokens)", 
                 mem.recall("NVDA risk", max_tokens=500))
    
    print_result("Recall: 'market overview' (max 1000 tokens)",
                 mem.recall("market overview", max_tokens=1000))
    
    # ─────────────────────────────────────────────────────────
    print_section("5. MULTI-AGENT ISOLATION")
    # ─────────────────────────────────────────────────────────
    
    # Create another agent - each has private memory
    analyst = vfs.agent_memory("analyst")
    
    # Analyst stores in private space
    analyst.remember(
        "Technical setup: Head and shoulders forming on SPY daily.",
        title="spy_pattern",
        importance=0.8,
        tags=["pattern", "spy"]
    )
    print("✓ Analyst stored: SPY pattern (private to analyst)")
    
    # Trader cannot see analyst's private memory
    trader_recall = mem.recall("SPY pattern", max_tokens=500)
    print_result("Trader tries to recall analyst's memory", 
                 "Cannot access - private to analyst" if "No relevant" in trader_recall else trader_recall)
    
    # Each agent has isolated stats
    print_result("Trader stats", f"Private: {mem.stats()['private_count']}")
    print_result("Analyst stats", f"Private: {analyst.stats()['private_count']}")
    
    # ─────────────────────────────────────────────────────────
    print_section("6. METADATA & TAGS")
    # ─────────────────────────────────────────────────────────
    
    # Get tag cloud
    cloud = mem.tag_cloud()
    print_result("Tag Cloud", 
                 "\n".join([f"{tag}: {count}" for tag, count in list(cloud.items())[:10]]))
    
    # Search by tag
    tagged = mem.by_tag("market")
    print_result("Memories tagged 'market'",
                 "\n".join([n.path for n in tagged[:5]]))
    
    # Stats
    stats = mem.stats()
    print_result("Agent Stats", 
                 f"Private: {stats['private_count']}, Shared: {stats['shared_accessible']}")
    
    # ─────────────────────────────────────────────────────────
    print_section("7. LISTING & HISTORY")
    # ─────────────────────────────────────────────────────────
    
    # List all nodes
    nodes = vfs.list("/memory", limit=10)
    print_result("All memories (first 10)",
                 "\n".join([n.path for n in nodes]))
    
    # View history
    history = vfs.history("/memory/lessons/risk_management.md", limit=3)
    print_result("Change history",
                 "\n".join([f"[{h.timestamp[:19] if hasattr(h, 'timestamp') else ''}] {h.change_type if hasattr(h, 'change_type') else 'update'}" 
                           for h in history]))
    
    # Storage stats
    stats = vfs.stats()
    print_result("Storage Stats",
                 f"Nodes: {stats['nodes']}, Edges: {stats['edges']}")
    
    # ─────────────────────────────────────────────────────────
    print_section("8. CLEANUP")
    # ─────────────────────────────────────────────────────────
    
    # Delete a node
    vfs.delete("/memory/market/BTC_update.md")
    print("✓ Deleted: /memory/market/BTC_update.md")
    
    # Verify
    node = vfs.read("/memory/market/BTC_update.md")
    print(f"✓ Verified deletion: {node is None}")
    
    # ─────────────────────────────────────────────────────────
    print_section("DEMO COMPLETE")
    # ─────────────────────────────────────────────────────────
    
    print("""
    🎉 You've experienced AVM's core features:
    
    ✓ Read/Write structured memories
    ✓ Full-text search with ranking
    ✓ Knowledge graph with relationships
    ✓ Token-aware recall for AI agents
    ✓ Multi-agent collaboration
    ✓ Metadata and tagging
    
    Next steps:
    - Mount as filesystem: avm-mount /mnt/avm --user myagent
    - Use MCP server: avm-mcp --user myagent
    - Read the docs: https://github.com/bkmashiro/avm
    
    Happy hacking! 🚀
    """)


if __name__ == "__main__":
    main()
