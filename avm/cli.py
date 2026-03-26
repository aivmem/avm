#!/usr/bin/env python3
"""
avm/cli.py - AVM command line interface

Config-driven virtual filesystem CLI

usage:
    vfs read /market/indicators/AAPL.md
    vfs write /memory/lesson.md --content "Today learned..."
    vfs search "RSI oversold"
    vfs links /research/MSFT.md
    vfs stats
"""

import argparse
import json
import sys
import platform
from pathlib import Path
from typing import Optional

from .core import AVM
from .config import load_config
from .node import AVMNode, NodeType
from .graph import EdgeType

IS_WINDOWS = sys.platform == "win32"

# Alias for backwards compatibility
VFS = AVM


def get_vfs(config_path: Optional[str] = None, db_path: Optional[str] = None) -> AVM:
    """Get VFS instance"""
    config = load_config(config_path)
    if db_path:
        config.db_path = db_path
    return VFS(config)


def cmd_read(args):
    """readnode"""
    vfs = get_vfs(args.config, args.db)
    path = args.path
    
    try:
        if args.as_of:
            node = vfs.read_at_time(path, args.as_of)
        elif args.version:
            node = vfs.read_at_version(path, args.version)
        else:
            node = vfs.read(path, force_refresh=args.refresh)
    except PermissionError as e:
        print(f"Permission denied: {e}", file=sys.stderr)
        return 1
    
    if node is None:
        print(f"Not found: {path}", file=sys.stderr)
        return 1
    
    if args.json:
        print(json.dumps(node.to_dict(), indent=2, default=str))
    else:
        if args.meta:
            print(f"# {path}")
            print(f"# Version: {node.version}")
            print(f"# Updated: {node.updated_at}")
            print(f"# Meta: {json.dumps(node.meta)}")
            print()
        print(node.content)
    
    return 0


def cmd_write(args):
    """writenode"""
    vfs = get_vfs(args.config, args.db)
    path = args.path
    
    # Get content
    if args.content:
        content = args.content
    elif args.file:
        content = Path(args.file).read_text()
    else:
        content = sys.stdin.read()
    
    # Parse metadata
    meta = {}
    if args.meta:
        meta = json.loads(args.meta)
    
    try:
        saved = vfs.write(path, content, meta)
    except PermissionError as e:
        print(f"Permission denied: {e}", file=sys.stderr)
        return 1
    
    if args.json:
        print(json.dumps(saved.to_dict(), indent=2, default=str))
    else:
        print(f"Saved: {saved.path} (v{saved.version})")
    
    return 0


def cmd_mv(args):
    """Move/rename a node or an entire prefix tree."""
    vfs = get_vfs(args.config, args.db)
    try:
        n = vfs.rename(args.src, args.dst)
        print(f"Moved {n} node(s): {args.src} → {args.dst}")
        return 0
    except FileNotFoundError as e:
        print(f"mv: {e}", file=sys.stderr)
        return 1
    except PermissionError as e:
        print(f"mv: permission denied: {e}", file=sys.stderr)
        return 1


def cmd_delete(args):
    """deletenode"""
    vfs = get_vfs(args.config, args.db)
    path = args.path
    
    try:
        if vfs.delete(path):
            print(f"Deleted: {path}")
            return 0
        else:
            print(f"Not found: {path}", file=sys.stderr)
            return 1
    except PermissionError as e:
        print(f"Permission denied: {e}", file=sys.stderr)
        return 1


def cmd_list(args):
    """listnode"""
    vfs = get_vfs(args.config, args.db)
    
    nodes = vfs.list(args.prefix, limit=args.limit)
    
    if args.json:
        print(json.dumps([n.to_dict() for n in nodes], indent=2, default=str))
    else:
        for node in nodes:
            size = len(node.content)
            print(f"{node.path}\tv{node.version}\t{size}B\t{node.updated_at.strftime('%Y-%m-%d %H:%M')}")
    
    return 0


def cmd_links(args):
    """View node relationships"""
    vfs = get_vfs(args.config, args.db)
    path = args.path
    
    edges = vfs.links(path, direction=args.direction)
    
    if args.json:
        print(json.dumps([
            {
                "source": e.source,
                "target": e.target,
                "type": e.edge_type.value,
                "weight": e.weight,
            }
            for e in edges
        ], indent=2))
    else:
        if not edges:
            print(f"No links for {path}")
        else:
            print(f"Links for {path}:")
            for e in edges:
                arrow = "-->" if e.source == path else "<--"
                other = e.target if e.source == path else e.source
                print(f"  {arrow} [{e.edge_type.value}] {other}")
    
    return 0


def cmd_link(args):
    """addrelated"""
    vfs = get_vfs(args.config, args.db)
    
    edge_type = EdgeType(args.type)
    edge = vfs.link(args.source, args.target, edge_type, args.weight)
    
    print(f"Added: {edge}")
    return 0


def cmd_search(args):
    """full-textsearch"""
    vfs = get_vfs(args.config, args.db)
    
    results = vfs.search(args.query, limit=args.limit)
    
    if args.json:
        print(json.dumps([
            {"path": n.path, "score": s, "snippet": n.content[:200]}
            for n, s in results
        ], indent=2))
    else:
        if not results:
            print("No results found.")
        else:
            for node, score in results:
                snippet = node.content[:100].replace("\n", " ")
                print(f"[{score:.2f}] {node.path}")
                print(f"    {snippet}...")
                print()
    
    return 0


def cmd_history(args):
    """View change history"""
    vfs = get_vfs(args.config, args.db)
    
    diffs = vfs.history(args.path, limit=args.limit)
    
    if args.json:
        print(json.dumps([d.to_dict() for d in diffs], indent=2, default=str))
    else:
        for d in diffs:
            print(f"v{d.version} [{d.change_type}] {d.changed_at.strftime('%Y-%m-%d %H:%M:%S')}")
            if args.verbose and d.diff_content:
                print(d.diff_content[:500])
            print()
    
    return 0


def cmd_warmup(args):
    """Pre-load embedding model for faster recall"""
    import time
    import os
    import warnings
    import io
    import contextlib
    
    # Suppress all warnings
    warnings.filterwarnings('ignore')
    os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
    os.environ['TRANSFORMERS_VERBOSITY'] = 'error'
    
    start = time.time()
    
    # Suppress stderr during model load
    with contextlib.redirect_stderr(io.StringIO()):
        vfs = get_vfs(args.config, args.db)
    
    if vfs._embedding_store is None:
        print("Embedding not enabled. Set embedding.enabled=true in config.yaml")
        return
    
    # Warmup the backend (suppress stderr)
    backend = vfs._embedding_store.backend
    with contextlib.redirect_stderr(io.StringIO()):
        if hasattr(backend, 'warmup'):
            backend.warmup()
    
    elapsed = (time.time() - start) * 1000
    print(f"✓ Embedding model loaded in {elapsed:.0f}ms")
    print(f"  Model: {getattr(backend, 'model_name', 'unknown')}")
    print(f"  Dimension: {backend.dimension}")


