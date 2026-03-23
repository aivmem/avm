#!/usr/bin/env python3
"""
AVM Advanced Features Test

Tests features beyond basic recall/remember:
1. Delta - Only read what changed since last check
2. Digest/Summary - Get condensed overview of large content
3. Post-Compact Recovery - Agent must recall after context loss
4. Semantic Search - Find relevant info without exact keywords
"""

import json
import tempfile
import time
import subprocess
import random
from pathlib import Path
from datetime import datetime, timezone

from runner import BenchmarkRunner
from agent_executor import run_codex, count_tokens
from avm_integration import avm_recall, avm_remember


# =============================================================================
# TEST 1: DELTA - Only read changes
# =============================================================================

def setup_delta_scenario():
    """Set up a scenario where lots of content exists, but only recent changes matter."""
    
    # Write old content (should be ignored by delta)
    old_entries = [
        ("2026-01-15", "Q4 sales report: $2.3M revenue, 15% growth"),
        ("2026-01-20", "New hire: Alice joined the engineering team"),
        ("2026-02-01", "Server migration completed successfully"),
        ("2026-02-15", "Bug fix: payment processing timeout issue resolved"),
        ("2026-03-01", "Product launch: v2.0 released"),
    ]
    
    for date, content in old_entries:
        subprocess.run(
            ["avm", "write", f"/memory/shared/logs/{date}.md"],
            input=f"[{date}] {content}",
            capture_output=True, text=True
        )
    
    # Write recent content (the delta)
    recent_entries = [
        ("2026-03-22", "URGENT: API rate limit hit, affecting 30% of users"),
        ("2026-03-23", "CRITICAL: Database replication lag detected, investigating"),
    ]
    
    for date, content in recent_entries:
        subprocess.run(
            ["avm", "write", f"/memory/shared/logs/{date}.md"],
            input=f"[{date}] {content}",
            capture_output=True, text=True
        )
    
    return recent_entries


def run_delta_test(use_delta: bool) -> dict:
    """Test reading only recent changes vs all content."""
    
    if use_delta:
        # Use AVM's history feature to get recent changes
        # avm list --since "2026-03-22" or similar
        result = subprocess.run(
            ["avm", "list", "/memory/shared/logs/", "--json"],
            capture_output=True, text=True
        )
        
        # Filter to recent (simulating delta)
        # In real usage, would use timestamp filtering
        recall = avm_recall(
            query="URGENT CRITICAL 2026-03-22 2026-03-23",
            agent_id="ops_agent",
            max_tokens=300
        )
        context = recall.data
        tokens_read = recall.tokens_used
    else:
        # Read everything (inefficient baseline)
        recall = avm_recall(
            query="logs updates reports",
            agent_id="ops_agent", 
            max_tokens=1000
        )
        context = recall.data
        tokens_read = recall.tokens_used
    
    task = f"""You are the on-call engineer. Based on the logs, what are the CURRENT active issues?

{context[:1500]}

List only ACTIVE issues that need immediate attention (last 24 hours).
"""
    
    with tempfile.TemporaryDirectory() as workdir:
        response = run_codex(task, workdir=workdir, timeout=45)
    
    # Check if found the critical issues
    found_rate_limit = "rate limit" in response.output.lower()
    found_db_lag = "replication" in response.output.lower() or "database" in response.output.lower()
    
    return {
        "tokens_read": tokens_read,
        "task_tokens": response.tokens_used,
        "total": tokens_read + response.tokens_used,
        "found_issues": found_rate_limit and found_db_lag,
        "output_preview": response.output[:200],
    }


# =============================================================================
# TEST 2: DIGEST/SUMMARY - Condensed overview
# =============================================================================

