"""
Tests for handlers: IndexHandler, ConfigHandler, MetaHandler
"""

import os
import pytest
import tempfile
import json
import yaml

# Set temp data dir before imports
os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()

from avm.index_handler import (
    IndexHandler, IndexStore, IndexEntry, FileEntry,
    ProjectScanHook, EXTRACTORS
)
from avm.config_handler import (
    ConfigHandler, ConfigStore, MetaHandler,
    DEFAULT_SETTINGS, deep_merge
)


class TestIndexHandler:
    """Tests for IndexHandler."""
    
    def test_scan_hook_basic(self, tmp_path):
        """Test ProjectScanHook scans directory."""
        # Create test files
        (tmp_path / "main.py").write_text("def hello(): pass")
        (tmp_path / "README.md").write_text("# Test")
        (tmp_path / "data.json").write_text("{}")
        
        hook = ProjectScanHook()
        entry = hook.scan(str(tmp_path), name="test-project")
        
        assert entry.name == "test-project"
        assert len(entry.files) >= 2
        paths = [f.path for f in entry.files]
        assert "main.py" in paths
        assert "README.md" in paths
    
    def test_scan_hook_with_extractors(self, tmp_path):
        """Test signature extraction."""
        (tmp_path / "code.py").write_text("""
def calculate(x, y):
    return x + y

class Calculator:
    def add(self, a, b):
        return a + b
""")
        
        hook = ProjectScanHook(extractors=[".py"])
        entry = hook.scan(str(tmp_path), name="test")
        
        py_file = next(f for f in entry.files if f.path == "code.py")
        assert "def calculate" in py_file.description
        assert "class Calculator" in py_file.description
    
    def test_index_store_crud(self):
        """Test IndexStore CRUD operations."""
        store = IndexStore()
        
        # Create
        entry = IndexEntry(
            name="myproject",
            root="/tmp/myproject",
            files=[FileEntry(path="main.py", mtime=1000)]
        )
        store.save("project", entry)
        
        # Read
        retrieved = store.get("project", "myproject")
        assert retrieved is not None
        assert retrieved.name == "myproject"
        assert len(retrieved.files) == 1
        
        # List
        names = store.list("project")
        assert "myproject" in names
        
        # Delete
        store.delete("project", "myproject")
        assert store.get("project", "myproject") is None
    
    def test_index_handler_read(self, tmp_path):
        """Test IndexHandler read operations."""
        (tmp_path / "test.py").write_text("def foo(): pass")
        
        handler = IndexHandler({"root": str(tmp_path), "scan_hook": "code"})
        
        # Scan
        result = handler.read("/index/code/test:scan", {})
        assert "files" in result.lower() or "scanned" in result.lower()
        
        # Read
        content = handler.read("/index/code/test", {})
        assert content is not None
        
        # Status
        status = handler.read("/index/code/test:status", {})
        assert "clean" in status.lower() or "dirty" in status.lower() or "missing" in status.lower()
    
    def test_extractors_exist(self):
        """Test extractors are registered."""
        assert ".py" in EXTRACTORS
        assert ".js" in EXTRACTORS
        assert ".go" in EXTRACTORS
        assert ".rs" in EXTRACTORS


class TestConfigHandler:
    """Tests for ConfigHandler."""
    
    @pytest.fixture(autouse=True)
    def reset_config_handler(self):
        """Reset ConfigHandler singleton before each test."""
        ConfigHandler._store = None
        yield
        ConfigHandler._store = None
    
    def test_config_store_merge(self, tmp_path):
        """Test config layering."""
        user_config = {"memory": {"duplicate_check": True}}
        store = ConfigStore(user_config=user_config, storage_path=str(tmp_path / "db"))
        
        merged = store.get_merged()
        
        # User config overrides default
        assert merged["memory"]["duplicate_check"] is True
        # Default preserved
        assert merged["memory"]["duplicate_threshold"] == 0.85
    
    def test_config_store_runtime_changes(self, tmp_path):
        """Test runtime modifications."""
        store = ConfigStore(storage_path=str(tmp_path / "db"))
        
        # Set value
        store.set_value("memory.duplicate_threshold", 0.9)
        assert store.get_value("memory.duplicate_threshold") == 0.9
        
        # Update dict
        store.update({"scoring": {"importance_weight": 0.5}})
        assert store.get_value("scoring.importance_weight") == 0.5
        
        # Reset
        store.reset("memory.duplicate_threshold")
        assert store.get_value("memory.duplicate_threshold") == 0.85
    
    def test_config_handler_read(self):
        """Test ConfigHandler read."""
        handler = ConfigHandler({"user_config": {}})
        
        # YAML format
        yaml_out = handler.read("/.config/settings.yaml", {})
        assert yaml_out is not None
        config = yaml.safe_load(yaml_out)
        assert "memory" in config
        
        # JSON format
        json_out = handler.read("/.config/settings.json", {})
        config = json.loads(json_out)
        assert "memory" in config
        
        # Section
        memory = handler.read("/.config/memory", {})
        assert memory is not None
    
    def test_config_handler_write(self):
        """Test ConfigHandler write."""
        handler = ConfigHandler({"user_config": {}})
        
        # Write section
        result = handler.write("/.config/memory", "duplicate_check: true", {})
        assert result is True
        
        # Verify
        assert handler.store.get_value("memory.duplicate_check") is True
        
        # Reset
        result = handler.write("/.config/memory", "reset", {})
        assert result is True
    
    def test_deep_merge(self):
        """Test deep merge utility."""
        base = {"a": {"b": 1, "c": 2}, "d": 3}
        overlay = {"a": {"b": 10}, "e": 5}
        
        result = deep_merge(base, overlay)
        
        assert result["a"]["b"] == 10  # Overwritten
        assert result["a"]["c"] == 2   # Preserved
        assert result["d"] == 3        # Preserved
        assert result["e"] == 5        # Added


class TestMetaHandler:
    """Tests for MetaHandler."""
    
    def test_meta_version(self):
        """Test version read."""
        handler = MetaHandler({})
        version = handler.read("/.meta/version", {})
        assert version is not None
        assert "." in version  # e.g., "0.9.0"
    
    def test_meta_info(self):
        """Test info read."""
        handler = MetaHandler({})
        info = handler.read("/.meta/info", {})
        data = json.loads(info)
        assert "version" in data
        assert "python" in data
    
    def test_meta_read_only(self):
        """Test meta is read-only."""
        handler = MetaHandler({})
        assert handler.write("/.meta/version", "1.0.0", {}) is False
        assert handler.delete("/.meta/version", {}) is False