def cmd_stats(args):
    """storagestatistics"""
    vfs = get_vfs(args.config, args.db)
    
    stats = vfs.stats()
    
    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        try:
            from rich.console import Console
            from rich.table import Table
            from rich.panel import Panel
            
            console = Console()
            
            # Main stats panel
            main_table = Table(show_header=False, box=None)
            main_table.add_column("Key", style="cyan")
            main_table.add_column("Value", style="green")
            main_table.add_row("📁 Database", stats['db_path'])
            main_table.add_row("📄 Nodes", str(stats['nodes']))
            main_table.add_row("🔗 Edges", str(stats['edges']))
            main_table.add_row("📝 Diffs", str(stats['diffs']))
            
            console.print(Panel(main_table, title="[bold]AVM Statistics[/bold]", border_style="blue"))
            
            # By prefix table
            if stats.get("by_prefix"):
                prefix_table = Table(title="By Prefix", show_header=True)
                prefix_table.add_column("Prefix", style="cyan")
                prefix_table.add_column("Count", style="green", justify="right")
                
                for prefix, count in sorted(stats["by_prefix"].items()):
                    prefix_table.add_row(prefix, str(count))
                
                console.print(prefix_table)
        except ImportError:
            # Fallback to plain text
            print(f"VFS Statistics")
            print(f"==============")
            print(f"Database: {stats['db_path']}")
            print(f"Nodes: {stats['nodes']}")
            print(f"Edges: {stats['edges']}")
            print(f"Diffs: {stats['diffs']}")
            print()
            print("By prefix:")
            for prefix, count in stats.get("by_prefix", {}).items():
                print(f"  {prefix}: {count}")
    
    return 0





def cmd_refresh(args):
    """refresh live node"""
    vfs = get_vfs(args.config, args.db)
    
    if args.all:
        print("Refreshing all live nodes...")
        nodes = vfs.list("/live", limit=1000)
        count = 0
        for node in nodes:
            try:
                refreshed = vfs.read(node.path, force_refresh=True)
                if refreshed:
                    count += 1
                    print(f"  {node.path}")
            except Exception as e:
                print(f"  {node.path} - Error: {e}")
        print(f"Refreshed {count} nodes")
    elif args.path:
        try:
            node = vfs.read(args.path, force_refresh=True)
            if node:
                print(f"Refreshed: {node.path} (v{node.version})")
            else:
                print(f"Not found: {args.path}", file=sys.stderr)
                return 1
        except PermissionError as e:
            print(f"Permission denied: {e}", file=sys.stderr)
            return 1
    else:
        # listexpirednode
        nodes = vfs.list("/live", limit=1000)
        expired = [n for n in nodes if n.is_expired]
        
        if expired:
            print(f"Expired nodes ({len(expired)}):")
            for node in expired:
                print(f"  {node.path} (updated: {node.updated_at})")
        else:
            print("No expired nodes.")
    
    return 0


def cmd_config(args):
    """Show configuration"""
    vfs = get_vfs(args.config, args.db)
    
    if args.json:
        print(json.dumps(vfs.config.to_dict(), indent=2))
    else:
        print("VFS Configuration")
        print("=================")
        print()
        print("Providers:")
        for p in vfs.config.providers:
            print(f"  {p.pattern} -> {p.type} (ttl={p.ttl}s)")
        print()
        print("Permissions:")
        for r in vfs.config.permissions:
            print(f"  {r.pattern} -> {r.access}")
        print()
        print(f"Default access: {vfs.config.default_access}")
        print(f"Default TTL: {vfs.config.default_ttl}s")
    
    return 0


def cmd_retrieve(args):
    """Linked retrieval"""
    vfs = get_vfs(args.config, args.db)
    
    result = vfs.retrieve(
        args.query,
        k=args.limit,
        expand_graph=not args.no_graph,
        graph_depth=args.depth,
    )
    
    if args.json:
        print(json.dumps({
            "query": result.query,
            "nodes": [{"path": n.path, "score": result.scores.get(n.path, 0)} 
                      for n in result.nodes],
            "sources": result.sources,
            "edges": result.graph_edges,
        }, indent=2))
    else:
        print(f"Query: {result.query}")
        print(f"Found: {len(result.nodes)} nodes")
        print()
        
        for node in result.nodes:
            score = result.get_score(node.path)
            source = result.get_source(node.path)
            badge = {"semantic": "🎯", "fts": "📝", "graph": "🔗"}.get(source, "")
            print(f"{badge} [{score:.2f}] {node.path}")
        
        if result.graph_edges:
            print()
            print("Graph edges:")
            for src, tgt, etype in result.graph_edges:
                print(f"  {src} --[{etype}]--> {tgt}")
    
    return 0


def cmd_synthesize(args):
    """Generate synthesized document"""
    vfs = get_vfs(args.config, args.db)
    
    doc = vfs.synthesize(
        args.query,
        k=args.limit,
        title=args.title,
    )
    
    print(doc)


def cmd_memory_recall(args):
    """Agent Memory retrieve"""
    import io
    import contextlib
    from .agent_memory import ScoringStrategy
    
    # Suppress progress bars by default (unless --verbose)
    if not getattr(args, 'verbose', False):
        # Redirect stderr to suppress progress bars and warnings
        import warnings
        warnings.filterwarnings('ignore')
        # Suppress HF/embedding progress bars via environment
        import os
        os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
        os.environ['TRANSFORMERS_VERBOSITY'] = 'error'
    
    vfs = get_vfs(args.config, args.db)
    memory = vfs.agent_memory(args.agent)
    
    strategy = ScoringStrategy(args.strategy) if args.strategy else None
    
    min_rel = getattr(args, 'min_relevance', 0.3)
    
    # Capture and filter output if not verbose
    if not getattr(args, 'verbose', False):
        # Run with stderr suppressed
        with contextlib.redirect_stderr(io.StringIO()):
            result = memory.recall(
                args.query,
                max_tokens=args.max_tokens,
                strategy=strategy,
                include_shared=not args.private_only,
                min_relevance=min_rel,
            )
    else:
        result = memory.recall(
            args.query,
            max_tokens=args.max_tokens,
            strategy=strategy,
            include_shared=not args.private_only,
            min_relevance=min_rel,
        )
    
    print(result)


def cmd_memory_remember(args):
    """write Agent Memory"""
    vfs = get_vfs(args.config, args.db)
    memory = vfs.agent_memory(args.agent)
    
    # Get content
    if args.content:
        content = args.content
    elif args.file:
        content = Path(args.file).read_text()
    else:
        content = sys.stdin.read()
    
    tags = args.tags.split(",") if args.tags else None
    
    node = memory.remember(
        content,
        title=args.title,
        importance=args.importance,
        tags=tags,
    )
    
    print(f"Remembered: {node.path} (importance={args.importance})")


