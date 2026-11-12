"""客户维护的名单：不合格供应商名单等（config/lists/*.yaml）。

名单文件不存在或未维护时 available=False，调用方必须提示「名单未提供」，不能当作未命中。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..env_config import ROOT

LISTS = ROOT / "config" / "lists"


def _norm(s: str) -> str:
    return re.sub(r"[\s()（）]", "", s or "")


class NameList:
    def __init__(self, name: str, root: Path = LISTS):
        self.path = root / f"{name}.yaml"
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) if self.path.exists() else None
        data = data or {}
        self.items = [x for x in (data.get("items") or []) if x and x.get("name")]
        self.updated = data.get("updated")
        self.available = bool(data.get("maintained")) and self.path.exists()

    def find(self, company: str) -> dict | None:
        key = _norm(company)
        return next((x for x in self.items if _norm(x["name"]) == key), None)