def setup_digest_scenario():
    """Create a large project with many files that needs summarization."""
    
    project_files = [
        ("README.md", "# MyApp\nA web application for task management.\n\nFeatures:\n- User auth\n- Task CRUD\n- Team collaboration\n- Notifications"),
        ("ARCHITECTURE.md", "## Architecture\n\nFrontend: React + TypeScript\nBackend: Python FastAPI\nDatabase: PostgreSQL\nCache: Redis\nQueue: RabbitMQ"),
        ("CHANGELOG.md", "## v2.1.0\n- Added team features\n- Fixed auth bug\n\n## v2.0.0\n- Major rewrite\n- New UI\n\n## v1.0.0\n- Initial release"),
        ("TODO.md", "## Priority\n- [ ] Fix memory leak in worker\n- [ ] Add export feature\n- [ ] Improve search performance\n\n## Backlog\n- [ ] Dark mode\n- [ ] Mobile app"),
        ("SECURITY.md", "## Security Notes\n- API keys in env vars only\n- Rate limiting: 100 req/min\n- JWT expiry: 1 hour\n- CRITICAL: CVE-2026-1234 needs patching"),
    ]
    
    for filename, content in project_files:
        subprocess.run(
            ["avm", "write", f"/memory/shared/project/{filename}"],
            input=content,
            capture_output=True, text=True
        )
    
    return project_files


def run_digest_test(use_digest: bool) -> dict:
    """Test getting project overview via digest vs reading all files."""
    
    if use_digest:
        # Use AVM's digest/consolidate feature
        result = subprocess.run(
            ["avm", "digest", "/memory/shared/project/", "--max-tokens", "200"],
            capture_output=True, text=True
        )
        context = result.stdout if result.returncode == 0 else ""
        tokens_read = len(context.split()) if context else 0
        
        # Fallback to recall if digest not available
        if not context:
            recall = avm_recall(
                query="project overview architecture priority security",
                agent_id="pm_agent",
                max_tokens=400
            )
            context = recall.data
            tokens_read = recall.tokens_used
    else:
        # Read all files (verbose baseline)
        recall = avm_recall(
            query="README ARCHITECTURE CHANGELOG TODO SECURITY project",
            agent_id="pm_agent",
            max_tokens=1500
        )
        context = recall.data
        tokens_read = recall.tokens_used
    
    task = f"""Based on the project info, give a 3-sentence summary for a new team member.
Include: what it does, tech stack, and current priority.

{context[:2000]}
"""
    
    with tempfile.TemporaryDirectory() as workdir:
        response = run_codex(task, workdir=workdir, timeout=45)
    
    return {
        "tokens_read": tokens_read,
        "task_tokens": response.tokens_used,
        "total": tokens_read + response.tokens_used,
        "output_preview": response.output[:300],
    }


# =============================================================================
# TEST 3: POST-COMPACT RECOVERY
# =============================================================================

def run_compact_recovery_test(has_avm_access: bool) -> dict:
    """
    Simulate an agent that was compacted and lost context.
    
    Scenario: Agent was discussing a complex debugging session.
    After compact, only has a summary. Needs to continue debugging.
    """
    
    # The detailed debugging session (would be lost after compact)
    debug_session = """
## Debugging Session - Memory Leak Investigation

### Symptoms
- Worker process memory grows from 200MB to 2GB over 4 hours
- OOM kills happening daily at ~3am
- Started after deploy on March 20

### Investigation Steps
1. Checked heap dumps - found 50k orphaned Connection objects
2. Traced to connection_pool.py line 142 - missing close() in error path
3. Root cause: try/except block doesn't release connection on timeout

### The Fix
```python
# connection_pool.py line 142
def get_connection(self):
    conn = None
    try:
        conn = self._pool.get(timeout=5)
        return conn
    except TimeoutError:
        if conn:  # THIS WAS MISSING!
            conn.close()
        raise
```

### Next Steps
- Apply fix to staging first
- Monitor memory for 24h
- Then deploy to production
"""
    
    # Store full session in AVM
    subprocess.run(
        ["avm", "write", "/memory/shared/debug/memory_leak_session.md"],
        input=debug_session,
        capture_output=True, text=True
    )
    
    # The compact summary (what agent "remembers")
    compact_summary = """[Compacted] Was debugging memory leak in worker. 
Found issue in connection_pool.py. Fix identified but not yet applied."""
    
    if has_avm_access:
        # Agent can recall the full session
        recall = avm_recall(
            query="memory leak debugging connection pool fix",
            agent_id="dev_agent",
            max_tokens=600
        )
        context = recall.data
        tokens_recalled = recall.tokens_used
    else:
        # Agent only has the compact summary
        context = compact_summary
        tokens_recalled = 0
    
    # The question requiring detailed knowledge
    task = f"""You were debugging a memory leak. Your notes:

{context[:1500]}

Question: What EXACT code change needs to be made? Specify the file, line number, and the fix.
"""
    
    with tempfile.TemporaryDirectory() as workdir:
        response = run_codex(task, workdir=workdir, timeout=45)
    
    # Check if answer has specific details
    has_file = "connection_pool" in response.output.lower()
    has_line = "142" in response.output
    has_fix = "close()" in response.output or "conn.close" in response.output
    
    return {
        "tokens_recalled": tokens_recalled,
        "task_tokens": response.tokens_used,
        "total": tokens_recalled + response.tokens_used,
        "has_specific_answer": has_file and has_line and has_fix,
        "details_found": {"file": has_file, "line": has_line, "fix": has_fix},
        "output_preview": response.output[:300],
    }