def cmd_context(args):
    """Generate context injection for agent prompts.
    
    Outputs formatted memory context suitable for system prompts.
    """
    vfs = get_vfs(args.config, args.db)
    memory = vfs.agent_memory(args.agent)
    
    # Build context from multiple sources
    sections = []
    
    # 1. Recent memories (last 24h)
    recent = memory.recall(
        "recent activity",
        max_tokens=args.recent_tokens,
        prefixes=[f"/memory/private/{args.agent}/"],
    )
    if recent.strip():
        sections.append(f"## Recent Activity\n{recent}")
    
    # 2. User preferences (if asked)
    if args.preferences:
        prefs = memory.recall(
            "user preferences settings",
            max_tokens=args.pref_tokens,
        )
        if prefs.strip():
            sections.append(f"## User Preferences\n{prefs}")
    
    # 3. Lessons learned (high importance)
    if args.lessons:
        lessons = memory.recall(
            "lesson learned mistake important",
            max_tokens=args.lesson_tokens,
        )
        if lessons.strip():
            sections.append(f"## Lessons Learned\n{lessons}")
    
    # 4. Custom query
    if args.query:
        custom = memory.recall(args.query, max_tokens=args.query_tokens)
        if custom.strip():
            sections.append(f"## Relevant Context\n{custom}")
    
    # Output
    if not sections:
        if not args.quiet:
            print("# No memory context found", file=sys.stderr)
        return 0
    
    output = "\n\n".join(sections)
    
    if args.format == "markdown":
        print(output)
    elif args.format == "xml":
        print(f"<memory_context agent=\"{args.agent}\">\n{output}\n</memory_context>")
    elif args.format == "json":
        print(json.dumps({"agent": args.agent, "context": output}))


def cmd_ask(args):
    """Ask the Librarian for information routing."""
    vfs = get_vfs(args.config, args.db)
    
    from .librarian import Librarian, PrivacyPolicy
    
    privacy = PrivacyPolicy(args.privacy)
    librarian = Librarian(vfs.store, vfs.config, privacy)
    
    response = librarian.query(args.agent, args.query, limit=args.limit)
    
    if args.json:
        print(json.dumps(response.to_dict(), indent=2, default=str))
        return
    
    print(f"Query: {args.query}")
    print(f"Requester: {args.agent}")
    print(f"Matches: {response.accessible_count}/{response.total_matches} accessible")
    print()
    
    if response.accessible:
        print("## Accessible Content")
        for node in response.accessible[:5]:
            print(f"  • {node.path}")
            if node.content:
                snippet = node.content[:100].replace("\n", " ")
                print(f"    {snippet}...")
        print()
    
    if response.suggestions:
        print("## Collaboration Suggestions")
        for s in response.suggestions[:5]:
            print(f"  • Ask **{s.agent}** about: {s.topic}")
            if s.reason:
                print(f"    ({s.reason})")
        print()


def cmd_who_knows(args):
    """Find agents who know about a topic."""
    vfs = get_vfs(args.config, args.db)
    
    from .librarian import Librarian
    
    librarian = Librarian(vfs.store, vfs.config)
    agents = librarian.who_knows(args.topic, limit=args.limit)
    
    if args.json:
        print(json.dumps([a.to_dict() for a in agents], indent=2))
        return
    
    print(f"Agents who might know about '{args.topic}':")
    for agent in agents:
        caps = ", ".join(agent.capabilities) if agent.capabilities else "general"
        print(f"  • {agent.id} ({caps}) - {agent.memory_count} memories")


def cmd_gossip(args):
    """Gossip protocol commands"""
    vfs = get_vfs(args.config, args.db)
    
    from .topic_index import TopicIndex
    from .gossip import GossipStore
    
    topic_index = TopicIndex(vfs.store)
    gossip = GossipStore(vfs.store, topic_index, args.agent)
    
    if args.gossip_action == "publish":
        digest = gossip.publish_digest()
        print(f"Published digest v{digest.version} with {len(digest.topics)} topics")
    
    elif args.gossip_action == "refresh":
        gossip.refresh()
        print(f"Refreshed. Known agents: {len(gossip.agents())}")
        for agent in gossip.agents():
            d = gossip.get_digest(agent)
            print(f"  • {agent} (v{d.version}, {len(d.topics)} topics)")
    
    elif args.gossip_action == "who-knows":
        results = gossip.who_knows(args.topic)
        if not results:
            print(f"No agents found for topic: {args.topic}")
        else:
            print(f"Agents who might know about '{args.topic}':")
            for agent, confidence in results:
                print(f"  • {agent} ({confidence:.0%} confidence)")
    
    elif args.gossip_action == "stats":
        stats = gossip.stats()
        print(f"Gossip Protocol Stats")
        print(f"=====================")
        print(f"Known agents: {stats['known_agents']}")
        print(f"Own version: {stats['own_version']}")
        print()
        for a in stats['agents']:
            print(f"  • {a['id']}: v{a['version']}, {a['topics']} topics, {a['memories']} memories, {a['age_hours']:.1f}h old")
    
    else:
        print("Usage: avm gossip {publish|refresh|who-knows|stats}")


def cmd_agents(args):
    """List all agents in the system."""
    vfs = get_vfs(args.config, args.db)
    
    from .librarian import Librarian
    
    librarian = Librarian(vfs.store, vfs.config)
    
    if args.json:
        print(json.dumps(librarian.directory(), indent=2))
        return
    
    directory = librarian.directory()
    
    print(f"Agents ({directory['total_agents']} total):")
    for agent in directory['agents']:
        caps = ", ".join(agent['capabilities']) if agent['capabilities'] else "general"
        print(f"  • {agent['id']} ({caps})")
    
    print()
    print("By Capability:")
    for cap, agent_ids in directory['by_capability'].items():
        print(f"  • {cap}: {', '.join(agent_ids)}")


def cmd_memory_stats(args):
    """Agent Memory statistics"""
    vfs = get_vfs(args.config, args.db)
    memory = vfs.agent_memory(args.agent)
    
    stats = memory.stats()
    
    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        print(f"Agent Memory: {stats['agent_id']}")
        print(f"================")
        print(f"Private memories: {stats['private_count']}")
        print(f"Shared accessible: {stats['shared_accessible']}")
        print(f"Private prefix: {stats['private_prefix']}")
        print(f"Max tokens: {stats['config']['max_tokens']}")
        print(f"Strategy: {stats['config']['strategy']}")


def cmd_semantic(args):
    """Semantic search using embedding"""
    vfs = get_vfs(args.config, args.db)

    if vfs._embedding_store is None:
        print("Embedding not enabled. Set embedding.enabled=true in config.yaml", file=sys.stderr)
        return 1

    prefix = None
    if args.agent:
        prefix = f"/memory/private/{args.agent}"

    results = vfs._embedding_store.search(args.query, k=args.limit, prefix=prefix)

    if args.json:
        print(json.dumps([
            {"path": n.path, "score": s, "snippet": n.content[:200]}
            for n, s in results
        ], indent=2))
    else:
        if not results:
            print("No results found.")
        else:
            for node, score in results:
                snippet = node.content[:100].replace("\n", " ")
                print(f"[{score:.4f}] {node.path}")
                print(f"    {snippet}...")
                print()

    return 0


def cmd_telemetry(args):
    """Show operation telemetry"""
    from .telemetry import get_telemetry
    
    telem = get_telemetry()
    
    if args.op == "stats":
        stats = telem.stats(agent=args.agent, since=args.since)
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print(f"Total operations: {stats['total_ops']}")
            print(f"Error rate: {stats['error_rate']*100:.1f}%")
            print("\nBy operation:")
            for op, data in stats['by_op'].items():
                print(f"  {op}: {data['count']} calls, avg {data['avg_latency_ms']}ms")
    else:
        entries = telem.query(
            agent=args.agent,
            op=args.op,
            since=args.since,
            limit=args.limit
        )
        
        if args.json:
            print(json.dumps(entries, indent=2))
        else:
            for e in entries:
                status = "✓" if e['success'] else "✗"
                tokens_in = str(e['tokens_in']) if e['tokens_in'] else "-"
                tokens_out = str(e['tokens_out']) if e['tokens_out'] else "-"
                tokens = f"{tokens_in:>4}/{tokens_out:<4}"
                latency = f"{e['latency_ms']:.0f}ms" if e['latency_ms'] else "-"
                print(f"{status} [{e['ts'][:19]}] {e['op']:<8} {e['agent']:<15} {tokens} {latency:>5}")


