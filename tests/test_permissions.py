"""Tests for permissions functionality."""

import os
import tempfile
import pytest

from avm.permissions import (
    PermBits,
    Capability,
    User,
    Group,
    NodeOwnership,
    UserRegistry,
    PermissionManager,
    parse_mode,
    mode_to_string,
    string_to_mode,
)


@pytest.fixture
def temp_env():
    """Create temp environment."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        os.environ["XDG_DATA_HOME"] = tmpdir
        yield tmpdir


class TestPermBits:
    """Test PermBits flags."""
    
    def test_read_flag(self):
        """Test read permission flag."""
        assert PermBits.R is not None
    
    def test_write_flag(self):
        """Test write permission flag."""
        assert PermBits.W is not None
    
    def test_execute_flag(self):
        """Test execute permission flag."""
        assert PermBits.X is not None
    
    def test_combine_flags(self):
        """Test combining permission flags."""
        rw = PermBits.R | PermBits.W
        assert PermBits.R in rw
        assert PermBits.W in rw


class TestModeConversion:
    """Test mode conversion functions."""
    
    def test_parse_mode(self):
        """Test parsing mode integer."""
        result = parse_mode(0o755)
        assert "owner" in result
        assert "group" in result
        assert "other" in result
    
    def test_mode_to_string(self):
        """Test mode to string conversion."""
        s = mode_to_string(0o755)
        assert len(s) == 9
        assert s == "rwxr-xr-x"
    
    def test_string_to_mode(self):
        """Test string to mode conversion."""
        mode = string_to_mode("rwxr-xr-x")
        assert mode == 0o755


class TestUser:
    """Test User class."""
    
    def test_create_user(self):
        """Test creating a user."""
        user = User(uid=1000, name="testuser")
        assert user.uid == 1000
        assert user.name == "testuser"


class TestGroup:
    """Test Group class."""
    
    def test_create_group(self):
        """Test creating a group."""
        group = Group(gid=100, name="developers")
        assert group.gid == 100
        assert group.name == "developers"


class TestNodeOwnership:
    """Test NodeOwnership class."""
    
    def test_create_ownership(self):
        """Test creating node ownership."""
        ownership = NodeOwnership(owner="alice", group="developers", mode=0o644)
        assert ownership.owner == "alice"
        assert ownership.group == "developers"
        assert ownership.mode == 0o644


class TestUserRegistry:
    """Test UserRegistry class."""
    
    def test_create_registry(self):
        """Test creating user registry."""
        registry = UserRegistry()
        assert registry is not None


class TestPermissionManager:
    """Test PermissionManager class."""
    
    def test_create_manager(self):
        """Test creating permission manager."""
        manager = PermissionManager()
        assert manager is not None
