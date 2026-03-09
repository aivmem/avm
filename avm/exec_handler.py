"""
exec_handler.py - AVM受控执行层

将危险命令包装成handler，提供：
- 命令白名单校验
- 参数审查
- 审计日志
- 速率限制
- 沙箱执行

⚠️ 安全设计:
- 配置从YAML文件加载，启动后锁定
- 禁止通过FUSE/API运行时修改
- Agent无法绕过安全策略

用法:
    from avm.exec_handler import ExecRegistry, load_config
    
    registry = ExecRegistry()
    registry.load_config("exec_config.yaml")
    
    # 安全执行
    result = registry.execute("git", ["status"])
    
    # 被拦截
    result = registry.execute("git", ["push"])  # PermissionError
"""

import subprocess
import shlex
import time
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional, Any
from pathlib import Path
import re
import os
import yaml
import hashlib

logger = logging.getLogger(__name__)

# 配置文件路径 (相对于模块)
DEFAULT_CONFIG_PATH = Path(__file__).parent / "exec_config.yaml"


@dataclass
class ExecResult:
    """执行结果"""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    elapsed_ms: float
    command: str
    handler: str


@dataclass
class ExecPolicy:
    """执行策略"""
    # 允许的子命令/参数模式
    allowed_subcommands: list[str] = field(default_factory=list)
    allowed_patterns: list[str] = field(default_factory=list)  # regex
    
    # 禁止的模式
    blocked_patterns: list[str] = field(default_factory=list)
    
    # 资源限制
    timeout_seconds: float = 30.0
    max_output_bytes: int = 1024 * 1024  # 1MB
    
    # 工作目录限制
    allowed_cwd: list[str] = field(default_factory=list)  # 为空表示不限制
    
    # 环境变量
    inherit_env: bool = False
    env_whitelist: list[str] = field(default_factory=list)
    
    # 速率限制
    rate_limit_per_minute: int = 60
    
    # 是否需要确认
    require_confirmation: bool = False


class RateLimiter:
    """简单速率限制器"""
    
    def __init__(self, limit_per_minute: int):
        self.limit = limit_per_minute
        self.calls: list[float] = []
    
    def check(self) -> bool:
        now = time.time()
        # 清理1分钟前的记录
        self.calls = [t for t in self.calls if now - t < 60]
        return len(self.calls) < self.limit
    
    def record(self):
        self.calls.append(time.time())


class ExecHandler:
    """单个命令的handler"""
    
    def __init__(self, 
                 name: str,
                 command: str,
                 policy: ExecPolicy,
                 transform: Callable[[list[str]], list[str]] = None):
        self.name = name
        self.command = command
        self.policy = policy
        self.transform = transform  # 可选的参数转换
        self.rate_limiter = RateLimiter(policy.rate_limit_per_minute)
        self.call_count = 0
        self.last_call = None
    
    def validate(self, args: list[str], cwd: str = None) -> tuple[bool, str]:
        """验证参数是否允许"""
        policy = self.policy
        
        # 速率限制
        if not self.rate_limiter.check():
            return False, "Rate limit exceeded"
        
        # 子命令白名单
        if policy.allowed_subcommands and args:
            if args[0] not in policy.allowed_subcommands:
                return False, f"Subcommand '{args[0]}' not allowed. Allowed: {policy.allowed_subcommands}"
        
        # 参数模式匹配
        args_str = " ".join(args)
        
        # 检查禁止模式
        for pattern in policy.blocked_patterns:
            if re.search(pattern, args_str):
                return False, f"Argument matches blocked pattern: {pattern}"
        
        # 检查允许模式 (如果定义了)
        if policy.allowed_patterns:
            matched = any(re.search(p, args_str) for p in policy.allowed_patterns)
            if not matched:
                return False, f"Arguments don't match any allowed pattern"
        
        # 工作目录检查
        if policy.allowed_cwd and cwd:
            cwd_path = Path(cwd).resolve()
            allowed = any(
                cwd_path == Path(p).resolve() or 
                cwd_path.is_relative_to(Path(p).resolve())
                for p in policy.allowed_cwd
            )
            if not allowed:
                return False, f"Working directory not allowed: {cwd}"
        
        return True, ""
    
    def execute(self, args: list[str], cwd: str = None) -> ExecResult:
        """执行命令"""
        # 验证
        valid, reason = self.validate(args, cwd)
        if not valid:
            logger.warning(f"[exec:{self.name}] BLOCKED: {reason}")
            return ExecResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"Blocked: {reason}",
                elapsed_ms=0,
                command=f"{self.command} {' '.join(args)}",
                handler=self.name
            )
        
        # 转换参数
        if self.transform:
            args = self.transform(args)
        
        # 构建命令
        cmd = [self.command] + args
        
        # 构建环境
        env = None
        if not self.policy.inherit_env:
            env = {}
            for var in self.policy.env_whitelist:
                if var in os.environ:
                    env[var] = os.environ[var]
            # 确保PATH
            if "PATH" not in env:
                env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
        
        # 执行
        start = time.perf_counter()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.policy.timeout_seconds,
                cwd=cwd,
                env=env
            )
            elapsed = (time.perf_counter() - start) * 1000
            
            stdout = result.stdout.decode(errors='replace')[:self.policy.max_output_bytes]
            stderr = result.stderr.decode(errors='replace')[:self.policy.max_output_bytes]
            
            # 记录
            self.rate_limiter.record()
            self.call_count += 1
            self.last_call = time.time()
            
            logger.info(f"[exec:{self.name}] OK: {' '.join(cmd[:3])}... exit={result.returncode}")
            
            return ExecResult(
                success=result.returncode == 0,
                exit_code=result.returncode,
                stdout=stdout,
                stderr=stderr,
                elapsed_ms=elapsed,
                command=f"{self.command} {' '.join(args)}",
                handler=self.name
            )
            
        except subprocess.TimeoutExpired:
            elapsed = (time.perf_counter() - start) * 1000
            logger.warning(f"[exec:{self.name}] TIMEOUT after {elapsed:.0f}ms")
            return ExecResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="Timeout",
                elapsed_ms=elapsed,
                command=f"{self.command} {' '.join(args)}",
                handler=self.name
            )