def cmd_savings(args):
    """Show token savings from recall operations"""
    from .telemetry import get_telemetry
    
    telem = get_telemetry()
    savings = telem.token_savings(agent=args.agent, since=args.since)
    
    if args.json:
        print(json.dumps(savings, indent=2))
    else:
        print("Token Savings Report")
        print("====================")
        print(f"Total recalls: {savings['recalls']}")
        print(f"Tokens returned: {savings['tokens_returned']:,}")
        print(f"Tokens available: {savings['tokens_available']:,}")
        print(f"Tokens saved: {savings['tokens_saved']:,}")
        print(f"Savings: {savings['savings_pct']}%")


def cmd_subscribe(args):
    """Subscribe to path pattern changes"""
    from .subscriptions import get_subscription_store, SubscriptionMode
    
    store = get_subscription_store()
    mode = SubscriptionMode(args.mode)
    webhook_url = getattr(args, 'webhook', None)
    
    sub = store.subscribe(
        args.agent, args.pattern, 
        mode=mode, 
        throttle_seconds=args.throttle,
        webhook_url=webhook_url,
    )
    
    if args.json:
        print(json.dumps({
            "id": sub.id, "agent": sub.agent_id, "pattern": sub.pattern,
            "mode": sub.mode.value, "throttle": sub.throttle_seconds,
            "webhook": sub.webhook_url,
        }, indent=2))
    else:
        print(f"Subscribed: {sub.agent_id} → {sub.pattern}")
        print(f"  Mode: {sub.mode.value}")
        if sub.mode == SubscriptionMode.THROTTLED:
            print(f"  Throttle: {sub.throttle_seconds}s")
        if sub.webhook_url:
            print(f"  Webhook: {sub.webhook_url}")
    return 0


def cmd_subscriptions(args):
    """List subscriptions"""
    from .subscriptions import get_subscription_store
    
    store = get_subscription_store()
    subs = store.list_subscriptions(agent_id=args.agent)
    
    if args.json:
        print(json.dumps([{
            "id": s.id, "agent": s.agent_id, "pattern": s.pattern,
            "mode": s.mode.value, "throttle": s.throttle_seconds
        } for s in subs], indent=2))
    else:
        if not subs:
            print("No subscriptions.")
            return 0
        for s in subs:
            mode_info = s.mode.value
            if s.mode.value == "throttled":
                mode_info += f" ({s.throttle_seconds}s)"
            print(f"{s.agent_id}: {s.pattern} [{mode_info}]")
    return 0


def cmd_unsubscribe(args):
    """Remove subscription"""
    from .subscriptions import get_subscription_store
    
    store = get_subscription_store()
    store.unsubscribe(args.agent, args.pattern)
    print(f"Unsubscribed: {args.agent} ← {args.pattern}")
    return 0


def cmd_pending(args):
    """Show pending notifications"""
    from .subscriptions import get_subscription_store
    
    store = get_subscription_store()
    pending = store.get_pending(args.agent, mark_delivered=args.clear)
    
    if args.json:
        print(json.dumps(pending, indent=2))
    else:
        if not pending:
            print("No pending notifications.")
            return 0
        print(f"Pending notifications for {args.agent}:")
        for p in pending:
            print(f"  [{p['timestamp'][:16]}] {p['path']}")
        if args.clear:
            print(f"\n(Marked {len(pending)} as delivered)")
    return 0


def cmd_export(args):
    """Export memories to archive"""
    import tarfile
    import io
    from datetime import datetime
    
    vfs = get_vfs(args.config, args.db)
    
    nodes = vfs.list(args.prefix, limit=10000)
    
    if args.format == "tar.gz":
        output = args.output or f"avm-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz"
        
        with tarfile.open(output, "w:gz") as tar:
            for node in nodes:
                content = (node.content or "").encode('utf-8')
                info = tarfile.TarInfo(name=node.path.lstrip('/'))
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
                
                # Also save metadata
                meta_content = json.dumps(node.meta, indent=2, default=str).encode('utf-8')
                meta_info = tarfile.TarInfo(name=node.path.lstrip('/') + '.meta.json')
                meta_info.size = len(meta_content)
                tar.addfile(meta_info, io.BytesIO(meta_content))
        
        print(f"Exported {len(nodes)} nodes to {output}")
    
    elif args.format == "jsonl":
        output = args.output or f"avm-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
        
        with open(output, 'w') as f:
            for node in nodes:
                f.write(json.dumps({
                    "path": node.path,
                    "content": node.content,
                    "meta": node.meta,
                    "version": node.version,
                }, default=str) + '\n')
        
        print(f"Exported {len(nodes)} nodes to {output}")
    
    return 0


def cmd_graph(args):
    """Generate knowledge graph visualization"""
    vfs = get_vfs(args.config, args.db)
    
    # Get starting node
    start_node = vfs.read(args.path)
    if not start_node:
        print(f"Not found: {args.path}", file=sys.stderr)
        return 1
    
    # BFS to collect connected nodes
    visited = set()
    edges = []
    queue = [(args.path, 0)]
    
    while queue:
        path, depth = queue.pop(0)
        if path in visited or depth > args.depth:
            continue
        visited.add(path)
        
        # Get links from this node
        links = vfs.store.get_links(path)
        for link in links:
            edges.append((path, link.target, link.relation))
            if link.target not in visited:
                queue.append((link.target, depth + 1))
    
    if not edges and len(visited) == 1:
        # No links, just list children
        children = vfs.list(args.path, limit=50)
        for child in children:
            if child.path != args.path:
                edges.append((args.path, child.path, "contains"))
    
    if args.format == "mermaid":
        lines = ["graph TD"]
        seen_nodes = set()
        for src, dst, rel in edges:
            src_id = src.replace("/", "_").replace(".", "_").replace("-", "_")
            dst_id = dst.replace("/", "_").replace(".", "_").replace("-", "_")
            src_label = src.split("/")[-1]
            dst_label = dst.split("/")[-1]
            if src not in seen_nodes:
                lines.append(f"    {src_id}[{src_label}]")
                seen_nodes.add(src)
            if dst not in seen_nodes:
                lines.append(f"    {dst_id}[{dst_label}]")
                seen_nodes.add(dst)
            lines.append(f"    {src_id} -->|{rel}| {dst_id}")
        print('\n'.join(lines))
    
    elif args.format == "dot":
        lines = ["digraph G {"]
        for src, dst, rel in edges:
            lines.append(f'    "{src}" -> "{dst}" [label="{rel}"];')
        lines.append("}")
        print('\n'.join(lines))
    
    else:  # text
        print(f"Graph from {args.path} (depth {args.depth}):")
        print(f"Nodes: {len(visited)}")
        print(f"Edges: {len(edges)}")
        for src, dst, rel in edges:
            print(f"  {src} --[{rel}]--> {dst}")
    
    return 0


