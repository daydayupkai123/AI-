"""采集调度（资料中心进程内的后台线程）：按 config/collect.yaml 定期列出各来源待审单据，入同步队列提前下载、解析入库。

- 调度线程：每 20 秒检查一次，各来源按 interval_minutes 与 active_hours 判断是否到期，到期执行一轮
- 一轮：读各列表 → 登记单据（upsert_listed）→ 需要同步的入队（普通优先级）；open_detail=false 的列表只登记不入队
- 同步工作线程（sync_workers 个）：按优先级取队列执行单据同步；审查时的当场同步不经队列，OCR 配额优先
- 保留期：retention_days 大于 0 时清理过期的执行档案与不再出现的原件 / 解析结果
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from ..errors import friendly
from . import listers, settings

TICK_S = 20


def _num(cfg: dict, key: str, default: float) -> float:
    v = cfg.get(key)
    return float(default if v is None else v)


def in_active_hours(spec: str | None, now: datetime | None = None) -> bool:
    if not spec:
        return True
    try:
        a, b = [x.strip() for x in spec.split("-")]
        now = now or datetime.now()
        cur = now.strftime("%H:%M")
        return a <= cur <= b if a <= b else (cur >= a or cur <= b)
    except ValueError:
        return True


class Collector:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last: dict[str, float] = {}
        self._running: set[str] = set()
        self._lock = threading.Lock()
        self.last_error: dict[str, str] = {}

    # ------------------------------------------------------------------ 生命周期
    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        t = threading.Thread(target=self._loop, daemon=True, name="rc-collector")
        t.start()
        self._threads.append(t)
        for i in range(max(1, int(settings.collect().get("sync_workers") or 2))):
            w = threading.Thread(target=self._worker, daemon=True, name=f"rc-sync-{i}")
            w.start()
            self._threads.append(w)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        self._threads = []

    # ------------------------------------------------------------------ 调度
    def _loop(self) -> None:
        self._stop.wait(_num(settings.collect(), "start_delay_s", 30))  # 服务启动后稍候再开始第一轮
        while not self._stop.is_set():
            cfg = settings.collect()
            if cfg.get("enabled", True) and in_active_hours(cfg.get("active_hours")):
                interval = _num(cfg, "interval_minutes", 30) * 60
                for source, scfg in (cfg.get("sources") or {}).items():
                    if scfg.get("enabled") and time.time() - self._last.get(source, 0) >= interval:
                        self.run_round(source)
            self._retention(cfg)
            self._stop.wait(TICK_S)

    def run_round(self, source: str, force: bool = False) -> dict:
        """执行一轮采集（同一来源不并发）。返回本轮统计。
        force：人工「立即采集」时为 True，列表中可打开的单据全部重新同步（不等 resync_hours），
        附件版本未变的不重复下载、解析结果命中缓存，只重读表单与附件清单。"""
        with self._lock:
            if source in self._running:
                return {"source": source, "skipped": "上一轮尚未结束"}
            self._running.add(source)
        self._last[source] = time.time()
        cfg = settings.collect()
        scfg = (cfg.get("sources") or {}).get(source) or {}
        rid = self.store.start_round(source)
        stats = {"source": source, "listed": 0, "queued": 0, "synced": 0, "failed": 0, "lists": []}
        err = None
        try:
            lister = listers.LISTERS.get(source)
            if not lister:
                raise ValueError(f"来源 {source} 暂不支持采集")
            budget = int(_num(cfg, "max_requests_per_round", 50))
            for lst in scfg.get("lists") or []:
                t_list = time.time()
                try:
                    rows = self.service.with_login(source, lambda c, x=lst: lister(c, x))
                except Exception as exc:  # noqa: BLE001
                    info = friendly(exc)
                    stats["lists"].append({"name": lst.get("name"), "error": f"{info['title']}｜{info['detail']}"})
                    stats["failed"] += 1
                    continue
                open_detail = bool(lst.get("open_detail"))
                queued = 0
                for r in rows:
                    self.store.upsert_listed(source=source, request_id=r["request_id"], employee=lst.get("employee"),
                                             list_name=lst.get("name") or "", list_scope="pending"
                                             if listers.is_pending(lst) else "done", title=r.get("title") or "",
                                             open_detail=open_detail)
                    stats["listed"] += 1
                    if open_detail and budget > 0 and self._due(source, r["request_id"], cfg, force):
                        self.store.create_job(kind="request", source=source, request_id=r["request_id"], task_id=None,
                                              priority=1, trigger="collect")
                        budget -= 1
                        queued += 1
                stats["queued"] += queued
                stats["lists"].append({"name": lst.get("name"), "rows": len(rows), "queued": queued})
                # 列表读取成功：本轮未出现在列表中的旧快照将被标为 stale（不再自动审查）
                self.store.mark_list_ok(source, lst.get("name") or "", t_list, len(rows))
        except Exception as exc:  # noqa: BLE001
            info = friendly(exc)
            err = f"{info['title']}｜{info['detail']}"
            self.last_error[source] = err
        finally:
            self.store.finish_round(rid, listed=stats["listed"], queued=stats["queued"], synced=0,
                                    failed=stats["failed"], error=err or (
                                        "；".join(f"{x['name']}：{x['error']}" for x in stats["lists"] if x.get("error"))
                                        or None))
            with self._lock:
                self._running.discard(source)
        stats["error"] = err
        return stats

    def _due(self, source: str, request_id: str, cfg: dict, force: bool = False) -> bool:
        """是否需要（重新）同步：从未同步、上次失败且已过重试间隔、或已同步超过 resync_hours。"""
        if self.store.active_job(source, request_id):
            return False
        if force:
            return True
        snap = self.store.get_snapshot(source, request_id)
        if not snap:
            return True
        now = time.time()
        if snap["status"] == "failed":
            last = self.store.last_job_finished(source, request_id) or 0
            return now - last >= _num(cfg, "failed_retry_minutes", 60) * 60
        if not snap.get("synced_at"):
            return True
        return now - snap["synced_at"] >= _num(cfg, "resync_hours", 12) * 3600

    # ------------------------------------------------------------------ 同步队列
    def _worker(self) -> None:
        while not self._stop.is_set():
            job = self._claim()
            if not job:
                self._stop.wait(1)
                continue
            snap = self.store.get_snapshot(job["source"], job["request_id"]) or {}
            why = self._excluded(job["source"], snap)
            if why:
                self.store.update_job(job["job_id"], status="failed", error=why)
                self.store.set_snapshot_status(job["source"], job["request_id"], "excluded", why)
                continue
            try:
                self.service.run_request_job(job["job_id"], job["source"], job["request_id"], snap.get("employee"),
                                             skip_secret_levels=settings.collect().get("skip_prefetch_secret_levels"))
            except Exception:  # noqa: BLE001
                pass  # 已在任务与快照中记录失败原因

    def _excluded(self, source: str, snap: dict) -> str | None:
        """入队后配置可能已变：按当前配置再判断一次（列表已关闭详情读取、标题被排除）。"""
        import re

        lst = next((x for x in ((settings.collect().get("sources") or {}).get(source) or {}).get("lists") or []
                    if x.get("name") == snap.get("list_name")), None)
        if lst is None:
            return None
        if not lst.get("open_detail"):
            return f"列表「{lst.get('name')}」已配置为只读列表（open_detail: false）"
        if lst.get("title_exclude") and re.search(lst["title_exclude"], snap.get("title") or ""):
            return f"标题命中采集排除规则（{lst['title_exclude']}）"
        return None

    def _claim(self) -> dict | None:
        with self._lock:
            job = self.store.next_queued()
            if job:
                self.store.update_job(job["job_id"], status="running")
            return job

    # ------------------------------------------------------------------ 保留期
    def _retention(self, cfg: dict) -> None:
        days = cfg.get("retention_days") or {}
        now = time.time()
        if float(days.get("archive") or 0) > 0:
            self.store.purge_archive(now - float(days["archive"]) * 86400)
        if float(days.get("files") or 0) > 0:
            self.store.purge_files(now - float(days["files"]) * 86400)

    def status(self) -> dict:
        cfg = settings.collect()
        interval = _num(cfg, "interval_minutes", 30) * 60
        return {"enabled": bool(cfg.get("enabled", True)), "active_now": in_active_hours(cfg.get("active_hours")),
                "interval_minutes": cfg.get("interval_minutes"), "active_hours": cfg.get("active_hours"),
                "sources": {s: {"enabled": bool(v.get("enabled")), "lists": [x.get("name") for x in v.get("lists") or []],
                                "last_round_at": self._last.get(s),
                                "next_round_at": (self._last.get(s, 0) + interval) if v.get("enabled") else None,
                                "running": s in self._running, "last_error": self.last_error.get(s)}
                            for s, v in (cfg.get("sources") or {}).items()},
                "queue": self.store.queue_counts(), "rounds": self.store.recent_rounds(10),
                "workers_alive": sum(1 for t in self._threads if t.is_alive())}
