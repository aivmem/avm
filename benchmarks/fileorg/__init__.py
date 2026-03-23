"""fileorg - Organize files by extension based on YAML config."""

from .fileorg import (
    build_extension_map,
    load_config,
    main,
    organize_files,
)

__version__ = "0.1.0"
__all__ = ["main", "load_config", "build_extension_map", "organize_files"]
