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
# This handles both "fusepy not installed" and "libfuse not found" cases
HAS_FUSE = False
AVMFuse = None
_pid_file = None
_write_pid = None
_get_pid = None
_remove_pid = None
_is_mounted = None

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
except (ImportError, OSError):
    # ImportError: fusepy not installed
    # OSError: libfuse not found
    pass

pytestmark = pytest.mark.skipif(not HAS_FUSE, reason="FUSE not available (fusepy or libfuse missing)")


@pytest.fixture
def temp_db():
    """Create a temporary database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
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


class TestShortcuts:
    """Test shortcut functionality."""
    
    def test_generate_shortcut(self, fuse_instance):
        """Test shortcut generation."""
        shortcut = fuse_instance._generate_shortcut("/memory/test.md")
        assert len(shortcut) >= 3
        assert shortcut.isalnum()
    
    def test_shortcut_consistency(self, fuse_instance):
        """Test same path generates same shortcut."""
        s1 = fuse_instance._generate_shortcut("/memory/test.md")
        s2 = fuse_instance._generate_shortcut("/memory/test.md")
        assert s1 == s2
    
    def test_resolve_shortcut(self, avm_instance, fuse_instance):
        """Test shortcut resolution."""
        # Write a node with shortcut
        avm_instance.write("/memory/shortcut_test.md", "test", 
                          meta={"shortcut": "abc"})
        
        resolved = fuse_instance._resolve_shortcut("abc")
        assert resolved == "/memory/shortcut_test.md"
    
    def test_resolve_nonexistent_shortcut(self, fuse_instance):
        """Test resolving non-existent shortcut."""
        resolved = fuse_instance._resolve_shortcut("zzz999")
        assert resolved is None
    
    def test_parse_path_with_shortcut(self, avm_instance, fuse_instance):
        """Test _parse_path resolves shortcuts."""
        avm_instance.write("/memory/parse_test.md", "content",
                          meta={"shortcut": "xyz"})
        
        real_path, suffix, params = fuse_instance._parse_path("/@xyz")
        assert real_path == "/memory/parse_test.md"
        assert suffix is None
    
    def test_shortcut_with_suffix(self, avm_instance, fuse_instance):
        """Test shortcut with virtual suffix."""
        avm_instance.write("/memory/suffix_test.md", "content",
                          meta={"shortcut": "suf"})
        
        real_path, suffix, params = fuse_instance._parse_path("/@suf:meta")
        assert real_path == "/memory/suffix_test.md"
        assert suffix == ":meta"


class TestListFeatures:
    """Test :list functionality."""
    
    def test_list_basic(self, avm_instance, fuse_instance):
        """Test basic :list output."""
        avm_instance.write("/memory/list1.md", "Content one")
        avm_instance.write("/memory/list2.md", "Content two")
        
        content = fuse_instance._get_virtual_content("/memory", ":list", None)
        assert "list1.md" in content
        assert "list2.md" in content
    
    def test_list_with_limit(self, avm_instance, fuse_instance):
        """Test :list with limit parameter."""
        for i in range(5):
            avm_instance.write(f"/memory/limit{i}.md", f"Content {i}")
        
        content = fuse_instance._get_virtual_content("/memory", ":list", 
                                                     {"limit": "2"})
        lines = [l for l in content.strip().split('\n') if l]
        assert len(lines) <= 2
    
    def test_list_with_offset(self, avm_instance, fuse_instance):
        """Test :list with offset parameter."""
        for i in range(5):
            avm_instance.write(f"/memory/off{i}.md", f"Content {i}")
        
        content1 = fuse_instance._get_virtual_content("/memory", ":list",
                                                      {"limit": "10"})
        content2 = fuse_instance._get_virtual_content("/memory", ":list",
                                                      {"limit": "10", "offset": "2"})
        
        lines1 = [l for l in content1.strip().split('\n') if l]
        lines2 = [l for l in content2.strip().split('\n') if l]
        
        # Offset should reduce results
        assert len(lines2) <= len(lines1)
    
    def test_list_with_search(self, avm_instance, fuse_instance):
        """Test :list with search query."""
        avm_instance.write("/memory/apple.md", "This is about apples")
        avm_instance.write("/memory/banana.md", "This is about bananas")
        
        content = fuse_instance._get_virtual_content("/memory", ":list",
                                                     {"q": "apple"})
        assert "apple" in content.lower()
    
    def test_list_shows_shortcut(self, avm_instance, fuse_instance):
        """Test :list output includes shortcuts."""
        avm_instance.write("/memory/shortcut_list.md", "Test content")
        
        content = fuse_instance._get_virtual_content("/memory", ":list", None)
        # Should contain @ shortcut prefix
        assert "@" in content
    
    def test_list_truncates_long_filename(self, avm_instance, fuse_instance):
        """Test :list truncates long filenames."""
        long_name = "a" * 50 + ".md"
        avm_instance.write(f"/memory/{long_name}", "content")
        
        content = fuse_instance._get_virtual_content("/memory", ":list", None)
        # Should be truncated with ...
        assert "..." in content


class TestSharedPermissions:
    """Test shared file permissions."""
    
    def test_can_see_shared_no_restriction(self, avm_instance):
        """Test can see shared file with no restrictions."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, "agent1")
        
        avm_instance.write("/memory/shared/open.md", "public",
                          meta={})
        
        node = avm_instance.read("/memory/shared/open.md")
        assert fuse._can_see_shared(node) is True
    
    def test_can_see_shared_with_permission(self, avm_instance):
        """Test can see shared file when in shared_with list."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, "agent1")
        
        avm_instance.write("/memory/shared/restricted.md", "secret",
                          meta={"shared_with": ["agent1", "agent2"]})
        
        node = avm_instance.read("/memory/shared/restricted.md")
        assert fuse._can_see_shared(node) is True
    
    def test_cannot_see_shared_without_permission(self, avm_instance):
        """Test cannot see shared file when not in shared_with list."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, "agent3")
        
        avm_instance.write("/memory/shared/restricted.md", "secret",
                          meta={"shared_with": ["agent1", "agent2"]})
        
        node = avm_instance.read("/memory/shared/restricted.md")
        assert fuse._can_see_shared(node) is False
    
    def test_admin_bypasses_shared_check(self, avm_instance):
        """Test admin mode bypasses shared_with check."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, None)  # Admin mode
        
        avm_instance.write("/memory/shared/restricted.md", "secret",
                          meta={"shared_with": ["agent1"]})
        
        node = avm_instance.read("/memory/shared/restricted.md")
        assert fuse._can_see_shared(node) is True


class TestPathSuffix:
    """Test :path suffix."""
    
    def test_path_returns_relative(self, avm_instance, fuse_instance):
        """Test :path returns relative path."""
        avm_instance.write("/memory/test/nested.md", "content")
        
        content = fuse_instance._get_virtual_content(
            "/memory/test/nested.md", ":path", None)
        
        assert content.strip() == "memory/test/nested.md"
        assert not content.startswith("/")


class TestInfoSuffix:
    """Test :info suffix."""
    
    def test_info_lists_suffixes(self, avm_instance, fuse_instance):
        """Test :info lists available suffixes."""
        avm_instance.write("/memory/info_test.md", "content",
                          meta={"tags": ["test"]})
        
        content = fuse_instance._get_virtual_content(
            "/memory/info_test.md", ":info", None)
        
        assert ":data" in content
        assert ":tags" in content


class TestDelta:
    """Test :delta and :mark functionality."""
    
    def test_delta_never_read(self, avm_instance):
        """Test delta for never-read file."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, "agent1")
        
        avm_instance.write("/memory/shared/delta1.md", "content")
        
        content = fuse._get_virtual_content("/memory/shared/delta1.md", ":delta", None)
        assert "first read" in content or "never read" in content
    
    def test_delta_no_changes(self, avm_instance):
        """Test delta when no changes since last read."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, "agent1")
        
        avm_instance.write("/memory/shared/delta2.md", "content",
                          meta={"last_read": {"agent1": 1}})
        
        content = fuse._get_virtual_content("/memory/shared/delta2.md", ":delta", None)
        assert "no changes" in content
    
    def test_delta_shows_diff(self, avm_instance):
        """Test delta shows diff when changes exist."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, "agent1")
        
        # Create and modify to generate diff
        avm_instance.write("/memory/shared/delta3.md", "line1")
        node = avm_instance.read("/memory/shared/delta3.md")
        node.meta["last_read"] = {"agent1": 1}  # Mark v1 as read
        avm_instance.write("/memory/shared/delta3.md", "line1\nline2", meta=node.meta)
        
        content = fuse._get_virtual_content("/memory/shared/delta3.md", ":delta", None)
        # Should contain version info or diff
        assert "v2" in content or "line2" in content or "changed" in content
    
    def test_mark_shows_version(self, avm_instance):
        """Test :mark shows current read marker."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, "agent1")
        
        avm_instance.write("/memory/shared/mark1.md", "content",
                          meta={"last_read": {"agent1": 3}})
        
        content = fuse._get_virtual_content("/memory/shared/mark1.md", ":mark", None)
        assert "marked: v3" in content
    
    def test_mark_write_updates(self, avm_instance):
        """Test writing to :mark updates marker."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, "agent1")
        
        avm_instance.write("/memory/shared/mark2.md", "content")
        
        # Write to mark
        fuse._set_virtual_content("/memory/shared/mark2.md", ":mark", "")
        
        # Check marker updated
        node = avm_instance.read("/memory/shared/mark2.md")
        assert node.meta.get("last_read", {}).get("agent1") == node.version
    
    def test_version_unchanged_on_meta_only(self, avm_instance):
        """Test version doesn't bump on meta-only changes."""
        avm_instance.write("/memory/shared/version1.md", "content")
        node1 = avm_instance.read("/memory/shared/version1.md")
        v1 = node1.version
        
        # Update meta only (same content)
        node1.meta["some_key"] = "value"
        avm_instance.store.put_node(node1, save_diff=False)
        
        node2 = avm_instance.read("/memory/shared/version1.md")
        assert node2.version == v1  # Version unchanged


