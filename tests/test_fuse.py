"""Tests for FUSE mount functionality."""

import os
import stat
import errno
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from avm import AVM

# Try to import fuse-related items, skip if not available
try:
    from avm.fuse_mount import (
        AVMFuse,
        _pid_file,
        _write_pid,
        _get_pid,
        _remove_pid,
        _is_mounted,
        HAS_FUSE,
    )
except ImportError:
    HAS_FUSE = False
    AVMFuse = None

pytestmark = pytest.mark.skipif(not HAS_FUSE, reason="fusepy not installed")


@pytest.fixture
def temp_db():
    """Create a temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["XDG_DATA_HOME"] = tmpdir
        yield tmpdir


@pytest.fixture
def avm_instance(temp_db):
    """Create an AVM instance with temp db."""
    return AVM()


@pytest.fixture
def fuse_instance(avm_instance):
    """Create an AVMFuse instance."""
    return AVMFuse(avm_instance)


class TestAVMFuse:
    """Test AVMFuse class."""
    
    def test_init(self, fuse_instance):
        """Test initialization."""
        assert fuse_instance.vfs is not None
        assert fuse_instance._write_buffers == {}
        assert fuse_instance.fd == 0
    
    def test_init_with_user(self, avm_instance):
        """Test initialization with user."""
        fuse = AVMFuse(avm_instance, user="test-user")
        assert fuse.user == "test-user"
    
    def test_parse_path_simple(self, fuse_instance):
        """Test simple path parsing."""
        path, suffix, params = fuse_instance._parse_path("/memory/test.md")
        assert path == "/memory/test.md"
        assert suffix is None
        assert params is None
    
    def test_parse_path_with_suffix(self, fuse_instance):
        """Test path parsing with virtual suffix."""
        path, suffix, params = fuse_instance._parse_path("/memory/test.md:meta")
        assert path == "/memory/test.md"
        assert suffix == ":meta"
        assert params is None
    
    def test_parse_path_with_query(self, fuse_instance):
        """Test path parsing with query params."""
        path, suffix, params = fuse_instance._parse_path("/:search?q=hello")
        assert path == "/"
        assert suffix == ":search"
        assert params == {"q": "hello"}
    
    def test_parse_path_list(self, fuse_instance):
        """Test :list virtual path."""
        path, suffix, params = fuse_instance._parse_path("/memory/:list")
        assert path == "/memory"
        assert suffix == ":list"
    
    def test_getattr_root(self, fuse_instance):
        """Test getattr for root directory."""
        attrs = fuse_instance.getattr("/")
        assert stat.S_ISDIR(attrs['st_mode'])
        assert attrs['st_nlink'] == 2
    
    def test_getattr_memory_dir(self, fuse_instance):
        """Test getattr for /memory directory."""
        attrs = fuse_instance.getattr("/memory")
        assert stat.S_ISDIR(attrs['st_mode'])
    
    def test_getattr_nonexistent(self, fuse_instance):
        """Test getattr for non-existent path."""
        from fuse import FuseOSError
        import errno
        
        # Mock FuseOSError
        with patch.object(fuse_instance, 'vfs') as mock_vfs:
            mock_vfs.read.return_value = None
            mock_vfs.list.return_value = []
            
            with pytest.raises(Exception):  # FuseOSError
                fuse_instance.getattr("/nonexistent")
    
    def test_readdir_root(self, fuse_instance):
        """Test readdir for root."""
        entries = fuse_instance.readdir("/", None)
        assert "." in entries
        assert ".." in entries
        assert ":list" in entries
        assert ":stats" in entries
    
    def test_opendir(self, fuse_instance):
        """Test opendir returns 0."""
        assert fuse_instance.opendir("/") == 0
    
    def test_releasedir(self, fuse_instance):
        """Test releasedir returns 0."""
        assert fuse_instance.releasedir("/", 0) == 0
    
    def test_mkdir(self, fuse_instance):
        """Test mkdir is no-op."""
        assert fuse_instance.mkdir("/test", 0o755) == 0
    
    def test_create_and_write(self, fuse_instance):
        """Test creating and writing a file."""
        # Create
        fh = fuse_instance.create("/memory/test.md", 0o644)
        assert fh > 0
        
        # Write
        data = b"Hello World"
        written = fuse_instance.write("/memory/test.md", data, 0, fh)
        assert written == len(data)
        
        # Release (should flush to store)
        fuse_instance.release("/memory/test.md", fh)
        
        # Verify in store
        node = fuse_instance.vfs.read("/memory/test.md")
        assert node is not None
        assert node.content == "Hello World"
    
    def test_read_file(self, fuse_instance):
        """Test reading a file."""
        # Write first
        fuse_instance.vfs.write("/memory/read_test.md", "Test content")
        
        # Read
        content = fuse_instance.read("/memory/read_test.md", 100, 0, 0)
        assert content == b"Test content"
    
    def test_read_with_offset(self, fuse_instance):
        """Test reading with offset."""
        fuse_instance.vfs.write("/memory/offset.md", "Hello World")
        
        content = fuse_instance.read("/memory/offset.md", 5, 6, 0)
        assert content == b"World"
    
    def test_truncate(self, fuse_instance):
        """Test truncating a file."""
        fuse_instance.vfs.write("/memory/trunc.md", "Hello World")
        
        fuse_instance.truncate("/memory/trunc.md", 5)
        
        node = fuse_instance.vfs.read("/memory/trunc.md")
        assert node.content == "Hello"
    
    def test_unlink(self, fuse_instance):
        """Test deleting a file."""
        fuse_instance.vfs.write("/memory/delete.md", "To delete")
        
        fuse_instance.unlink("/memory/delete.md")
        
        node = fuse_instance.vfs.read("/memory/delete.md")
        assert node is None
    
    def test_rename(self, fuse_instance):
        """Test renaming a file."""
        fuse_instance.vfs.write("/memory/old.md", "Content")
        
        fuse_instance.rename("/memory/old.md", "/memory/new.md")
        
        old = fuse_instance.vfs.read("/memory/old.md")
        new = fuse_instance.vfs.read("/memory/new.md")
        assert old is None
        assert new is not None
        assert new.content == "Content"
    
    def test_virtual_stats(self, fuse_instance):
        """Test :stats virtual node."""
        content = fuse_instance._get_virtual_content("/", ":stats", None)
        assert "nodes" in content
        assert "db_path" in content
    
    def test_virtual_list(self, fuse_instance):
        """Test :list virtual node."""
        fuse_instance.vfs.write("/memory/a.md", "A")
        fuse_instance.vfs.write("/memory/b.md", "B")
        
        content = fuse_instance._get_virtual_content("/memory", ":list", None)
        assert "/memory/a.md" in content or "a.md" in content
    
    def test_virtual_meta(self, fuse_instance):
        """Test :meta virtual node."""
        fuse_instance.vfs.write("/memory/meta.md", "Test")
        
        content = fuse_instance._get_virtual_content("/memory/meta.md", ":meta", None)
        # Meta returns JSON
        assert "{" in content or content == "{}"
    
    def test_virtual_search(self, fuse_instance):
        """Test :search virtual node."""
        fuse_instance.vfs.write("/memory/searchable.md", "unique keyword here")
        
        content = fuse_instance._get_virtual_content("/", ":search", {"q": "unique"})
        # Should return search results
        assert isinstance(content, str)


class TestPidManagement:
    """Test PID file management functions."""
    
    def test_pid_file_path(self):
        """Test PID file path generation."""
        path = _pid_file("/tmp/test-mount")
        assert "tmp_test-mount.pid" in str(path)
        assert path.suffix == ".pid"
    
    def test_write_and_get_pid(self):
        """Test writing and reading PID."""
        mountpoint = "/tmp/test-pid-write"
        try:
            _write_pid(mountpoint, 99999)
            pid = _get_pid(mountpoint)
            assert pid == 99999
        finally:
            _remove_pid(mountpoint)
    
    def test_remove_pid(self):
        """Test removing PID file."""
        mountpoint = "/tmp/test-pid-remove"
        _write_pid(mountpoint, 88888)
        
        _remove_pid(mountpoint)
        
        pid = _get_pid(mountpoint)
        assert pid is None
    
    def test_get_pid_nonexistent(self):
        """Test getting PID for non-existent file."""
        pid = _get_pid("/nonexistent/path/12345")
        assert pid is None


class TestMountStatus:
    """Test mount status checking."""
    
    def test_is_mounted_false(self):
        """Test is_mounted returns False for non-mounted path."""
        result = _is_mounted("/nonexistent/path")
        assert result is False
    
    @patch('subprocess.run')
    def test_is_mounted_true(self, mock_run):
        """Test is_mounted returns True when mounted."""
        mock_run.return_value = MagicMock(
            stdout="AVMFuse on /tmp/test (macfuse)"
        )
        
        result = _is_mounted("/tmp/test")
        assert result is True
    
    @patch('subprocess.run')
    def test_is_mounted_private_tmp(self, mock_run):
        """Test is_mounted handles /tmp -> /private/tmp."""
        mock_run.return_value = MagicMock(
            stdout="AVMFuse on /private/tmp/test (macfuse)"
        )
        
        result = _is_mounted("/tmp/test")
        assert result is True