def cmd_bundle(args):
    """Bundle related memories for handoff"""
    from datetime import datetime, timedelta
    
    vfs = get_vfs(args.config, args.db)
    
    # Calculate since date
    if args.since:
        if args.since.endswith('d'):
            days = int(args.since[:-1])
            since_dt = datetime.now() - timedelta(days=days)
        else:
            since_dt = datetime.fromisoformat(args.since)
    else:
        since_dt = datetime.now() - timedelta(days=7)
    
    # Find all nodes under prefix
    nodes = vfs.list(args.prefix, limit=500)
    
    # Filter by date
    filtered = []
    for node in nodes:
        if node.updated_at and node.updated_at >= since_dt:
            filtered.append(node)
    
    # Sort by date
    filtered.sort(key=lambda n: n.updated_at or datetime.min)
    
    if args.json:
        print(json.dumps([{
            "path": n.path,
            "updated_at": n.updated_at.isoformat() if n.updated_at else None,
            "content": n.content[:500] if n.content else "",
            "meta": n.meta,
        } for n in filtered], indent=2, default=str))
    else:
        # Generate markdown handoff document
        lines = [
            f"# Task Bundle: {args.prefix}",
            f"Generated: {datetime.now().isoformat()[:16]}",
            f"Since: {since_dt.isoformat()[:10]}",
            f"Items: {len(filtered)}",
            "",
            "---",
            "",
        ]
        
        for node in filtered:
            date_str = node.updated_at.strftime("%Y-%m-%d %H:%M") if node.updated_at else "?"
            lines.append(f"## {node.path}")
            lines.append(f"*Updated: {date_str}*")
            lines.append("")
            # Include content (truncated)
            content = node.content or ""
            if len(content) > 1000:
                content = content[:1000] + "\n\n*[truncated...]*"
            lines.append(content)
            lines.append("")
            lines.append("---")
            lines.append("")
        
        print('\n'.join(lines))
    return 0


def cmd_restore(args):
    """Restore a file from trash"""
    vfs = get_vfs(args.config, args.db)
    
    restored = vfs.restore(args.path)
    if restored:
        print(f"Restored: {restored.path}")
        return 0
    else:
        print(f"Not found or restore failed: {args.path}", file=sys.stderr)
        return 1


def cmd_trash(args):
    """List or empty trash"""
    vfs = get_vfs(args.config, args.db)
    
    trash_items = vfs.list("/trash", limit=100)
    
    if args.empty:
        for item in trash_items:
            vfs.delete(item.path, hard=True)
        print(f"Emptied {len(trash_items)} items from trash")
        return 0
    
    if not trash_items:
        print("Trash is empty")
        return 0
    
    print(f"Trash ({len(trash_items)} items):")
    for item in trash_items:
        deleted_at = item.meta.get('deleted_at', '?')[:16]
        original = item.meta.get('original_path', item.path.replace('/trash', '', 1))
        print(f"  [{deleted_at}] {original}")
    return 0


def cmd_cold(args):
    """Show cold (decayed) memories"""
    from .advanced import MemoryDecay
    
    vfs = get_vfs(args.config, args.db)
    decay = MemoryDecay(vfs.store, half_life_days=args.half_life)
    
    cold = decay.get_cold_memories(
        prefix=args.prefix,
        threshold=args.threshold,
        limit=args.limit
    )
    
    if args.json:
        print(json.dumps([n.to_dict() for n in cold], indent=2, default=str))
    else:
        if not cold:
            print("No cold memories found.")
            return 0
        print(f"Cold memories (importance × decay < {args.threshold}):")
        print()
        for node in cold:
            importance = node.meta.get("importance", 0.5)
            decay_factor = decay.calculate_decay(node)
            score = importance * decay_factor
            print(f"  {node.path}")
            print(f"    importance={importance:.2f} × decay={decay_factor:.2f} = {score:.3f}")
            print()
    return 0


def cmd_compact(args):
    """Compact old versions of a memory"""
    from .advanced import MemoryCompactor
    
    vfs = get_vfs(args.config, args.db)
    compactor = MemoryCompactor(vfs.store)
    
    result = compactor.compact(args.path, keep_recent=args.keep)
    
    if args.json:
        print(json.dumps({
            "base_path": result.base_path,
            "versions_before": result.versions_before,
            "versions_after": result.versions_after,
            "summary_path": result.summary_path,
            "removed_paths": result.removed_paths,
        }, indent=2))
    else:
        print(f"Compacted: {result.base_path}")
        print(f"  Versions: {result.versions_before} → {result.versions_after}")
        if result.summary_path:
            print(f"  Summary: {result.summary_path}")
        if result.removed_paths:
            print(f"  Removed: {len(result.removed_paths)} versions")
    return 0


def cmd_dedupe(args):
    """Check for duplicate content"""
    from .advanced import SemanticDeduplicator
    
    vfs = get_vfs(args.config, args.db)
    deduper = SemanticDeduplicator(vfs.store)
    
    # Read content
    if args.file:
        content = Path(args.file).read_text()
    elif args.content:
        content = args.content
    else:
        content = sys.stdin.read()
    
    result = deduper.check_duplicate(content, prefix=args.prefix, threshold=args.threshold)
    
    if args.json:
        print(json.dumps({
            "is_duplicate": result.is_duplicate,
            "similar_path": result.similar_path,
            "similarity": result.similarity,
            "method": result.method,
        }, indent=2))
    else:
        if result.is_duplicate:
            print(f"DUPLICATE detected!")
            print(f"  Similar to: {result.similar_path}")
            print(f"  Similarity: {result.similarity:.1%}")
            print(f"  Method: {result.method}")
        else:
            print("No duplicates found.")
    return 0


def cmd_archive(args):
    """Archive cold memories to /archive/"""
    from .advanced import MemoryDecay
    
    vfs = get_vfs(args.config, args.db)
    decay = MemoryDecay(vfs.store, half_life_days=args.half_life)
    
    cold = decay.get_cold_memories(
        prefix=args.prefix,
        threshold=args.threshold,
        limit=args.limit
    )
    
    if not cold:
        print("No cold memories to archive.")
        return 0
    
    if args.dry_run:
        print(f"Would archive {len(cold)} memories:")
        for node in cold:
            archive_path = node.path.replace("/memory/", "/archive/", 1)
            print(f"  {node.path} → {archive_path}")
        return 0
    
    archived = []
    for node in cold:
        archive_path = node.path.replace("/memory/", "/archive/", 1)
        # Write to archive
        vfs.write(archive_path, node.content, meta=node.meta)
        # Delete original
        vfs.store.delete_node(node.path)
        archived.append((node.path, archive_path))
    
    if args.json:
        print(json.dumps({"archived": archived}, indent=2))
    else:
        print(f"Archived {len(archived)} memories:")
        for src, dst in archived:
            print(f"  {src} → {dst}")
    return 0