class TestChanges:
    """Test :changes functionality."""
    
    def test_changes_shows_recent(self, avm_instance, fuse_instance):
        """Test :changes shows recently modified files."""
        avm_instance.write("/memory/changes1.md", "content")
        
        content = fuse_instance._get_virtual_content("/memory", ":changes", 
                                                     {"minutes": "60"})
        assert "changes1.md" in content or "no changes" in content


class TestTTL:
    """Test :ttl functionality."""
    
    def test_ttl_set_minutes(self, avm_instance, fuse_instance):
        """Test setting TTL in minutes."""
        avm_instance.write("/memory/ttl1.md", "content")
        
        fuse_instance._set_virtual_content("/memory/ttl1.md", ":ttl", "5m")
        
        node = avm_instance.read("/memory/ttl1.md")
        assert "expires_at" in node.meta
    
    def test_ttl_read_remaining(self, avm_instance, fuse_instance):
        """Test reading remaining TTL."""
        avm_instance.write("/memory/ttl2.md", "content")
        fuse_instance._set_virtual_content("/memory/ttl2.md", ":ttl", "60m")
        
        content = fuse_instance._get_virtual_content("/memory/ttl2.md", ":ttl", None)
        # Should show remaining time
        assert "m" in content or "h" in content or "never" in content
    
    def test_ttl_never(self, avm_instance, fuse_instance):
        """Test setting TTL to never."""
        avm_instance.write("/memory/ttl3.md", "content",
                          meta={"expires_at": "2026-01-01T00:00:00"})
        
        fuse_instance._set_virtual_content("/memory/ttl3.md", ":ttl", "never")
        
        node = avm_instance.read("/memory/ttl3.md")
        assert "expires_at" not in node.meta


