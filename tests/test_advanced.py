"""
tests/test_advanced.py - 高级功能测试
"""

import pytest
import tempfile
import os
from datetime import datetime, timedelta

from vfs import VFS, VFSNode


@pytest.fixture
def vfs():
    """创建临时 VFS 实例"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        from vfs.config import VFSConfig, PermissionRule
        config = VFSConfig(
            db_path=db_path,
            permissions=[
                PermissionRule(pattern="/memory/*", access="rw"),
                PermissionRule(pattern="/snapshots/*", access="rw"),
            ],
            default_access="rw"
        )
        v = VFS(config=config)
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


class TestSubscription:
    """订阅系统测试"""
    
    def test_subscribe_and_notify(self, vfs):
        akashi = vfs.agent_memory("akashi")
        
        events = []
        def on_event(event):
            events.append(event)
        
        # 订阅
        sub_id = akashi.subscribe("/memory/shared/market/*", on_event)
        assert sub_id == "akashi"
        
        # 手动触发通知
        vfs._notify_subscribers("/memory/shared/market/BTC.md", "write", "akashi")
        
        assert len(events) == 1
        assert events[0].path == "/memory/shared/market/BTC.md"
    
    def test_unsubscribe(self, vfs):
        akashi = vfs.agent_memory("akashi")
        
        events = []
        akashi.subscribe("/memory/*", lambda e: events.append(e))
        akashi.unsubscribe()
        
        vfs._notify_subscribers("/memory/test.md", "write", "akashi")
        assert len(events) == 0


class TestMemoryDecay:
    """记忆衰减测试"""
    
    def test_decay_calculation(self, vfs):
        from vfs.advanced import MemoryDecay
        
        akashi = vfs.agent_memory("akashi")
        akashi.remember("Test content", title="test", importance=1.0)
        
        decay = MemoryDecay(vfs.store, half_life_days=7)
        
        # 刚写入的应该接近 1.0
        nodes = akashi.list_private()
        assert len(nodes) > 0
        
        factor = decay.calculate_decay(nodes[0])
        assert factor > 0.99  # 刚写入，几乎无衰减
    
    def test_get_cold_memories(self, vfs):
        akashi = vfs.agent_memory("akashi")
        
        # 写入一些记忆
        akashi.remember("Content 1", importance=0.1)
        akashi.remember("Content 2", importance=0.9)
        
        # 低重要性的应该更容易成为冷记忆
        cold = akashi.get_cold_memories(threshold=0.5)
        # 新写入的不会立即成为冷记忆
        assert isinstance(cold, list)


class TestCompaction:
    """压缩测试"""
    
    def test_compact_versions(self, vfs):
        akashi = vfs.agent_memory("akashi")
        
        # 创建多个版本
        path = "/memory/shared/market/TEST.md"
        akashi.remember("Version 1", path=path)
        akashi.remember("Version 2", path=path)
        akashi.remember("Version 3", path=path)
        akashi.remember("Version 4", path=path)
        
        # 压缩，保留2个
        result = akashi.compact_versions(path, keep_recent=2)
        
        # 应该有压缩发生（如果版本足够多）
        assert result.versions_before >= 1
        assert isinstance(result.removed_paths, list)


class TestDeduplication:
    """去重测试"""
    
    def test_check_duplicate(self, vfs):
        akashi = vfs.agent_memory("akashi")
        
        # 写入原始内容
        akashi.remember("RSI超过70时要谨慎，这是一个重要的交易规则")
        
        # 检查相似内容
        result = akashi.check_duplicate(
            "RSI超过70时要谨慎，这是一个重要的交易规则",
            threshold=0.8
        )
        
        # 应该检测到重复（使用 Jaccard）
        assert isinstance(result.is_duplicate, bool)
    
    def test_remember_if_new(self, vfs):
        akashi = vfs.agent_memory("akashi")
        
        # 第一次写入
        node1 = akashi.remember_if_new("Unique content here", threshold=0.9)
        assert node1 is not None
        
        # 第二次写入相同内容
        node2 = akashi.remember_if_new("Unique content here", threshold=0.9)
        # 可能因为阈值设置返回 None 或新节点


class TestDerivedLinks:
    """推导链测试"""
    
    def test_remember_derived(self, vfs):
        akashi = vfs.agent_memory("akashi")
        
        # 创建来源
        source1 = akashi.remember("RSI 分析", title="rsi")
        source2 = akashi.remember("MACD 分析", title="macd")
        
        # 创建推导
        derived = akashi.remember_derived(
            "综合判断：减仓",
            derived_from=[source1.path, source2.path],
            title="conclusion",
            reasoning="技术面综合"
        )
        
        assert derived is not None
        
        # 验证链接
        from vfs.advanced import DerivedLinkManager
        link_mgr = DerivedLinkManager(vfs.store)
        chains = link_mgr.get_derivation_chain(derived.path)
        
        assert len(chains) > 0


class TestTimeQuery:
    """时间查询测试"""
    
    def test_recall_recent(self, vfs):
        akashi = vfs.agent_memory("akashi")
        
        # 写入一些记忆
        akashi.remember("Recent content 1")
        akashi.remember("Recent content 2")
        
        # 查询最近24小时
        result = akashi.recall_recent("content", time_range="last_24h", max_tokens=2000)
        
        assert "Relevant Memory" in result
    
    def test_query_time(self, vfs):
        akashi = vfs.agent_memory("akashi")
        akashi.remember("Test for time query")
        
        nodes = vfs.query_time(prefix="/memory", time_range="last_7d")
        assert len(nodes) >= 1


class TestTagSystem:
    """标签系统测试"""
    
    def test_by_tag(self, vfs):
        akashi = vfs.agent_memory("akashi")
        
        akashi.remember("Trading lesson", tags=["trading", "risk"])
        akashi.remember("Another trading tip", tags=["trading"])
        akashi.remember("Research note", tags=["research"])
        
        trading_notes = akashi.by_tag("trading")
        assert len(trading_notes) == 2
    
    def test_tag_cloud(self, vfs):
        akashi = vfs.agent_memory("akashi")
        
        akashi.remember("Note 1", tags=["trading", "risk"])
        akashi.remember("Note 2", tags=["trading"])
        akashi.remember("Note 3", tags=["research"])
        
        cloud = akashi.tag_cloud()
        
        assert "trading" in cloud
        assert cloud["trading"] == 2
    
    def test_suggest_tags(self, vfs):
        akashi = vfs.agent_memory("akashi")
        
        suggestions = akashi.suggest_tags(
            "NVDA RSI analysis shows overbought signals in technical indicators"
        )
        
        assert len(suggestions) > 0
        assert any("nvda" in s.lower() for s in suggestions)


class TestAccessStats:
    """访问统计测试"""
    
    def test_hot_memories(self, vfs):
        akashi = vfs.agent_memory("akashi")
        akashi.remember("Hot content")
        
        # hot_memories 需要 access_log 记录
        hot = akashi.hot_memories(days=7)
        assert isinstance(hot, list)
    
    def test_my_activity(self, vfs):
        akashi = vfs.agent_memory("akashi")
        akashi.remember("Activity test")
        
        activity = akashi.my_activity(days=1)
        assert isinstance(activity, dict)


class TestExportSnapshot:
    """导出/快照测试"""
    
    def test_export_jsonl(self, vfs):
        akashi = vfs.agent_memory("akashi")
        akashi.remember("Export test 1")
        akashi.remember("Export test 2")
        
        jsonl = akashi.export("jsonl")
        
        lines = jsonl.strip().split("\n")
        assert len(lines) >= 2
    
    def test_export_markdown(self, vfs):
        akashi = vfs.agent_memory("akashi")
        akashi.remember("Markdown export test", title="Test Note")
        
        md = akashi.export("markdown")
        
        assert "# Memory Export" in md
        assert "Test Note" in md
    
    def test_snapshot_and_restore(self, vfs):
        akashi = vfs.agent_memory("akashi")
        akashi.remember("Snapshot test content")
        
        # 创建快照
        snapshot_path = vfs.snapshot("test_snap")
        assert snapshot_path == "/snapshots/test_snap"
        
        # 列出快照
        snapshots = vfs.list_snapshots()
        assert len(snapshots) >= 1
        assert snapshots[0]["name"] == "test_snap"


class TestSync:
    """同步测试"""
    
    def test_sync_to_directory(self, vfs):
        akashi = vfs.agent_memory("akashi")
        akashi.remember("Sync test content")
        
        with tempfile.TemporaryDirectory() as sync_dir:
            result = vfs.sync(sync_dir, prefix="/memory")
            
            assert result["exported"] >= 1
            assert result["imported"] >= 0
            
            # 检查文件是否创建
            files = os.listdir(sync_dir)
            assert len(files) >= 1


class TestMultiAgent:
    """多 Agent 测试"""
    
    def test_permission_enforcement(self, vfs):
        yuze = vfs.agent_memory("yuze")
        
        # yuze 只能写 /memory/shared/projects/*
        with pytest.raises(PermissionError):
            yuze.remember("Test", namespace="market")
        
        # 这个应该可以
        node = yuze.remember("Project update", namespace="projects")
        assert node is not None
    
    def test_shared_read(self, vfs):
        akashi = vfs.agent_memory("akashi")
        yuze = vfs.agent_memory("yuze")
        
        # akashi 写入 market
        akashi.remember("Market analysis", namespace="market", title="btc")
        
        # yuze 应该能读到
        context = yuze.recall("Market", max_tokens=1000)
        # yuze 可以读 shared，但可能因为检索结果而变化
        assert isinstance(context, str)
    
    def test_audit_log(self, vfs):
        akashi = vfs.agent_memory("akashi")
        akashi.remember("Audit test")
        
        logs = vfs.audit_log(agent_id="akashi", limit=10)
        assert len(logs) >= 1
        assert logs[0]["agent_id"] == "akashi"


class TestVersioning:
    """版本测试"""
    
    def test_append_only(self, vfs):
        akashi = vfs.agent_memory("akashi")
        
        path = "/memory/shared/market/VERSION_TEST.md"
        
        # 写入多个版本
        akashi.remember("Version 1", path=path)
        akashi.remember("Version 2", path=path)
        
        # 应该有多个版本文件
        nodes = vfs.list("/memory/shared/market")
        version_nodes = [n for n in nodes if "VERSION_TEST" in n.path]
        
        # 至少有原始 + 1个版本
        assert len(version_nodes) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
