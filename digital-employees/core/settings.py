"""读取 config/*.yaml；按文件修改时间缓存，改完配置下一次调用即生效。"""
from __future__ import annotations

import threading
from pathlib import Path

import yaml

from .config import ROOT

CONFIG_DIR = ROOT / "config"
_cache: dict[Path, tuple[float, dict]] = {}
_lock = threading.Lock()


def load(name: str, root: Path = CONFIG_DIR, raw: bool = False) -> dict:
    """raw=False 时叠加规则配置页已发布的参数（core/ruleconfig.py）；raw=True 只读 YAML 原值（配置页展示默认值用）。"""
    path = root / name
    mtime = path.stat().st_mtime
    with _lock:
        hit = _cache.get(path)
        if hit and hit[0] == mtime:
            data = hit[1]
        else:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            _cache[path] = (mtime, data)
    if raw:
        return data
    from . import ruleconfig

    return ruleconfig.overlay(name, data)