class TestDeltaFirstRead:
    """Test :delta first read returns full content."""
    
    def test_delta_first_read_full_content(self, avm_instance):
        """Test delta returns full content on first read."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, "new_agent")
        
        avm_instance.write("/memory/shared/first.md", "Line 1\nLine 2\nLine 3")
        
        content = fuse._get_virtual_content("/memory/shared/first.md", ":delta", None)
        assert "first read" in content
        assert "Line 1" in content
        assert "Line 2" in content
    
    def test_delta_updates_marker_on_read(self, avm_instance):
        """Test delta updates marker after showing content."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, "marker_agent")
        
        avm_instance.write("/memory/shared/marker.md", "content")
        
        # First read
        fuse._get_virtual_content("/memory/shared/marker.md", ":delta", None,
                                  update_markers=True)
        
        # Check marker was set
        node = avm_instance.read("/memory/shared/marker.md")
        assert node.meta.get("last_read", {}).get("marker_agent") == node.version


class TestAutoMarkRead:
    """Test auto-mark on shared file read."""
    
    def test_auto_mark_on_read(self, avm_instance):
        """Test reading shared file auto-marks position."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, "reader")
        
        avm_instance.write("/memory/shared/automark.md", "content")
        
        # Simulate read via FUSE read method
        fuse.fd = 0
        fuse._open_files = {}
        fuse._write_buffers = {}
        
        fd = fuse.open("/memory/shared/automark.md", 0)
        fuse.read("/memory/shared/automark.md", 1000, 0, fd)
        
        # Check marker was set
        node = avm_instance.read("/memory/shared/automark.md")
        assert "reader" in node.meta.get("last_read", {})
    
    def test_no_auto_mark_on_private(self, avm_instance):
        """Test private files don't get auto-marked."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, "reader")
        
        avm_instance.write("/memory/private/reader/note.md", "content",
                          meta={"created_by": "reader"})
        
        fuse.fd = 0
        fuse._open_files = {}
        fuse._write_buffers = {}
        
        fd = fuse.open("/memory/private/reader/note.md", 0)
        fuse.read("/memory/private/reader/note.md", 1000, 0, fd)
        
        # Private files should not have last_read
        node = avm_instance.read("/memory/private/reader/note.md")
        assert "last_read" not in node.meta


