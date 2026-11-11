"""资料中心客户端：数字员工与工作台只通过它访问资料中心。

- LocalResourceClient：进程内直接调用服务层（测试、单进程调试）
- HttpResourceClient：调用独立运行的资料中心进程；长任务（下载、解析、同步）提交后轮询进度事件，语义与进程内一致
default_client() 按 config/resource.yaml（或 DE_RC_MODE / DE_RC_URL）选择。
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, is_dataclass
from typing import Callable

import requests

from .. import errors as E
from . import settings

Progress = Callable[[dict], None]


class ResourceUnavailable(E.DEError):
    title = "资料中心无法访问"
    hint = ("资料中心是独立进程，请先启动：.venv\\Scripts\\python.exe -m core.resource.api（默认 http://127.0.0.1:8091），"
            "或在 config/resource.yaml 中改为 inprocess 单进程运行。")


_ERRORS = {c.__name__: c for c in (E.SessionExpired, E.BrowserUnavailable, E.NoAccess, E.WrongWorkflow,
                                   E.UpstreamUnavailable, E.UpstreamUnexpected, ResourceUnavailable)}


def error_payload(exc: BaseException) -> dict:
    info = E.friendly(exc)
    return {"code": type(exc).__name__ if isinstance(exc, E.DEError) else info["code"], "title": info["title"],
            "hint": info["hint"], "detail": info["detail"]}


def raise_payload(p: dict):
    cls = _ERRORS.get(p.get("code"), E.DEError)
    raise cls(p.get("detail") or "", title=p.get("title"), hint=p.get("hint"))


def _plain(atts: list) -> list[dict]:
    return [asdict(a) if is_dataclass(a) else dict(a) for a in atts]


class LocalResourceClient:
    def __init__(self, service):
        self.service = service

    def lookup(self, source, attachments):
        return self.service.lookup(source, attachments)

    def ensure_files(self, source, request_id, workflow_id, attachments, task_id=None, progress=None):
        return self.service.ensure_files(source, request_id, workflow_id, attachments, task_id, progress)

    def ensure_parsed(self, source, request_id, files, task_id=None, progress=None):
        return self.service.ensure_parsed(source, request_id, files, task_id, progress)

    def parse_plan(self, source, files):
        return self.service.parse_plan(source, files)

    def parsed(self, sig, source="contract"):
        return self.service.parsed(sig, source)

    def read_blob(self, sig):
        return self.service.read_blob(sig)

    def blob_by_prefix(self, prefix):
        return self.service.blob_by_prefix(prefix)

    def sync_request(self, source, request_id, employee=None, trigger="manual", progress=None):
        return self.service.sync_request(source, request_id, employee, trigger=trigger, progress=progress)

    def requests(self, employee=None, status=None, limit=100):
        return self.service.requests(employee, status, limit)

    def request(self, source, request_id):
        return self.service.request(source, request_id)

    def health(self):
        return self.service.health()

    def __getattr__(self, name):
        # 采集、档案等其余服务方法直接透传
        return getattr(self.service, name)


class HttpResourceClient:
    def __init__(self, base_url: str | None = None, poll_s: float | None = None):
        self.base = (base_url or settings.url()).rstrip("/")
        self.poll_s = float(poll_s or settings.resource().get("poll_interval_s") or 0.5)
        self.s = requests.Session()
        self.s.trust_env = False

    def _req(self, method: str, path: str, timeout: float = 60, **kw):
        try:
            r = self.s.request(method, self.base + path, timeout=timeout, **kw)
        except requests.RequestException as exc:
            raise ResourceUnavailable(f"{self.base}{path}：{type(exc).__name__}: {exc}") from exc
        if r.status_code == 404 and r.headers.get("content-type", "").startswith("application/json") \
                and (r.json() or {}).get("detail") == "not_found":
            return None
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                raise ResourceUnavailable(f"{method} {path} 返回 {r.status_code}：{r.text[:200]}") from None
            if isinstance(body, dict) and isinstance(body.get("error"), dict):
                raise_payload(body["error"])
            raise ResourceUnavailable(f"{method} {path} 返回 {r.status_code}：{str(body)[:200]}")
        return r

    def _json(self, method: str, path: str, **kw):
        r = self._req(method, path, **kw)
        return None if r is None else r.json()

    def _job(self, path: str, body: dict, progress: Progress | None):
        job = self._json("POST", path, json=body)["job_id"]
        since, slow_since = 0, None
        while True:
            # OCR 满负荷时资料中心偶尔几十秒不响应；查进度是幂等的，超时就重试，连续 5 分钟无响应才判定不可用
            try:
                d = self._json("GET", f"/v1/jobs/{job}/events", params={"since": since}, timeout=60)
                slow_since = None
            except ResourceUnavailable as exc:
                slow_since = slow_since or time.time()
                if not isinstance(exc.__cause__, requests.RequestException) or time.time() - slow_since > 300:
                    raise
                time.sleep(2)
                continue
            for ev in d["events"]:
                if progress:
                    progress(ev)
            since += len(d["events"])
            if d["status"] == "done":
                return d["result"]
            if d["status"] == "failed":
                raise_payload(d["error"])
            time.sleep(self.poll_s)

    def lookup(self, source, attachments):
        return self._json("POST", "/v1/files/lookup", json={"source": source, "attachments": _plain(attachments)})

    def ensure_files(self, source, request_id, workflow_id, attachments, task_id=None, progress=None):
        return self._job("/v1/files/ensure", {"source": source, "request_id": request_id, "workflow_id": workflow_id,
                                              "attachments": _plain(attachments), "task_id": task_id}, progress)

    def ensure_parsed(self, source, request_id, files, task_id=None, progress=None):
        return self._job("/v1/parse/ensure", {"source": source, "request_id": request_id, "files": files,
                                              "task_id": task_id}, progress)

    def parse_plan(self, source, files):
        return self._json("POST", "/v1/parse/plan", json={"source": source, "files": files}, timeout=120)

    def parsed(self, sig, source="contract"):
        return self._json("GET", f"/v1/parse/{sig}", params={"source": source}, timeout=120)

    def read_blob(self, sig):
        r = self._req("GET", f"/v1/files/{sig}/content", timeout=300)
        if r is None:
            raise FileNotFoundError(sig)
        return r.content

    def blob_by_prefix(self, prefix):
        d = self._json("GET", f"/v1/files/{prefix}")
        return d["sig"] if d else None

    def sync_request(self, source, request_id, employee=None, trigger="manual", progress=None):
        return self._job("/v1/requests/sync", {"source": source, "request_id": request_id, "employee": employee,
                                               "trigger": trigger}, progress)

    def requests(self, employee=None, status=None, limit=100):
        return self._json("GET", "/v1/requests", params={k: v for k, v in
                                                          {"employee": employee, "status": status, "limit": limit}.items()
                                                          if v is not None})

    def request(self, source, request_id):
        return self._json("GET", f"/v1/requests/{source}/{requests.utils.quote(request_id, safe='')}")

    def health(self):
        return self._json("GET", "/v1/health", timeout=5)

    def stats(self):
        return self._json("GET", "/v1/stats", timeout=30)

    def archive_start(self, task_id, employee, source, request_id, trigger_by, versions):
        self._json("POST", f"/v1/archive/{task_id}/start", json={"employee": employee, "source": source,
                                                                  "request_id": request_id, "trigger_by": trigger_by,
                                                                  "versions": versions})

    def archive_items(self, task_id, items):
        return self._json("POST", f"/v1/archive/{task_id}/items", json={"items": items}, timeout=120)["seq"]

    def archive_finish(self, task_id, status, material_fp=None, verdict=None, error=None):
        self._json("POST", f"/v1/archive/{task_id}/finish", json={"status": status, "material_fp": material_fp,
                                                                   "verdict": verdict, "error": error})

    def archive_shots(self, task_id, items):
        return self._json("POST", f"/v1/archive/{task_id}/shots", json={"items": items}, timeout=300)

    def archive(self, task_id, kinds=None):
        return self._json("GET", f"/v1/archive/{task_id}", params={"kinds": ",".join(kinds)} if kinds else None,
                          timeout=120)

    def shot_png(self, shot_id):
        r = self._req("GET", f"/v1/archive/shots/{shot_id}.png")
        return None if r is None else r.content

    def locate(self, items):
        return self._json("POST", "/v1/locate", json={"items": items}, timeout=300)

    def page_image(self, sig, page_no, dpi=110, filename=""):
        r = self._req("GET", f"/v1/files/{sig}/pages/{page_no}.png", params={"dpi": dpi}, timeout=120)
        if r is None:
            return None
        w, h = (float(x) for x in (r.headers.get("X-Page-Size") or "0,0").split(","))
        return r.content, w, h

    def archive_page(self, task_id, meta, png, pii):
        import base64

        return self._json("POST", f"/v1/archive/{task_id}/pages", timeout=120,
                          json={"meta": meta, "png_b64": base64.b64encode(png).decode(), "pii": pii})["page_id"]

    def page_png(self, page_id, masked=True, max_width=None):
        params = {"masked": int(bool(masked)), **({"w": max_width} if max_width else {})}
        r = self._req("GET", f"/v1/archive/pages/{page_id}.png", params=params, timeout=120)
        return None if r is None else r.content

    def collect_status(self):
        return self._json("GET", "/v1/collect/status")

    def collect_run(self, source):
        return self._json("POST", "/v1/collect/run", params={"source": source})


_default = {"client": None, "key": None}
_default_lock = threading.Lock()


def default_client(sessions=None):
    """进程内单例：同一进程的所有审查共用一个资料中心客户端（共享 OCR 限流与数据库连接）。"""
    key = (settings.mode(), settings.url())
    with _default_lock:
        if _default["client"] is None or _default["key"] != key:
            if key[0] == "inprocess":
                from .service import ResourceService
                from .store import ResourceStore

                if sessions is None:
                    from ..session import CdpSessionProvider

                    sessions = CdpSessionProvider()
                _default["client"] = LocalResourceClient(ResourceService(ResourceStore(), sessions))
            elif key[0] == "http":
                _default["client"] = HttpResourceClient(key[1])
            else:
                raise E.DEError(f"config/resource.yaml 中的 mode「{key[0]}」不支持（可选 http / inprocess）",
                                title="资料中心配置有误")
            _default["key"] = key
        return _default["client"]