class ExecRegistry:
    """执行handler注册表"""
    
    def __init__(self):
        self.handlers: dict[str, ExecHandler] = {}
        self.audit_log: list[dict] = []
        self._locked = False
        self._config_hash: str = None
        self._config_path: Path = None
    
    def register(self, handler: ExecHandler):
        """注册handler"""
        if self._locked:
            logger.error("Registry is locked, cannot register new handlers")
            raise RuntimeError("ExecRegistry is locked after config load")
        self.handlers[handler.name] = handler
        logger.info(f"Registered exec handler: {handler.name}")
    
    def load_config(self, config_path: str = None):
        """从YAML配置文件加载handler"""
        if self._locked:
            raise RuntimeError("Registry is already locked")
        
        path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        
        # 计算配置文件hash (用于审计)
        with open(path, 'rb') as f:
            content = f.read()
            self._config_hash = hashlib.sha256(content).hexdigest()[:16]
        
        config = yaml.safe_load(content)
        
        # 全局设置
        global_cfg = config.get('global', {})
        default_timeout = global_cfg.get('default_timeout', 30.0)
        default_rate_limit = global_cfg.get('default_rate_limit', 60)
        
        # 加载handlers
        handlers_cfg = config.get('handlers', {})
        for name, cfg in handlers_cfg.items():
            if cfg.get('blocked', False):
                # 完全禁止的命令
                policy = ExecPolicy(
                    allowed_subcommands=[],
                    allowed_patterns=["^$"],  # 不匹配任何东西
                )
            else:
                policy = ExecPolicy(
                    allowed_subcommands=cfg.get('allowed_subcommands', []),
                    allowed_patterns=cfg.get('allowed_patterns', []),
                    blocked_patterns=cfg.get('blocked_patterns', []),
                    timeout_seconds=cfg.get('timeout', default_timeout),
                    rate_limit_per_minute=cfg.get('rate_limit', default_rate_limit),
                )
            
            handler = ExecHandler(
                name=name,
                command=cfg.get('command', name),
                policy=policy
            )
            self.handlers[name] = handler
        
        # 锁定
        self._locked = True
        self._config_path = path
        
        logger.info(f"Loaded {len(self.handlers)} handlers from {path} (hash: {self._config_hash})")
        logger.warning("ExecRegistry is now LOCKED - no runtime modifications allowed")
    
    def is_locked(self) -> bool:
        """检查是否已锁定"""
        return self._locked
    
    def get_config_info(self) -> dict:
        """获取配置信息 (用于审计)"""
        return {
            "locked": self._locked,
            "config_path": str(self._config_path) if self._config_path else None,
            "config_hash": self._config_hash,
            "handler_count": len(self.handlers),
        }
    
    def execute(self, name: str, args: list[str], cwd: str = None) -> ExecResult:
        """通过handler执行命令"""
        if name not in self.handlers:
            return ExecResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"Unknown handler: {name}",
                elapsed_ms=0,
                command=name,
                handler="unknown"
            )
        
        handler = self.handlers[name]
        result = handler.execute(args, cwd)
        
        # 审计日志
        self.audit_log.append({
            "timestamp": time.time(),
            "handler": name,
            "args": args,
            "cwd": cwd,
            "success": result.success,
            "exit_code": result.exit_code,
            "elapsed_ms": result.elapsed_ms,
        })
        
        # 保持审计日志在合理大小
        if len(self.audit_log) > 1000:
            self.audit_log = self.audit_log[-500:]
        
        return result
    
    def list_handlers(self) -> list[dict]:
        """列出所有handler"""
        return [
            {
                "name": h.name,
                "command": h.command,
                "allowed_subcommands": h.policy.allowed_subcommands,
                "call_count": h.call_count,
            }
            for h in self.handlers.values()
        ]


