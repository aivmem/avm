"""Tests for AVM daemon."""
import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# Skip if fuse not available
try:
    import fuse
    HAS_FUSE = True
except (ImportError, OSError):
    HAS_FUSE = False


class TestDaemonConfig:
    """Test daemon configuration."""
    
    def test_mount_config_creation(self):
        """Test MountConfig dataclass."""
        from avm.daemon import MountConfig
        
        config = MountConfig(
            path="/tmp/test",
            agent="test_agent"
        )
        
        assert config.path == "/tmp/test"
        assert config.agent == "test_agent"
        assert config.enabled is True
    
    def test_mount_config_disabled(self):
        """Test MountConfig with enabled=False."""
        from avm.daemon import MountConfig
        
        config = MountConfig(
            path="/tmp/test",
            agent="test",
            enabled=False
        )
        
        assert config.enabled is False
    
    def test_daemon_config_creation(self):
        """Test DaemonConfig dataclass."""
        from avm.daemon import DaemonConfig, MountConfig
        
        config = DaemonConfig(mounts=[
            MountConfig("/tmp/a", "agent_a"),
            MountConfig("/tmp/b", "agent_b"),
        ])
        
        assert len(config.mounts) == 2
    
    def test_daemon_config_default(self):
        """Test DaemonConfig default values."""
        from avm.daemon import DaemonConfig
        
        config = DaemonConfig()
        assert config.mounts == []
    
    def test_daemon_config_save(self):
        """Test saving config."""
        from avm.daemon import DaemonConfig, MountConfig, CONFIG_DIR
        import yaml
        
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            config_dir = Path(tmpdir) / "config"
            
            with patch('avm.daemon.CONFIG_DIR', config_dir):
                with patch('avm.daemon.MOUNTS_CONFIG', config_dir / "mounts.yaml"):
                    config = DaemonConfig(mounts=[
                        MountConfig("/tmp/test", "test_agent")
                    ])
                    config.save()
                    
                    # Check file was created
                    assert (config_dir / "mounts.yaml").exists()


class TestMountProcess:
    """Test MountProcess management."""
    
    def test_mount_process_init(self):
        """Test MountProcess initialization."""
        from avm.daemon import MountProcess
        
        proc = MountProcess("/tmp/test", "test_agent")
        
        assert proc.mountpoint == "/tmp/test"
        assert proc.agent_id == "test_agent"
        assert proc.pid is None


@pytest.mark.skipif(not HAS_FUSE, reason="libfuse not available")
class TestAVMDaemon:
    """Test AVMDaemon class."""
    
    def test_daemon_init(self):
        """Test AVMDaemon initialization."""
        from avm.daemon import AVMDaemon
        
        daemon = AVMDaemon()
        assert daemon.mounts == {}
        assert daemon._running is False
    
    def test_daemon_has_config(self):
        """Test daemon has config."""
        from avm.daemon import AVMDaemon
        
        daemon = AVMDaemon()
        assert hasattr(daemon, 'config')


class TestConfigParsing:
    """Test config file parsing."""
    
    def test_parse_mount_config(self):
        """Test parsing mount configuration."""
        from avm.daemon import MountConfig
        
        config = MountConfig(path="/path/to/mount", agent="my_agent")
        assert config.path == "/path/to/mount"
        assert config.agent == "my_agent"
    
    def test_mount_config_from_yaml(self):
        """Test loading config from YAML data."""
        from avm.daemon import MountConfig
        import yaml
        
        yaml_data = """
path: /tmp/avm
agent: test_agent
enabled: true
"""
        data = yaml.safe_load(yaml_data)
        config = MountConfig(**data)
        
        assert config.path == "/tmp/avm"
        assert config.agent == "test_agent"
        assert config.enabled is True
