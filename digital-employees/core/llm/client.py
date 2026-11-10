"""大模型客户端：按 config/llm.yaml 动态加载（文件修改后自动重新读取），统一流式输出。

输出事件：{"type": "think", "text": ...}（深度思考）/ {"type": "text", "text": ...}（正文）
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Iterator

import requests
import yaml

from ..config import ROOT

CONFIG_PATH = Path(os.environ.get("DE_LLM_CONFIG", str(ROOT / "config" / "llm.yaml")))
_cache = {"mtime": None, "cfg": None}
_lock = threading.Lock()


def _expand(v):
    if isinstance(v, str):
        return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), v)
    if isinstance(v, dict):
        return {k: _expand(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_expand(x) for x in v]
    return v


def config() -> dict:
    with _lock:
        mtime = CONFIG_PATH.stat().st_mtime
        if _cache["mtime"] != mtime:
            _cache["cfg"] = _expand(yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {})
            _cache["mtime"] = mtime
        return _cache["cfg"]


def provider(role: str = "chat") -> dict:
    cfg = config()
    name = (cfg.get("roles") or {}).get(role) or next(iter(cfg.get("providers") or {}), None)
    p = (cfg.get("providers") or {}).get(name)
    if not p:
        raise RuntimeError(f"config/llm.yaml 中未配置 {role} 使用的模型")
    return {"name": name, **p}


def status(role: str = "chat") -> dict:
    p = provider(role)
    info = {"provider": p["name"], "type": p.get("type"), "model": p.get("model"), "base_url": p.get("base_url"),
            "reachable": False, "model_ready": False}
    try:
        if p.get("type") == "ollama":
            tags = requests.get(p["base_url"].rstrip("/") + "/api/tags", timeout=3).json()
            names = [m.get("name") for m in tags.get("models", [])]
            info["reachable"] = True
            info["model_ready"] = any(n == p["model"] or n.split(":")[0] == p["model"] for n in names)
            info["available"] = names
        else:
            r = requests.get(p["base_url"].rstrip("/") + "/models", timeout=5,
                             headers={"Authorization": f"Bearer {p.get('api_key', '')}"})
            info["reachable"] = r.status_code < 500
            info["model_ready"] = r.ok
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


class _ThinkSplitter:
    """把正文里内嵌的 <think>…</think> 拆成思考事件（部分模型不走独立字段）。"""

    def __init__(self):
        self.in_think = False
        self.buf = ""

    def feed(self, text: str) -> Iterator[dict]:
        self.buf += text
        while self.buf:
            tag = "</think>" if self.in_think else "<think>"
            idx = self.buf.find(tag)
            if idx == -1:
                keep = len(tag) - 1
                emit, self.buf = (self.buf[:-keep], self.buf[-keep:]) if len(self.buf) > keep else ("", self.buf)
                if emit:
                    yield {"type": "think" if self.in_think else "text", "text": emit}
                return
            if idx:
                yield {"type": "think" if self.in_think else "text", "text": self.buf[:idx]}
            self.buf = self.buf[idx + len(tag):]
            self.in_think = not self.in_think

    def flush(self) -> Iterator[dict]:
        if self.buf:
            yield {"type": "think" if self.in_think else "text", "text": self.buf}
            self.buf = ""


def stream(messages: list[dict], role: str = "chat", **overrides) -> Iterator[dict]:
    p = {**provider(role), **overrides}
    split = _ThinkSplitter()
    if p.get("type") == "ollama":
        body = {"model": p["model"], "messages": messages, "stream": True,
                "options": {"temperature": p.get("temperature", 0.6), **(p.get("options") or {})}}
        if "think" in p:
            body["think"] = bool(p["think"])
        with requests.post(p["base_url"].rstrip("/") + "/api/chat", json=body, stream=True,
                           timeout=(10, p.get("timeout", 300))) as r:
            if r.status_code != 200:
                raise RuntimeError(f"Ollama 返回 {r.status_code}：{r.text[:300]}")
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                d = json.loads(line)
                if d.get("error"):
                    raise RuntimeError(d["error"])
                msg = d.get("message") or {}
                if msg.get("thinking"):
                    yield {"type": "think", "text": msg["thinking"]}
                if msg.get("content"):
                    yield from split.feed(msg["content"])
                if d.get("done"):
                    break
    else:
        body = {"model": p["model"], "messages": messages, "stream": True, "temperature": p.get("temperature", 0.5)}
        headers = {"Authorization": f"Bearer {p.get('api_key', '')}", "Content-Type": "application/json"}
        with requests.post(p["base_url"].rstrip("/") + "/chat/completions", json=body, headers=headers, stream=True,
                           timeout=(10, p.get("timeout", 120))) as r:
            if r.status_code != 200:
                raise RuntimeError(f"模型服务返回 {r.status_code}：{r.text[:300]}")
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                delta = ((json.loads(data).get("choices") or [{}])[0]).get("delta") or {}
                think = delta.get("reasoning_content") or delta.get("reasoning")
                if think:
                    yield {"type": "think", "text": think}
                if delta.get("content"):
                    yield from split.feed(delta["content"])
    yield from split.flush()


def complete(messages: list[dict], role: str = "extract", **overrides) -> str:
    """非流式：返回正文（丢弃思考过程），供抽取、语义判定使用。"""
    return "".join(e["text"] for e in stream(messages, role, **overrides) if e["type"] == "text").strip()