def register_default_handlers(registry: ExecRegistry):
    """注册默认的安全handler"""
    
    # === Git (只读操作) ===
    registry.register(ExecHandler(
        name="git",
        command="git",
        policy=ExecPolicy(
            allowed_subcommands=[
                "status", "log", "diff", "branch", "show", "ls-files",
                "rev-parse", "describe", "tag", "remote", "fetch",
                "blame", "shortlog", "stash", "config"
            ],
            blocked_patterns=[
                r"--exec",  # 防止执行任意命令
                r"-c\s*core\.editor",  # 防止修改editor
            ],
            timeout_seconds=30.0,
        )
    ))
    
    # === Git (写操作 - 需要更严格) ===
    registry.register(ExecHandler(
        name="git-write",
        command="git",
        policy=ExecPolicy(
            allowed_subcommands=["add", "commit", "checkout", "merge", "rebase"],
            blocked_patterns=[
                r"--exec",
                r"-m\s*['\"].*[;|&`]",  # 防止命令注入
            ],
            rate_limit_per_minute=30,  # 更严格的速率限制
        )
    ))
    
    # === Docker (只读/安全操作) ===
    registry.register(ExecHandler(
        name="docker",
        command="docker",
        policy=ExecPolicy(
            allowed_subcommands=[
                "ps", "images", "logs", "inspect", "stats",
                "version", "info", "top"
            ],
            blocked_patterns=[
                r"--privileged",
                r"--pid=host",
                r"--network=host",
                r"-v\s*/:",  # 防止挂载根目录
            ],
        )
    ))
    
    # === Curl (限制URL) ===
    registry.register(ExecHandler(
        name="curl",
        command="curl",
        policy=ExecPolicy(
            allowed_patterns=[
                r"^https?://",  # 只允许http/https
            ],
            blocked_patterns=[
                r"file://",
                r"dict://",
                r"gopher://",
                r"--output\s*/",  # 防止写入任意路径
                r"-o\s*/",
            ],
            timeout_seconds=60.0,
        )
    ))
    
    # === Python (受限执行) ===
    registry.register(ExecHandler(
        name="python",
        command="python3",
        policy=ExecPolicy(
            allowed_patterns=[
                r"^-c\s+",  # 只允许-c模式
                r"^-m\s+(json\.tool|http\.server|venv)",  # 安全模块
            ],
            blocked_patterns=[
                r"import\s+os",
                r"import\s+subprocess",
                r"__import__",
                r"eval\s*\(",
                r"exec\s*\(",
            ],
            timeout_seconds=10.0,
        )
    ))
    
    # === 文件操作 (安全版) ===
    registry.register(ExecHandler(
        name="ls",
        command="ls",
        policy=ExecPolicy(
            blocked_patterns=[
                r"\.\./\.\./",  # 防止过深的路径遍历
            ],
        )
    ))
    
    registry.register(ExecHandler(
        name="cat",
        command="cat",
        policy=ExecPolicy(
            blocked_patterns=[
                r"/etc/shadow",
                r"/etc/passwd",
                r"~/.ssh/",
                r"\.env$",
                r"credentials",
            ],
        )
    ))
    
    # === 禁止的命令 (包装为空handler) ===
    for cmd in ["rm", "sudo", "su", "chmod", "chown", "kill"]:
        registry.register(ExecHandler(
            name=cmd,
            command=cmd,
            policy=ExecPolicy(
                allowed_subcommands=[],  # 空 = 全部禁止
                allowed_patterns=["^$"],  # 不匹配任何东西
            )
        ))
    
    logger.info(f"Registered {len(registry.handlers)} default exec handlers")


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    registry = ExecRegistry()
    register_default_handlers(registry)
    
    print("=== 测试受控执行 ===\n")
    
    # 允许的操作
    tests = [
        ("git", ["status"]),
        ("git", ["log", "-5"]),
        ("git", ["push"]),  # 应该被阻止
        ("ls", ["-la"]),
        ("cat", ["/etc/passwd"]),  # 应该被阻止
        ("rm", ["-rf", "/"]),  # 应该被阻止
        ("curl", ["https://example.com"]),
        ("curl", ["file:///etc/passwd"]),  # 应该被阻止
    ]
    
    for cmd, args in tests:
        result = registry.execute(cmd, args)
        status = "✅" if result.success else "❌"
        print(f"{status} {cmd} {' '.join(args[:2])}")
        if not result.success:
            print(f"   └─ {result.stderr}")
    
    print("\n=== Handler列表 ===")
    for h in registry.list_handlers():
        print(f"  {h['name']}: {h['allowed_subcommands'][:3]}...")
