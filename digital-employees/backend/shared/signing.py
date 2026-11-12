"""三个签名：内容签名、处理键、完整性签名（见 docs/文件解析结果缓存与存储设计.md 第 2 节）。"""
from __future__ import annotations

import hashlib
import hmac
import json

from .env_config import hmac_key


def content_sig(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def proc_key(sig: str, processor: str, version: str, params: dict | None = None) -> str:
    return hashlib.sha256(canonical([sig, processor, version, params or {}])).hexdigest()


def integrity(sig: str, key: str, result_bytes: bytes) -> str:
    msg = f"{sig}|{key}|{hashlib.sha256(result_bytes).hexdigest()}".encode("utf-8")
    return hmac.new(hmac_key(), msg, hashlib.sha256).hexdigest()


def verify(sig: str, key: str, result_bytes: bytes, expected: str) -> bool:
    return hmac.compare_digest(integrity(sig, key, result_bytes), expected or "")
