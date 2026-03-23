#!/usr/bin/env python3
"""
Agent executor for AVM benchmarks.
Uses subprocess to call coding agents (Codex/Claude Code).
"""

import json
import subprocess
import time
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    import tiktoken
    _encoder = tiktoken.encoding_for_model("gpt-4")
    def count_tokens(text: str) -> int:
        return len(_encoder.encode(text))
except ImportError:
    def count_tokens(text: str) -> int:
        # Fallback: rough estimate
        return int(len(text.split()) * 1.3)


@dataclass
class AgentResponse:
    """Response from an agent execution."""
    success: bool
    output: str
    tokens_used: int
    latency_ms: float
    error: str = ""


def run_claude_code(task: str, workdir: str = None, timeout: int = 120) -> AgentResponse:
    """
    Run Claude Code with a task.
    Uses --print mode for non-interactive execution.
    """
    start = time.time()
    
    cmd = [
        "claude",
        "--print",
        "--permission-mode", "bypassPermissions",
        "--model", "claude-sonnet-4-6",
        task
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workdir,
        )
        
        latency = (time.time() - start) * 1000
        
        # Claude Code doesn't easily report tokens, estimate from output length
        tokens_estimate = len(result.stdout.split()) * 1.3
        
        return AgentResponse(
            success=result.returncode == 0,
            output=result.stdout,
            tokens_used=int(tokens_estimate),
            latency_ms=latency,
            error=result.stderr if result.returncode != 0 else "",
        )
    except subprocess.TimeoutExpired:
        return AgentResponse(
            success=False,
            output="",
            tokens_used=0,
            latency_ms=timeout * 1000,
            error="Timeout",
        )
    except Exception as e:
        return AgentResponse(
            success=False,
            output="",
            tokens_used=0,
            latency_ms=(time.time() - start) * 1000,
            error=str(e),
        )


def run_codex(task: str, workdir: str = None, timeout: int = 120) -> AgentResponse:
    """
    Run Codex CLI with a task using exec mode.
    Uses a clean workdir to avoid reading unrelated files.
    """
    start = time.time()
    
    # Use workdir if provided, otherwise create temp
    if not workdir:
        workdir = tempfile.mkdtemp(prefix="codex_bench_")
    
    cmd = [
        "codex", "exec",
        "-c", "approval_policy=never",
        "--skip-git-repo-check",
        task
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workdir,
        )
        
        latency = (time.time() - start) * 1000
        
        # Parse actual token count from Codex output or use tiktoken
        output = result.stdout.strip()
        tokens_used = 0
        
        # Try to parse from Codex output first
        if "tokens used" in output:
            lines = output.split('\n')
            for i, line in enumerate(lines):
                if "tokens used" in line.lower() and i + 1 < len(lines):
                    try:
                        tokens_used = int(lines[i + 1].replace(',', '').strip())
                        output = '\n'.join(lines[:i]).strip()
                    except ValueError:
                        pass
                    break
        
        # Fallback: count with tiktoken (input + output estimate)
        if tokens_used == 0:
            tokens_used = count_tokens(task) + count_tokens(output)
        
        return AgentResponse(
            success=result.returncode == 0,
            output=output.strip(),
            tokens_used=tokens_used,
            latency_ms=latency,
            error=result.stderr if result.returncode != 0 else "",
        )
    except subprocess.TimeoutExpired:
        return AgentResponse(
            success=False,
            output="",
            tokens_used=0,
            latency_ms=timeout * 1000,
            error="Timeout",
        )
    except Exception as e:
        return AgentResponse(
            success=False,
            output="",
            tokens_used=0,
            latency_ms=(time.time() - start) * 1000,
            error=str(e),
        )


