"""资料中心服务层：附件查询与补齐（下载 → 内容签名 → 出处）、解析补齐（命中签名缓存直接复用）、单据同步（表单快照）。

HTTP 接口（backend/storage_service/server.py）与进程内客户端（backend/storage_service/client.py）都调用这里，语义一致。
下载、签名、解析只在这里做一套；数字员工只交附件清单、取解析结果。
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from shared.errors import DEError, SessionExpired, friendly
from shared.parsing import formats, ocr
from shared.parsing.ocr_remote import priority as ocr_priority
from shared.parsing.pipeline import Parser
from shared.source_adapters import contract, docflow, fincloud
from shared.source_adapters.contract import Attachment
from . import fingerprint
from .store import ResourceStore

Progress = Callable[[dict], None]
PRIORITY = {"inline": 10, "manual": 5, "collect": 1}
ARCHIVES = ("zip", "rar", "7z")


class LocalFileClient:
    """本地事项：附件路径就是 loadlink；按单号在各员工的本地事项目录中查找表单（样例单号按员工区分，如 DEMO-BX-001）。"""

    def __init__(self, root: Path | None = None):
        from shared.source_adapters.local import CASES

        self.root = Path(root or CASES)

    def download(self, att: Attachment) -> bytes:
        return Path(att.loadlink).read_bytes()

    def fetch(self, request_id: str):
        from shared.errors import NoAccess
        from shared.source_adapters.local import LocalCaseClient

        for d in sorted(p for p in self.root.glob("*") if p.is_dir()):
            if (d / request_id / "case.json").exists():
                return LocalCaseClient(d.name, root=self.root).fetch(request_id)
        raise NoAccess(f"本地事项 {request_id} 不存在（{self.root}）", title="本地事项不存在")


SOURCES = {
    contract.SOURCE: (contract.ContractClient, contract.HOST, "合同系统"),
    docflow.SOURCE: (docflow.DocflowClient, docflow.HOST, "公文系统"),
    fincloud.SOURCE: (fincloud.FincloudClient, fincloud.HOST, "通财云"),
}


def _att(a) -> Attachment:
    return a if isinstance(a, Attachment) else Attachment(**{k: a.get(k, "") or "" for k in Attachment.__dataclass_fields__})


def _noop(_e: dict) -> None:
    pass


class ResourceService:
    def __init__(self, store: ResourceStore, sessions=None, clients: dict | None = None):
        """clients：直接给定各来源的取数客户端（测试、本地事项）；否则按来源用会话创建。"""
        self.store = store
        self.sessions = sessions
        self._fixed = dict(clients or {})
        self._clients: dict[str, object] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 取数客户端
    def client(self, source: str):
        if source in self._fixed:
            return self._fixed[source]
        if source == "local":
            return LocalFileClient()
        with self._lock:
            if source not in self._clients:
                if source not in SOURCES:
                    raise DEError(f"资料中心不支持来源 {source}", title="不支持的来源")
                if self.sessions is None:
                    raise DEError(f"资料中心未配置会话，无法访问{SOURCES[source][2]}", title="资料中心未配置登录会话")
                self._clients[source] = SOURCES[source][0](self.sessions.session())
            return self._clients[source]

    def with_login(self, source: str, fn):
        if source == "local":
            return fn(self.client(source))
        try:
            return fn(self.client(source))
        except SessionExpired:
            if source in self._fixed or source == "local" or source not in SOURCES or self.sessions is None:
                raise
            host = SOURCES[source][1]
            if host:
                self.sessions.warmup(host)
            with self._lock:
                self._clients.pop(source, None)
            return fn(self.client(source))

    # ------------------------------------------------------------------ 附件
    def lookup(self, source: str, attachments: list) -> list[dict]:
        """只查不下载：每个附件是否已入库、是否已解析、未解析时预计需要 OCR 的页数。"""
        parser = Parser(self.store, source_system=source)
        out = []
        for a in map(_att, attachments):
            sig = self.store.known_version(source, a.image_file_id, a.version_id)
            row = {"filename": a.filename, "field_label": a.field_label, "image_file_id": a.image_file_id,
                   "version_id": a.version_id, "sig": sig, "stored": bool(sig), "parsed": None}
            if sig:
                row["parsed"] = parser.status(sig)
                if not row["parsed"]:
                    row["ocr_pages_est"] = self.ocr_estimate(sig, a.filename)
            out.append(row)
        return out

    def ocr_estimate(self, sig: str, filename: str = "") -> int:
        try:
            data = self.store.read_blob(sig)
            kind = formats.detect(data, filename)
            if kind == "pdf":
                return formats.pdf_ocr_pages(data)[1]
            return 1 if kind == "image" else 0
        except Exception:  # noqa: BLE001
            return 0

    def parse_plan(self, source: str, files: list[dict]) -> dict:
        """给定已入库文件：哪些已解析、未解析的预计 OCR 页数与耗时（用于当场同步提示）。"""
        parser = Parser(self.store, source_system=source)
        items, pages = [], 0
        for f in files:
            st = parser.status(f["sig"])
            est = 0 if st else self.ocr_estimate(f["sig"], f.get("filename", ""))
            pages += est
            items.append({"sig": f["sig"], "filename": f.get("filename", ""), "parsed": st, "ocr_pages_est": est})
        eng = ocr.engine()
        return {"items": items, "ocr_pages": pages, "eta_s": round(eng.estimate_seconds(pages)), "engine": eng.name}

    def ensure_files(self, source: str, request_id: str, workflow_id: str, attachments: list,
                     task_id: str | None = None, progress: Progress | None = None, trigger: str = "inline") -> list[dict]:
        """缺失的附件下载入库（同一附件版本已下载过直接复用），记录本次出现。"""
        progress = progress or _noop
        job = self.store.create_job(kind="files", source=source, request_id=request_id, task_id=task_id,
                                    priority=PRIORITY.get(trigger, 1), trigger=trigger)
        self.store.update_job(job, status="running")
        out, nbytes = [], 0
        try:
            for i, a in enumerate(map(_att, attachments), start=1):
                sig = self.store.known_version(source, a.image_file_id, a.version_id)
                reused = bool(sig)
                if not reused:
                    progress({"type": "file.downloading", "filename": a.filename, "index": i, "total": len(attachments)})
                    data = self.with_login(source, lambda c, x=a: c.download(x))
                    nbytes += len(data)
                    sig = self.store.put_blob(data, ext=a.ext)
                self.store.add_occurrence(content_sig=sig, source_system=source, request_id=request_id,
                                          workflow_id=workflow_id, field_key=a.field_key, field_label=a.field_label,
                                          file_id=a.file_id, image_file_id=a.image_file_id, version_id=a.version_id,
                                          filename=a.filename, upload_time=a.upload_time, secret_level=a.secret_level,
                                          task_id=task_id)
                progress({"type": "file.downloaded", "filename": a.filename, "sig": sig, "reused": reused})
                out.append({"sig": sig, "filename": a.filename, "field_label": a.field_label, "field_key": a.field_key,
                            "reused": reused, "size": self.store.blob_size(sig)})
                self.store.update_job(job, progress={"done": i, "total": len(attachments), "bytes": nbytes})
            self.store.update_job(job, status="done")
            return out
        except Exception as exc:
            self.store.update_job(job, status="failed", error=f"{type(exc).__name__}: {exc}")
            raise

    def ensure_parsed(self, source: str, request_id: str, files: list[dict], task_id: str | None = None,
                      progress: Progress | None = None, trigger: str = "inline") -> list[dict]:
        """解析未解析的文件（压缩包内文件一并处理）；返回每个文件的解析概要（含子文件，parent_sig 标明归属）。"""
        progress = progress or _noop
        parser = Parser(self.store, source_system=source)
        if isinstance(ocr.engine(), ocr.RapidEngine):
            ocr.pool()
        job = self.store.create_job(kind="parse", source=source, request_id=request_id, task_id=task_id,
                                    priority=PRIORITY.get(trigger, 1), trigger=trigger)
        self.store.update_job(job, status="running")
        done = {"n": 0}

        level = PRIORITY.get(trigger, 1)

        def one(f: dict) -> dict:
            progress({"type": "file.started", "filename": f["filename"], "sig": f["sig"]})
            t0 = time.time()
            with ocr_priority(level):
                d = parser.parse(f["sig"], f["filename"], request_id, progress=progress, task_id=task_id)
            pages = d.get("pages", [])
            info = {"sig": f["sig"], "filename": f["filename"], "parent_sig": f.get("parent_sig"),
                    "kind": d.get("kind"), "status": d.get("status"), "error": d.get("error"),
                    "cache": d.get("_cache"), "verified": d.get("_verified"), "proc_key": d.get("_key"),
                    "pages": len(pages), "ocr_pages": sum(1 for p in pages if str(p.get("method", "")).startswith("ocr")),
                    "children": [{"sig": c["sig"], "name": c["name"]} for c in d.get("children", [])],
                    "ms": int((time.time() - t0) * 1000)}
            progress({"type": "file.parsed", **{k: info[k] for k in ("filename", "sig", "kind", "cache", "status",
                                                                       "pages", "ocr_pages", "ms")},
                      "children": len(info["children"])})
            done["n"] += 1
            self.store.update_job(job, progress={"done": done["n"]})
            return info

        try:
            out, batch = [], [dict(f) for f in files]
            while batch:
                with ThreadPoolExecutor(max_workers=6) as ex:
                    infos = list(ex.map(one, batch))
                out += infos
                batch = [{"sig": c["sig"], "filename": c["name"], "parent_sig": i["sig"]}
                         for i in infos for c in i["children"]]
            self.store.update_job(job, status="done")
            return out
        except Exception as exc:
            self.store.update_job(job, status="failed", error=f"{type(exc).__name__}: {exc}")
            raise

    def parsed(self, sig: str, source: str = "contract") -> dict | None:
        """已入库的解析结果（含 OCR 失败页的部分结果也返回，失败页在 pages 中标记 ocr-failed）。"""
        return Parser(self.store, source_system=source).cached(sig, allow_failed_pages=True)

    def read_blob(self, sig: str) -> bytes:
        return self.store.read_blob(sig)

    def blob_by_prefix(self, prefix: str) -> str | None:
        return self.store.blob_by_prefix(prefix) if len(prefix) >= 12 else None

    # ------------------------------------------------------------------ 单据同步
    def sync_request(self, source: str, request_id: str, employee: str | None = None, *, trigger: str = "manual",
                     task_id: str | None = None, progress: Progress | None = None,
                     skip_secret_levels: list[str] | None = None) -> dict:
        """取表单快照 → 下载附件 → 解析；返回单据快照（含资料状态与材料指纹）。"""
        progress = progress or _noop
        job = self.store.create_job(kind="request", source=source, request_id=request_id, task_id=task_id,
                                    priority=PRIORITY.get(trigger, 1), trigger=trigger)
        return self.run_request_job(job, source, request_id, employee, progress, skip_secret_levels)

    def run_request_job(self, job: str, source: str, request_id: str, employee: str | None,
                        progress: Progress | None = None, skip_secret_levels: list[str] | None = None) -> dict:
        progress = progress or _noop
        trig = (self.store.get_job(job) or {}).get("trigger") or "manual"
        self.store.update_job(job, status="running")
        self.store.set_snapshot_status(source, request_id, "syncing")
        try:
            req = self.with_login(source, lambda c: c.fetch(request_id))
            skip = set(skip_secret_levels or [])
            atts = [a for a in req.attachments if not (a.secret_level and a.secret_level in skip)]
            files = self.ensure_files(source, req.request_id, req.workflow_id, atts, progress=progress, trigger=trig)
            parsed = self.ensure_parsed(source, req.request_id, files, progress=progress, trigger=trig)
            tops = [p for p in parsed if not p.get("parent_sig")]
            ok = sum(1 for p in tops if p["status"] == "ok" or p["kind"] in ARCHIVES)
            att_meta = [{k: v for k, v in asdict(a).items() if k != "loadlink"} for a in req.attachments]
            status = "ready" if ok == len(tops) and len(atts) == len(req.attachments) else "partial"
            self.store.save_snapshot(
                source=source, request_id=str(request_id), employee=employee, title=req.request_name,
                workflow_id=req.workflow_id, workflow_name=req.workflow_name,
                material_fp=fingerprint.material_fp(req.fields, [asdict(a) for a in req.attachments]),
                fields=req.fields, attachments=att_meta, files_total=len(req.attachments), files_ready=len(files),
                parsed_ready=ok, status=status,
                error=None if status == "ready" else (f"{len(req.attachments) - len(atts)} 份涉密附件未提前下载"
                                                       if len(atts) < len(req.attachments)
                                                       else f"{len(tops) - ok} 份文件未完整识别"))
            self.store.update_job(job, status="done", progress={"files": len(files), "parsed": ok})
            return self.store.get_snapshot(source, str(request_id))
        except Exception as exc:
            info = friendly(exc)
            self.store.update_job(job, status="failed", error=f"{info['title']}｜{info['detail']}")
            self.store.set_snapshot_status(source, str(request_id), "failed", f"{info['title']}｜{info['detail']}")
            raise

    def requests(self, employee: str | None = None, status: str | None = None, limit: int = 100) -> list[dict]:
        return self.store.list_snapshots(employee, status, limit)

    def request(self, source: str, request_id: str) -> dict | None:
        snap = self.store.get_snapshot(source, request_id)
        if snap is None:
            return None
        latest: dict[tuple, dict] = {}
        for occ in self.store.occurrences(source, request_id):  # 每次同步都会记一次出现，按文件去重取最新
            latest[(occ["content_sig"], occ["filename"], occ["parent_sig"])] = occ
        snap["files"] = list(latest.values())
        parser = Parser(self.store, source_system=source)
        for f in snap["files"]:
            f["parsed"] = parser.status(f["content_sig"])
            f["size_bytes"] = self.store.blob_size(f["content_sig"])
        snap["archives"] = self.store.archives_for(source, request_id)
        return snap

    def stats(self) -> dict:
        eng = ocr.engine()
        return {**self.store.stats(), "ocr_engine": eng.name, "ocr_params": eng.params()}

    def job(self, job_id: str) -> dict | None:
        return self.store.get_job(job_id)

    # ------------------------------------------------------------------ 执行档案
    def archive_start(self, task_id: str, employee: str, source: str, request_id: str, trigger_by: str,
                      versions: dict) -> None:
        self.store.archive_start(task_id=task_id, employee=employee, source=source, request_id=request_id,
                                 trigger_by=trigger_by, versions=versions)

    def archive_items(self, task_id: str, items: list[dict]) -> int:
        from .desensitize import mask_obj

        return self.store.archive_items(task_id, [{**it, "title": mask_obj(it.get("title")),
                                                   "body": mask_obj(it.get("body"))} for it in items])

    def archive_finish(self, task_id: str, status: str, material_fp: str | None = None, verdict: dict | None = None,
                       error: str | None = None) -> None:
        from .desensitize import mask_text

        self.store.archive_finish(task_id, status=status, material_fp=material_fp, verdict=verdict,
                                  error=mask_text(error) if error else None)

    def archive_shots(self, task_id: str, items: list[dict], limit: int = 30) -> list[dict]:
        """items：[{sig, filename, page, quote, label, rule_id}] → 渲染证据截图并入档。"""
        from . import shots
        from .desensitize import mask_text

        out, seen = [], set()
        for it in items:
            if len(out) >= limit:
                break
            key = (it["sig"], it.get("page"), (it.get("quote") or "")[:40])
            if key in seen or not self.store.has_blob(it["sig"]):
                continue
            seen.add(key)
            doc = self.parsed(it["sig"])
            dpi = int(((doc or {}).get("params") or {}).get("dpi") or 150)
            try:
                r = shots.render(self.store.read_blob(it["sig"]), it.get("filename") or "", doc, it.get("page"),
                                 it.get("quote") or "", ocr_dpi=dpi)
            except Exception as exc:  # noqa: BLE001
                r = {"method": "error", "page_no": it.get("page"), "rects": [], "png": None, "error": str(exc)}
            uri = None
            if r.get("png"):
                path = self.store.root / "shots" / task_id / f"{len(out):03d}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(r["png"])
                uri = str(path.relative_to(self.store.root))
            sid = self.store.save_shot(task_id=task_id, sig=it["sig"], filename=it.get("filename") or "",
                                       page_no=r.get("page_no"), quote=mask_text(it.get("quote") or ""),
                                       label=it.get("label") or "", rule_id=it.get("rule_id") or "",
                                       method=r["method"], rects=r["rects"], png_uri=uri)
            out.append({"shot_id": sid, "method": r["method"], "page_no": r.get("page_no"), "has_png": bool(uri),
                        "rule_id": it.get("rule_id"), "filename": it.get("filename")})
        return out

    def archive(self, task_id: str, kinds: list[str] | None = None) -> dict | None:
        return self.store.get_archive(task_id, kinds)

    # ------------------------------------------------------------------ 原文对照
    def locate(self, items: list[dict]) -> list[dict]:
        """items：[{sigs:[候选文件签名], quote, alt, page}] → 每项在第一个能定位的文件中的位置（只读已入库原件与解析结果）。"""
        from . import shots

        out = []
        for it in items:
            best = None
            for sig in it.get("sigs") or []:
                if not self.store.has_blob(sig):
                    continue
                doc = self.parsed(sig)
                name = (self.store.get_meta(sig) or {}).get("filename") or it.get("names", {}).get(sig, "")
                for q in [x for x in (it.get("quote"), it.get("alt")) if x]:
                    try:
                        r = shots.locate(self.store.read_blob(sig), name, doc, q, it.get("page"))
                    except Exception as exc:  # noqa: BLE001
                        r = {"method": "error", "error": f"{type(exc).__name__}: {exc}", "rects": []}
                    r["sig"] = sig
                    if r["method"] in ("text", "ocr", "para"):
                        best = r
                        break
                    best = best if best and best.get("method") == "page" else r
                if best and best["method"] in ("text", "ocr", "para"):
                    break
            out.append(best or {"method": "none", "rects": []})
        return out

    def page_image(self, sig: str, page_no: int, dpi: int = 110, filename: str = "") -> tuple[bytes, float, float] | None:
        from . import shots

        if not self.store.has_blob(sig):
            return None
        return shots.page_png(self.store.read_blob(sig), filename, page_no, dpi)

    def archive_page(self, task_id: str, meta: dict, png: bytes, pii: list) -> str:
        from .image_trim import trim_bottom_whitespace

        png, width, height = trim_bottom_whitespace(png)
        return self.store.save_page(task_id=task_id, title=meta.get("title") or "", url=meta.get("url") or "",
                                    width=width or meta.get("width"), height=height or meta.get("height"),
                                    pii=pii, png=png)

    def page_png(self, page_id: str, masked: bool = True, max_width: int | None = None) -> bytes | None:
        """平台页面截图。masked：按入档时定位的敏感信息坐标打码（前端只取打码版）；原图只供资料中心内部核查。
        展示时裁掉四周留白；结果落盘缓存，避免每次打开档案都对超高整页图现裁。"""
        p = self.store.get_page(page_id)
        if not p:
            return None
        path = self.store.root / p["png_uri"]
        if not path.exists():
            return None
        import io

        from PIL import Image, ImageDraw

        from .image_trim import trim_image

        mw = int(max_width) if max_width else 0
        cache = path.with_name(f"{path.stem}.view{'m' if masked else 'r'}{f'w{mw}' if mw else ''}.v2.png")
        try:
            if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
                return cache.read_bytes()
        except OSError:
            pass

        im = Image.open(path).convert("RGB")
        if masked:
            d = ImageDraw.Draw(im)
            for x0, y0, x1, y1 in p["pii"]:
                d.rectangle([x0, y0, x1, y1], fill=(46, 50, 56))
        im = trim_image(im)
        if mw and im.width > mw:
            im = im.resize((mw, max(1, int(im.height * mw / im.width))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=False, compress_level=6)
        data = buf.getvalue()
        try:
            cache.write_bytes(data)
        except OSError:
            pass
        return data

    def shot_png(self, shot_id: str) -> bytes | None:
        s = self.store.get_shot(shot_id)
        if not s or not s.get("png_uri"):
            return None
        path = self.store.root / s["png_uri"]
        return path.read_bytes() if path.exists() else None

    # ------------------------------------------------------------------ 采集
    @property
    def collector(self):
        if getattr(self, "_collector", None) is None:
            from .collector import Collector

            self._collector = Collector(self)
        return self._collector

    def start_background(self) -> None:
        self.collector.start()

    def stop_background(self) -> None:
        if getattr(self, "_collector", None) is not None:
            self._collector.stop()

    def collect_status(self) -> dict:
        return self.collector.status()

    def collect_run(self, source: str) -> dict:
        """人工「立即采集」：强制重新同步列表中的单据，以便发现刚修改的表单 / 附件。"""
        return self.collector.run_round(source, force=True)

    def health(self) -> dict:
        eng = ocr.engine()
        return {"ok": True, "db": str(self.store.db_path), "ocr_engine": eng.name, "ocr_params": eng.params(),
                "migrated": self.store.migrated}