def cmd_cluster(args):
    """Cluster memories by topic similarity"""
    from .consolidation import MemoryConsolidator, ConsolidationConfig
    from .topic_index import TopicIndex
    
    vfs = get_vfs(args.config, args.db)
    agent_id = args.agent or vfs.agent_id
    
    config = ConsolidationConfig(
        min_cluster_size=args.min_size,
        max_clusters=args.max_clusters,
    )
    
    topic_index = TopicIndex(vfs.store)
    consolidator = MemoryConsolidator(vfs.store, topic_index, config)
    
    # Get memories
    prefix = f"/memory/private/{agent_id}" if agent_id else "/memory"
    memories = consolidator._get_memories(prefix)
    
    # Cluster
    clusters = consolidator.cluster_memories(memories)
    
    if not clusters:
        print("No clusters found (need more memories or higher topic diversity).")
        return 0
    
    if args.json:
        print(json.dumps([{
            "id": c.id,
            "topic": c.topic,
            "size": len(c.memories),
            "avg_importance": c.avg_importance,
            "topics": list(c.centroid_topics)[:10],
            "memories": c.memories[:5],
        } for c in clusters], indent=2))
    else:
        print(f"Found {len(clusters)} clusters:\n")
        for c in clusters:
            print(f"  📁 {c.topic.upper()} ({len(c.memories)} memories)")
            print(f"     Importance: {c.avg_importance:.2f}")
            print(f"     Topics: {', '.join(sorted(c.centroid_topics)[:5])}")
            for p in c.memories[:3]:
                print(f"       - {p}")
            print()
    
    # Generate summaries if requested
    if args.summarize:
        created = consolidator.generate_cluster_summaries(clusters)
        print(f"\n✅ Created {created} cluster summaries in /memory/clusters/")
    
    return 0


def cmd_consolidate(args):
    """Run full memory consolidation"""
    from .consolidation import MemoryConsolidator, ConsolidationConfig
    from .topic_index import TopicIndex
    
    vfs = get_vfs(args.config, args.db)
    agent_id = args.agent or vfs.agent_id
    
    topic_index = TopicIndex(vfs.store)
    consolidator = MemoryConsolidator(vfs.store, topic_index)
    
    result = consolidator.run(agent_id=agent_id, dry_run=args.dry_run)
    
    if args.json:
        print(json.dumps({
            "processed": result.memories_processed,
            "decayed": result.importance_decayed,
            "merged": result.memories_merged,
            "summaries": result.summaries_created,
            "duration_ms": result.duration_ms,
            "dry_run": args.dry_run,
        }, indent=2))
    else:
        print(f"Memory Consolidation {'(dry-run)' if args.dry_run else ''}:")
        print(f"  Memories processed: {result.memories_processed}")
        print(f"  Importance decayed: {result.importance_decayed}")
        print(f"  Memories merged:    {result.memories_merged}")
        print(f"  Summaries created:  {result.summaries_created}")
        print(f"  Duration:           {result.duration_ms:.1f}ms")
    
    return 0


def _cmd_serve(args):
    """Start HTTP API server."""
    import os
    os.environ.setdefault("AVM_AGENT", args.agent)
    # Patch sys.argv so api_server.main() sees the right args
    sys.argv = ["avm-serve", "--agent", args.agent, "--host", args.host, "--port", str(args.port)]
    from .api_server import main as serve_main
    serve_main()


