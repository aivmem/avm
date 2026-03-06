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


def cmd_import(args):
    """importfile"""
    from .tools import VFSImporter
    
    vfs = get_vfs(args.config, args.db)
    importer = VFSImporter(vfs.store)
    source = Path(args.source)
    
    if source.is_file():
        node = importer.import_file(str(source), f"{args.prefix}/{source.name}")
        print(f"Imported: {node.path}")
    elif source.is_dir():
        nodes = importer.import_directory(
            str(source),
            args.prefix,
            pattern=args.pattern,
            flatten=args.flatten,
        )
        print(f"Imported {len(nodes)} files")
        for node in nodes:
            print(f"  {node.path}")
    else:
        print(f"Not found: {source}", file=sys.stderr)
        return 1
    
    return 0


def cmd_export(args):
    """exportnode"""
    from .tools import VFSExporter
    
    vfs = get_vfs(args.config, args.db)
    exporter = VFSExporter(vfs.store)
    
    if args.format == "json":
        data = exporter.export_to_json(args.prefix, args.output)
        if not args.output:
            print(json.dumps(data, indent=2, default=str))
        else:
            print(f"Exported {len(data)} nodes to {args.output}")
    else:
        if not args.output:
            print("Error: --output required for files format", file=sys.stderr)
            return 1
        count = exporter.export_to_directory(args.prefix, args.output)
        print(f"Exported {count} files to {args.output}")
    
    return 0


def cmd_autolink(args):
    """auto-discoverrelation"""
    from .tools import RelationBuilder
    
    vfs = get_vfs(args.config, args.db)
    builder = RelationBuilder(vfs.store)
    
    total = 0
    
    if args.by in ("symbol", "all"):
        count = builder.auto_link_by_symbol(args.prefix)
        print(f"Symbol-based links: {count}")
        total += count
    
    if args.by in ("tag", "all"):
        count = builder.link_by_tags()
        print(f"Tag-based links: {count}")
        total += count
    
    print(f"Total links added: {total}")
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
    
    # import
    p_import = subparsers.add_parser("import", help="Import files")
    p_import.add_argument("source", help="Local file or directory")
    p_import.add_argument("--prefix", "-p", default="/research", help="VFS path prefix")
    p_import.add_argument("--pattern", default="**/*.md", help="Glob pattern")
    p_import.add_argument("--flatten", action="store_true", help="Flatten directory")
    p_import.set_defaults(func=cmd_import)
    
    # export
    p_export = subparsers.add_parser("export", help="Export nodes")
    p_export.add_argument("prefix", nargs="?", default="/", help="Path prefix")
    p_export.add_argument("--output", "-o", help="Output path")
    p_export.add_argument("--format", "-f", choices=["json", "files"], default="json")
    p_export.set_defaults(func=cmd_export)
    
    # auto-link
    p_autolink = subparsers.add_parser("auto-link", help="Auto-discover relationships")
    p_autolink.add_argument("--prefix", "-p", default="/", help="Path prefix")
    p_autolink.add_argument("--by", choices=["symbol", "tag", "all"], default="all")
    p_autolink.set_defaults(func=cmd_autolink)
    
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
