# fileorg

Organize files in a directory by extension using YAML-based rules.

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Configuration](#configuration)
- [Examples](#examples)
- [Behavior](#behavior)
- [Exit Codes](#exit-codes)
- [Troubleshooting](#troubleshooting)

## Installation

```bash
pip install pyyaml
```

## Quick Start

```bash
# Generate default config
fileorg init

# Preview changes (dry-run)
fileorg run --dry-run

# Organize files
fileorg run
```

## Usage

```
fileorg [OPTIONS] [COMMAND]
```

### Global Options

| Option | Description |
|--------|-------------|
| `-c, --config PATH` | Path to config file (default: `fileorg.yaml`) |

### Commands

#### `run` - Execute file organization (default)

```bash
fileorg run [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-n, --dry-run` | Show what would be done without making changes |
| `-v, --verbose` | Enable verbose output |

Examples:
```bash
fileorg run                      # Organize files using fileorg.yaml
fileorg run -n                   # Preview changes
fileorg run -v                   # Show all operations
fileorg -c ~/rules.yaml run      # Use custom config
```

#### `init` - Generate default config file

```bash
fileorg init [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-o, --output PATH` | Output path for config file (default: `fileorg.yaml`) |
| `-f, --force` | Overwrite existing config file |

Examples:
```bash
fileorg init                     # Create fileorg.yaml
fileorg init -o custom.yaml      # Create custom.yaml
fileorg init -f                  # Overwrite existing config
```

#### `validate` - Validate config file

```bash
fileorg validate
```

Checks config for:
- Valid YAML syntax
- Required fields (`rules`)
- Source directory existence
- Rule structure (each rule has `target` and `extensions`)

#### `list` - List configured rules

```bash
fileorg list
```

Displays all extension-to-folder mappings from the config.

## Configuration

Config file format (`fileorg.yaml`):

```yaml
# Source directory to organize (default: current directory)
source: .

# Enable dry-run mode by default (default: false)
dry_run: false

# Organization rules
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
```

### Config Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `source` | string | No | `.` | Directory to organize |
| `dry_run` | boolean | No | `false` | Default dry-run mode |
| `rules` | list | Yes | - | Organization rules |

### Rule Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `extensions` | list | Yes | File extensions (without dots) |
| `target` | string | Yes | Target folder name |

## Examples

### Organize Downloads folder

```yaml
# ~/fileorg-downloads.yaml
source: ~/Downloads
dry_run: false

rules:
  - extensions: [jpg, jpeg, png, gif, heic]
    target: Images
  - extensions: [mp4, mov, avi, mkv]
    target: Videos
  - extensions: [pdf, doc, docx, xlsx]
    target: Documents
  - extensions: [dmg, pkg, exe, zip]
    target: Installers
```

```bash
fileorg -c ~/fileorg-downloads.yaml run
```

### Preview before organizing

```bash
# Always preview first
fileorg run --dry-run

# Output:
#   [DRY-RUN] photo.jpg -> Images/
#   [DRY-RUN] report.pdf -> Documents/
#   [DRY-RUN] script.py -> Code/
```

## Running as Module

```bash
python -m fileorg run
python -m fileorg init
```

## Behavior

- **Directories are skipped** - only files in the source directory are processed
- **Subdirectories are not scanned** - only top-level files are organized
- **Collision handling** - if a file already exists at the target location, it is skipped with a warning
- **Target folders are auto-created** - destination folders are created as needed
- **Case-insensitive matching** - `.JPG` and `.jpg` match the same rule
- **Extensions without dots** - config uses `jpg` not `.jpg` (dots are stripped automatically)

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (config not found, validation failed, move errors) |

## Troubleshooting

### Config file not found

```
Error: Config file not found: fileorg.yaml
```

Run `fileorg init` to create a default config, or specify a path with `-c`.

### Source directory not found

```
Error: Source directory not found: /path/to/dir
```

Check that the `source` path in your config exists and is accessible.

### No files moved

If `fileorg run` reports 0 files moved:
- Run with `--verbose` to see which files are being skipped
- Check that your rules include the extensions you want to organize
- Verify files exist in the source directory (not subdirectories)

### Permission denied

```
Error moving file.txt: [Errno 13] Permission denied
```

Check that you have write permission for both the source file and target directory.

### Config validation failed

```
Config validation failed:
  - Rule 1: missing 'target'
```

Ensure each rule in your config has both `extensions` (list) and `target` (string) fields.

## API Usage

You can also use fileorg as a Python library:

```python
from fileorg import load_config, build_extension_map, organize_files
from pathlib import Path

# Load config
config = load_config(Path("fileorg.yaml"))

# Build extension mapping
ext_map = build_extension_map(config["rules"])

# Organize files
source = Path(config.get("source", ".")).expanduser().resolve()
stats = organize_files(source, ext_map, dry_run=True, verbose=True)

print(f"Would move {stats['moved']} files")
```