class MultiAgentExecutor:
    """Executes multi-agent scenarios."""
    
    def __init__(self, agent_type: str = "claude"):
        self.agent_type = agent_type
        self.run_fn = run_claude_code if agent_type == "claude" else run_codex
    
    def run_scenario(self, scenario: dict, workdir: Path, log_callback: Callable = None) -> dict:
        """
        Run a scenario with multiple agents.
        
        Args:
            scenario: The scenario definition
            workdir: Working directory for the scenario
            log_callback: Function to call for logging events
        
        Returns:
            Results dictionary
        """
        results = {
            "agents": {},
            "total_tokens": 0,
            "total_latency_ms": 0,
        }
        
        # For simple scenarios, run agents sequentially
        agents = scenario.get("agents", [])
        context = scenario.get("initial_context", "")
        provided_code = scenario.get("provided_code", "")
        
        # Build task context
        task_context = f"""
Context: {context}

{f'Provided Code:{chr(10)}{provided_code}' if provided_code else ''}

Assertions to satisfy:
{chr(10).join(f'- {a}' for a in scenario.get('assertions', []))}
"""
        
        for agent in agents:
            agent_id = agent["id"]
            agent_role = agent["role"]
            
            # Build agent-specific task
            task = f"""You are {agent_id} with role: {agent_role}

{task_context}

Complete your part of this task. Be concise and produce working code/output.
"""
            
            if log_callback:
                log_callback(agent_id, "start", {"role": agent_role})
            
            # Run agent
            response = self.run_fn(task, workdir=str(workdir), timeout=90)
            
            results["agents"][agent_id] = {
                "success": response.success,
                "output_length": len(response.output),
                "tokens": response.tokens_used,
                "latency_ms": response.latency_ms,
                "error": response.error,
            }
            
            results["total_tokens"] += response.tokens_used
            results["total_latency_ms"] += response.latency_ms
            
            if log_callback:
                log_callback(agent_id, "complete", {
                    "success": response.success,
                    "tokens": response.tokens_used,
                    "latency_ms": response.latency_ms,
                })
            
            # Save agent output for next agent's context
            output_file = workdir / f"{agent_id}_output.txt"
            output_file.write_text(response.output)
            
            # Update context for next agent
            task_context += f"\n\n{agent_id}'s output:\n{response.output[:2000]}"
        
        return results


def test_simple():
    """Quick test with a simple task."""
    print("Testing Claude Code...")
    response = run_claude_code("Print 'Hello from benchmark test'", timeout=30)
    print(f"Success: {response.success}")
    print(f"Latency: {response.latency_ms:.0f}ms")
    print(f"Output: {response.output[:200]}")
    return response.success


def run_claude_opus(task: str, workdir: str = None, timeout: int = 120) -> AgentResponse:
    """
    Run Claude Code (Opus) with a task.
    Uses --print mode for non-interactive execution.
    """
    start = time.time()
    
    if not workdir:
        workdir = tempfile.mkdtemp(prefix="claude_bench_")
    
    cmd = [
        "claude",
        "--print",
        "--dangerously-skip-permissions",
        "--model", "claude-opus-4-5",  # Use Opus for complex tasks
        task
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workdir,
        )
        
        latency = (time.time() - start) * 1000
        output = result.stdout.strip()
        
        # Count tokens with tiktoken (approximate for Claude)
        tokens_used = count_tokens(task) + count_tokens(output)
        
        return AgentResponse(
            success=result.returncode == 0 and len(output) > 0,
            output=output,
            tokens_used=tokens_used,
            latency_ms=latency,
            error=result.stderr if result.returncode != 0 else "",
        )
    except subprocess.TimeoutExpired:
        return AgentResponse(
            success=False,
            output="",
            tokens_used=0,
            latency_ms=timeout * 1000,
            error="Timeout",
        )
    except Exception as e:
        return AgentResponse(
            success=False,
            output="",
            tokens_used=0,
            latency_ms=(time.time() - start) * 1000,
            error=str(e),
        )


def run_agent(task: str, agent_type: str = "codex", workdir: str = None, timeout: int = 120) -> AgentResponse:
    """
    Unified interface to run any agent type.
    
    Args:
        task: The task/prompt
        agent_type: "codex" or "claude"
        workdir: Working directory
        timeout: Timeout in seconds
    
    Returns:
        AgentResponse with results
    """
    if agent_type == "claude":
        return run_claude_opus(task, workdir, timeout)
    else:
        return run_codex(task, workdir, timeout)


def test_codex():
    """Quick test with Codex."""
    print("Testing Codex...")
    response = run_codex("Print 'Hello from Codex benchmark test'", timeout=30)
    print(f"Success: {response.success}")
    print(f"Latency: {response.latency_ms:.0f}ms")
    print(f"Output: {response.output[:500]}")
    print(f"Error: {response.error[:200] if response.error else 'none'}")
    return response.success


def test_claude():
    """Quick test with Claude."""
    print("Testing Claude...")
    response = run_claude_opus("Print 'Hello from Claude benchmark test'", timeout=30)
    print(f"Success: {response.success}")
    print(f"Latency: {response.latency_ms:.0f}ms")
    print(f"Output: {response.output[:500]}")
    print(f"Error: {response.error[:200] if response.error else 'none'}")
    return response.success


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "codex":
            test_codex()
        elif sys.argv[1] == "claude":
            test_claude()
        else:
            test_simple()
    else:
        test_simple()
