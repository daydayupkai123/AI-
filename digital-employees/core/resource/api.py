"""资料中心 HTTP 服务（独立进程）。

  .venv\\Scripts\\python.exe -m core.resource.api        # http://127.0.0.1:8091

长任务（附件补齐、解析补齐、单据同步）提交后立即返回 job_id，进度事件与结果经 /v1/jobs/{id}/events 轮询。
"""
from __future__ import annotations

import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from ..parsing import ocr
from . import settings
from .client import error_payload
from .service import ResourceService
from .store import ResourceStore


class JobBus:
    """长任务的进度事件与结果（内存，任务结束后保留 1 小时供轮询）。"""

    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def start(self, fn) -> str:
        job_id = f"j{time.time_ns():x}"
        with self.lock:
            self.jobs[job_id] = {"events": [], "status": "running", "result": None, "error": None, "at": time.time()}

        def emit(ev: dict) -> None:
            with self.lock:
                self.jobs[job_id]["events"].append(ev)

        def run() -> None:
            try:
                result = fn(emit)
                with self.lock:
                    self.jobs[job_id].update(status="done", result=result)
            except Exception as exc:  # noqa: BLE001
                with self.lock:
                    self.jobs[job_id].update(status="failed", error=error_payload(exc))

        threading.Thread(target=run, daemon=True, name=f"rc-{job_id}").start()
        self._gc()
        return job_id

    def read(self, job_id: str, since: int) -> dict | None:
        with self.lock:
            j = self.jobs.get(job_id)
            if not j:
                return None
            return {"events": j["events"][since:], "status": j["status"], "result": j["result"], "error": j["error"]}

    def _gc(self) -> None:
        cut = time.time() - 3600
        with self.lock:
            for k in [k for k, j in self.jobs.items() if j["status"] != "running" and j["at"] < cut]:
                self.jobs.pop(k, None)


class LookupIn(BaseModel):
    source: str
    attachments: list[dict]


class FilesIn(BaseModel):
    source: str
    request_id: str
    workflow_id: str = ""
    attachments: list[dict]
    task_id: str | None = None


class ParseIn(BaseModel):
    source: str
    request_id: str
    files: list[dict]
    task_id: str | None = None


class PlanIn(BaseModel):
    source: str
    files: list[dict]


class SyncIn(BaseModel):
    source: str
    request_id: str
    employee: str | None = None
    trigger: str = "manual"


class ArchiveStartIn(BaseModel):
    employee: str
    source: str
    request_id: str
    trigger_by: str = "web"
    versions: dict = {}


class ArchiveItemsIn(BaseModel):
    items: list[dict]


class ArchiveFinishIn(BaseModel):
    status: str
    material_fp: str | None = None
    verdict: dict | None = None
    error: str | None = None


class ShotsIn(BaseModel):
    items: list[dict]


class LocateIn(BaseModel):
    items: list[dict]


class PageIn(BaseModel):
    meta: dict
    png_b64: str
    pii: list[list[float]] = []


