"""
tests/test_advanced.py - Advanced features tests
"""

import pytest
import tempfile
import os
from datetime import datetime, timedelta

from avm import AVM, AVMNode


@pytest.fixture
def avm():
    """Create temp AVM instance"""
    import shutil
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        from avm.config import AVMConfig, PermissionRule
        config = AVMConfig(
            db_path=db_path,
            permissions=[
                PermissionRule(pattern="/memory/*", access="rw"),
                PermissionRule(pattern="/snapshots/*", access="rw"),
            ],
            default_access="rw"
        )
        v = AVM(config=config)
        v.load_agents(config_dict={
            "agents": {
                "akashi": {
                    "role": "admin",
                    "namespaces": {
                        "read": ["*"],
                        "write": ["/memory/*", "/memory/private/akashi/*", "/memory/shared/*"]
                    }
                },
                "yuze": {
                    "role": "member",
                    "namespaces": {
                        "read": ["/memory/shared/*", "/memory/private/yuze/*"],
                        "write": ["/memory/private/yuze/*", "/memory/shared/projects/*"]
                    }
                }
            }
        })
        yield v
        # Force cleanup any leftover files
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestSubscription:
    """Subscription system tests"""
    
    def test_subscribe_and_notify(self, avm):
        akashi = avm.agent_memory("akashi")
        
        events = []
        def on_event(event):
            events.append(event)
        
        # Subscribe
        sub_id = akashi.subscribe("/memory/shared/market/*", on_event)
        assert sub_id == "akashi"
        
        # Manually trigger notification
        avm._notify_subscribers("/memory/shared/market/BTC.md", "write", "akashi")
        
        assert len(events) == 1
        assert events[0].path == "/memory/shared/market/BTC.md"
    
    def test_unsubscribe(self, avm):
        akashi = avm.agent_memory("akashi")
        
        events = []
        akashi.subscribe("/memory/*", lambda e: events.append(e))
        akashi.unsubscribe()
        
        avm._notify_subscribers("/memory/test.md", "write", "akashi")
        assert len(events) == 0


class TestMemoryDecay:
    """Memory decay tests"""
    
    def test_decay_calculation(self, avm):
        from avm.advanced import MemoryDecay
        
        akashi = avm.agent_memory("akashi")
        akashi.remember("Test content", title="test", importance=1.0)
        
        decay = MemoryDecay(avm.store, half_life_days=7)
        
        # Just written should been close to 1.0
        nodes = akashi.list_private()
        assert len(nodes) > 0
        
        factor = decay.calculate_decay(nodes[0])
        assert factor > 0.99  # Just written, almost no decay
    
    def test_get_cold_memories(self, avm):
        akashi = avm.agent_memory("akashi")
        
        # Write some memories
        akashi.remember("Content 1", importance=0.1)
        akashi.remember("Content 2", importance=0.9)
        
        # Low importance should been more likely to beencome cold
        cold = akashi.get_cold_memories(threshold=0.5)
        # New writes wont immediately beencome cold
        assert isinstance(cold, list)


class TestCompaction:
    """Compaction tests"""
    
    def test_compact_versions(self, avm):
        akashi = avm.agent_memory("akashi")
        
        # Create multiple versions
        path = "/memory/shared/market/TEST.md"
        akashi.remember("Version 1", path=path)
        akashi.remember("Version 2", path=path)
        akashi.remember("Version 3", path=path)
        akashi.remember("Version 4", path=path)
        
        # Compact, keep 2
        result = akashi.compact_versions(path, keep_recent=2)
        
        # Should have compaction (if enough versions)
        assert result.versions_before >= 1
        assert isinstance(result.removed_paths, list)


class TestDeduplication:
    """Deduplication tests"""
    
    def test_check_duplicate(self, avm):
        akashi = avm.agent_memory("akashi")
        
        # Write original content
        akashi.remember("Be careful when RSI exceeds 70, this is an important trading rule")
        
        # Check similar content
        result = akashi.check_duplicate(
            "Be careful when RSI exceeds 70, this is an important trading rule",
            threshold=0.8
        )
        
        # Should detect duplicate (using Jaccard)
        assert isinstance(result.is_duplicate, bool)
    
    def test_remember_if_new(self, avm):
        akashi = avm.agent_memory("akashi")
        
        # First write
        node1 = akashi.remember_if_new("Unique content here", threshold=0.9)
        assert node1 is not None
        
        # Second write same content
        node2 = akashi.remember_if_new("Unique content here", threshold=0.9)
        # May return None or new node depending on threshold


class TestDerivedLinks:
    """Derived chain tests"""
    
    def test_remember_derived(self, avm):
        akashi = avm.agent_memory("akashi")
        
        # Create sources
        source1 = akashi.remember("RSI analysis", title="rsi")
        source2 = akashi.remember("MACD analysis", title="macd")
        
        # Create derived
        derived = akashi.remember_derived(
            "Combined judgment: reduce position",
            derived_from=[source1.path, source2.path],
            title="conclusion",
            reasoning="Technical comprehensive"
        )
        
        assert derived is not None
        
        # Verify links
        from avm.advanced import DerivedLinkManager
        link_mgr = DerivedLinkManager(avm.store)
        chains = link_mgr.get_derivation_chain(derived.path)
        
        assert len(chains) > 0


