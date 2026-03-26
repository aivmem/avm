"""
AVM HTTP API Server
轻量 FastAPI server，提供 REST 接口访问 AVM 记忆。
供 Docker 容器和 Windows 客户端使用。
"""
from __future__ import annotations
import os
from pathlib import Path

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from .core import AVM

app = None  # lazy init


def create_app(agent_id: str = "default") -> "FastAPI":
    if not HAS_FASTAPI:
        raise ImportError("Install fastapi and uvicorn: pip install fastapi uvicorn")

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel

    avm = AVM(agent_id=agent_id)
    app = FastAPI(title="AVM API", version="1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    class RememberRequest(BaseModel):
        content: str
        importance: float = 0.5
        tags: list[str] = []

    class RecallRequest(BaseModel):
        query: str
        max_tokens: int = 500

    @app.get("/health")
    def health():
        return {"status": "ok", "agent": agent_id}

    @app.post("/remember")
    def remember(req: RememberRequest):
        """Store a memory."""
        memory = avm.agent_memory(agent_id)
        node = memory.remember(req.content, importance=req.importance, tags=req.tags)
        return {"path": str(node.path)}

    @app.post("/recall")
    def recall(req: RecallRequest):
        """Retrieve relevant memories."""
        memory = avm.agent_memory(agent_id)
        results = memory.recall(req.query, max_tokens=req.max_tokens)
        return {"results": results, "query": req.query}

    @app.get("/stats")
    def stats():
        """Memory statistics."""
        return avm.stats()

    return app


def main():
    """Entry point for `avm serve` CLI command."""
    import argparse
    parser = argparse.ArgumentParser(description="AVM HTTP API Server")
    parser.add_argument("--agent", default=os.environ.get("AVM_AGENT", "default"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    app = create_app(args.agent)
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
