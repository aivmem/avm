"""
AVM HTTP Client — for Windows or no-FUSE environments
"""
import os
import json

try:
    import urllib.request as req
except ImportError:
    pass

AVM_SERVER_URL = os.environ.get("AVM_SERVER_URL", "http://localhost:8765")


def recall(query: str, max_tokens: int = 500) -> str:
    data = json.dumps({"query": query, "max_tokens": max_tokens}).encode()
    r = req.urlopen(req.Request(
        f"{AVM_SERVER_URL}/recall",
        data=data, headers={"Content-Type": "application/json"}
    ))
    return json.loads(r.read())["results"]


def remember(content: str, importance: float = 0.5) -> str:
    data = json.dumps({"content": content, "importance": importance}).encode()
    r = req.urlopen(req.Request(
        f"{AVM_SERVER_URL}/remember",
        data=data, headers={"Content-Type": "application/json"}
    ))
    return json.loads(r.read())["path"]
