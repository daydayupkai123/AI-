"""带内容签名缓存的解析入口（资料中心使用）：命中且完整性校验通过直接复用，否则解析并入库。

返回的文档带 _cache（hit / miss）与 _verified，调用方据此记录缓存命中统计。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

from ..signing import canonical, integrity, proc_key, verify
from . import formats, ocr

PROCESSOR = "auto"
PROCESSOR_VER = "1"

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def params() -> dict:
    """处理参数：解析引擎与 DPI。引擎变化即为新的处理键，不会混用不同引擎的结果。"""
    return ocr.engine().params()


class Parser:
    def __init__(self, store, source_system: str = "contract"):
        self.store = store
        self.source_system = source_system

    def key_for(self, sig: str) -> str:
        return proc_key(sig, PROCESSOR, PROCESSOR_VER, params())

    def _load(self, sig: str) -> dict | None:
        key = self.key_for(sig)
        row = self.store.get_parse(key)
        if not row or row["status"] == "failed":
            return None
        path = self.store.root / row["result_uri"]
        if not path.exists():
            return None
        body = path.read_bytes()
        if not verify(sig, key, body, row["integrity"]):
            return None
        doc = json.loads(body)
        doc["_cache"], doc["_verified"], doc["_key"] = "hit", True, key
        return doc

    def cached(self, sig: str, allow_failed_pages: bool = False) -> dict | None:
        """命中且完整性校验通过才返回；含 OCR 失败页的结果默认视为未命中（下次同步只重试失败页）。"""
        doc = self._load(sig)
        if doc and not allow_failed_pages and _failed_pages(doc):
            return None
        if doc and doc.get("kind") == "doc" and not (doc.get("meta") or {}).get("approx_reason") and any(
                p.get("method") == "text-approx" for p in doc.get("pages") or []):
            return None  # 旧版 .doc 近似提取的结果：现已能按分段表精确提取，重新解析
        return doc

    def status(self, sig: str) -> dict | None:
        """只查索引不读结果：是否已解析、状态、页数、OCR 页数。"""
        row = self.store.get_parse(self.key_for(sig))
        if not row:
            return None
        return {"status": row["status"], "pages": row["page_count"], "ocr_pages": row["ocr_pages"],
                "error": row["error"]}

    def parse(self, sig: str, filename: str = "", request_id: str | None = None,
              progress: Callable[[dict], None] | None = None, task_id: str | None = None) -> dict:
        cached = self.cached(sig)
        if cached:
            return cached
        key = self.key_for(sig)
        with _lock_for(key):
            cached = self.cached(sig)
            if cached:
                return cached
            t0 = time.time()
            data = self.store.read_blob(sig)
            kind = formats.detect(data, filename)
            prm = params()

            def on_page(done: int, total: int) -> None:
                if progress:
                    progress({"type": "file.ocr", "filename": filename, "sig": sig, "done": done, "total": total})

            prior = self._load(sig)
            if prior and _failed_pages(prior) and kind in ("pdf", "image"):
                return self._retry_failed(sig, key, kind, data, prior, prm, on_page, t0)
            doc = {"content_sig": sig, "kind": kind, "filename": filename, "processor": PROCESSOR,
                   "processor_ver": PROCESSOR_VER, "params": prm, "meta": {}, "pages": [],
                   "children": [], "warnings": []}
            status, error = "ok", None
            try:
                if kind in formats.PARSERS:
                    meta, pages, warns = formats.PARSERS[kind](data, on_page=on_page)
                    doc["meta"], doc["pages"], doc["warnings"] = meta, pages, warns
                elif kind in ("zip", "rar", "7z"):
                    for name, blob in formats.extract_archive(data, kind):
                        child = self.store.put_blob(blob, ext=Path(name).suffix.lstrip(".").lower())
                        self.store.add_occurrence(content_sig=child, source_system=self.source_system,
                                                  request_id=request_id, parent_sig=sig, filename=name,
                                                  field_label="压缩包内文件", task_id=task_id)
                        doc["children"].append({"sig": child, "name": name, "size": len(blob)})
                else:
                    status, error = "failed", f"不支持的格式：{kind}"
            except Exception as exc:  # noqa: BLE001
                status, error = "failed", f"{type(exc).__name__}: {exc}"
            if doc["meta"]:
                self.store.set_meta(sig, doc["meta"])
            return self._save(sig, key, kind, doc, status, error, prm, t0)

    def _retry_failed(self, sig, key, kind, data, prior, prm, on_page, t0) -> dict:
        """上次 OCR 失败的页单独重试，其余页沿用。"""
        doc = {k: v for k, v in prior.items() if not k.startswith("_")}
        nos = _failed_pages(doc)
        if kind == "pdf":
            import pymupdf

            pdf = pymupdf.open(stream=data, filetype="pdf")
            eng = ocr.engine()
            if getattr(eng, "send_pdf", False):
                results = eng.ocr_pdf_pages(data, [n - 1 for n in nos], on_page)
            else:
                results = eng.ocr_images([pdf[n - 1].get_pixmap(dpi=eng.dpi).tobytes("png") for n in nos], on_page)
        else:
            results = ocr.engine().ocr_images([data], on_page)
        by_no = dict(zip(nos, results))
        doc["pages"] = [formats._ocr_page(p["no"], by_no[p["no"]]) if p["no"] in by_no else p for p in doc["pages"]]
        return self._save(sig, key, kind, doc, "ok", None, prm, t0)

    def _save(self, sig, key, kind, doc, status, error, prm, t0) -> dict:
        failed = _failed_pages(doc)
        if status == "ok" and failed:
            status, error = "partial", f"第 {'、'.join(map(str, failed[:10]))} 页 OCR 失败"
        elif status == "ok" and kind not in ("zip", "rar", "7z") and not any(p["text"].strip() for p in doc["pages"]):
            status, error = "partial", "未提取到任何文字"
        ocr_confs = [p["conf"] for p in doc["pages"] if p.get("method") == "ocr" and p.get("conf") is not None]
        doc["status"], doc["error"] = status, error
        body = canonical(doc)
        ms = int((time.time() - t0) * 1000)
        self.store.save_parse(
            key=key, sig=sig, processor=PROCESSOR, version=PROCESSOR_VER, params=prm, origin="self",
            status=status, doc_bytes=body, integrity=integrity(sig, key, body),
            page_count=len(doc["pages"]), char_count=sum(len(p["text"]) for p in doc["pages"]),
            ocr_pages=sum(1 for p in doc["pages"] if str(p.get("method", "")).startswith("ocr")),
            quality=(sum(ocr_confs) / len(ocr_confs)) if ocr_confs else None,
            error=error, duration_ms=ms,
            pages=[{"no": p["no"], "method": p.get("method"), "conf": p.get("conf"), "text": p["text"]}
                   for p in doc["pages"]])
        doc["_cache"], doc["_verified"], doc["_key"], doc["_ms"] = "miss", None, key, ms
        return doc


def _failed_pages(doc: dict) -> list[int]:
    return [p["no"] for p in doc.get("pages", []) if p.get("method") == "ocr-failed"]


def full_text(doc: dict) -> str:
    return "\n".join(p["text"] for p in doc.get("pages", []))