class TestWriteAppend:
    """Test write with append mode."""
    
    def test_write_loads_existing(self, avm_instance):
        """Test write loads existing content."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, "writer")
        fuse.fd = 0
        fuse._open_files = {}
        fuse._write_buffers = {}
        
        # Create file with content
        avm_instance.write("/memory/append.md", "Line 1\n")
        
        # Open for write
        fd = fuse.open("/memory/append.md", 0)
        
        # Write at offset (simulating append)
        fuse.write("/memory/append.md", b"Line 2\n", 7, fd)
        
        # Release to flush
        fuse.release("/memory/append.md", fd)
        
        # Check content
        node = avm_instance.read("/memory/append.md")
        assert "Line 1" in node.content
        assert "Line 2" in node.content
    
    def test_write_overwrite_at_position(self, avm_instance):
        """Test write can overwrite at position."""
        from avm.fuse_mount import AVMFuse
        fuse = AVMFuse(avm_instance, "writer")
        fuse.fd = 0
        fuse._open_files = {}
        fuse._write_buffers = {}
        
        avm_instance.write("/memory/overwrite.md", "AAABBBCCC")
        
        fd = fuse.open("/memory/overwrite.md", 0)
        fuse.write("/memory/overwrite.md", b"XXX", 3, fd)
        fuse.release("/memory/overwrite.md", fd)
        
        node = avm_instance.read("/memory/overwrite.md")
        assert node.content == "AAAXXXCCC"


class TestStoreVersioning:
    """Test store version behavior."""
    
    def test_version_unchanged_same_content(self, avm_instance):
        """Test version doesn't bump when content unchanged."""
        avm_instance.write("/memory/version.md", "content")
        node1 = avm_instance.read("/memory/version.md")
        v1 = node1.version
        
        # Write same content with different meta
        node1.meta["key"] = "value"
        avm_instance.store.put_node(node1, save_diff=False)
        
        node2 = avm_instance.read("/memory/version.md")
        assert node2.version == v1
    
    def test_version_bumps_on_content_change(self, avm_instance):
        """Test version bumps when content changes."""
        avm_instance.write("/memory/version2.md", "content1")
        node1 = avm_instance.read("/memory/version2.md")
        v1 = node1.version
        
        avm_instance.write("/memory/version2.md", "content2")
        
        node2 = avm_instance.read("/memory/version2.md")
        assert node2.version == v1 + 1
