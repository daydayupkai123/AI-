"""资料中心配置：config/resource.yaml（服务地址与模式）、config/collect.yaml（采集策略），修改后自动重新读取。"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import yaml

from shared.env_config import ROOT

RESOURCE_PATH = Path(os.environ.get("DE_RC_CONFIG", str(ROOT / "config" / "resource.yaml")))
COLLECT_PATH = Path(os.environ.get("DE_COLLECT_CONFIG", str(ROOT / "config" / "collect.yaml")))
_cache: dict[Path, tuple[float | None, dict]] = {}
_lock = threading.Lock()


def _load(path: Path) -> dict:
    with _lock:
        mtime = path.stat().st_mtime if path.exists() else None
        hit = _cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        cfg = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if mtime else {}
        _cache[path] = (mtime, cfg)
        return cfg


def resource() -> dict:
    return _load(RESOURCE_PATH)


def collect() -> dict:
    return _load(COLLECT_PATH)


def mode() -> str:
    """inprocess：工作台进程内直接调用资料中心服务代码；http：调用独立运行的资料中心进程。"""
    return (os.environ.get("DE_RC_MODE") or resource().get("mode") or "http").strip()


def url() -> str:
    return (os.environ.get("DE_RC_URL") or resource().get("url") or "http://127.0.0.1:8091").rstrip("/")
