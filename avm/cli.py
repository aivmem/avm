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
from pathlib import Path
from typing import Optional

from .core import AVM
from .config import load_config
from .node import AVMNode, NodeType
from .graph import EdgeType

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


def cmd_stats(args):
    """storagestatistics"""
    vfs = get_vfs(args.config, args.db)
    
    stats = vfs.stats()
    
    if args.json:
        print(json.dumps(stats, indent=2))
    else:
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
    from .agent_memory import ScoringStrategy
    
    vfs = get_vfs(args.config, args.db)
    memory = vfs.agent_memory(args.agent)
    
    strategy = ScoringStrategy(args.strategy) if args.strategy else None
    
    result = memory.recall(
        args.query,
        max_tokens=args.max_tokens,
        strategy=strategy,
        include_shared=not args.private_only,
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
    sub = store.subscribe(args.agent, args.pattern, mode=mode, throttle_seconds=args.throttle)
    
    if args.json:
        print(json.dumps({
            "id": sub.id, "agent": sub.agent_id, "pattern": sub.pattern,
            "mode": sub.mode.value, "throttle": sub.throttle_seconds
        }, indent=2))
    else:
        print(f"Subscribed: {sub.agent_id} → {sub.pattern}")
        print(f"  Mode: {sub.mode.value}")
        if sub.mode == SubscriptionMode.THROTTLED:
            print(f"  Throttle: {sub.throttle_seconds}s")
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
    
    args = parser.parse_args()
    
    try:
        return args.func(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.json:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
