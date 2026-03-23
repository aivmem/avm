#!/usr/bin/env python3
"""vfs CLI — AI Virtual Filesystem

Usage:
  vfs write /path/to/node.md "content"
  vfs read  /path/to/node.md [--meta] [--raw] [--refresh]
  vfs ls    /path/prefix/
  vfs link  /from.md /to.md RELATION [--weight 0.8]
  vfs links /path/to/node.md
  vfs search "query string" [--limit 10]
  vfs delete /path/to/node.md
  vfs stats
"""

import sys, argparse, json, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from avm import VFSEngine

engine = VFSEngine()

# Auto-load trading providers if available
try:
    from trading.providers import register_providers
    register_providers(engine)
except ImportError:
    pass

# Auto-load any providers defined in config.yaml (optional)
try:
    import yaml
    _cfg_path = Path(__file__).parent / 'config.yaml'
    if _cfg_path.exists():
        cfg = yaml.safe_load(_cfg_path.read_text())
        _mounts = cfg.get('mounts', []) if cfg else []
        for mount in _mounts:
            ptype = mount.get('type', '')
            if ptype == 'static_file':
                from providers import StaticFileProvider
                engine.mount(StaticFileProvider(
                    pattern=mount['pattern'],
                    base_dir=mount.get('base_dir', '.'),
                    ttl=mount.get('ttl', 0),
                ))
            elif ptype == 'http':
                from providers import HTTPProvider
                engine.mount(HTTPProvider(
                    pattern=mount['pattern'],
                    url_template=mount['url_template'],
                    ttl=mount.get('ttl', 3600),
                ))
except Exception:
    pass  # config.yaml is optional; yaml may not been installed


# ── Command handlers ───────────────────────────────────────────────────────

def cmd_read(args):
    node = engine.read(args.path, force_refresh=args.refresh)
    if node:
        if args.raw:
            print(json.dumps({
                'path': node.path,
                'content': node.content,
                'sources': node.sources,
                'confidence': node.confidence,
                'tags': node.tags,
                'updated_at': node.updated_at,
                'expires_at': node.expires_at,
            }, ensure_ascii=False, indent=2))
        else:
            print(node.content)
            if args.meta:
                stale = node.expires_at and time.time() > node.expires_at
                status = '⚠️  STALE' if stale else '✅ fresh'
                print(f"\n---")
                print(f"sources: {node.sources}")
                print(f"confidence: {node.confidence:.2f}  |  {status}")
                if node.expires_at:
                    remaining = node.expires_at - time.time()
                    print(f"expires in: {remaining:.0f}s")
    else:
        print(f"[vfs] not found: {args.path}", file=sys.stderr)
        sys.exit(1)


def cmd_write(args):
    content = args.content if args.content else sys.stdin.read()
    tags = [t.strip() for t in args.tags.split(',')] if args.tags else []
    node = engine.write(
        args.path, content,
        tags=tags,
        confidence=args.confidence if args.confidence is not None else 1.0,
        ttl=args.ttl,
    )
    print(f"✅ written: {node.path}")


def cmd_ls(args):
    paths = engine.ls(args.path)
    if paths:
        for p in paths:
            print(p)
    else:
        print(f"[vfs] no nodes under {args.path!r}")


def cmd_links(args):
    edges = engine.links(args.path)
    if not edges:
        print(f"[vfs] no links for {args.path}")
        return
    for e in edges:
        if e.from_path == args.path:
            print(f"  → [{e.relation}] {e.to_path}  (weight={e.weight:.2f})")
        else:
            print(f"  ← [{e.relation}] {e.from_path}  (weight={e.weight:.2f})")
        if e.metadata:
            print(f"       metadata: {e.metadata}")


def cmd_link(args):
    engine.link(
        args.from_path, args.to_path, args.relation,
        weight=args.weight if args.weight is not None else 1.0,
    )
    print(f"✅ link: {args.from_path} --[{args.relation}]--> {args.to_path}")


