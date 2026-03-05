"""
vfs/providers/http_json.py - 通用 HTTP JSON Provider

从 HTTP API 获取 JSON 数据并格式化为 Markdown
"""

import json
import urllib.request
from datetime import datetime
from typing import Optional, Dict, Any

from .base import LiveProvider
from ..node import VFSNode
from ..store import VFSStore


class HttpJsonProvider(LiveProvider):
    """
    通用 HTTP JSON Provider
    
    配置:
        base_url: API 基础 URL
        token: Bearer token (可选)
        headers: 自定义请求头 (可选)
        path_mapping: 路径到 API endpoint 的映射 (可选)
    """
    
    def __init__(self, store: VFSStore, prefix: str, ttl_seconds: int = 60,
                 base_url: str = "", token: str = "", 
                 headers: Dict[str, str] = None,
                 path_mapping: Dict[str, str] = None):
        super().__init__(store, prefix, ttl_seconds)
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.extra_headers = headers or {}
        self.path_mapping = path_mapping or {}
    
    def _get_endpoint(self, path: str) -> str:
        """将 VFS 路径转换为 API endpoint"""
        # 移除前缀
        rel_path = path[len(self.prefix):].lstrip("/")
        
        # 检查映射
        if path in self.path_mapping:
            return self.path_mapping[path]
        
        # 默认：直接使用路径
        return f"/{rel_path}".replace(".md", "")
    
    def _request(self, endpoint: str) -> Any:
        """发送 HTTP 请求"""
        url = f"{self.base_url}{endpoint}"
        
        headers = {"User-Agent": "VFS/1.0"}
        headers.update(self.extra_headers)
        
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        
        req = urllib.request.Request(url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    
    def _format_json_to_md(self, data: Any, title: str = "") -> str:
        """将 JSON 数据格式化为 Markdown"""
        lines = []
        
        if title:
            lines.append(f"# {title}")
            lines.append("")
        
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    lines.append(f"## {key}")
                    lines.append("")
                    lines.append("```json")
                    lines.append(json.dumps(value, indent=2))
                    lines.append("```")
                else:
                    lines.append(f"- **{key}:** {value}")
        elif isinstance(data, list):
            lines.append("| # | Value |")
            lines.append("|---|-------|")
            for i, item in enumerate(data[:50]):  # 限制行数
                if isinstance(item, dict):
                    lines.append(f"| {i} | {json.dumps(item)} |")
                else:
                    lines.append(f"| {i} | {item} |")
        else:
            lines.append(str(data))
        
        lines.append("")
        lines.append(f"*Updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*")
        
        return "\n".join(lines)
    
    def fetch(self, path: str) -> Optional[VFSNode]:
        """获取数据"""
        try:
            endpoint = self._get_endpoint(path)
            data = self._request(endpoint)
            
            # 格式化为 Markdown
            title = path.split("/")[-1].replace(".md", "").replace("_", " ").title()
            content = self._format_json_to_md(data, title)
            
            return self._make_node(path, content, {"raw_data": data})
        
        except Exception as e:
            return self._make_node(
                path,
                f"# Error\n\nFailed to fetch: {e}",
                {"error": str(e)}
            )
