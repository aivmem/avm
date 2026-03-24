"""Tests for provider functionality."""

import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from avm.providers.base import AVMProvider


@pytest.fixture
def temp_env():
    """Create temp environment."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        os.environ["XDG_DATA_HOME"] = tmpdir
        yield tmpdir


class TestAVMProvider:
    """Test AVMProvider base class."""
    
    def test_is_abstract(self):
        """Test AVMProvider is abstract."""
        with pytest.raises(TypeError):
            AVMProvider()


class TestMemoryProvider:
    """Test MemoryProvider class."""
    
    def test_import(self):
        """Test MemoryProvider can be imported."""
        from avm.providers.memory import MemoryProvider
        assert MemoryProvider is not None


class TestIndicatorsProvider:
    """Test TechnicalIndicatorsProvider."""
    
    def test_import(self):
        """Test can import."""
        from avm.providers.indicators import TechnicalIndicatorsProvider
        assert TechnicalIndicatorsProvider is not None


class TestWatchlistProvider:
    """Test WatchlistProvider."""
    
    def test_import(self):
        """Test can import."""
        from avm.providers.watchlist import WatchlistProvider
        assert WatchlistProvider is not None


class TestNewsProvider:
    """Test NewsProvider."""
    
    def test_import(self):
        """Test can import."""
        from avm.providers.news import NewsProvider
        assert NewsProvider is not None