def cmd_digest(args):
    """Generate memory digest"""
    from .consolidation import generate_digest
    from .topic_index import TopicIndex
    
    vfs = get_vfs(args.config, args.db)
    agent_id = args.agent or vfs.agent_id
    
    topic_index = TopicIndex(vfs.store)
    
    digest = generate_digest(
        store=vfs.store,
        topic_index=topic_index,
        agent_id=agent_id,
        days=args.days,
        max_items=args.max_items,
    )
    
    if args.output:
        with open(args.output, "w") as f:
            f.write(digest)
        print(f"Digest saved to {args.output}")
    else:
        print(digest)
    
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="AI Virtual Filesystem (config-driven)",
        prog="vfs"
    )
    parser.add_argument("--config", "-c", help="Config file path")
    parser.add_argument("--db", help="Database path override")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # read
    p_read = subparsers.add_parser("read", help="Read a node")
    p_read.add_argument("path", help="Node path")
    p_read.add_argument("--refresh", "-r", action="store_true", help="Force refresh")
    p_read.add_argument("--meta", "-m", action="store_true", help="Show metadata")
    p_read.add_argument("--as-of", help="Read as of timestamp (ISO format, time travel)")
    p_read.add_argument("--version", "-v", type=int, help="Read specific version")
    p_read.set_defaults(func=cmd_read)
    
    # write
    p_write = subparsers.add_parser("write", help="Write a node")
    p_write.add_argument("path", help="Node path")
    p_write.add_argument("--content", "-c", help="Content to write")
    p_write.add_argument("--file", "-f", help="Read content from file")
    p_write.add_argument("--meta", "-m", help="Metadata as JSON")
    p_write.set_defaults(func=cmd_write)
    
    # delete
    p_delete = subparsers.add_parser("delete", help="Delete a node")
    p_delete.add_argument("path", help="Node path")
    p_delete.set_defaults(func=cmd_delete)

    # mv / move / rename
    p_mv = subparsers.add_parser("mv", aliases=["move", "rename"], help="Move/rename a node or prefix tree")
    p_mv.add_argument("src", help="Source path (use trailing / for prefix move)")
    p_mv.add_argument("dst", help="Destination path")
    p_mv.set_defaults(func=cmd_mv)

    # list
    p_list = subparsers.add_parser("list", help="List nodes")
    p_list.add_argument("prefix", nargs="?", default="/", help="Path prefix")
    p_list.add_argument("--limit", "-n", type=int, default=100, help="Max results")
    p_list.set_defaults(func=cmd_list)
    
    # links
    p_links = subparsers.add_parser("links", help="Show node links")
    p_links.add_argument("path", help="Node path")
    p_links.add_argument("--direction", "-d", choices=["in", "out", "both"], default="both")
    p_links.set_defaults(func=cmd_links)
    
    # link (add)
    p_link = subparsers.add_parser("link", help="Add a link")
    p_link.add_argument("source", help="Source path")
    p_link.add_argument("target", help="Target path")
    p_link.add_argument("--type", "-t", default="related", 
                        choices=["peer", "parent", "citation", "derived", "related"])
    p_link.add_argument("--weight", "-w", type=float, default=1.0)
    p_link.set_defaults(func=cmd_link)
    
    # search
    p_search = subparsers.add_parser("search", help="Full-text search")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--limit", "-n", type=int, default=10)
    p_search.set_defaults(func=cmd_search)
    
    # history
    p_history = subparsers.add_parser("history", help="Show change history")
    p_history.add_argument("path", help="Node path")
    p_history.add_argument("--limit", "-n", type=int, default=10)
    p_history.add_argument("--verbose", "-v", action="store_true")
    p_history.set_defaults(func=cmd_history)
    
    # stats
    p_stats = subparsers.add_parser("stats", help="Show storage stats")
    p_stats.set_defaults(func=cmd_stats)
    
    # warmup - pre-load embedding model
    p_warmup = subparsers.add_parser("warmup", help="Pre-load embedding model for faster recall")
    p_warmup.set_defaults(func=cmd_warmup)
    

    
    # refresh
    p_refresh = subparsers.add_parser("refresh", help="Refresh live nodes")
    p_refresh.add_argument("path", nargs="?", help="Path to refresh")
    p_refresh.add_argument("--all", "-a", action="store_true", help="Refresh all")
    p_refresh.set_defaults(func=cmd_refresh)
    
    # config
    p_config = subparsers.add_parser("config", help="Show configuration")
    p_config.set_defaults(func=cmd_config)
    
    # retrieve (Linked retrieval)
    p_retrieve = subparsers.add_parser("retrieve", help="Linked retrieval")
    p_retrieve.add_argument("query", help="Search query")
    p_retrieve.add_argument("--limit", "-n", type=int, default=5)
    p_retrieve.add_argument("--depth", "-d", type=int, default=1, help="Graph expansion depth")
    p_retrieve.add_argument("--no-graph", action="store_true", help="Disable graph expansion")
    p_retrieve.set_defaults(func=cmd_retrieve)
    
    # synthesize (dynamic document)
    p_synth = subparsers.add_parser("synthesize", aliases=["synth"], help="Generate dynamic document")
    p_synth.add_argument("query", help="Query topic")
    p_synth.add_argument("--limit", "-n", type=int, default=5)
    p_synth.add_argument("--title", "-t", help="Document title")
    p_synth.set_defaults(func=cmd_synthesize)
    
    # memory recall
    p_mem_recall = subparsers.add_parser("memory-recall", aliases=["recall"], 
                                          help="Agent memory recall")
    p_mem_recall.add_argument("query", help="Query")
    p_mem_recall.add_argument("--agent", "-a", default="default", help="Agent ID")
    p_mem_recall.add_argument("--max-tokens", "-t", type=int, default=4000)
    p_mem_recall.add_argument("--strategy", "-s", 
                              choices=["importance", "recency", "relevance", "balanced"])
    p_mem_recall.add_argument("--private-only", action="store_true")
    p_mem_recall.add_argument("--verbose", "-v", action="store_true", 
                              help="Show progress bars and warnings (default: quiet)")
    p_mem_recall.add_argument("--min-relevance", "-r", type=float, default=0.3,
                              help="Min relevance score (0-1), filters noise (default: 0.3)")
    p_mem_recall.set_defaults(func=cmd_memory_recall)
    
    # memory remember
    p_mem_write = subparsers.add_parser("memory-remember", aliases=["remember"],
                                         help="Write to agent memory")
    p_mem_write.add_argument("--agent", "-a", default="default", help="Agent ID")
    p_mem_write.add_argument("--content", "-c", help="Content")
    p_mem_write.add_argument("--file", "-f", help="Read from file")
    p_mem_write.add_argument("--title", "-t", help="Memory title")
    p_mem_write.add_argument("--importance", "-i", type=float, default=0.5)
    p_mem_write.add_argument("--tags", help="Comma-separated tags")
    p_mem_write.set_defaults(func=cmd_memory_remember)
    
    # context (for prompt injection)
    p_context = subparsers.add_parser("context", help="Generate memory context for prompts")
    p_context.add_argument("--agent", "-a", default="default", help="Agent ID")
    p_context.add_argument("--query", "-q", help="Custom query to include")
    p_context.add_argument("--preferences", "-p", action="store_true", help="Include user preferences")
    p_context.add_argument("--lessons", "-l", action="store_true", help="Include lessons learned")
    p_context.add_argument("--format", "-f", choices=["markdown", "xml", "json"], default="markdown")
    p_context.add_argument("--recent-tokens", type=int, default=300, help="Tokens for recent activity")
    p_context.add_argument("--pref-tokens", type=int, default=200, help="Tokens for preferences")
    p_context.add_argument("--lesson-tokens", type=int, default=200, help="Tokens for lessons")
    p_context.add_argument("--query-tokens", type=int, default=300, help="Tokens for custom query")
    p_context.add_argument("--quiet", action="store_true", help="No stderr output")
    p_context.set_defaults(func=cmd_context)
    
    # Librarian: ask
    p_ask = subparsers.add_parser("ask", help="Ask the Librarian for information routing")
    p_ask.add_argument("query", help="Query to ask")
    p_ask.add_argument("--agent", "-a", default="default", help="Requester agent ID")
    p_ask.add_argument("--limit", "-n", type=int, default=10, help="Max results")
    p_ask.add_argument("--privacy", "-p", choices=["full", "owner", "existence", "none"], 
                       default="owner", help="Privacy level for suggestions")
    p_ask.set_defaults(func=cmd_ask)
    
    # Librarian: who-knows
    p_who = subparsers.add_parser("who-knows", help="Find agents who know about a topic")
    p_who.add_argument("topic", help="Topic to search")
    p_who.add_argument("--limit", "-n", type=int, default=5, help="Max agents to return")
    p_who.set_defaults(func=cmd_who_knows)
    
    # Librarian: agents
    p_agents = subparsers.add_parser("agents", help="List all agents and their capabilities")
    p_agents.set_defaults(func=cmd_agents)
    
    # Gossip protocol
    p_gossip = subparsers.add_parser("gossip", help="Gossip protocol for decentralized discovery")
    p_gossip_sub = p_gossip.add_subparsers(dest="gossip_action")
    
    p_gossip_publish = p_gossip_sub.add_parser("publish", help="Publish own digest")
    p_gossip_publish.add_argument("--agent", "-a", default="default", help="Agent ID")
    
    p_gossip_refresh = p_gossip_sub.add_parser("refresh", help="Refresh known digests")
    p_gossip_refresh.add_argument("--agent", "-a", default="default", help="Agent ID")
    
    p_gossip_who = p_gossip_sub.add_parser("who-knows", help="Find agents who know a topic")
    p_gossip_who.add_argument("topic", help="Topic to search")
    p_gossip_who.add_argument("--agent", "-a", default="default", help="Agent ID")
    
    p_gossip_stats = p_gossip_sub.add_parser("stats", help="Show gossip stats")
    p_gossip_stats.add_argument("--agent", "-a", default="default", help="Agent ID")
    
    p_gossip.set_defaults(func=cmd_gossip)
    
    # memory stats
    p_mem_stats = subparsers.add_parser("memory-stats", help="Agent memory stats")
    p_mem_stats.add_argument("--agent", "-a", default="default", help="Agent ID")
    p_mem_stats.set_defaults(func=cmd_memory_stats)
    
    # semantic search
    p_semantic = subparsers.add_parser("semantic", help="Semantic search (embedding)")
    p_semantic.add_argument("query", help="Search query")
    p_semantic.add_argument("--limit", "-n", type=int, default=10)
    p_semantic.add_argument("--agent", "-a", help="Agent context (search within agent prefix)")
    p_semantic.set_defaults(func=cmd_semantic)

    # Telemetry commands
    p_telemetry = subparsers.add_parser("telemetry", aliases=["telem"], help="Show operation telemetry")
    p_telemetry.add_argument("--agent", "-a", help="Filter by agent")
    p_telemetry.add_argument("--op", help="Filter by operation (recall, remember)")
    p_telemetry.add_argument("--since", help="Filter since timestamp (ISO format)")
    p_telemetry.add_argument("--limit", "-n", type=int, default=20, help="Max entries")
    p_telemetry.set_defaults(func=cmd_telemetry)
    
    p_savings = subparsers.add_parser("savings", help="Show token savings from recall")
    p_savings.add_argument("--agent", "-a", help="Filter by agent")
    p_savings.add_argument("--since", help="Filter since timestamp (ISO format)")
    p_savings.set_defaults(func=cmd_savings)
    
    # subscribe command
    p_subscribe = subparsers.add_parser("subscribe", help="Subscribe to path pattern changes")
    p_subscribe.add_argument("pattern", help="Path pattern (e.g., /memory/shared/*)")
    p_subscribe.add_argument("--agent", "-a", required=True, help="Agent ID")
    p_subscribe.add_argument("--mode", "-m", default="batched", 
                             choices=["realtime", "throttled", "batched", "digest"],
                             help="Notification mode")
    p_subscribe.add_argument("--throttle", "-t", type=int, default=60, help="Throttle window (seconds)")
    p_subscribe.add_argument("--webhook", "-w", help="Webhook URL for push notifications")
    p_subscribe.set_defaults(func=cmd_subscribe)
    
    # subscriptions list
    p_subs_list = subparsers.add_parser("subscriptions", help="List subscriptions")
    p_subs_list.add_argument("--agent", "-a", help="Filter by agent")
    p_subs_list.set_defaults(func=cmd_subscriptions)
    
    # unsubscribe
    p_unsub = subparsers.add_parser("unsubscribe", help="Remove subscription")
    p_unsub.add_argument("pattern", help="Path pattern")
    p_unsub.add_argument("--agent", "-a", required=True, help="Agent ID")
    p_unsub.set_defaults(func=cmd_unsubscribe)
    
    # pending notifications
    p_pending = subparsers.add_parser("pending", help="Show pending notifications")
    p_pending.add_argument("--agent", "-a", required=True, help="Agent ID")
    p_pending.add_argument("--clear", action="store_true", help="Mark as delivered")
    p_pending.set_defaults(func=cmd_pending)
    
    # export
    p_export = subparsers.add_parser("export", help="Export memories to archive")
    p_export.add_argument("prefix", help="Path prefix to export (e.g., /memory)")
    p_export.add_argument("--output", "-o", help="Output file path")
    p_export.add_argument("--format", "-f", default="tar.gz", choices=["tar.gz", "jsonl"])
    p_export.set_defaults(func=cmd_export)
    
    # graph visualization
    p_graph = subparsers.add_parser("graph", help="Generate knowledge graph")
    p_graph.add_argument("path", help="Starting path")
    p_graph.add_argument("--depth", "-d", type=int, default=2, help="Max depth")
    p_graph.add_argument("--format", "-f", default="mermaid", choices=["mermaid", "dot", "text"])
    p_graph.set_defaults(func=cmd_graph)
    
    # bundle for handoff
    p_bundle = subparsers.add_parser("bundle", help="Bundle related memories for handoff")
    p_bundle.add_argument("prefix", help="Path prefix (e.g., /task/project-x)")
    p_bundle.add_argument("--since", "-s", default="7d", help="Since when (e.g., 7d, 2026-03-15)")
    p_bundle.set_defaults(func=cmd_bundle)
    
    # restore from trash
    p_restore = subparsers.add_parser("restore", help="Restore file from trash")
    p_restore.add_argument("path", help="Path in /trash/")
    p_restore.set_defaults(func=cmd_restore)
    
    # trash management
    p_trash = subparsers.add_parser("trash", help="List or empty trash")
    p_trash.add_argument("--empty", action="store_true", help="Empty trash permanently")
    p_trash.set_defaults(func=cmd_trash)
    
    # cold memories (decayed below threshold)
    p_cold = subparsers.add_parser("cold", help="Show cold (decayed) memories")
    p_cold.add_argument("--prefix", default="/memory", help="Path prefix to scan")
    p_cold.add_argument("--threshold", "-t", type=float, default=0.1, help="Decay threshold")
    p_cold.add_argument("--half-life", type=float, default=7.0, help="Half-life in days")
    p_cold.add_argument("--limit", "-n", type=int, default=20, help="Max results")
    p_cold.set_defaults(func=cmd_cold)
    
    # compact old versions
    p_compact = subparsers.add_parser("compact", help="Compact old versions into summary")
    p_compact.add_argument("path", help="Base path to compact")
    p_compact.add_argument("--keep", "-k", type=int, default=3, help="Keep N recent versions")
    p_compact.set_defaults(func=cmd_compact)
    
    # dedupe check
    p_dedupe = subparsers.add_parser("dedupe", help="Check for duplicate content")
    p_dedupe.add_argument("--content", "-c", help="Content to check")
    p_dedupe.add_argument("--file", "-f", help="Read content from file")
    p_dedupe.add_argument("--prefix", default="/memory", help="Path prefix to search")
    p_dedupe.add_argument("--threshold", "-t", type=float, default=0.8, help="Similarity threshold")
    p_dedupe.set_defaults(func=cmd_dedupe)
    
    # archive cold memories
    p_archive = subparsers.add_parser("archive", help="Archive cold memories")
    p_archive.add_argument("--prefix", default="/memory", help="Path prefix to scan")
    p_archive.add_argument("--threshold", "-t", type=float, default=0.1, help="Decay threshold")
    p_archive.add_argument("--half-life", type=float, default=7.0, help="Half-life in days")
    p_archive.add_argument("--limit", "-n", type=int, default=100, help="Max to archive")
    p_archive.add_argument("--dry-run", action="store_true", help="Show what would be archived")
    p_archive.set_defaults(func=cmd_archive)
    
    # cluster memories
    p_cluster = subparsers.add_parser("cluster", help="Cluster memories by topic similarity")
    p_cluster.add_argument("--agent", "-a", help="Agent ID (default: from config)")
    p_cluster.add_argument("--min-size", type=int, default=3, help="Minimum cluster size")
    p_cluster.add_argument("--max-clusters", type=int, default=20, help="Maximum clusters")
    p_cluster.add_argument("--summarize", "-s", action="store_true", help="Generate summaries")
    p_cluster.set_defaults(func=cmd_cluster)
    
    # consolidate memories
    p_consolidate = subparsers.add_parser("consolidate", help="Run memory consolidation")
    p_consolidate.add_argument("--agent", "-a", help="Agent ID (default: from config)")
    p_consolidate.add_argument("--dry-run", action="store_true", help="Preview without modifying")
    p_consolidate.set_defaults(func=cmd_consolidate)
    
    # digest - generate memory summary
    p_digest = subparsers.add_parser("digest", help="Generate memory digest/summary")
    p_digest.add_argument("--agent", "-a", help="Agent ID (default: from config)")
    p_digest.add_argument("--days", "-d", type=int, default=1, help="Days to look back (default: 1)")
    p_digest.add_argument("--max-items", "-n", type=int, default=10, help="Max items per category")
    p_digest.add_argument("--output", "-o", help="Save to file instead of stdout")
    p_digest.set_defaults(func=cmd_digest)

    # serve - HTTP API server (for Docker / Windows / no-FUSE environments)
    p_serve = subparsers.add_parser("serve", help="Start HTTP API server (no FUSE required)")
    p_serve.add_argument("--agent", default="default", help="Agent ID")
    p_serve.add_argument("--host", default="0.0.0.0", help="Bind host")
    p_serve.add_argument("--port", type=int, default=8765, help="Port")
    p_serve.set_defaults(func=lambda a: _cmd_serve(a))

    args = parser.parse_args()
    
    # On Windows, FUSE-related commands are not supported
    FUSE_COMMANDS = {"mount", "unmount", "daemon"}
    if IS_WINDOWS and getattr(args, "command", None) in FUSE_COMMANDS:
        print(
            f"Error: '{args.command}' is not supported on Windows (FUSE unavailable).\n"
            "Use 'avm serve' to start the HTTP API server and access memories via HTTP.",
            file=sys.stderr,
        )
        return 1

    try:
        return args.func(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.json:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