def build_app(service: ResourceService, *, start_background: bool = True) -> FastAPI:
    bus = JobBus()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if isinstance(ocr.engine(), ocr.RapidEngine):
            ocr.pool()  # 主线程预建 OCR 进程池
        service.store.fail_stale_jobs()
        if start_background and hasattr(service, "start_background"):
            service.start_background()
        yield
        if hasattr(service, "stop_background"):
            service.stop_background()

    app = FastAPI(title="AI 数字员工 · 资料中心", lifespan=lifespan)

    @app.exception_handler(Exception)
    async def on_error(_req, exc):
        return JSONResponse(status_code=500, content={"error": error_payload(exc)})

    @app.get("/v1/health")
    def health():
        return service.health()

    @app.post("/v1/files/lookup")
    def lookup(body: LookupIn):
        return service.lookup(body.source, body.attachments)

    @app.post("/v1/files/ensure")
    def ensure_files(body: FilesIn):
        return {"job_id": bus.start(lambda emit: service.ensure_files(
            body.source, body.request_id, body.workflow_id, body.attachments, body.task_id, emit))}

    @app.post("/v1/parse/plan")
    def parse_plan(body: PlanIn):
        return service.parse_plan(body.source, body.files)

    @app.post("/v1/parse/ensure")
    def ensure_parsed(body: ParseIn):
        return {"job_id": bus.start(lambda emit: service.ensure_parsed(
            body.source, body.request_id, body.files, body.task_id, emit))}

    @app.post("/v1/requests/sync")
    def sync(body: SyncIn):
        return {"job_id": bus.start(lambda emit: service.sync_request(
            body.source, body.request_id, body.employee, trigger=body.trigger, progress=emit))}

    @app.get("/v1/jobs/{job_id}/events")
    def job_events(job_id: str, since: int = 0):
        d = bus.read(job_id, since)
        if d is None:
            raise HTTPException(404, "not_found")
        return d

    @app.get("/v1/jobs/{job_id}")
    def job(job_id: str):
        d = service.job(job_id)
        if d is None:
            raise HTTPException(404, "not_found")
        return d

    @app.get("/v1/parse/{sig}")
    def parsed(sig: str, source: str = "contract"):
        d = service.parsed(sig, source)
        if d is None:
            raise HTTPException(404, "not_found")
        return d

    @app.get("/v1/files/{prefix}")
    def file_info(prefix: str):
        sig = service.blob_by_prefix(prefix)
        if not sig:
            raise HTTPException(404, "not_found")
        return {"sig": sig, "size": service.store.blob_size(sig), "meta": service.store.get_meta(sig)}

    @app.get("/v1/files/{sig}/content")
    def file_content(sig: str):
        if len(sig) != 64 or not service.store.has_blob(sig):
            raise HTTPException(404, "not_found")
        return Response(service.read_blob(sig), media_type="application/octet-stream")

    @app.get("/v1/requests")
    def list_requests(employee: str | None = None, status: str | None = None, limit: int = 100):
        return service.requests(employee, status, limit)

    @app.get("/v1/requests/{source}/{request_id}")
    def get_request(source: str, request_id: str):
        d = service.request(source, request_id)
        if d is None:
            raise HTTPException(404, "not_found")
        return d

    @app.post("/v1/archive/{task_id}/start")
    def archive_start(task_id: str, body: ArchiveStartIn):
        service.archive_start(task_id, body.employee, body.source, body.request_id, body.trigger_by, body.versions)
        return {"ok": True}

    @app.post("/v1/archive/{task_id}/items")
    def archive_items(task_id: str, body: ArchiveItemsIn):
        return {"seq": service.archive_items(task_id, body.items)}

    @app.post("/v1/archive/{task_id}/finish")
    def archive_finish(task_id: str, body: ArchiveFinishIn):
        service.archive_finish(task_id, body.status, body.material_fp, body.verdict, body.error)
        return {"ok": True}

    @app.post("/v1/archive/{task_id}/shots")
    def archive_shots(task_id: str, body: ShotsIn):
        return service.archive_shots(task_id, body.items)

    @app.get("/v1/archive/{task_id}")
    def archive(task_id: str, kinds: str | None = None):
        d = service.archive(task_id, kinds.split(",") if kinds else None)
        if d is None:
            raise HTTPException(404, "not_found")
        return d

    @app.get("/v1/archive/shots/{shot_id}.png")
    def shot_png(shot_id: str):
        png = service.shot_png(shot_id)
        if png is None:
            raise HTTPException(404, "not_found")
        return Response(png, media_type="image/png")

    @app.post("/v1/locate")
    def locate(body: LocateIn):
        return service.locate(body.items)

    @app.get("/v1/files/{sig}/pages/{page_no}.png")
    def file_page(sig: str, page_no: int, dpi: int = 110):
        r = service.page_image(sig, page_no, max(50, min(dpi, 200)))
        if r is None:
            raise HTTPException(404, "not_found")
        png, w, h = r
        return Response(png, media_type="image/png", headers={"X-Page-Size": f"{w:.1f},{h:.1f}"})

    @app.post("/v1/archive/{task_id}/pages")
    def archive_page(task_id: str, body: PageIn):
        import base64

        return {"page_id": service.archive_page(task_id, body.meta, base64.b64decode(body.png_b64), body.pii)}

    @app.get("/v1/archive/pages/{page_id}.png")
    def page_png(page_id: str, masked: int = 1, w: int | None = None):
        png = service.page_png(page_id, masked=bool(masked), max_width=w)
        if png is None:
            raise HTTPException(404, "not_found")
        return Response(png, media_type="image/png")

    @app.get("/v1/stats")
    def stats():
        return service.stats()

    @app.get("/v1/collect/status")
    def collect_status():
        return service.collect_status()

    @app.post("/v1/collect/run")
    def collect_run(source: str):
        """立即执行一轮采集（后台进行，进度见 /v1/collect/status）。"""
        threading.Thread(target=service.collect_run, args=(source,), daemon=True).start()
        return {"started": source}

    app.state.service = service
    app.state.bus = bus
    return app


def main() -> None:
    import uvicorn

    from ..session import provider_from_config

    service = ResourceService(ResourceStore(), provider_from_config())
    if service.store.migrated:
        print("资料中心：已从旧库迁入", service.store.migrated)
    uvicorn.run(build_app(service), host="127.0.0.1", port=int(settings.resource().get("port") or 8091),
                log_level="warning")


if __name__ == "__main__":
    main()
