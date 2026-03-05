#!/usr/bin/env python3
"""
vfs/cli.py - VFS命令行接口

用法:
    vfs read /research/MSFT.md
    vfs write /memory/lesson.md --content "今天学到..."
    vfs links /research/MSFT.md
    vfs search "能源板块超卖"
    vfs stats
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .store import VFSStore
from .node import VFSNode, NodeType
from .graph import EdgeType


def get_store(db_path: Optional[str] = None) -> VFSStore:
    """获取存储实例"""
    return VFSStore(db_path)


def _load_alpaca_env():
    """加载 Alpaca 配置"""
    env_path = Path.home() / ".openclaw" / "workspace" / "trading" / ".env"
    if env_path.exists():
        return dict(
            line.split("=", 1) 
            for line in env_path.read_text().splitlines() 
            if "=" in line
        )
    return None


def _get_provider(store, path, force_refresh=False):
    """根据路径获取对应的 provider 并获取节点"""
    from .providers import (
        AlpacaPositionsProvider, AlpacaOrdersProvider,
        TechnicalIndicatorsProvider, NewsProvider
    )
    
    # Alpaca positions
    if path.startswith("/live/positions"):
        env = _load_alpaca_env()
        if not env:
            return None, "Alpaca credentials not found"
        provider = AlpacaPositionsProvider(
            store,
            api_key=env.get("ALPACA_API_KEY", ""),
            secret_key=env.get("ALPACA_SECRET_KEY", ""),
            base_url=env.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        )
        return provider.get(path, force_refresh=force_refresh), None
    
    # Alpaca orders
    if path.startswith("/live/orders"):
        env = _load_alpaca_env()
        if not env:
            return None, "Alpaca credentials not found"
        provider = AlpacaOrdersProvider(
            store,
            api_key=env.get("ALPACA_API_KEY", ""),
            secret_key=env.get("ALPACA_SECRET_KEY", ""),
            base_url=env.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        )
        return provider.get(path, force_refresh=force_refresh), None
    
    # Technical indicators
    if path.startswith("/live/indicators"):
        provider = TechnicalIndicatorsProvider(store)
        return provider.get(path, force_refresh=force_refresh), None
    
    # News
    if path.startswith("/live/news"):
        provider = NewsProvider(store)
        return provider.get(path, force_refresh=force_refresh), None
    
    # Watchlist
    if path.startswith("/live/watchlist"):
        from .providers import WatchlistProvider
        provider = WatchlistProvider(store)
        return provider.get(path, force_refresh=force_refresh), None
    
    # Default: direct store access
    return store.get_node(path), None


def cmd_read(args):
    """读取节点"""
    store = get_store(args.db)
    path = args.path
    
    node, error = _get_provider(store, path, force_refresh=args.refresh)
    
    if error:
        print(f"Error: {error}", file=sys.stderr)
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
    """写入节点"""
    store = get_store(args.db)
    path = args.path
    
    # 检查权限
    if not path.startswith("/memory"):
        print(f"Error: Cannot write to {path} (only /memory/* is writable)", file=sys.stderr)
        return 1
    
    # 获取内容
    if args.content:
        content = args.content
    elif args.file:
        content = Path(args.file).read_text()
    else:
        content = sys.stdin.read()
    
    # 解析元数据
    meta = {}
    if args.meta:
        meta = json.loads(args.meta)
    
    node = VFSNode(
        path=path,
        content=content,
        meta=meta,
        node_type=NodeType.FILE,
    )
    
    saved = store.put_node(node)
    
    if args.json:
        print(json.dumps(saved.to_dict(), indent=2, default=str))
    else:
        print(f"Saved: {saved.path} (v{saved.version})")
    
    return 0


def cmd_delete(args):
    """删除节点"""
    store = get_store(args.db)
    path = args.path
    
    if not path.startswith("/memory"):
        print(f"Error: Cannot delete {path} (only /memory/* is deletable)", file=sys.stderr)
        return 1
    
    if store.delete_node(path):
        print(f"Deleted: {path}")
        return 0
    else:
        print(f"Not found: {path}", file=sys.stderr)
        return 1


def cmd_list(args):
    """列出节点"""
    store = get_store(args.db)
    
    nodes = store.list_nodes(args.prefix, limit=args.limit)
    
    if args.json:
        print(json.dumps([n.to_dict() for n in nodes], indent=2, default=str))
    else:
        for node in nodes:
            size = len(node.content)
            print(f"{node.path}\tv{node.version}\t{size}B\t{node.updated_at.strftime('%Y-%m-%d %H:%M')}")
    
    return 0


def cmd_links(args):
    """查看节点关联"""
    store = get_store(args.db)
    path = args.path
    
    edges = store.get_links(path, direction=args.direction)
    
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
    """添加关联"""
    store = get_store(args.db)
    
    edge_type = EdgeType(args.type)
    edge = store.add_edge(args.source, args.target, edge_type, args.weight)
    
    print(f"Added: {edge}")
    return 0


def cmd_search(args):
    """全文搜索"""
    store = get_store(args.db)
    
    results = store.search(args.query, limit=args.limit)
    
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
    """查看变更历史"""
    store = get_store(args.db)
    
    diffs = store.get_history(args.path, limit=args.limit)
    
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
    """存储统计"""
    store = get_store(args.db)
    
    stats = store.stats()
    
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
    """导入文件"""
    from .tools import VFSImporter
    
    store = get_store(args.db)
    importer = VFSImporter(store)
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
    """导出节点"""
    from .tools import VFSExporter
    
    store = get_store(args.db)
    exporter = VFSExporter(store)
    
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
    """自动发现关系"""
    from .tools import RelationBuilder
    
    store = get_store(args.db)
    builder = RelationBuilder(store)
    
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


def main():
    parser = argparse.ArgumentParser(
        description="AI Virtual Filesystem",
        prog="vfs"
    )
    parser.add_argument("--db", help="Database path (default: ~/.openclaw/vfs/vfs.db)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # read
    p_read = subparsers.add_parser("read", help="Read a node")
    p_read.add_argument("path", help="Node path")
    p_read.add_argument("--refresh", action="store_true", help="Force refresh (for live nodes)")
    p_read.add_argument("--meta", action="store_true", help="Show metadata")
    p_read.set_defaults(func=cmd_read)
    
    # write
    p_write = subparsers.add_parser("write", help="Write a node (only /memory/*)")
    p_write.add_argument("path", help="Node path")
    p_write.add_argument("--content", "-c", help="Content to write")
    p_write.add_argument("--file", "-f", help="Read content from file")
    p_write.add_argument("--meta", "-m", help="Metadata as JSON")
    p_write.set_defaults(func=cmd_write)
    
    # delete
    p_delete = subparsers.add_parser("delete", help="Delete a node (only /memory/*)")
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
    p_import.add_argument("--pattern", default="**/*.md", help="Glob pattern (for directories)")
    p_import.add_argument("--flatten", action="store_true", help="Flatten directory structure")
    p_import.set_defaults(func=cmd_import)
    
    # export
    p_export = subparsers.add_parser("export", help="Export nodes")
    p_export.add_argument("prefix", nargs="?", default="/", help="Path prefix to export")
    p_export.add_argument("--output", "-o", help="Output path (file for JSON, dir for files)")
    p_export.add_argument("--format", "-f", choices=["json", "files"], default="json")
    p_export.set_defaults(func=cmd_export)
    
    # auto-link
    p_autolink = subparsers.add_parser("auto-link", help="Auto-discover relationships")
    p_autolink.add_argument("--prefix", "-p", default="/", help="Path prefix")
    p_autolink.add_argument("--by", choices=["symbol", "tag", "all"], default="all")
    p_autolink.set_defaults(func=cmd_autolink)
    
    args = parser.parse_args()
    
    try:
        return args.func(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
