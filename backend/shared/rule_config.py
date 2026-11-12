"""规则配置：草稿 → 发布 → 版本留痕；已发布配置在审查时生效。

- 配置项只限代码中为每条规则声明过的内容（employee_registry/flows.py）：启用 / 停用及原因、显示名称、档位（采购）、
  核实建议、参数（映射到 config/<员工>.yaml 中的路径）。判定逻辑仍在代码中。
- 参数：已发布值叠加到对应 YAML（shared.settings.load 读取时合并），规则代码照常读取配置，无需改动。
- 启停 / 名称 / 档位 / 核实建议：规则引擎执行时统一生效（停用的规则记「未执行」并写明原因）。
- 生效版本号 = 代码规则版本 + 「+c<发布序号>」，写入任务与报告；执行档案保存当时的配置快照。
- 发布后不自动重审：报告版本与当前生效版本不同的即「按旧版规则生成」，可在页面一键批量重审。
"""
from __future__ import annotations

import copy
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from .env_config import RUNTIME

DB_PATH = Path(os.environ.get("DE_RULECFG_DB", str(RUNTIME / "rules" / "rule_config.sqlite3")))
SCHEMA = """
CREATE TABLE IF NOT EXISTS rule_cfg_version (
  employee TEXT NOT NULL, n INTEGER NOT NULL, created_at REAL NOT NULL, author TEXT, note TEXT, body TEXT NOT NULL,
  PRIMARY KEY (employee, n));
CREATE TABLE IF NOT EXISTS rule_cfg_draft (
  employee TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL, author TEXT);
CREATE TABLE IF NOT EXISTS rule_cfg_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, employee TEXT NOT NULL, at REAL NOT NULL, author TEXT, action TEXT NOT NULL,
  rule_id TEXT, field TEXT, old TEXT, new TEXT, note TEXT);
"""
EMPTY = {"rules": {}}
FIELDS = ("enabled", "reason", "name", "tier", "suggest", "params")

_lock = threading.RLock()
_conn: dict = {"path": None, "db": None}
_cache: dict = {}
CACHE_S = 2.0


def _db() -> sqlite3.Connection:
    with _lock:
        if _conn["db"] is None or _conn["path"] != DB_PATH:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(str(DB_PATH), check_same_thread=False, isolation_level=None, timeout=30)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            _conn.update(path=DB_PATH, db=db)
        return _conn["db"]


def reset_cache() -> None:
    _cache.clear()


# ------------------------------------------------------------------ 读取
def published(employee: str) -> tuple[int, dict]:
    """当前生效（最近一次发布）的配置：(发布序号, 配置)；没有发布过返回 (0, 空配置)。带 2 秒缓存。"""
    hit = _cache.get(employee)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1], hit[2]
    with _lock:
        row = _db().execute("SELECT n, body FROM rule_cfg_version WHERE employee=? ORDER BY n DESC LIMIT 1",
                            (employee,)).fetchone()
    n, body = (row["n"], json.loads(row["body"])) if row else (0, copy.deepcopy(EMPTY))
    _cache[employee] = (time.time(), n, body)
    return n, body


def draft(employee: str) -> dict:
    """草稿（没有草稿时等于当前生效配置）。"""
    with _lock:
        row = _db().execute("SELECT body FROM rule_cfg_draft WHERE employee=?", (employee,)).fetchone()
    return json.loads(row["body"]) if row else copy.deepcopy(published(employee)[1])


def has_draft(employee: str) -> bool:
    with _lock:
        row = _db().execute("SELECT body FROM rule_cfg_draft WHERE employee=?", (employee,)).fetchone()
    return bool(row) and json.loads(row["body"]) != published(employee)[1]


def rule_cfg(employee: str, rule_id: str) -> dict:
    return published(employee)[1].get("rules", {}).get(rule_id) or {}


def effective_version(employee: str, code_version: str) -> str:
    """配置为空（从未发布或已恢复代码默认）时就是代码规则版本，避免把按默认规则生成的报告误标为旧版。"""
    n, body = published(employee)
    return f"{code_version}+c{n}" if n and (body.get("rules") or body.get("flow_params")) else code_version


def snapshot(employee: str) -> dict:
    n, body = published(employee)
    return {"n": n, "body": body}


