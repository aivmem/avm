#!/usr/bin/env python3
"""
AVM Playground - Interactive Demo with Rich UI

Run: python playground.py
"""

import os
import sys
import tempfile
import time

# Check for rich, offer to install
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.tree import Tree
    from rich.syntax import Syntax
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.markdown import Markdown
    from rich.layout import Layout
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    print("Installing rich for beentter visualization...")
    os.system(f"{sys.executable} -m pip install rich -q")
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.tree import Tree
    from rich.syntax import Syntax
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.markdown import Markdown
    from rich.layout import Layout
    from rich import box

# Use temp database
os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()

from avm import AVM
from avm.graph import EdgeType

console = Console()


def banner():
    console.print(Panel.fit("""
[bold cyan]
     █████╗ ██╗   ██╗███╗   ███╗
    ██╔══██╗██║   ██║████╗ ████║
    ███████║██║   ██║██╔████╔██║
    ██╔══██║╚██╗ ██╔╝██║╚██╔╝██║
    ██║  ██║ ╚████╔╝ ██║ ╚═╝ ██║
    ╚═╝  ╚═╝  ╚═══╝  ╚═╝     ╚═╝
[/bold cyan]
[dim]AI Virtual Memory - Interactive Playground[/dim]
    """, border_style="cyan"))


def section(title: str, icon: str = "📦"):
    console.print()
    console.rule(f"[bold yellow]{icon} {title}[/bold yellow]")
    console.print()


def show_code(code: str, language: str = "python"):
    console.print(Syntax(code, language, theme="monokai", line_numbers=False))


def show_result(labeenl: str, content: str, style: str = "green"):
    console.print(Panel(content, title=f"[bold]{labeenl}[/bold]", border_style=style))


def show_table(title: str, columns: list, rows: list):
    table = Table(title=title, box=box.ROUNDED)
    for col in columns:
        table.add_column(col, style="cyan")
    for row in rows:
        table.add_row(*[str(x) for x in row])
    console.print(table)


AUTO_MODE = "--auto" in sys.argv or "-a" in sys.argv

def pause():
    if AUTO_MODE:
        console.print()
        time.sleep(0.3)
    else:
        console.print("\n[dim]Press Enter to continue...[/dim]")
        input()


