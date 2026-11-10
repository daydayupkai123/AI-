"""隔离的运行环境：临时工作台存储 + 临时资料中心 + 临时样例目录 + 临时报告目录。"""
from __future__ import annotations

from pathlib import Path

from core.resource.client import LocalResourceClient
from core.resource.service import ResourceService
from core.resource.store import ResourceStore
from core.storage import Store


def temp_store(tmp: Path) -> Store:
    return Store(db_path=tmp / "db" / "de.sqlite3")


def temp_resources(tmp: Path, sessions=None, clients: dict | None = None) -> LocalResourceClient:
    rs = ResourceStore(db_path=tmp / "resource" / "resource.sqlite3", root=tmp / "store", legacy_db=None)
    return LocalResourceClient(ResourceService(rs, sessions, clients))


def by_id(results: list[dict]) -> dict[str, dict]:
    return {r["rule_id"]: r for r in results}
