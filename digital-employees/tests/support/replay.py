"""采购离线重放：从本地存储还原历史单据的表单与附件清单，不访问合同系统。

表单只还原规则用到的字段（P01 证据里的四项 + 报告头），附件全部带 version_id，
下载节点会命中「同一附件版本已下载」直接复用原件；解析节点命中 L1 缓存。
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from core.config import DB_PATH, RC_DB_PATH, RUNTIME, STORE
from core.resource.client import LocalResourceClient
from core.resource.service import ResourceService
from core.resource.store import ResourceStore
from core.sources.contract import Attachment, RequestData
from core.storage import Store


def latest_report(request_id: str, db_path: Path = DB_PATH) -> dict | None:
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT r.body FROM report r JOIN task t ON t.task_id = r.task_id "
                     "WHERE t.employee = 'procurement' AND t.request_id = ? AND t.status = 'done' "
                     "ORDER BY t.created_at DESC LIMIT 1", (request_id,)).fetchone()
    db.close()
    return json.loads(row["body"]) if row else None


def baseline(request_id: str) -> tuple[Path, Path, Path] | None:
    """历史基准 (工作台库, 资料中心库, 存储目录)：DE_REPLAY_RUNTIME 指定的运行目录；否则当前运行数据；
    当前没有该单的历史报告时（如 tools/reset_runtime.py 清理后），用最近一次清理前的备份。"""
    env = os.environ.get("DE_REPLAY_RUNTIME")
    roots = [Path(env)] if env else sorted((RUNTIME / "backup").glob("reset-*"), reverse=True)
    cands = ([] if env else [(DB_PATH, RC_DB_PATH, STORE)]) + \
        [(r / "store" / "de.sqlite3", r / "resource" / "resource.sqlite3", r / "store") for r in roots]
    for db, rc, store in cands:
        if db.exists() and latest_report(request_id, db):
            return db, rc, store
    return None


def rebuild_request(request_id: str, report: dict, db_path: Path) -> RequestData:
    """db_path：资料中心库（file_occurrence 归资料中心）。"""
    h = report["header"]
    p01 = next(r for r in report["rules"] if r["rule_id"] == "P01")
    form = {}
    for e in p01["evidence"]:
        k, _, v = e["snippet"].partition("：")
        form[k] = v
    labels = {"合同名称": form.get("合同名称", ""), "采购内容": h.get("采购内容", ""), "采购方式": h.get("采购方式", ""),
              "预算价格（万元）": h.get("预算", ""), "采购价格（万元）": h.get("采购价格", ""),
              "候选供应商": h.get("候选供应商", "")}
    fields = [{"field": f"field{i}", "label": k, "htmltype": "1", "value": v, "display": v}
              for i, (k, v) in enumerate(labels.items(), start=1)]
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT content_sig, filename, field_label, field_key, file_id, image_file_id, version_id, "
                      "upload_time, secret_level, MIN(id) AS first_id FROM file_occurrence "
                      "WHERE source_system = 'contract' AND request_id = ? AND parent_sig IS NULL "
                      "AND version_id IS NOT NULL AND version_id <> '' "
                      "GROUP BY image_file_id, version_id ORDER BY first_id", (request_id,)).fetchall()
    db.close()
    atts = [Attachment(field_key=r["field_key"], field_label=r["field_label"], filename=r["filename"],
                       ext=Path(r["filename"]).suffix.lstrip(".").lower(), file_id=r["file_id"] or "",
                       image_file_id=r["image_file_id"], version_id=r["version_id"],
                       upload_time=r["upload_time"] or "", secret_level=r["secret_level"] or "",
                       loadlink="") for r in rows]
    return RequestData(request_id=request_id, workflow_id="100", workflow_name=h.get("workflow_name", ""),
                       request_name=h.get("request_name", ""), node_name=h.get("node_name", ""),
                       fields=fields, approval_log=[], attachments=atts)


class ReplayClient:
    def __init__(self, req: RequestData):
        self.req = req

    def fetch(self, request_id: str) -> RequestData:
        assert str(request_id) == self.req.request_id
        return self.req

    def download(self, att):
        raise AssertionError(f"重放不应触发下载：{att.filename}")


class NoSessions:
    def session(self):
        raise AssertionError("重放不应借用浏览器会话")

    def warmup(self, host: str) -> None:
        raise AssertionError("重放不应触发单点登录")


def _copy(src_path: Path, dst_path: Path) -> None:
    src = sqlite3.connect(str(src_path))
    dst = sqlite3.connect(str(dst_path))
    src.backup(dst)
    src.close()
    dst.close()


def replay_store(tmp: Path, db_path: Path = DB_PATH) -> Store:
    """临时工作台库（复制历史库，任务写入不污染历史）。"""
    db = tmp / "replay.sqlite3"
    _copy(db_path, db)
    return Store(db_path=db)


def replay_resources(tmp: Path, rc_path: Path = RC_DB_PATH, store_root: Path = STORE,
                     db_path: Path = DB_PATH) -> tuple[LocalResourceClient, Path]:
    """临时资料中心库：复制历史资料中心库；尚未建立时从旧工作台库迁入。原件/解析目录用历史目录（只读命中）。"""
    db = tmp / "replay_resource.sqlite3"
    if rc_path.exists():
        _copy(rc_path, db)
        rs = ResourceStore(db_path=db, root=store_root, legacy_db=None)
    else:
        rs = ResourceStore(db_path=db, root=store_root, legacy_db=db_path)
    return LocalResourceClient(ResourceService(rs, NoSessions())), db


def comparable(results: list[dict]) -> list[tuple]:
    return [(r["rule_id"], r["status"], r["tier"], r["message"]) for r in results]
