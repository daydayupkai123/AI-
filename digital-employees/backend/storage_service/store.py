"""资料中心存储：原件（按内容签名寻址）、出处、解析结果、单据快照、同步任务、采集轮次、执行档案。

独立库文件（默认 .runtime/resource/resource.sqlite3），原件与解析结果目录沿用 .runtime/store。
首次创建时从旧的工作台库一次性迁入文件与解析记录（已有 OCR 结果不重做）。
表结构见 docs/文件解析结果缓存与存储设计.md 与 docs/资料中心与自动化设计.md。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from shared.env_config import DB_PATH, RC_DB_PATH, STORE
from shared.signing import content_sig

SCHEMA = """
CREATE TABLE IF NOT EXISTS file_blob (
  content_sig TEXT PRIMARY KEY, size_bytes INTEGER NOT NULL, kind TEXT, ext TEXT,
  storage_uri TEXT NOT NULL, first_seen_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS file_occurrence (
  id INTEGER PRIMARY KEY AUTOINCREMENT, content_sig TEXT NOT NULL, source_system TEXT NOT NULL,
  request_id TEXT, workflow_id TEXT, field_key TEXT, field_label TEXT, file_id TEXT,
  image_file_id TEXT, version_id TEXT, filename TEXT, parent_sig TEXT, upload_time TEXT,
  secret_level TEXT, fetched_at REAL NOT NULL, task_id TEXT,
  UNIQUE (source_system, request_id, field_key, image_file_id, parent_sig, filename, content_sig));
CREATE INDEX IF NOT EXISTS ix_occ_req ON file_occurrence (source_system, request_id);
CREATE INDEX IF NOT EXISTS ix_occ_ver ON file_occurrence (source_system, image_file_id, version_id);
CREATE INDEX IF NOT EXISTS ix_occ_sig ON file_occurrence (content_sig);
CREATE TABLE IF NOT EXISTS file_meta (
  content_sig TEXT PRIMARY KEY, meta TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS parse_result (
  proc_key TEXT PRIMARY KEY, content_sig TEXT NOT NULL, processor TEXT NOT NULL,
  processor_ver TEXT NOT NULL, params TEXT, origin TEXT NOT NULL, status TEXT NOT NULL,
  page_count INTEGER, char_count INTEGER, ocr_pages INTEGER, quality REAL,
  result_uri TEXT, integrity TEXT NOT NULL, error TEXT, duration_ms INTEGER, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_parse_sig ON parse_result (content_sig);
CREATE TABLE IF NOT EXISTS parse_page (
  proc_key TEXT NOT NULL, page_no INTEGER NOT NULL, method TEXT, ocr_conf REAL, text TEXT,
  PRIMARY KEY (proc_key, page_no));
CREATE TABLE IF NOT EXISTS request_snapshot (
  source TEXT NOT NULL, request_id TEXT NOT NULL, employee TEXT, list_name TEXT, list_scope TEXT,
  title TEXT, workflow_id TEXT, workflow_name TEXT, material_fp TEXT, fields TEXT, attachments TEXT,
  files_total INTEGER, files_ready INTEGER, parsed_ready INTEGER, status TEXT NOT NULL, error TEXT,
  open_detail INTEGER, first_seen_at REAL NOT NULL, listed_at REAL, synced_at REAL,
  PRIMARY KEY (source, request_id));
CREATE INDEX IF NOT EXISTS ix_snap_emp ON request_snapshot (employee, status);
CREATE TABLE IF NOT EXISTS sync_job (
  job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT, request_id TEXT, task_id TEXT,
  priority INTEGER NOT NULL, trigger TEXT NOT NULL, status TEXT NOT NULL, progress TEXT, error TEXT,
  created_at REAL NOT NULL, started_at REAL, finished_at REAL);
CREATE INDEX IF NOT EXISTS ix_job_status ON sync_job (status, priority, created_at);
CREATE TABLE IF NOT EXISTS list_state (
  source TEXT NOT NULL, list_name TEXT NOT NULL, last_ok_at REAL NOT NULL, rows INTEGER,
  PRIMARY KEY (source, list_name));
CREATE TABLE IF NOT EXISTS collect_round (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL,
  listed INTEGER, queued INTEGER, synced INTEGER, failed INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS archive_run (
  task_id TEXT PRIMARY KEY, employee TEXT, source TEXT, request_id TEXT, trigger_by TEXT, status TEXT,
  started_at REAL NOT NULL, finished_at REAL, material_fp TEXT, versions TEXT, verdict TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS ix_arc_req ON archive_run (source, request_id);
CREATE TABLE IF NOT EXISTS archive_item (
  id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, seq INTEGER NOT NULL, at REAL NOT NULL,
  kind TEXT NOT NULL, title TEXT, body TEXT, size INTEGER);
CREATE INDEX IF NOT EXISTS ix_arc_item ON archive_item (task_id, seq);
CREATE TABLE IF NOT EXISTS archive_shot (
  shot_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, content_sig TEXT, filename TEXT, page_no INTEGER,
  quote TEXT, label TEXT, rule_id TEXT, method TEXT, rects TEXT, png_uri TEXT, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_arc_shot ON archive_shot (task_id);
CREATE TABLE IF NOT EXISTS archive_page (
  page_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, title TEXT, url TEXT, width INTEGER, height INTEGER,
  pii TEXT, png_uri TEXT NOT NULL, png_sig TEXT, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_arc_page ON archive_page (task_id);
"""

_MIGRATE_TABLES = ("file_blob", "file_occurrence", "file_meta", "parse_result", "parse_page")


class ResourceStore:
    def __init__(self, db_path: Path = RC_DB_PATH, root: Path = STORE, legacy_db: Path | None = DB_PATH):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        fresh = not db_path.exists()
        self.db_path = db_path
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        with self._lock:
            self._db.executescript(SCHEMA)
        self.migrated: dict[str, int] = {}
        if fresh and legacy_db and Path(legacy_db).exists() and Path(legacy_db).resolve() != db_path.resolve():
            self._migrate(Path(legacy_db))

    def _migrate(self, legacy: Path) -> None:
        """旧工作台库中的文件与解析记录一次性迁入（只读旧库，不删除）。"""
        with self._lock:
            self._db.execute("ATTACH DATABASE ? AS legacy", (str(legacy),))
            try:
                have = {r[0] for r in self._db.execute("SELECT name FROM legacy.sqlite_master WHERE type='table'")}
                self._db.execute("BEGIN")
                for t in _MIGRATE_TABLES:
                    if t not in have:
                        continue
                    cols = [r[1] for r in self._db.execute(f"PRAGMA legacy.table_info({t})")]
                    mine = {r[1] for r in self._db.execute(f"PRAGMA main.table_info({t})")}
                    common = ",".join(c for c in cols if c in mine)
                    cur = self._db.execute(f"INSERT OR IGNORE INTO main.{t} ({common}) SELECT {common} FROM legacy.{t}")
                    self.migrated[t] = cur.rowcount
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
            finally:
                self._db.execute("DETACH DATABASE legacy")

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

    # ------------------------------------------------------------------ L0 原件
    def blob_path(self, sig: str) -> Path:
        return self.root / "blobs" / sig[:2] / sig

    def put_blob(self, data: bytes, kind: str = "", ext: str = "") -> str:
        sig = content_sig(data)
        path = self.blob_path(sig)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        self._exec("INSERT OR IGNORE INTO file_blob VALUES (?,?,?,?,?,?)",
                   (sig, len(data), kind, ext, str(path.relative_to(self.root)), time.time()))
        return sig

    def has_blob(self, sig: str) -> bool:
        return self.blob_path(sig).exists()

    def read_blob(self, sig: str) -> bytes:
        return self.blob_path(sig).read_bytes()

    def blob_size(self, sig: str) -> int | None:
        row = self._one("SELECT size_bytes FROM file_blob WHERE content_sig=?", (sig,))
        return row["size_bytes"] if row else None

    def blob_by_prefix(self, prefix: str) -> str | None:
        row = self._one("SELECT content_sig FROM file_blob WHERE content_sig LIKE ? LIMIT 1", (prefix + "%",))
        return row["content_sig"] if row else None

    def add_occurrence(self, **kw) -> None:
        cols = ["content_sig", "source_system", "request_id", "workflow_id", "field_key", "field_label",
                "file_id", "image_file_id", "version_id", "filename", "parent_sig", "upload_time",
                "secret_level", "task_id"]
        vals = [kw.get(c) for c in cols]
        self._exec(f"INSERT OR IGNORE INTO file_occurrence ({','.join(cols)}, fetched_at) "
                   f"VALUES ({','.join('?' * len(cols))}, ?)", (*vals, time.time()))

    def known_version(self, source_system: str, image_file_id: str, version_id: str) -> str | None:
        """同一附件版本（不可变）已下载过则返回其内容签名，可跳过重复下载。"""
        if not image_file_id or not version_id:
            return None
        row = self._one("SELECT content_sig FROM file_occurrence WHERE source_system=? AND image_file_id=? "
                        "AND version_id=? ORDER BY id DESC LIMIT 1", (source_system, image_file_id, version_id))
        if row and self.has_blob(row["content_sig"]):
            return row["content_sig"]
        return None

    def occurrences(self, source_system: str, request_id: str) -> list[dict]:
        return [dict(r) for r in self._all(
            "SELECT * FROM file_occurrence WHERE source_system=? AND request_id=? ORDER BY id",
            (source_system, request_id))]

    def set_meta(self, sig: str, meta: dict) -> None:
        self._exec("INSERT OR REPLACE INTO file_meta VALUES (?,?)", (sig, json.dumps(meta, ensure_ascii=False)))

    def get_meta(self, sig: str) -> dict:
        row = self._one("SELECT meta FROM file_meta WHERE content_sig=?", (sig,))
        return json.loads(row["meta"]) if row else {}

    # ------------------------------------------------------------------ L1 解析
    def parsed_path(self, sig: str, key: str) -> Path:
        return self.root / "parsed" / sig[:2] / sig / f"{key}.json"

    def get_parse(self, key: str):
        return self._one("SELECT * FROM parse_result WHERE proc_key=?", (key,))

    def save_parse(self, *, key: str, sig: str, processor: str, version: str, params: dict, origin: str,
                   status: str, doc_bytes: bytes, integrity: str, page_count: int, char_count: int,
                   ocr_pages: int, quality: float | None, error: str | None, duration_ms: int,
                   pages: list[dict]) -> None:
        path = self.parsed_path(sig, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_bytes(doc_bytes)
        tmp.replace(path)
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.execute("INSERT OR REPLACE INTO parse_result VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (key, sig, processor, version, json.dumps(params), origin, status, page_count,
                                  char_count, ocr_pages, quality, str(path.relative_to(self.root)), integrity,
                                  error, duration_ms, time.time()))
                self._db.execute("DELETE FROM parse_page WHERE proc_key=?", (key,))
                self._db.executemany("INSERT INTO parse_page VALUES (?,?,?,?,?)",
                                     [(key, p["no"], p.get("method"), p.get("conf"), p.get("text", "")) for p in pages])
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------ 单据快照
    def get_snapshot(self, source: str, request_id: str) -> dict | None:
        row = self._one("SELECT * FROM request_snapshot WHERE source=? AND request_id=?", (source, request_id))
        return _snap(row) if row else None

    def upsert_listed(self, *, source: str, request_id: str, employee: str, list_name: str, list_scope: str,
                      title: str, open_detail: bool) -> None:
        now = time.time()
        self._exec("INSERT INTO request_snapshot (source, request_id, employee, list_name, list_scope, title, status, "
                   "open_detail, first_seen_at, listed_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
                   "ON CONFLICT(source, request_id) DO UPDATE SET employee=excluded.employee, "
                   "list_name=excluded.list_name, list_scope=excluded.list_scope, "
                   "title=COALESCE(NULLIF(excluded.title, ''), request_snapshot.title), "
                   "open_detail=excluded.open_detail, listed_at=excluded.listed_at",
                   (source, request_id, employee, list_name, list_scope, title, "listed", int(open_detail), now, now))

    def save_snapshot(self, *, source: str, request_id: str, employee: str | None, title: str, workflow_id: str,
                      workflow_name: str, material_fp: str, fields: list[dict], attachments: list[dict],
                      files_total: int, files_ready: int, parsed_ready: int, status: str, error: str | None) -> None:
        now = time.time()
        self._exec(
            "INSERT INTO request_snapshot (source, request_id, employee, title, workflow_id, workflow_name, material_fp, "
            "fields, attachments, files_total, files_ready, parsed_ready, status, error, first_seen_at, synced_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source, request_id) DO UPDATE SET "
            "employee=COALESCE(excluded.employee, request_snapshot.employee), "
            "title=COALESCE(NULLIF(request_snapshot.title, ''), excluded.title), "
            "workflow_id=excluded.workflow_id, workflow_name=excluded.workflow_name, material_fp=excluded.material_fp, "
            "fields=excluded.fields, attachments=excluded.attachments, files_total=excluded.files_total, "
            "files_ready=excluded.files_ready, parsed_ready=excluded.parsed_ready, status=excluded.status, "
            "error=excluded.error, synced_at=excluded.synced_at",
            (source, request_id, employee, title, workflow_id, workflow_name, material_fp,
             json.dumps(fields, ensure_ascii=False), json.dumps(attachments, ensure_ascii=False), files_total,
             files_ready, parsed_ready, status, error, now, now))

    def set_snapshot_status(self, source: str, request_id: str, status: str, error: str | None = None) -> None:
        self._exec("UPDATE request_snapshot SET status=?, error=? WHERE source=? AND request_id=?",
                   (status, error, source, request_id))

    def list_snapshots(self, employee: str | None = None, status: str | None = None, limit: int = 100) -> list[dict]:
        """stale：该单据所属列表最近一次成功读取时已不在列表中（如换账号后看不到、单据已办结离开待办）。"""
        sql = ("SELECT s.*, l.last_ok_at AS list_ok_at FROM request_snapshot s LEFT JOIN list_state l "
               "ON l.source = s.source AND l.list_name = s.list_name WHERE 1=1")
        args: list = []
        if employee:
            sql += " AND s.employee=?"
            args.append(employee)
        if status:
            sql += " AND s.status=?"
            args.append(status)
        sql += " ORDER BY COALESCE(s.listed_at, s.synced_at, s.first_seen_at) DESC LIMIT ?"
        args.append(limit)
        out = []
        for r in self._all(sql, args):
            d = _snap(r)
            ok_at = d.pop("list_ok_at", None)
            d["stale"] = bool(ok_at and d.get("listed_at") and d["listed_at"] < ok_at)
            out.append(d)
        return out

    def stats(self) -> dict:
        """全流程演示用的汇总：原件、出现记录、解析、快照、同步队列、采集轮次、执行档案。"""
        def one(sql: str) -> dict:
            return dict(self._one(sql))

        def group(sql: str) -> dict:
            return {r[0] or "": r[1] for r in self._all(sql)}

        return {
            "blobs": one("SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS bytes FROM file_blob"),
            "occurrences": one("SELECT COUNT(*) AS n, COUNT(DISTINCT content_sig) AS sigs, "
                               "COUNT(DISTINCT source_system || '/' || request_id) AS requests, "
                               "SUM(CASE WHEN parent_sig IS NOT NULL THEN 1 ELSE 0 END) AS extracted FROM file_occurrence"),
            "parse": one("SELECT COUNT(*) AS n, COALESCE(SUM(page_count), 0) AS pages, "
                         "COALESCE(SUM(ocr_pages), 0) AS ocr_pages, "
                         "SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS ok FROM parse_result"),
            "parse_by_processor": group("SELECT json_extract(params, '$.ocr'), COUNT(*) FROM parse_result GROUP BY 1"),
            "snapshots": group("SELECT status, COUNT(*) FROM request_snapshot GROUP BY status"),
            "snapshots_by_employee": group("SELECT employee, COUNT(*) FROM request_snapshot GROUP BY employee"),
            "jobs": group("SELECT trigger || ':' || status, COUNT(*) FROM sync_job GROUP BY 1"),
            "rounds": one("SELECT COUNT(*) AS n, COALESCE(SUM(listed), 0) AS listed, COALESCE(SUM(queued), 0) AS queued, "
                          "MAX(started_at) AS last_at FROM collect_round"),
            "archives": group("SELECT trigger_by, COUNT(*) FROM archive_run GROUP BY trigger_by"),
            "archive_items": group("SELECT kind, COUNT(*) FROM archive_item GROUP BY kind"),
            "shots": one("SELECT COUNT(*) AS n FROM archive_shot")["n"],
        }

    def archives_for(self, source: str, request_id: str) -> list[dict]:
        return [dict(r) for r in self._all(
            "SELECT task_id, employee, trigger_by, status, started_at, finished_at, material_fp FROM archive_run "
            "WHERE source=? AND request_id=? ORDER BY started_at DESC", (source, request_id))]

    def mark_list_ok(self, source: str, list_name: str, at: float, rows: int) -> None:
        self._exec("INSERT OR REPLACE INTO list_state VALUES (?,?,?,?)", (source, list_name, at, rows))

    # ------------------------------------------------------------------ 同步任务与采集轮次
    def create_job(self, *, kind: str, source: str | None, request_id: str | None, task_id: str | None,
                   priority: int, trigger: str) -> str:
        job_id = uuid.uuid4().hex
        self._exec("INSERT INTO sync_job (job_id, kind, source, request_id, task_id, priority, trigger, status, "
                   "progress, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (job_id, kind, source, request_id, task_id, priority, trigger, "queued", "{}", time.time()))
        return job_id

    def update_job(self, job_id: str, *, status: str | None = None, progress: dict | None = None,
                   error: str | None = None) -> None:
        sets, args = [], []
        if status:
            sets.append("status=?")
            args.append(status)
            if status == "running":
                sets.append("started_at=?")
                args.append(time.time())
            if status in ("done", "failed"):
                sets.append("finished_at=?")
                args.append(time.time())
        if progress is not None:
            sets.append("progress=?")
            args.append(json.dumps(progress, ensure_ascii=False))
        if error is not None:
            sets.append("error=?")
            args.append(error)
        if sets:
            self._exec(f"UPDATE sync_job SET {', '.join(sets)} WHERE job_id=?", (*args, job_id))

    def get_job(self, job_id: str) -> dict | None:
        row = self._one("SELECT * FROM sync_job WHERE job_id=?", (job_id,))
        if not row:
            return None
        d = dict(row)
        d["progress"] = json.loads(d["progress"] or "{}")
        return d

    def active_job(self, source: str, request_id: str) -> dict | None:
        row = self._one("SELECT job_id FROM sync_job WHERE source=? AND request_id=? AND kind='request' "
                        "AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1", (source, request_id))
        return self.get_job(row["job_id"]) if row else None

    def next_queued(self) -> dict | None:
        row = self._one("SELECT job_id FROM sync_job WHERE status='queued' AND kind='request' "
                        "ORDER BY priority DESC, created_at LIMIT 1")
        return self.get_job(row["job_id"]) if row else None

    def last_job_finished(self, source: str, request_id: str) -> float | None:
        row = self._one("SELECT MAX(finished_at) AS t FROM sync_job WHERE source=? AND request_id=? AND kind='request'",
                        (source, request_id))
        return row["t"] if row else None

    def queue_counts(self) -> dict:
        return {r["status"]: r["n"] for r in self._all(
            "SELECT status, COUNT(*) AS n FROM sync_job WHERE kind='request' GROUP BY status")}

    def purge_archive(self, before: float) -> int:
        """删除开始时间早于 before 的执行档案（含截图文件）。"""
        olds = [r["task_id"] for r in self._all("SELECT task_id FROM archive_run WHERE started_at<?", (before,))]
        for tid in olds:
            for s in self._all("SELECT png_uri FROM archive_shot WHERE task_id=? UNION ALL "
                               "SELECT png_uri FROM archive_page WHERE task_id=?", (tid, tid)):
                if s["png_uri"]:
                    (self.root / s["png_uri"]).unlink(missing_ok=True)
            for t in ("archive_item", "archive_shot", "archive_page", "archive_run"):
                self._exec(f"DELETE FROM {t} WHERE task_id=?", (tid,))
        return len(olds)

    def purge_files(self, before: float) -> int:
        """删除最近一次出现早于 before 的原件及其解析结果（仍在近期单据中出现的保留）。"""
        sigs = [r["content_sig"] for r in self._all(
            "SELECT content_sig FROM file_occurrence GROUP BY content_sig HAVING MAX(fetched_at)<?", (before,))]
        for sig in sigs:
            for p in self._all("SELECT proc_key, result_uri FROM parse_result WHERE content_sig=?", (sig,)):
                if p["result_uri"]:
                    (self.root / p["result_uri"]).unlink(missing_ok=True)
                self._exec("DELETE FROM parse_page WHERE proc_key=?", (p["proc_key"],))
            self._exec("DELETE FROM parse_result WHERE content_sig=?", (sig,))
            self.blob_path(sig).unlink(missing_ok=True)
            for t in ("file_occurrence", "file_meta", "file_blob"):
                self._exec(f"DELETE FROM {t} WHERE content_sig=?", (sig,))
        return len(sigs)

    def fail_stale_jobs(self) -> int:
        """服务重启时：采集队列里未完成的单据同步重新排队（同步可重复执行，已下载、已解析的直接复用）；
        随审查发起的当场同步已随原进程结束，标记失败。"""
        self._exec("UPDATE sync_job SET status='queued', started_at=NULL WHERE kind='request' AND status='running'")
        cur = self._exec("UPDATE sync_job SET status='failed', error='资料中心重启，任务中断', finished_at=? "
                         "WHERE kind<>'request' AND status IN ('queued', 'running')", (time.time(),))
        return cur.rowcount

    def start_round(self, source: str) -> int:
        cur = self._exec("INSERT INTO collect_round (source, started_at) VALUES (?,?)", (source, time.time()))
        return cur.lastrowid

    def finish_round(self, round_id: int, *, listed: int, queued: int, synced: int, failed: int,
                     error: str | None = None) -> None:
        self._exec("UPDATE collect_round SET finished_at=?, listed=?, queued=?, synced=?, failed=?, error=? WHERE id=?",
                   (time.time(), listed, queued, synced, failed, error, round_id))

    def recent_rounds(self, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self._all("SELECT * FROM collect_round ORDER BY id DESC LIMIT ?", (limit,))]

    # ------------------------------------------------------------------ 执行档案
    def archive_start(self, *, task_id: str, employee: str, source: str, request_id: str, trigger_by: str,
                      versions: dict) -> None:
        self._exec("INSERT OR REPLACE INTO archive_run (task_id, employee, source, request_id, trigger_by, status, "
                   "started_at, versions) VALUES (?,?,?,?,?,?,?,?)",
                   (task_id, employee, source, request_id, trigger_by, "running", time.time(),
                    json.dumps(versions, ensure_ascii=False)))

    def archive_items(self, task_id: str, items: list[dict]) -> int:
        with self._lock:
            row = self._db.execute("SELECT COALESCE(MAX(seq), 0) FROM archive_item WHERE task_id=?", (task_id,)).fetchone()
            seq = row[0]
            rows = []
            for it in items:
                seq += 1
                body = json.dumps(it.get("body"), ensure_ascii=False, default=str)
                rows.append((task_id, seq, it.get("at") or time.time(), it["kind"], it.get("title"), body, len(body)))
            self._db.executemany("INSERT INTO archive_item (task_id, seq, at, kind, title, body, size) "
                                 "VALUES (?,?,?,?,?,?,?)", rows)
            return seq

    def archive_finish(self, task_id: str, *, status: str, material_fp: str | None, verdict: dict | None,
                       error: str | None) -> None:
        self._exec("UPDATE archive_run SET status=?, finished_at=?, material_fp=COALESCE(?, material_fp), verdict=?, "
                   "error=? WHERE task_id=?",
                   (status, time.time(), material_fp, json.dumps(verdict, ensure_ascii=False) if verdict else None,
                    error, task_id))

    def archive_set_fp(self, task_id: str, material_fp: str) -> None:
        self._exec("UPDATE archive_run SET material_fp=? WHERE task_id=?", (material_fp, task_id))

    def get_archive(self, task_id: str, kinds: list[str] | None = None) -> dict | None:
        run = self._one("SELECT * FROM archive_run WHERE task_id=?", (task_id,))
        if not run:
            return None
        out = dict(run)
        out["versions"] = json.loads(out["versions"] or "{}")
        out["verdict"] = json.loads(out["verdict"]) if out["verdict"] else None
        sql, args = "SELECT seq, at, kind, title, body, size FROM archive_item WHERE task_id=?", [task_id]
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            args += kinds
        out["items"] = [{**dict(r), "body": json.loads(r["body"]) if r["body"] else None}
                        for r in self._all(sql + " ORDER BY seq", args)]
        out["shots"] = [dict(r) for r in self._all("SELECT * FROM archive_shot WHERE task_id=? ORDER BY created_at",
                                                   (task_id,))]
        for s in out["shots"]:
            s["rects"] = json.loads(s["rects"] or "[]")
        out["pages"] = [{k: r[k] for k in ("page_id", "title", "url", "width", "height", "created_at")}
                        | {"pii_count": len(json.loads(r["pii"] or "[]"))}
                        for r in self._all("SELECT * FROM archive_page WHERE task_id=? ORDER BY created_at", (task_id,))]
        return out

    def save_page(self, *, task_id: str, title: str, url: str, width: int | None, height: int | None, pii: list,
                  png: bytes) -> str:
        """平台页面截图原样保存（打码只在展示时按 pii 坐标进行）。"""
        import hashlib

        page_id = uuid.uuid4().hex[:16]
        path = self.root / "pages" / task_id / f"{page_id}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        self._exec("INSERT INTO archive_page VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (page_id, task_id, title, url, width, height, json.dumps(pii), str(path.relative_to(self.root)),
                    hashlib.sha256(png).hexdigest(), time.time()))
        return page_id

    def get_page(self, page_id: str) -> dict | None:
        row = self._one("SELECT * FROM archive_page WHERE page_id=?", (page_id,))
        if not row:
            return None
        d = dict(row)
        d["pii"] = json.loads(d["pii"] or "[]")
        return d

    def save_shot(self, *, task_id: str, sig: str, filename: str, page_no: int | None, quote: str, label: str,
                  rule_id: str, method: str, rects: list, png_uri: str | None) -> str:
        shot_id = uuid.uuid4().hex[:16]
        self._exec("INSERT INTO archive_shot VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (shot_id, task_id, sig, filename, page_no, quote, label, rule_id, method,
                    json.dumps(rects), png_uri, time.time()))
        return shot_id

    def get_shot(self, shot_id: str) -> dict | None:
        row = self._one("SELECT * FROM archive_shot WHERE shot_id=?", (shot_id,))
        return dict(row) if row else None


def _snap(row) -> dict:
    d = dict(row)
    for k in ("fields", "attachments"):
        d[k] = json.loads(d[k]) if d.get(k) else []
    return d
