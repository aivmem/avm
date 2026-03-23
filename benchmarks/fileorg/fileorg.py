#!/usr/bin/env python3
"""fileorg - Organize files by extension based on YAML config."""

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import yaml


DEFAULT_CONFIG = """# fileorg configuration
source: .
dry_run: false

rules:
  # Images
  - extensions: [jpg, jpeg, png, gif, webp, svg]
    target: Images

  # Documents
  - extensions: [pdf, doc, docx, txt, md]
    target: Documents

  # Code
  - extensions: [py, js, ts, go, rs, java]
    target: Code

  # Archives
  - extensions: [zip, tar, gz, 7z, rar]
    target: Archives
"""


def load_config(config_path: Path) -> dict:
    """Load and validate config from YAML file."""
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    if not config:
        print("Error: Empty config file", file=sys.stderr)
        sys.exit(1)

    if "rules" not in config:
        print("Error: Config must contain 'rules' section", file=sys.stderr)
        sys.exit(1)

    return config


def build_extension_map(rules: list) -> dict[str, str]:
    """Build extension -> target folder mapping from rules."""
    ext_map = {}
    for rule in rules:
        target = rule.get("target")
        extensions = rule.get("extensions", [])
        for ext in extensions:
            ext_lower = ext.lower().lstrip(".")
            ext_map[ext_lower] = target
    return ext_map


def organize_files(
    source: Path,
    ext_map: dict[str, str],
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Organize files in source directory based on extension mapping."""
    stats = {"moved": 0, "skipped": 0, "errors": 0}

    if not source.exists():
        print(f"Error: Source directory not found: {source}", file=sys.stderr)
        sys.exit(1)

    for item in source.iterdir():
        if item.is_dir():
            continue

        ext = item.suffix.lower().lstrip(".")
        if ext not in ext_map:
            if verbose:
                print(f"  Skip: {item.name} (no matching rule)")
            stats["skipped"] += 1
            continue

        target_folder = source / ext_map[ext]
        target_path = target_folder / item.name

        if dry_run:
            print(f"  [DRY-RUN] {item.name} -> {ext_map[ext]}/")
            stats["moved"] += 1
        else:
            try:
                target_folder.mkdir(exist_ok=True)
                if target_path.exists():
                    print(f"  Warning: {target_path} already exists, skipping")
                    stats["skipped"] += 1
                    continue
                shutil.move(str(item), str(target_path))
                if verbose:
                    print(f"  Moved: {item.name} -> {ext_map[ext]}/")
                stats["moved"] += 1
            except Exception as e:
                print(f"  Error moving {item.name}: {e}", file=sys.stderr)
                stats["errors"] += 1

    return stats


def cmd_run(args: argparse.Namespace) -> int:
    """Execute file organization."""
    config = load_config(args.config)

    source = args.source if args.source else Path(config.get("source", "."))
    source = source.expanduser().resolve()
    dry_run = args.dry_run if args.dry_run else config.get("dry_run", False)
    verbose = args.verbose

    ext_map = build_extension_map(config["rules"])

    print(f"Organizing files in: {source}")
    if dry_run:
        print("Mode: DRY-RUN (no changes will be made)")
    print()

    stats = organize_files(source, ext_map, dry_run=dry_run, verbose=verbose)

    print()
    print(f"Done. Moved: {stats['moved']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}")

    return 0 if stats["errors"] == 0 else 1


def cmd_init(args: argparse.Namespace) -> int:
    """Generate default config file."""
    config_path = args.output

    if config_path.exists() and not args.force:
        print(f"Error: {config_path} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1

    with open(config_path, "w") as f:
        f.write(DEFAULT_CONFIG)

    print(f"Created config file: {config_path}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate config file."""
    config = load_config(args.config)

    source = Path(config.get("source", ".")).expanduser()
    rules = config.get("rules", [])

    errors = []

    if not source.exists():
        errors.append(f"Source directory does not exist: {source}")

    if not rules:
        errors.append("No rules defined")

    for i, rule in enumerate(rules):
        if "target" not in rule:
            errors.append(f"Rule {i+1}: missing 'target'")
        if "extensions" not in rule:
            errors.append(f"Rule {i+1}: missing 'extensions'")
        elif not isinstance(rule["extensions"], list):
            errors.append(f"Rule {i+1}: 'extensions' must be a list")

    if errors:
        print("Config validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("Config is valid.")
    print(f"  Source: {source}")
    print(f"  Rules: {len(rules)}")
    print(f"  Dry-run: {config.get('dry_run', False)}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List configured rules."""
    config = load_config(args.config)
    rules = config.get("rules", [])

    if not rules:
        print("No rules defined.")
        return 0

    print("Configured rules:")
    for rule in rules:
        target = rule.get("target", "???")
        extensions = rule.get("extensions", [])
        ext_str = ", ".join(f".{e}" for e in extensions)
        print(f"  {ext_str} -> {target}/")

    return 0


def add_config_arg(parser: argparse.ArgumentParser) -> None:
    """Add common config argument to a parser."""
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=Path("fileorg.yaml"),
        help="Path to config file (default: fileorg.yaml)",
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fileorg",
        description="Organize files by extension based on YAML config",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run command
    run_parser = subparsers.add_parser("run", help="Execute file organization")
    add_config_arg(run_parser)
    run_parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    run_parser.add_argument(
        "-s", "--source",
        type=Path,
        help="Override source directory from config",
    )
    run_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    # init command
    init_parser = subparsers.add_parser("init", help="Generate default config file")
    init_parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("fileorg.yaml"),
        help="Output path for config file (default: fileorg.yaml)",
    )
    init_parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Overwrite existing config file",
    )

    # validate command
    validate_parser = subparsers.add_parser("validate", help="Validate config file")
    add_config_arg(validate_parser)

    # list command
    list_parser = subparsers.add_parser("list", help="List configured rules")
    add_config_arg(list_parser)

    args = parser.parse_args(argv)

    # Default to 'run' if no command specified
    if args.command is None:
        args.command = "run"
        args.config = Path("fileorg.yaml")
        args.dry_run = False
        args.source = None
        args.verbose = False

    commands = {
        "run": cmd_run,
        "init": cmd_init,
        "validate": cmd_validate,
        "list": cmd_list,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
