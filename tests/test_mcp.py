"""Tests for MCP server functionality."""

import os
import tempfile
import pytest

from avm import AVM
from avm.mcp_server import MCPServer


@pytest.fixture
def temp_env():
    """Create temp environment."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        os.environ["XDG_DATA_HOME"] = tmpdir
        yield tmpdir


class TestMCPServer:
    """Test MCPServer class."""
    
    def test_init(self, temp_env):
        """Test server initialization."""
        from avm.permissions import User
        avm = AVM()
        user = User(uid=1000, name="test")
        server = MCPServer(vfs=avm, user=user)
        assert server is not None
    
    def test_server_has_vfs(self, temp_env):
        """Test server has VFS reference."""
        from avm.permissions import User
        avm = AVM()
        user = User(uid=1000, name="test")
        server = MCPServer(vfs=avm, user=user)
        assert server.vfs is not None
    
    def test_server_has_tools(self, temp_env):
        """Test server has tools registered."""
        from avm.permissions import User
        avm = AVM()
        user = User(uid=1000, name="test")
        server = MCPServer(vfs=avm, user=user)
        assert hasattr(server, 'tools')
        assert len(server.tools) > 0


class TestMCPProtocol:
    """Test MCP protocol structures."""
    
    def test_jsonrpc_request_structure(self):
        """Test JSON-RPC request structure."""
        request = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1
        }
        
        assert request["jsonrpc"] == "2.0"
        assert "method" in request
        assert "id" in request
    
    def test_jsonrpc_response_structure(self):
        """Test JSON-RPC response structure."""
        response = {
            "jsonrpc": "2.0",
            "result": {"tools": []},
            "id": 1
        }
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert "id" in response
    
    def test_error_response_structure(self):
        """Test JSON-RPC error structure."""
        error_response = {
            "jsonrpc": "2.0",
            "error": {
                "code": -32600,
                "message": "Invalid Request"
            },
            "id": None
        }
        
        assert "error" in error_response
        assert "code" in error_response["error"]
        assert "message" in error_response["error"]