# ------------------------------------------------------------------ 参数叠加（shared.settings.load 调用）
def _set_path(data: dict, path: str, value) -> None:
    keys = path.split(".")
    cur = data
    for k in keys[:-1]:
        if not isinstance(cur.get(k), dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value


def get_path(data: dict, path: str, default=None):
    cur = data
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def overlay(filename: str, data: dict) -> dict:
    """把已发布的规则参数叠加到 YAML 配置上（文件名 → 员工由 flows.CONFIG_FILES 决定）。"""
    from employee_registry.flows import CONFIG_FILES

    emp = CONFIG_FILES.get(filename)
    if not emp:
        return data
    n, body = published(emp)
    if not n:
        return data
    out = copy.deepcopy(data)
    for rid, rc in (body.get("rules") or {}).items():
        for path, value in (rc.get("params") or {}).items():
            _set_path(out, path, value)
        # 报销规则在 YAML 中自带的开关（rules.<id>.enabled / reason）与配置页保持一致
        if filename == "reimburse.yaml" and "enabled" in rc:
            _set_path(out, f"rules.{rid}.enabled", bool(rc["enabled"]))
            if rc.get("reason"):
                _set_path(out, f"rules.{rid}.reason", rc["reason"])
    for path, value in (body.get("flow_params") or {}).items():
        _set_path(out, path, value)
    return out


# ------------------------------------------------------------------ 规则执行时生效（启停 / 名称 / 档位 / 核实建议）
def apply_result(employee: str, r: dict) -> dict:
    rc = rule_cfg(employee, r.get("rule_id", ""))
    if not rc:
        return r
    if rc.get("name"):
        r["name"] = rc["name"]
    if rc.get("tier") and employee == "procurement":
        r["tier"] = rc["tier"]
    if rc.get("suggest"):
        r["suggest"] = rc["suggest"]
    return r


def disabled_reason(employee: str, rule_id: str) -> str | None:
    rc = rule_cfg(employee, rule_id)
    if rc.get("enabled") is False:
        return rc.get("reason") or "已在规则配置中停用"
    return None


# ------------------------------------------------------------------ 编辑 / 发布 / 回退
def save_draft(employee: str, body: dict, author: str = "", note: str = "") -> dict:
    old = draft(employee)
    body = _normalize(body)
    with _lock:
        _db().execute("INSERT OR REPLACE INTO rule_cfg_draft VALUES (?,?,?,?)",
                      (employee, json.dumps(body, ensure_ascii=False), time.time(), author))
        for rid, field, a, b in diff(old, body):
            _db().execute("INSERT INTO rule_cfg_log (employee, at, author, action, rule_id, field, old, new, note) "
                          "VALUES (?,?,?,?,?,?,?,?,?)",
                          (employee, time.time(), author, "edit", rid, field, _j(a), _j(b), note))
    return body


def publish(employee: str, author: str = "", note: str = "") -> int:
    body = draft(employee)
    n, cur = published(employee)
    if body == cur and n:
        raise ValueError("草稿与当前生效配置相同，无需发布")
    with _lock:
        _db().execute("INSERT INTO rule_cfg_version VALUES (?,?,?,?,?,?)",
                      (employee, n + 1, time.time(), author, note, json.dumps(body, ensure_ascii=False)))
        _db().execute("DELETE FROM rule_cfg_draft WHERE employee=?", (employee,))
        _db().execute("INSERT INTO rule_cfg_log (employee, at, author, action, note) VALUES (?,?,?,?,?)",
                      (employee, time.time(), author, "publish", f"发布第 {n + 1} 版：{note}"))
    _cache.pop(employee, None)
    return n + 1


def discard_draft(employee: str, author: str = "") -> None:
    with _lock:
        _db().execute("DELETE FROM rule_cfg_draft WHERE employee=?", (employee,))
        _db().execute("INSERT INTO rule_cfg_log (employee, at, author, action, note) VALUES (?,?,?,?,?)",
                      (employee, time.time(), author, "discard", "放弃草稿"))


def rollback_to(employee: str, n: int, author: str = "") -> dict:
    """把草稿设为历史版本 n（或 0 = 代码默认），需再发布才生效。"""
    body = copy.deepcopy(EMPTY) if n == 0 else version_body(employee, n)
    if body is None:
        raise KeyError(n)
    return save_draft(employee, body, author, note=f"回退到第 {n} 版")


def version_body(employee: str, n: int) -> dict | None:
    with _lock:
        row = _db().execute("SELECT body FROM rule_cfg_version WHERE employee=? AND n=?", (employee, n)).fetchone()
    return json.loads(row["body"]) if row else None


def versions(employee: str) -> list[dict]:
    with _lock:
        rows = _db().execute("SELECT n, created_at, author, note, body FROM rule_cfg_version WHERE employee=? "
                             "ORDER BY n DESC", (employee,)).fetchall()
    bodies = {r["n"]: json.loads(r["body"]) for r in rows}
    return [{"n": r["n"], "created_at": r["created_at"], "author": r["author"], "note": r["note"],
             "changes": len(diff(bodies.get(r["n"] - 1, EMPTY), bodies[r["n"]]))}  # 相对于前一版改了几项
            for r in rows]


def log(employee: str, limit: int = 100) -> list[dict]:
    with _lock:
        rows = _db().execute("SELECT * FROM rule_cfg_log WHERE employee=? ORDER BY id DESC LIMIT ?",
                             (employee, limit)).fetchall()
    return [dict(r) for r in rows]


def diff(a: dict | None, b: dict | None) -> list[tuple]:
    """[(规则编号, 字段, 旧值, 新值)]；参数逐项比较。"""
    a, b = a or EMPTY, b or EMPTY
    out = []
    ids = sorted(set((a.get("rules") or {}).keys()) | set((b.get("rules") or {}).keys()))
    for rid in ids:
        ra, rb = (a.get("rules") or {}).get(rid) or {}, (b.get("rules") or {}).get(rid) or {}
        for f in FIELDS:
            if f == "params":
                pa, pb = ra.get("params") or {}, rb.get("params") or {}
                for p in sorted(set(pa) | set(pb)):
                    if pa.get(p) != pb.get(p):
                        out.append((rid, f"参数 {p}", pa.get(p), pb.get(p)))
            elif ra.get(f) != rb.get(f):
                out.append((rid, f, ra.get(f), rb.get(f)))
    fa, fb = a.get("flow_params") or {}, b.get("flow_params") or {}
    for p in sorted(set(fa) | set(fb)):
        if fa.get(p) != fb.get(p):
            out.append(("流程", f"参数 {p}", fa.get(p), fb.get(p)))
    return out


def _normalize(body: dict) -> dict:
    rules = {}
    for rid, rc in (body.get("rules") or {}).items():
        clean = {k: v for k, v in (rc or {}).items() if k in FIELDS and v not in (None, "", {})}
        if clean:
            rules[rid] = clean
    out = {"rules": rules}
    if body.get("flow_params"):
        out["flow_params"] = body["flow_params"]
    return out


def _j(v) -> str | None:
    return None if v is None else json.dumps(v, ensure_ascii=False)
