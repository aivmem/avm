"""Additional tests for handlers functionality."""

import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from avm.handlers import (
    BaseHandler,
    FileHandler,
    HTTPHandler,
    ScriptHandler,
    PluginHandler,
    SQLiteHandler,
    ProviderConfig,
    ProviderManager,
    get_handlers_skill_info,
)


@pytest.fixture
def temp_env():
    """Create temp environment."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        os.environ["XDG_DATA_HOME"] = tmpdir
        yield tmpdir


class TestProviderConfig:
    """Test ProviderConfig class."""
    
    def test_create_config(self):
        """Test creating provider config."""
        config = ProviderConfig(
            pattern="/data/*",
            handler="file",
        )
        assert config.pattern == "/data/*"
        assert config.handler == "file"
    
    def test_config_matches(self):
        """Test pattern matching."""
        config = ProviderConfig(pattern="/data/*.json", handler="file")
        assert config.matches("/data/test.json")
        assert not config.matches("/other/test.json")
    
    def test_config_with_ttl(self):
        """Test config with TTL."""
        config = ProviderConfig(pattern="/cache/*", handler="http", ttl=300)
        assert config.ttl == 300
    
    def test_config_access_modes(self):
        """Test access modes."""
        ro_config = ProviderConfig(pattern="/readonly/*", handler="file", access="ro")
        rw_config = ProviderConfig(pattern="/readwrite/*", handler="file", access="rw")
        
        assert ro_config.access == "ro"
        assert rw_config.access == "rw"


class TestFileHandler:
    """Test FileHandler class."""
    
    def test_class_attributes(self):
        """Test FileHandler has required attributes."""
        assert FileHandler.name == "file"
        assert FileHandler.description is not None
    
    def test_init(self, temp_env):
        """Test FileHandler initialization."""
        handler = FileHandler(config={"root": temp_env})
        assert handler is not None
        assert handler.config["root"] == temp_env


class TestHTTPHandler:
    """Test HTTPHandler class."""
    
    def test_class_attributes(self):
        """Test HTTPHandler has required attributes."""
        assert HTTPHandler.name == "http"
        assert HTTPHandler.description is not None
    
    def test_init(self):
        """Test HTTPHandler initialization."""
        handler = HTTPHandler(config={"base_url": "http://example.com"})
        assert handler is not None


class TestScriptHandler:
    """Test ScriptHandler class."""
    
    def test_class_attributes(self):
        """Test ScriptHandler has required attributes."""
        assert ScriptHandler.name == "script"
        assert ScriptHandler.description is not None


class TestSQLiteHandler:
    """Test SQLiteHandler class."""
    
    def test_class_attributes(self):
        """Test SQLiteHandler has required attributes."""
        assert SQLiteHandler.name == "sqlite"
        assert SQLiteHandler.description is not None
    
    def test_init(self, temp_env):
        """Test SQLiteHandler initialization."""
        db_file = os.path.join(temp_env, "test.db")
        handler = SQLiteHandler(config={"database": db_file})
        assert handler is not None


class TestProviderManager:
    """Test ProviderManager class."""
    
    def test_init_empty(self):
        """Test empty manager initialization."""
        manager = ProviderManager()
        assert manager is not None
        assert len(manager.providers) == 0
    
    def test_init_with_configs(self):
        """Test manager with config list."""
        configs = [
            {"pattern": "/data/*", "handler": "file", "config": {"root": "/tmp"}},
        ]
        manager = ProviderManager(configs)
        assert len(manager.providers) == 1
    
    def test_add_provider(self):
        """Test adding a provider."""
        manager = ProviderManager()
        manager.add_provider({
            "pattern": "/api/*",
            "handler": "http",
            "config": {"base_url": "http://example.com"}
        })
        assert len(manager.providers) == 1


class TestHandlerRegistry:
    """Test handler registration."""
    
    def test_get_handlers_info(self):
        """Test getting handlers skill info."""
        info = get_handlers_skill_info()
        assert isinstance(info, str)
        assert "file" in info.lower() or len(info) > 0