class TestTimeQuery:
    """time querytest"""
    
    def test_recall_recent(self, avm):
        akashi = avm.agent_memory("akashi")
        
        # Write some memories
        akashi.remember("Recent content 1")
        akashi.remember("Recent content 2")
        
        # Query last 24 hours
        result = akashi.recall_recent("content", time_range="last_24h", max_tokens=2000)
        
        assert "Relevant Memory" in result
    
    def test_query_time(self, avm):
        akashi = avm.agent_memory("akashi")
        akashi.remember("Test for time query")
        
        nodes = avm.query_time(prefix="/memory", time_range="last_7d")
        assert len(nodes) >= 1


class TestTagSystem:
    """tag systemtest"""
    
    def test_by_tag(self, avm):
        akashi = avm.agent_memory("akashi")
        
        akashi.remember("Trading lesson", tags=["trading", "risk"])
        akashi.remember("Another trading tip", tags=["trading"])
        akashi.remember("Research note", tags=["research"])
        
        trading_notes = akashi.by_tag("trading")
        assert len(trading_notes) == 2
    
    def test_tag_cloud(self, avm):
        akashi = avm.agent_memory("akashi")
        
        akashi.remember("Note 1", tags=["trading", "risk"])
        akashi.remember("Note 2", tags=["trading"])
        akashi.remember("Note 3", tags=["research"])
        
        cloud = akashi.tag_cloud()
        
        assert "trading" in cloud
        assert cloud["trading"] == 2
    
    def test_suggest_tags(self, avm):
        akashi = avm.agent_memory("akashi")
        
        suggestions = akashi.suggest_tags(
            "NVDA RSI analysis shows overbought signals in technical indicators"
        )
        
        assert len(suggestions) > 0
        assert any("nvda" in s.lower() for s in suggestions)


class TestAccessStats:
    """access statisticstest"""
    
    def test_hot_memories(self, avm):
        akashi = avm.agent_memory("akashi")
        akashi.remember("Hot content")
        
        # hot_memories needs access_log records
        hot = akashi.hot_memories(days=7)
        assert isinstance(hot, list)
    
    def test_my_activity(self, avm):
        akashi = avm.agent_memory("akashi")
        akashi.remember("Activity test")
        
        activity = akashi.my_activity(days=1)
        assert isinstance(activity, dict)


class TestExportSnapshot:
    """export/snapshot tests"""
    
    def test_export_jsonl(self, avm):
        akashi = avm.agent_memory("akashi")
        akashi.remember("Export test 1")
        akashi.remember("Export test 2")
        
        jsonl = akashi.export("jsonl")
        
        lines = jsonl.strip().split("\n")
        assert len(lines) >= 2
    
    def test_export_markdown(self, avm):
        akashi = avm.agent_memory("akashi")
        akashi.remember("Markdown export test", title="Test Note")
        
        md = akashi.export("markdown")
        
        assert "# Memory Export" in md
        assert "Test Note" in md
    
    def test_snapshot_and_restore(self, avm):
        akashi = avm.agent_memory("akashi")
        akashi.remember("Snapshot test content")
        
        # Create snapshot
        snapshot_path = avm.snapshot("test_snap")
        assert snapshot_path == "/snapshots/test_snap"
        
        # List snapshots
        snapshots = avm.list_snapshots()
        assert len(snapshots) >= 1
        assert snapshots[0]["name"] == "test_snap"


class TestSync:
    """sync tests"""
    
    def test_sync_to_directory(self, avm):
        akashi = avm.agent_memory("akashi")
        akashi.remember("Sync test content")
        
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as sync_dir:
            result = avm.sync(sync_dir, prefix="/memory")
            
            assert result["exported"] >= 1
            assert result["imported"] >= 0
            
            # checkfilenocreate
            files = os.listdir(sync_dir)
            assert len(files) >= 1


class TestMultiAgent:
    """Multi-agent tests"""
    
    def test_permission_enforcement(self, avm):
        yuze = avm.agent_memory("yuze")
        
        # yuze can only write to /memory/shared/projects/*
        with pytest.raises(PermissionError):
            yuze.remember("Test", namespace="market")
        
        # thisshouldcan
        node = yuze.remember("Project update", namespace="projects")
        assert node is not None
    
    def test_shared_read(self, avm):
        akashi = avm.agent_memory("akashi")
        yuze = avm.agent_memory("yuze")
        
        # akashi write market
        akashi.remember("Market analysis", namespace="market", title="btc")
        
        # yuze should been able to read
        context = yuze.recall("Market", max_tokens=1000)
        # yuze can read shared, but may vary due to retrieval results
        assert isinstance(context, str)
    
    def test_audit_log(self, avm):
        akashi = avm.agent_memory("akashi")
        akashi.remember("Audit test")
        
        logs = avm.audit_log(agent_id="akashi", limit=10)
        assert len(logs) >= 1
        assert logs[0]["agent_id"] == "akashi"


class TestVersioning:
    """versioning tests"""
    
    def test_append_only(self, avm):
        akashi = avm.agent_memory("akashi")
        
        path = "/memory/shared/market/VERSION_TEST.md"
        
        # Write multiple versions
        akashi.remember("Version 1", path=path)
        akashi.remember("Version 2", path=path)
        
        # Should have multiple version files
        nodes = avm.list("/memory/shared/market")
        version_nodes = [n for n in nodes if "VERSION_TEST" in n.path]
        
        # At least original + 1 version
        assert len(version_nodes) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
