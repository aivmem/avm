#!/usr/bin/env python3
"""
AVM integration for multi-agent benchmarks.

Provides recall/remember operations for agents to share knowledge.
"""

import subprocess
import json
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class AVMResult:
    """Result from an AVM operation."""
    success: bool
    data: str
    tokens_used: int  # Estimated tokens for the retrieved/stored content
    latency_ms: float
    error: str = ""


def avm_recall(query: str, agent_id: str, max_tokens: int = 500) -> AVMResult:
    """
    Recall relevant memories for an agent.
    
    Args:
        query: Search query for relevant memories
        agent_id: The agent performing the recall
        max_tokens: Maximum tokens to retrieve
    
    Returns:
        AVMResult with retrieved memories
    """
    start = time.time()
    
    cmd = [
        "avm", "recall",
        "-a", agent_id,
        "-t", str(max_tokens),
        query
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        latency = (time.time() - start) * 1000
        output = result.stdout.strip()
        
        # Remove null bytes and other control characters
        output = output.replace('\x00', '')
        output = ''.join(c for c in output if ord(c) >= 32 or c in '\n\r\t')
        
        # Estimate tokens from output length
        tokens = len(output.split()) if output else 0
        
        return AVMResult(
            success=result.returncode == 0,
            data=output,
            tokens_used=tokens,
            latency_ms=latency,
            error=result.stderr if result.returncode != 0 else "",
        )
    except subprocess.TimeoutExpired:
        return AVMResult(
            success=False,
            data="",
            tokens_used=0,
            latency_ms=30000,
            error="Timeout",
        )
    except Exception as e:
        return AVMResult(
            success=False,
            data="",
            tokens_used=0,
            latency_ms=(time.time() - start) * 1000,
            error=str(e),
        )


def avm_remember(content: str, agent_id: str, importance: float = 0.6, 
                 title: Optional[str] = None) -> AVMResult:
    """
    Store a memory for an agent.
    
    Args:
        content: Content to remember
        agent_id: The agent storing the memory
        importance: Importance score (0-1)
        title: Optional title for the memory
    
    Returns:
        AVMResult with storage confirmation
    """
    start = time.time()
    
    cmd = [
        "avm", "remember",
        "-a", agent_id,
        "-i", str(importance),
        "-c", content,
    ]
    
    if title:
        cmd.extend(["-t", title])
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        latency = (time.time() - start) * 1000
        
        # Tokens used is the content being stored
        tokens = len(content.split())
        
        return AVMResult(
            success=result.returncode == 0,
            data=result.stdout.strip(),
            tokens_used=tokens,
            latency_ms=latency,
            error=result.stderr if result.returncode != 0 else "",
        )
    except subprocess.TimeoutExpired:
        return AVMResult(
            success=False,
            data="",
            tokens_used=0,
            latency_ms=30000,
            error="Timeout",
        )
    except Exception as e:
        return AVMResult(
            success=False,
            data="",
            tokens_used=0,
            latency_ms=(time.time() - start) * 1000,
            error=str(e),
        )


def avm_write(path: str, content: str) -> AVMResult:
    """
    Write content to AVM shared storage.
    
    Args:
        path: Path in AVM (e.g., /shared/project/notes.md)
        content: Content to write
    
    Returns:
        AVMResult with write confirmation
    """
    start = time.time()
    
    cmd = [
        "avm", "write",
        path,
        content,
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        latency = (time.time() - start) * 1000
        tokens = len(content.split())
        
        return AVMResult(
            success=result.returncode == 0,
            data=result.stdout.strip(),
            tokens_used=tokens,
            latency_ms=latency,
            error=result.stderr if result.returncode != 0 else "",
        )
    except Exception as e:
        return AVMResult(
            success=False,
            data="",
            tokens_used=0,
            latency_ms=(time.time() - start) * 1000,
            error=str(e),
        )


def avm_read(path: str) -> AVMResult:
    """
    Read content from AVM shared storage.
    
    Args:
        path: Path in AVM (e.g., /shared/project/notes.md)
    
    Returns:
        AVMResult with content
    """
    start = time.time()
    
    cmd = [
        "avm", "read",
        path,
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        latency = (time.time() - start) * 1000
        output = result.stdout.strip()
        tokens = len(output.split()) if output else 0
        
        return AVMResult(
            success=result.returncode == 0,
            data=output,
            tokens_used=tokens,
            latency_ms=latency,
            error=result.stderr if result.returncode != 0 else "",
        )
    except Exception as e:
        return AVMResult(
            success=False,
            data="",
            tokens_used=0,
            latency_ms=(time.time() - start) * 1000,
            error=str(e),
        )


def avm_memory_stats(agent_id: str) -> dict:
    """Get memory statistics for an agent."""
    try:
        result = subprocess.run(
            ["avm", "memory-stats", "-a", agent_id],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        # Parse output
        stats = {}
        for line in result.stdout.strip().split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                stats[key.strip().lower().replace(' ', '_')] = value.strip()
        
        return stats
    except Exception as e:
        return {"error": str(e)}


def test_avm():
    """Test AVM integration."""
    print("Testing AVM integration...\n")
    
    # Test remember
    print("1. Testing remember...")
    result = avm_remember(
        content="Bug fix: use re.escape() to handle special characters in search queries",
        agent_id="bench_debugger",
        importance=0.7,
        title="regex_escape_fix"
    )
    print(f"   Success: {result.success}")
    print(f"   Latency: {result.latency_ms:.0f}ms")
    print(f"   Output: {result.data[:100]}")
    
    # Test recall
    print("\n2. Testing recall...")
    result = avm_recall(
        query="regex special characters bug fix",
        agent_id="bench_fixer",
        max_tokens=200
    )
    print(f"   Success: {result.success}")
    print(f"   Latency: {result.latency_ms:.0f}ms")
    print(f"   Tokens: {result.tokens_used}")
    print(f"   Data preview: {result.data[:200] if result.data else '(empty)'}")
    
    # Test memory stats
    print("\n3. Testing memory stats...")
    stats = avm_memory_stats("bench_debugger")
    print(f"   Stats: {stats}")
    
    return result.success


if __name__ == "__main__":
    test_avm()
