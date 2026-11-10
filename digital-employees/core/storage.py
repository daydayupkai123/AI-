"""工作台存储（SQLite）：任务、节点留痕、规则结果、报告、缓存访问统计、模型与外部查询缓存。

原件、出处与解析结果归资料中心（core/resource/store.py），工作台只经资料中心接口读取。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS task (
  task_id TEXT PRIMARY KEY, employee TEXT NOT NULL, source_system TEXT, request_id TEXT,
  trigger_by TEXT, status TEXT NOT NULL, rules_version TEXT, created_at REAL NOT NULL,
  finished_at REAL, error TEXT);
CREATE TABLE IF NOT EXISTS node_run (
  id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, node TEXT NOT NULL,
  status TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL, duration_ms INTEGER,
  summary TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS rule_result (
  task_id TEXT NOT NULL, rule_id TEXT NOT NULL, rule_ver TEXT, name TEXT, tier TEXT,
  status TEXT NOT NULL, message TEXT, evidence TEXT, duration_ms INTEGER,
  PRIMARY KEY (task_id, rule_id));
CREATE TABLE IF NOT EXISTS report (
  task_id TEXT PRIMARY KEY, body TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS cache_access (
  id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, layer TEXT, cache_key TEXT,
  hit INTEGER, verified INTEGER, ms INTEGER, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS llm_cache (
  cache_key TEXT PRIMARY KEY, provider TEXT, model TEXT, prompt_ver TEXT, body TEXT NOT NULL,
  integrity TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS external_cache (
  cache_key TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL, fetched_at REAL NOT NULL,
  expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS llm_call (
  id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, role TEXT, purpose TEXT, provider TEXT, model TEXT,
  cached INTEGER, ok INTEGER, ms INTEGER, error TEXT, at REAL NOT NULL);
"""
# 后加的列：旧库启动时补齐
TASK_COLUMNS = {"material_fp": "TEXT", "superseded_by": "TEXT"}