def cmd_search(args):
    nodes = engine.search(args.query, limit=args.limit or 10)
    if not nodes:
        print(f"[vfs] no results for {args.query!r}")
        return
    for n in nodes:
        snippet = n.content[:120].replace('\n', ' ')
        print(f"  {n.path}")
        print(f"    {snippet}{'...' if len(n.content) > 120 else ''}")


def cmd_delete(args):
    existing = engine._get_from_db(args.path)
    if not existing:
        print(f"[vfs] not found: {args.path}", file=sys.stderr)
        sys.exit(1)
    engine.delete(args.path)
    print(f"🗑️  deleted: {args.path}")


def cmd_mv(args):
    from avm.core import AVM
    vfs = AVM()
    try:
        n = vfs.rename(args.src, args.dst)
        print(f"✅ moved {n} node(s): {args.src} → {args.dst}")
    except FileNotFoundError as e:
        print(f"[mv] {e}", file=sys.stderr)
        sys.exit(1)
    except PermissionError as e:
        print(f"[mv] permission denied: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_stats(args):
    s = engine.stats()
    print(f"nodes : {s['nodes']}")
    print(f"edges : {s['edges']}")
    print(f"db    : {s['db']}")


def cmd_touch(args):
    node = engine.touch(args.path)
    print(f"✅ touch: {node.path}")


# ── Argument parser ────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(prog='vfs', description='AI Virtual Filesystem')
    sub = p.add_subparsers(dest='cmd', metavar='COMMAND')

    # read
    r = sub.add_parser('read', aliases=['cat', 'get'], help='Read a node')
    r.add_argument('path')
    r.add_argument('--raw', action='store_true', help='Output raw JSON')
    r.add_argument('--meta', action='store_true', help='Show metadata footer')
    r.add_argument('--refresh', action='store_true', help='Force provider refresh')

    # write
    w = sub.add_parser('write', aliases=['set', 'put'], help='Write a node')
    w.add_argument('path')
    w.add_argument('content', nargs='?', help='Content (omit to read from stdin)')
    w.add_argument('--tags', help='Comma-separated tags')
    w.add_argument('--confidence', type=float)
    w.add_argument('--ttl', type=int, help='TTL in seconds')

    # ls
    ls_p = sub.add_parser('ls', aliases=['list'], help='List nodes under a prefix')
    ls_p.add_argument('path', nargs='?', default='/')

    # links
    lk = sub.add_parser('links', help='Show edges for a node')
    lk.add_argument('path')

    # link
    ln = sub.add_parser('link', help='Create a relationship edge')
    ln.add_argument('from_path')
    ln.add_argument('to_path')
    ln.add_argument('relation')
    ln.add_argument('--weight', type=float)

    # search
    sr = sub.add_parser('search', aliases=['find'], help='Full-text search')
    sr.add_argument('query')
    sr.add_argument('--limit', type=int, default=10)

    # delete
    dl = sub.add_parser('delete', aliases=['rm'], help='Delete a node')
    dl.add_argument('path')

    # touch
    tc = sub.add_parser('touch', help='Create an empty node if missing')
    tc.add_argument('path')

    # mv
    mv_p = sub.add_parser('mv', aliases=['move', 'rename'], help='Move/rename a node or prefix tree')
    mv_p.add_argument('src', help='Source path or prefix')
    mv_p.add_argument('dst', help='Destination path or prefix')

    # stats
    sub.add_parser('stats', help='Show database statistics')

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        return

    dispatch = {
        'read': cmd_read, 'cat': cmd_read, 'get': cmd_read,
        'write': cmd_write, 'set': cmd_write, 'put': cmd_write,
        'ls': cmd_ls, 'list': cmd_ls,
        'links': cmd_links,
        'link': cmd_link,
        'search': cmd_search, 'find': cmd_search,
        'delete': cmd_delete, 'rm': cmd_delete,
        'mv': cmd_mv, 'move': cmd_mv, 'rename': cmd_mv,
        'touch': cmd_touch,
        'stats': cmd_stats,
    }
    dispatch[args.cmd](args)


if __name__ == '__main__':
    main()