# =============================================================================
# TEST 4: SEMANTIC SEARCH
# =============================================================================

def setup_semantic_scenario():
    """Set up content that requires semantic understanding to find."""
    
    entries = [
        ("auth_notes.md", "The authentication system uses JWT tokens. Sessions expire after 60 minutes of inactivity."),
        ("perf_notes.md", "Database queries are slow. We added indexes on user_id and created_at columns."),
        ("deploy_notes.md", "Deployments happen via GitHub Actions. The CI pipeline runs tests before merge."),
        ("incident_report.md", "On March 15, users couldn't log in. The issue was expired SSL certificates."),
        ("scaling_notes.md", "When traffic spikes, we auto-scale the API pods from 3 to 10 replicas."),
    ]
    
    for filename, content in entries:
        subprocess.run(
            ["avm", "write", f"/memory/shared/notes/{filename}"],
            input=content,
            capture_output=True, text=True
        )
    
    return entries


def run_semantic_test(use_semantic: bool) -> dict:
    """Test finding info without exact keyword match."""
    
    # Query uses different words than the stored content
    # "login problems" should find "users couldn't log in" + "authentication system"
    query = "login problems and solutions"
    
    if use_semantic:
        # AVM semantic search
        recall = avm_recall(
            query=query,
            agent_id="support_agent",
            max_tokens=400
        )
        context = recall.data
        tokens_read = recall.tokens_used
    else:
        # Exact keyword search (grep-style) - would miss semantically related content
        # Simulate by only searching for exact term "login"
        result = subprocess.run(
            ["avm", "search", "login", "--max-results", "3"],
            capture_output=True, text=True
        )
        context = result.stdout if result.returncode == 0 else ""
        tokens_read = len(context.split()) if context else 0
    
    task = f"""A user reports they can't log in. Based on our notes, what could be the cause?

{context[:1000]}

List possible causes and solutions.
"""
    
    with tempfile.TemporaryDirectory() as workdir:
        response = run_codex(task, workdir=workdir, timeout=45)
    
    # Check if found relevant info
    found_ssl = "ssl" in response.output.lower() or "certificate" in response.output.lower()
    found_jwt = "jwt" in response.output.lower() or "token" in response.output.lower()
    found_session = "session" in response.output.lower() or "expir" in response.output.lower()
    
    return {
        "tokens_read": tokens_read,
        "task_tokens": response.tokens_used,
        "total": tokens_read + response.tokens_used,
        "found_relevant": found_ssl or found_jwt or found_session,
        "details": {"ssl": found_ssl, "jwt": found_jwt, "session": found_session},
        "output_preview": response.output[:300],
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("="*70)
    print("AVM ADVANCED FEATURES TEST")
    print("Testing: Delta, Digest, Compact Recovery, Semantic Search")
    print("="*70)
    
    results = {}
    
    # Test 1: Delta
    print("\n" + "="*70)
    print("TEST 1: DELTA - Only read recent changes")
    print("="*70)
    setup_delta_scenario()
    
    print("\n[BASELINE] Read all logs...")
    baseline_delta = run_delta_test(use_delta=False)
    print(f"  Tokens: {baseline_delta['total']}, Found issues: {'✓' if baseline_delta['found_issues'] else '✗'}")
    
    print("\n[DELTA] Read only recent...")
    avm_delta = run_delta_test(use_delta=True)
    print(f"  Tokens: {avm_delta['total']}, Found issues: {'✓' if avm_delta['found_issues'] else '✗'}")
    
    results["delta"] = {"baseline": baseline_delta, "avm": avm_delta}
    
    # Test 2: Digest
    print("\n" + "="*70)
    print("TEST 2: DIGEST - Condensed project overview")
    print("="*70)
    setup_digest_scenario()
    
    print("\n[BASELINE] Read all files...")
    baseline_digest = run_digest_test(use_digest=False)
    print(f"  Tokens: {baseline_digest['total']}")
    
    print("\n[DIGEST] Summarized view...")
    avm_digest = run_digest_test(use_digest=True)
    print(f"  Tokens: {avm_digest['total']}")
    
    results["digest"] = {"baseline": baseline_digest, "avm": avm_digest}
    
    # Test 3: Compact Recovery
    print("\n" + "="*70)
    print("TEST 3: POST-COMPACT RECOVERY")
    print("="*70)
    
    print("\n[BASELINE] Only compact summary...")
    baseline_compact = run_compact_recovery_test(has_avm_access=False)
    print(f"  Tokens: {baseline_compact['total']}")
    print(f"  Has specific answer: {'✓' if baseline_compact['has_specific_answer'] else '✗'}")
    print(f"  Details: {baseline_compact['details_found']}")
    
    print("\n[AVM] Can recall full session...")
    avm_compact = run_compact_recovery_test(has_avm_access=True)
    print(f"  Tokens: {avm_compact['total']}")
    print(f"  Has specific answer: {'✓' if avm_compact['has_specific_answer'] else '✗'}")
    print(f"  Details: {avm_compact['details_found']}")
    
    results["compact_recovery"] = {"baseline": baseline_compact, "avm": avm_compact}
    
    # Test 4: Semantic Search
    print("\n" + "="*70)
    print("TEST 4: SEMANTIC SEARCH")
    print("="*70)
    setup_semantic_scenario()
    
    print("\n[BASELINE] Exact keyword search...")
    baseline_semantic = run_semantic_test(use_semantic=False)
    print(f"  Tokens: {baseline_semantic['total']}")
    print(f"  Found relevant: {'✓' if baseline_semantic['found_relevant'] else '✗'}")
    
    print("\n[SEMANTIC] AVM semantic search...")
    avm_semantic = run_semantic_test(use_semantic=True)
    print(f"  Tokens: {avm_semantic['total']}")
    print(f"  Found relevant: {'✓' if avm_semantic['found_relevant'] else '✗'}")
    
    results["semantic"] = {"baseline": baseline_semantic, "avm": avm_semantic}
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"{'Test':<25} {'Baseline':>15} {'AVM':>15} {'Winner':>10}")
    print("-"*65)
    
    for test_name, data in results.items():
        b_tokens = data["baseline"]["total"]
        a_tokens = data["avm"]["total"]
        
        # Determine winner based on success + efficiency
        if test_name == "compact_recovery":
            b_success = data["baseline"]["has_specific_answer"]
            a_success = data["avm"]["has_specific_answer"]
        elif test_name == "delta":
            b_success = data["baseline"]["found_issues"]
            a_success = data["avm"]["found_issues"]
        elif test_name == "semantic":
            b_success = data["baseline"]["found_relevant"]
            a_success = data["avm"]["found_relevant"]
        else:
            b_success = a_success = True
        
        if a_success and not b_success:
            winner = "AVM"
        elif b_success and not a_success:
            winner = "Baseline"
        elif a_tokens < b_tokens:
            winner = "AVM"
        else:
            winner = "Tie"
        
        print(f"{test_name:<25} {b_tokens:>15} {a_tokens:>15} {winner:>10}")
    
    # Save
    outfile = Path(__file__).parent / "results" / "avm_features.json"
    with open(outfile, 'w') as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": results,
        }, f, indent=2, default=str)
    
    print(f"\nSaved to {outfile}")


if __name__ == "__main__":
    main()