class Store:
    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        with self._lock:
            self._db.executescript(SCHEMA)
            have = {r[1] for r in self._db.execute("PRAGMA table_info(task)")}
            for col, typ in TASK_COLUMNS.items():
                if col not in have:
                    self._db.execute(f"ALTER TABLE task ADD COLUMN {col} {typ}")
            self._db.execute("CREATE INDEX IF NOT EXISTS ix_task_req ON task (employee, request_id, created_at)")

    # ------------------------------------------------------------------ low level
    def _exec(self, sql: str, args=()):
        with self._lock:
            return self._db.execute(sql, args)

    def _one(self, sql: str, args=()):
        with self._lock:
            return self._db.execute(sql, args).fetchone()

    def _all(self, sql: str, args=()):
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def log_cache(self, task_id: str | None, layer: str, key: str, hit: bool, verified: bool | None, ms: int) -> None:
        self._exec("INSERT INTO cache_access (task_id, layer, cache_key, hit, verified, ms, at) VALUES (?,?,?,?,?,?,?)",
                   (task_id, layer, key, int(hit), None if verified is None else int(verified), ms, time.time()))

    # ------------------------------------------------------------------ 任务与结果
    def create_task(self, employee: str, source_system: str, request_id: str, rules_version: str,
                    trigger_by: str = "cli") -> str:
        task_id = uuid.uuid4().hex
        self._exec("INSERT INTO task (task_id, employee, source_system, request_id, trigger_by, status, "
                   "rules_version, created_at) VALUES (?,?,?,?,?,?,?,?)",
                   (task_id, employee, source_system, request_id, trigger_by, "running", rules_version, time.time()))
        return task_id

    def finish_task(self, task_id: str, status: str, error: str | None = None) -> None:
        self._exec("UPDATE task SET status=?, finished_at=?, error=? WHERE task_id=?",
                   (status, time.time(), error, task_id))

    def set_task_fp(self, task_id: str, material_fp: str) -> None:
        self._exec("UPDATE task SET material_fp=? WHERE task_id=?", (material_fp, task_id))

    def supersede_previous(self, task_id: str) -> int:
        """同一员工、同一单据之前已完成的审查标记为被本次取代。"""
        t = self.get_task(task_id)
        if not t:
            return 0
        cur = self._exec("UPDATE task SET superseded_by=? WHERE employee=? AND request_id=? AND source_system=? "
                         "AND task_id<>? AND status='done' AND superseded_by IS NULL AND created_at<?",
                         (task_id, t["employee"], t["request_id"], t["source_system"], task_id, t["created_at"]))
        return cur.rowcount

    def latest_task(self, employee: str, source_system: str, request_id: str) -> dict | None:
        row = self._one("SELECT * FROM task WHERE employee=? AND source_system=? AND request_id=? "
                        "ORDER BY created_at DESC LIMIT 1", (employee, source_system, request_id))
        return dict(row) if row else None

    def running_count(self, employee: str | None = None, trigger_by: str | None = None) -> int:
        sql, args = "SELECT COUNT(*) FROM task WHERE status='running'", []
        if employee:
            sql += " AND employee=?"
            args.append(employee)
        if trigger_by:
            sql += " AND trigger_by=?"
            args.append(trigger_by)
        return self._one(sql, args)[0]

    def fail_stale_tasks(self) -> int:
        """服务重启时，上次未结束的任务标记失败。"""
        cur = self._exec("UPDATE task SET status='failed', finished_at=?, error=? WHERE status='running'",
                         (time.time(), "工作台重启，审查中断｜请重新发起审查"))
        return cur.rowcount

    def node_start(self, task_id: str, node: str) -> int:
        cur = self._exec("INSERT INTO node_run (task_id, node, status, started_at) VALUES (?,?,?,?)",
                         (task_id, node, "running", time.time()))
        return cur.lastrowid

    def node_end(self, run_id: int, status: str, started: float, summary: str = "", error: str | None = None) -> None:
        now = time.time()
        self._exec("UPDATE node_run SET status=?, finished_at=?, duration_ms=?, summary=?, error=? WHERE id=?",
                   (status, now, int((now - started) * 1000), summary, error, run_id))

    def save_rules(self, task_id: str, results: list[dict]) -> None:
        for r in results:
            self._exec("INSERT OR REPLACE INTO rule_result VALUES (?,?,?,?,?,?,?,?,?)",
                       (task_id, r["rule_id"], r.get("rule_ver"), r["name"], r["tier"], r["status"],
                        r.get("message"), json.dumps(r.get("evidence", []), ensure_ascii=False), r.get("ms")))

    def save_report(self, task_id: str, body: dict) -> None:
        self._exec("INSERT OR REPLACE INTO report VALUES (?,?,?)",
                   (task_id, json.dumps(body, ensure_ascii=False), time.time()))

    def node_runs(self, task_id: str) -> list[dict]:
        return [dict(r) for r in self._all("SELECT node, status, duration_ms, summary, error FROM node_run "
                                           "WHERE task_id=? ORDER BY id", (task_id,))]

    def list_tasks(self, employee: str, limit: int = 30) -> list[dict]:
        rows = self._all("SELECT t.task_id, t.request_id, t.source_system, t.trigger_by, t.status, t.created_at, "
                         "t.finished_at, t.error, t.superseded_by, r.body "
                         "FROM task t LEFT JOIN report r ON r.task_id = t.task_id WHERE t.employee=? "
                         "ORDER BY t.created_at DESC LIMIT ?", (employee, limit))
        out = []
        for r in rows:
            body = json.loads(r["body"]) if r["body"] else {}
            h = body.get("header") or {}
            out.append({"task_id": r["task_id"], "request_id": r["request_id"], "status": r["status"],
                        "source": r["source_system"], "trigger_by": r["trigger_by"],
                        "superseded_by": r["superseded_by"],
                        "created_at": r["created_at"], "finished_at": r["finished_at"], "error": r["error"],
                        "request_name": h.get("request_name"), "采购内容": h.get("采购内容"),
                        "subject": h.get("subject") or h.get("采购内容") or h.get("request_name"),
                        "verdict": body.get("verdict"), "summary": body.get("summary")})
        return out

    def node_stats(self, employee: str, days: int = 30) -> dict:
        """近 days 天各节点的执行次数、平均耗时、失败次数。"""
        rows = self._all("SELECT n.node, COUNT(*) AS runs, AVG(n.duration_ms) AS avg_ms, "
                         "SUM(CASE WHEN n.status='failed' THEN 1 ELSE 0 END) AS failed FROM node_run n "
                         "JOIN task t ON t.task_id = n.task_id WHERE t.employee=? AND t.created_at>? GROUP BY n.node",
                         (employee, time.time() - days * 86400))
        return {r["node"]: {"runs": r["runs"], "avg_ms": int(r["avg_ms"] or 0), "failed": r["failed"]} for r in rows}

    def task_stats(self) -> dict:
        """按员工 × 触发方 × 状态汇总审查任务，另计被新版本取代的报告数。"""
        rows = self._all("SELECT employee, trigger_by, status, COUNT(*) AS n, "
                         "SUM(CASE WHEN superseded_by IS NOT NULL THEN 1 ELSE 0 END) AS superseded "
                         "FROM task GROUP BY employee, trigger_by, status")
        return [dict(r) for r in rows]

    def tasks_for(self, source_system: str, request_id: str) -> list[dict]:
        rows = self._all("SELECT t.task_id, t.employee, t.trigger_by, t.status, t.created_at, t.finished_at, t.error, "
                         "t.material_fp, t.superseded_by, r.body FROM task t LEFT JOIN report r ON r.task_id = t.task_id "
                         "WHERE t.source_system=? AND t.request_id=? ORDER BY t.created_at DESC", (source_system, request_id))
        out = []
        for r in rows:
            body = json.loads(r["body"]) if r["body"] else {}
            out.append({k: r[k] for k in ("task_id", "employee", "trigger_by", "status", "created_at", "finished_at",
                                          "error", "material_fp", "superseded_by")}
                       | {"verdict": body.get("verdict"), "summary": body.get("summary")})
        return out

    def get_report(self, task_id: str) -> dict | None:
        row = self._one("SELECT body FROM report WHERE task_id=?", (task_id,))
        return json.loads(row["body"]) if row else None

    def get_task(self, task_id: str) -> dict | None:
        row = self._one("SELECT * FROM task WHERE task_id=?", (task_id,))
        return dict(row) if row else None

    # ------------------------------------------------------------------ L3 外部查询
    def get_external(self, kind: str, key: str) -> dict | None:
        row = self._one("SELECT body, fetched_at FROM external_cache WHERE cache_key=? AND kind=? AND expires_at>?",
                        (key, kind, time.time()))
        return {**json.loads(row["body"]), "_cached_at": row["fetched_at"]} if row else None

    def put_external(self, kind: str, key: str, body: dict, ttl_s: float) -> None:
        now = time.time()
        self._exec("INSERT OR REPLACE INTO external_cache VALUES (?,?,?,?,?)",
                   (key, kind, json.dumps(body, ensure_ascii=False), now, now + ttl_s))

    # ------------------------------------------------------------------ L2 模型结果
    def get_llm_cache(self, key: str):
        return self._one("SELECT body, integrity FROM llm_cache WHERE cache_key=?", (key,))

    def put_llm_cache(self, key: str, provider: str, model: str, prompt_ver: str, body: str, integrity: str) -> None:
        self._exec("INSERT OR REPLACE INTO llm_cache VALUES (?,?,?,?,?,?,?)",
                   (key, provider, model, prompt_ver, body, integrity, time.time()))

    def log_llm(self, task_id: str | None, role: str, purpose: str, provider: str, model: str, cached: bool,
                ok: bool, ms: int, error: str | None = None) -> None:
        self._exec("INSERT INTO llm_call (task_id, role, purpose, provider, model, cached, ok, ms, error, at) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (task_id, role, purpose, provider, model, int(cached), int(ok), ms, error, time.time()))

    def llm_stats(self, task_id: str) -> dict:
        row = self._one("SELECT COUNT(*) AS n, SUM(cached) AS cached, SUM(1 - ok) AS failed, SUM(ms) AS ms "
                        "FROM llm_call WHERE task_id=?", (task_id,))
        return {"calls": row["n"] or 0, "cached": row["cached"] or 0, "failed": row["failed"] or 0,
                "ms": row["ms"] or 0}

    def cache_stats(self, task_id: str) -> dict:
        rows = self._all("SELECT layer, SUM(hit) AS hits, COUNT(*) AS total FROM cache_access WHERE task_id=? "
                         "GROUP BY layer", (task_id,))
        return {r["layer"]: {"hit": r["hits"], "total": r["total"]} for r in rows}