def main():
    banner()
    
    console.print("[bold green]Welcome to the AVM Playground![/bold green]")
    console.print("This demo will walk you through AVM's core features.\n")
    
    # Initialize
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Initializing AVM...", total=None)
        avm = AVM()
        time.sleep(0.5)
        progress.remove_task(task)
    
    console.print(f"[green]✓[/green] AVM initialized")
    console.print(f"[dim]Database: {avm.store.db_path}[/dim]\n")
    
    pause()
    
    # ═══════════════════════════════════════════════════════════
    section("1. BASIC READ/WRITE", "📝")
    # ═══════════════════════════════════════════════════════════
    
    console.print("Let's store some knowledge:\n")
    
    show_code('''avm.write("/memory/lessons/trading_rules.md", """
# Trading Rules

## Risk Management
- Never risk more than 2% per trade
- Always use stop-loss orders
- Scale into positions gradually

## Technical Analysis  
- RSI > 70 = Overbought (consider selling)
- RSI < 30 = Oversold (consider buying)
- MACD crossover = Trend change signal
""")''')
    
    avm.write("/memory/lessons/trading_rules.md", """# Trading Rules

## Risk Management
- Never risk more than 2% per trade
- Always use stop-loss orders
- Scale into positions gradually

## Technical Analysis  
- RSI > 70 = Overbought (consider selling)
- RSI < 30 = Oversold (consider buying)
- MACD crossover = Trend change signal
""")
    
    console.print("\n[green]✓[/green] Written: /memory/lessons/trading_rules.md")
    
    # Write more content
    avm.write("/memory/market/NVDA.md", """# NVDA Analysis

**Price**: $892.50 | **RSI**: 72.3 (Overbought)

## Signals
- 📉 MACD beenarish divergence
- 📊 Volume declining on highs
- ⚠️ Approaching $900 resistance

## Action
Reduce position by 50%. Stop-loss at $850.
""")
    console.print("[green]✓[/green] Written: /memory/market/NVDA.md")
    
    avm.write("/memory/market/BTC.md", """# BTC Update

**Price**: $67,250 | **RSI**: 58 (Neutral)

## Key Levels
- Support: $65,000
- Resistance: $70,000

## Outlook
Bullish structure. ETF inflows strong. Accumulate dips.
""")
    console.print("[green]✓[/green] Written: /memory/market/BTC.md")
    
    # Read back
    console.print("\nReading back the content:\n")
    node = avm.read("/memory/lessons/trading_rules.md")
    show_result("Content Preview", node.content[:300] + "...", "blue")
    
    pause()
    
    # ═══════════════════════════════════════════════════════════
    section("2. FULL-TEXT SEARCH", "🔍")
    # ═══════════════════════════════════════════════════════════
    
    console.print("Search across all memories:\n")
    
    show_code('results = avm.search("RSI overbought", limit=5)')
    
    results = avm.search("RSI overbought", limit=5)
    
    show_table(
        "Search Results: 'RSI overbought'",
        ["Rank", "Path", "Preview"],
        [(f"#{i+1}", node.path, node.content[:40] + "...") for i, (node, score) in enumerate(results)]
    )
    
    console.print()
    results2 = avm.search("risk management", limit=5)
    show_table(
        "Search Results: 'risk management'",
        ["Rank", "Path", "Preview"],
        [(f"#{i+1}", node.path, node.content[:40] + "...") for i, (node, score) in enumerate(results2)]
    )
    
    pause()
    
    # ═══════════════════════════════════════════════════════════
    section("3. KNOWLEDGE GRAPH", "🔗")
    # ═══════════════════════════════════════════════════════════
    
    console.print("Create relationships between memories:\n")
    
    show_code('''avm.link("/memory/market/NVDA.md", "/memory/lessons/trading_rules.md", EdgeType.RELATED)
avm.link("/memory/market/BTC.md", "/memory/lessons/trading_rules.md", EdgeType.RELATED)''')
    
    avm.link("/memory/market/NVDA.md", "/memory/lessons/trading_rules.md", EdgeType.RELATED)
    avm.link("/memory/market/BTC.md", "/memory/lessons/trading_rules.md", EdgeType.RELATED)
    
    console.print("[green]✓[/green] Links created\n")
    
    # Visualize as tree
    tree = Tree("[bold]📁 /memory/lessons/trading_rules.md[/bold]")
    edges = avm.links("/memory/lessons/trading_rules.md")
    for edge in edges:
        tree.add(f"[cyan]→ {edge.source}[/cyan] [dim]({edge.edge_type})[/dim]")
    
    console.print(Panel(tree, title="Knowledge Graph", border_style="magenta"))
    
    pause()
    
    # ═══════════════════════════════════════════════════════════
    section("4. AGENT MEMORY", "🤖")
    # ═══════════════════════════════════════════════════════════
    
    console.print("Create an AI agent with its own memory space:\n")
    
    show_code('''trader = avm.agent_memory("trader")

trader.remember(
    "NVDA showing weakness at resistance. RSI overbought.",
    title="nvda_alert",
    importance=0.9,
    tags=["market", "nvda", "alert"]
)''')
    
    trader = avm.agent_memory("trader")
    
    trader.remember(
        "NVDA showing weakness at resistance. RSI overbought at 72.",
        title="nvda_alert",
        importance=0.9,
        tags=["market", "nvda", "alert"]
    )
    console.print("[green]✓[/green] Remembered: NVDA alert (importance: 0.9)")
    
    trader.remember(
        "BTC holding $65K support. Structure remains bullish.",
        title="btc_note",
        importance=0.7,
        tags=["market", "btc", "bullish"]
    )
    console.print("[green]✓[/green] Remembered: BTC note (importance: 0.7)")
    
    trader.remember(
        "Fed minutes tomorrow. Market may been volatile.",
        title="macro_alert",
        importance=0.6,
        tags=["macro", "fed", "volatility"]
    )
    console.print("[green]✓[/green] Remembered: Macro alert (importance: 0.6)")
    
    pause()
    
    # ═══════════════════════════════════════════════════════════
    section("5. TOKEN-AWARE RECALL", "🧠")
    # ═══════════════════════════════════════════════════════════
    
    console.print("Recall memories with token budget (perfect for LLM context):\n")
    
    show_code('context = trader.recall("NVDA", max_tokens=500)')
    
    context = trader.recall("NVDA", max_tokens=500)
    
    # Use Text object to avoid markup parsing
    from rich.text import Text
    console.print(Panel(Text(context), title="[bold]Recall Result (max 500 tokens)[/bold]", border_style="green"))
    
    pause()
    
    # ═══════════════════════════════════════════════════════════
    section("6. MULTI-AGENT ISOLATION", "👥")
    # ═══════════════════════════════════════════════════════════
    
    console.print("Each agent  isolated private memory:\n")
    
    show_code('''analyst = avm.agent_memory("analyst")
analyst.remember("SPY head-and-shoulders pattern forming", ...)

# Trader cannot see analyst's private memory
trader.recall("SPY pattern")  # Returns nothing''')
    
    analyst = avm.agent_memory("analyst")
    analyst.remember(
        "SPY showing head-and-shoulders pattern on daily chart.",
        title="spy_pattern",
        importance=0.8,
        tags=["pattern", "spy"]
    )
    console.print("[green]✓[/green] Analyst stored: SPY pattern\n")
    
    # Show isolation
    table = Table(title="Agent Memory Isolation", box=box.ROUNDED)
    table.add_column("Agent", style="cyan")
    table.add_column("Private Memories", style="green")
    table.add_column("Can See Each Other?", style="red")
    
    table.add_row("trader", str(trader.stats()['private_count']), "❌ No")
    table.add_row("analyst", str(analyst.stats()['private_count']), "❌ No")
    
    console.print(table)
    
    pause()
    
    # ═══════════════════════════════════════════════════════════
    section("7. TAGS & METADATA", "🏷️")
    # ═══════════════════════════════════════════════════════════
    
    console.print("Organize memories with tags:\n")
    
    # Tag cloud
    cloud = trader.tag_cloud()
    
    tag_visual = " ".join([
        f"[{'bold ' if count > 1 else ''}cyan]{tag}[/] [dim]({count})[/dim]"
        for tag, count in cloud.items()
    ])
    
    console.print(Panel(tag_visual, title="Tag Cloud", border_style="cyan"))
    
    # Search by tag
    console.print("\nMemories tagged 'market':")
    tagged = trader.by_tag("market")
    for node in tagged[:5]:
        console.print(f"  [green]•[/green] {node.path}")
    
    pause()
    
    # ═══════════════════════════════════════════════════════════
    section("8. FILE STRUCTURE", "📂")
    # ═══════════════════════════════════════════════════════════
    
    console.print("View the virtual filesystem:\n")
    
    # Build tree
    root = Tree("[bold]📁 /memory[/bold]")
    
    lessons = root.add("📁 lessons")
    lessons.add("📄 trading_rules.md")
    
    market = root.add("📁 market")
    market.add("📄 NVDA.md")
    market.add("📄 BTC.md")
    
    private = root.add("📁 private")
    trader_dir = private.add("📁 trader")
    trader_dir.add("📄 nvda_alert.md")
    trader_dir.add("📄 btc_note.md")
    trader_dir.add("📄 macro_alert.md")
    analyst_dir = private.add("📁 analyst")
    analyst_dir.add("📄 spy_pattern.md")
    
    console.print(Panel(root, title="Virtual Filesystem", border_style="blue"))
    
    pause()
    
    # ═══════════════════════════════════════════════════════════
    section("9. STATISTICS", "📊")
    # ═══════════════════════════════════════════════════════════
    
    stats = avm.stats()
    
    table = Table(title="Storage Statistics", box=box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Total Nodes", str(stats['nodes']))
    table.add_row("Total Edges", str(stats['edges']))
    table.add_row("Database", stats['db_path'].split('/')[-1])
    
    console.print(table)
    
    pause()
    
    # ═══════════════════════════════════════════════════════════
    section("DEMO COMPLETE!", "🎉")
    # ═══════════════════════════════════════════════════════════
    
    console.print(Panel.fit("""
[bold green]You've experienced AVM's core features:[/bold green]

  ✅ Read/Write structured memories
  ✅ Full-text search with ranking
  ✅ Knowledge graph relationships
  ✅ Token-aware recall for AI agents
  ✅ Multi-agent memory isolation
  ✅ Tags and metadata

[bold yellow]Next Steps:[/bold yellow]

  [cyan]# Mount as filesystem[/cyan]
  avm-mount /mnt/avm --user myagent
  
  [cyan]# Start MCP server[/cyan]
  avm-mcp --user myagent
  
  [cyan]# Read the docs[/cyan]
  https://github.com/bkmashiro/avm

[dim]Happy hacking! 🚀[/dim]
    """, border_style="green"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Demo interrupted.[/yellow]")
