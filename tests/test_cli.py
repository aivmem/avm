"""Tests for CLI functionality."""

import os
import sys
import argparse
import tempfile
import pytest
from io import StringIO
from unittest.mock import patch, MagicMock

from avm.cli import (
    main,
    cmd_write,
    cmd_read,
    cmd_list,
    cmd_search,
    cmd_delete,
    cmd_stats,
    cmd_links,
    cmd_history,
    cmd_config,
)


def make_args(**kwargs):
    """Create argparse.Namespace with given attributes."""
    return argparse.Namespace(**kwargs)


@pytest.fixture
def temp_env():
    """Create temp environment for CLI tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["XDG_DATA_HOME"] = tmpdir
        yield tmpdir


class TestCLICommands:
    """Test CLI commands via main()."""
    
    def test_write_and_read(self, temp_env):
        """Test write and read commands."""
        # Write
        with patch('sys.argv', ['avm', 'write', '/memory/test.md', '-c', 'Hello']):
            result = main()
            assert result == 0
        
        # Read
        with patch('sys.argv', ['avm', 'read', '/memory/test.md']):
            result = main()
            assert result == 0
    
    def test_write_with_meta(self, temp_env):
        """Test write with metadata."""
        with patch('sys.argv', ['avm', 'write', '/memory/meta.md', '-c', 'With meta', '-m', '{"key": "value"}']):
            result = main()
            assert result == 0
    
    def test_list(self, temp_env):
        """Test list command."""
        # Write some files first
        with patch('sys.argv', ['avm', 'write', '/memory/a.md', '-c', 'A']):
            main()
        with patch('sys.argv', ['avm', 'write', '/memory/b.md', '-c', 'B']):
            main()
        
        # List
        with patch('sys.argv', ['avm', 'list', '/memory']):
            result = main()
            assert result == 0
    
    def test_search(self, temp_env):
        """Test search command."""
        with patch('sys.argv', ['avm', 'write', '/memory/searchable.md', '-c', 'unique keyword']):
            main()
        
        with patch('sys.argv', ['avm', 'search', 'unique']):
            result = main()
            assert result == 0
    
    def test_delete(self, temp_env):
        """Test delete command."""
        with patch('sys.argv', ['avm', 'write', '/memory/delete.md', '-c', 'Delete me']):
            main()
        
        with patch('sys.argv', ['avm', 'delete', '/memory/delete.md']):
            result = main()
            assert result == 0
    
    def test_stats(self, temp_env):
        """Test stats command."""
        with patch('sys.argv', ['avm', 'stats']):
            result = main()
            assert result == 0
    
    def test_links(self, temp_env):
        """Test links command."""
        # Create nodes
        with patch('sys.argv', ['avm', 'write', '/memory/source.md', '-c', 'Source']):
            main()
        with patch('sys.argv', ['avm', 'write', '/memory/target.md', '-c', 'Target']):
            main()
        
        # Create link
        with patch('sys.argv', ['avm', 'link', '/memory/source.md', '/memory/target.md']):
            main()
        
        # Get links
        with patch('sys.argv', ['avm', 'links', '/memory/source.md']):
            result = main()
            assert result == 0
    
    def test_history(self, temp_env):
        """Test history command."""
        # Create versions
        for i in range(3):
            with patch('sys.argv', ['avm', 'write', '/memory/versioned.md', '-c', f'Version {i}']):
                main()
        
        with patch('sys.argv', ['avm', 'history', '/memory/versioned.md']):
            result = main()
            assert result == 0
    
    def test_config(self, temp_env):
        """Test config command."""
        with patch('sys.argv', ['avm', 'config']):
            result = main()
            assert result == 0


class TestCLIMain:
    """Test main CLI entry point."""
    
    def test_main_no_args(self, temp_env):
        """Test main with no arguments shows help."""
        with patch('sys.argv', ['avm']):
            with pytest.raises(SystemExit) as exc_info:
                main()
            # argparse exits with 0 for help or 2 for error
            assert exc_info.value.code in (0, 2, None)
    
    def test_main_stats(self, temp_env):
        """Test main with stats command."""
        with patch('sys.argv', ['avm', 'stats']):
            result = main()
            assert result == 0
    
    def test_main_write(self, temp_env):
        """Test main with write command."""
        with patch('sys.argv', ['avm', 'write', '/memory/main-test.md', '-c', 'Test']):
            result = main()
            assert result == 0
    
    def test_main_read(self, temp_env):
        """Test main with read command."""
        # Write first
        with patch('sys.argv', ['avm', 'write', '/memory/read-main.md', '-c', 'Content']):
            main()
        
        # Read
        with patch('sys.argv', ['avm', 'read', '/memory/read-main.md']):
            result = main()
            assert result == 0
    
    def test_main_list(self, temp_env):
        """Test main with list command."""
        with patch('sys.argv', ['avm', 'list']):
            result = main()
            assert result == 0
    
    def test_main_search(self, temp_env):
        """Test main with search command."""
        with patch('sys.argv', ['avm', 'search', 'test']):
            result = main()
            assert result == 0
