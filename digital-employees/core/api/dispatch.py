"""自动审查派发（工作台进程内的后台线程）：资料中心「已就绪」的单据，若未审查过或材料指纹已变化，自动发起审查。

- 只对 config/collect.yaml 中 auto_review 为 true 的数字员工生效
- 同时最多 auto_review_concurrency 笔自动审查（人工发起的不受此限制）
- 最近一次审查失败且材料未变化的不反复重试（材料变化后会重新发起）
- 结果只推送到工作台任务台（不写客户系统、不发外部消息）
"""
from __future__ import annotations

import threading

from ..errors import friendly
from ..resource import settings as rc_settings

TICK_S = 60


def decide(snapshot: dict, latest: dict | None) -> str | None:
    """返回发起原因（new / changed）；不需要发起时返回 None。"""
    if snapshot.get("status") != "ready" or not snapshot.get("material_fp") or snapshot.get("stale"):
        return None
    if latest is None:
        return "new"
    if latest["status"] == "running":
        return None
    if latest.get("material_fp") and latest["material_fp"] != snapshot["material_fp"]:
        return "changed"
    return None


class AutoDispatcher:
    def __init__(self, store, resources, launch, employees):
        """launch(emp, request_id, source, trigger_by) -> task_id；employees：registry.EMPLOYEES。"""
        self.store, self.resources, self.launch = store, resources, launch
        self.employees = {e.id: e for e in employees}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None
        self.launched: list[dict] = []

    def start(self, delay_s: float = 20) -> None:
        if self._thread:
            return

        def loop():
            self._stop.wait(delay_s)
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(TICK_S)

        self._thread = threading.Thread(target=loop, daemon=True, name="auto-review")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def tick(self) -> list[dict]:
        cfg = rc_settings.collect()
        auto = cfg.get("auto_review") or {}
        conc = cfg.get("auto_review_concurrency")
        limit = int(2 if conc is None else conc)  # 0 = 暂停自动审查
        started = []
        try:
            for emp_id, on in auto.items():
                emp = self.employees.get(emp_id)
                if not on or emp is None:
                    continue
                for snap in self.resources().requests(employee=emp_id, status="ready", limit=200):
                    if self.store.running_count(trigger_by="auto") >= limit:
                        return started
                    if snap["source"] not in emp.sources:
                        continue
                    latest = self.store.latest_task(emp_id, snap["source"], snap["request_id"])
                    why = decide(snap, latest)
                    if not why:
                        continue
                    tid = self.launch(emp, snap["request_id"], snap["source"], "auto")
                    rec = {"employee": emp_id, "request_id": snap["request_id"], "reason": why, "task_id": tid}
                    started.append(rec)
                    self.launched = (self.launched + [rec])[-50:]
            self.last_error = None
        except Exception as exc:  # noqa: BLE001
            info = friendly(exc)
            self.last_error = f"{info['title']}｜{info['detail']}"
        return started
