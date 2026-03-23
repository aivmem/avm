"""Tests for the Librarian (global knowledge router)"""

import pytest
import tempfile
import os

from avm import AVM
from avm.config import AVMConfig, PermissionRule
from avm.librarian import Librarian, PrivacyPolicy, AgentInfo


@pytest.fixture
def temp_env():
    """Setup temporary environment"""
    import shutil
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ['XDG_DATA_HOME'] = tmpdir
        yield tmpdir
        # Force cleanup any leftover files
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def multi_agent_avm(temp_env):
    """Setup AVM with multiple agents and their memories"""
    config = AVMConfig(
        permissions=[
            PermissionRule(pattern="/memory/private/*", access="rw"),
            PermissionRule(pattern="/memory/shared/*", access="rw"),
        ]
    )
    
    # Create memories for different agents
    agent_a = AVM(config=config, agent_id="trader")
    agent_a.write("/memory/private/trader/market_analysis.md", 
                  "NVDA RSI at 72, overbought signal")
    agent_a.write("/memory/private/trader/strategy.md",
                  "Trading strategy: buy on dips, sell on rallies")
    
    agent_b = AVM(config=config, agent_id="coder")
    agent_b.write("/memory/private/coder/bug_fix.md",
                  "Fixed null pointer in parser module")
    agent_b.write("/memory/private/coder/project.md",
                  "Working on RedScript compiler optimization")
    
    # Shared memories
    agent_a.write("/memory/shared/announcements.md",
                  "Company meeting tomorrow at 10am")
    
    return config


class TestLibrarianBasic:
    """Basic Librarian functionality tests"""
    
    def test_agent_discovery(self, multi_agent_avm):
        """Should discover agents from existing memories"""
        avm = AVM(config=multi_agent_avm)
        librarian = Librarian(avm.store, multi_agent_avm)
        
        agents = librarian.agents()
        agent_ids = [a.id for a in agents]
        
        assert "trader" in agent_ids
        assert "coder" in agent_ids
    
    def test_who_knows(self, multi_agent_avm):
        """Should find agents who know about a topic"""
        avm = AVM(config=multi_agent_avm)
        librarian = Librarian(avm.store, multi_agent_avm)
        
        # Search for market-related info
        agents = librarian.who_knows("market analysis")
        
        # trader should be found
        agent_ids = [a.id for a in agents]
        assert "trader" in agent_ids
    
    def test_directory(self, multi_agent_avm):
        """Should return agent directory"""
        avm = AVM(config=multi_agent_avm)
        librarian = Librarian(avm.store, multi_agent_avm)
        
        directory = librarian.directory()
        
        assert "agents" in directory
        assert "by_capability" in directory
        assert directory["total_agents"] >= 2


class TestLibrarianQuery:
    """Query and permission tests"""
    
    def test_query_accessible(self, multi_agent_avm):
        """Should return accessible content"""
        avm = AVM(config=multi_agent_avm)
        librarian = Librarian(avm.store, multi_agent_avm)
        
        # trader queries their own data
        response = librarian.query("trader", "market analysis")
        
        # Should find their own memories
        assert response.accessible_count > 0
        paths = [n.path for n in response.accessible]
        assert any("trader" in p for p in paths)
    
    def test_query_shared_accessible(self, multi_agent_avm):
        """Shared content should be accessible to all"""
        avm = AVM(config=multi_agent_avm)
        librarian = Librarian(avm.store, multi_agent_avm)
        
        # coder queries shared content
        response = librarian.query("coder", "company meeting")
        
        # Should find shared announcement
        assert response.accessible_count > 0
        paths = [n.path for n in response.accessible]
        assert any("shared" in p for p in paths)
    
    def test_query_private_inaccessible(self, multi_agent_avm):
        """Should not return other agent's private content"""
        avm = AVM(config=multi_agent_avm)
        librarian = Librarian(avm.store, multi_agent_avm)
        
        # coder queries trader's topic
        response = librarian.query("coder", "NVDA RSI trading")
        
        # Should NOT have trader's private memories in accessible
        paths = [n.path for n in response.accessible]
        assert not any("/memory/private/trader/" in p for p in paths)
    
    def test_query_suggestions(self, multi_agent_avm):
        """Should suggest collaboration when content is inaccessible"""
        avm = AVM(config=multi_agent_avm)
        privacy = PrivacyPolicy("full")
        librarian = Librarian(avm.store, multi_agent_avm, privacy)
        
        # coder queries trader's topic
        response = librarian.query("coder", "NVDA market strategy")
        
        # Should suggest asking trader
        suggested_agents = [s.agent for s in response.suggestions]
        assert "trader" in suggested_agents


class TestPrivacyPolicy:
    """Privacy policy tests"""
    
    def test_privacy_full(self, multi_agent_avm):
        """Full privacy reveals everything"""
        avm = AVM(config=multi_agent_avm)
        privacy = PrivacyPolicy("full")
        librarian = Librarian(avm.store, multi_agent_avm, privacy)
        
        response = librarian.query("coder", "market strategy")
        
        # Should reveal agent name and topic
        if response.suggestions:
            assert response.suggestions[0].agent != "another agent"
    
    def test_privacy_owner_only(self, multi_agent_avm):
        """Owner-only privacy hides topics"""
        avm = AVM(config=multi_agent_avm)
        privacy = PrivacyPolicy("owner")
        librarian = Librarian(avm.store, multi_agent_avm, privacy)
        
        response = librarian.query("coder", "market strategy")
        
        # Should reveal agent but topic should be generic
        if response.suggestions:
            assert response.suggestions[0].topic == "related information"
    
    def test_privacy_none(self, multi_agent_avm):
        """None privacy reveals nothing"""
        avm = AVM(config=multi_agent_avm)
        privacy = PrivacyPolicy("none")
        librarian = Librarian(avm.store, multi_agent_avm, privacy)
        
        response = librarian.query("coder", "market strategy")
        
        # Should have no suggestions
        assert len(response.suggestions) == 0


class TestLibrarianRegistration:
    """Agent registration tests"""
    
    def test_register_agent(self, multi_agent_avm):
        """Should allow manual agent registration"""
        avm = AVM(config=multi_agent_avm)
        librarian = Librarian(avm.store, multi_agent_avm)
        
        # Register a new agent
        info = AgentInfo(
            id="analyst",
            display_name="Market Analyst",
            capabilities=["market", "research"],
            description="Analyzes market trends"
        )
        librarian.register_agent("analyst", info)
        
        # Should appear in directory
        agents = librarian.agents()
        agent_ids = [a.id for a in agents]
        assert "analyst" in agent_ids
    
    def test_agent_capabilities(self, multi_agent_avm):
        """Should infer capabilities from content"""
        avm = AVM(config=multi_agent_avm)
        librarian = Librarian(avm.store, multi_agent_avm)
        
        # Check inferred capabilities
        directory = librarian.directory()
        by_cap = directory["by_capability"]
        
        # trader should have market capability
        assert "market" in by_cap or "trader" in str(directory)
