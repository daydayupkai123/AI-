"""原文对照：报告中需关注的规则（问题 / 复核 / 待补充）↔ 源文件位置。

- 证据的文件字段可能是多份文件（「、」分隔）、可能没有页码：在候选文件的各页中按原文片段定位
- PDF 文字层精确到句；扫描件到 OCR 行；Word / Excel 到段落；定位不到只给页或标「未定位」，不伪造位置
- 定位结果按任务缓存（报告不变，结果不变）
"""
from __future__ import annotations

import re
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter()
ATTENTION = ("issue", "review", "missing", "error", "命中", "未能识别")
_cache: dict[str, dict] = {}
_lock = threading.Lock()


def _rc():
    from core.api import server

    return server.resources()


def _store():
    from core.api import server

    return server.store


def _files(rep: dict, rc) -> tuple[list[dict], dict[str, str]]:
    files, by_name = [], {}
    for m in rep.get("materials") or []:
        if not m.get("sig"):
            continue
        sig = rc.blob_by_prefix(m["sig"]) or m["sig"]
        name = m.get("filename") or ""
        files.append({"sig": sig, "filename": name, "name": name.split("/")[-1], "kind": m.get("kind"),
                      "pages": m.get("pages"), "role": m.get("role"), "status": m.get("status")})
        by_name[name] = sig
        by_name.setdefault(name.split("/")[-1], sig)
    return files, by_name


def _candidates(e: dict, by_name: dict[str, str]) -> list[str]:
    raw = str(e.get("file") or "")
    out = []
    for part in re.split(r"[、，,]", raw):
        part = part.strip()
        if not part:
            continue
        sig = by_name.get(part) or by_name.get(part.split("/")[-1])
        if not sig:  # 证据里的文件名可能被截断：按前缀匹配
            sig = next((s for n, s in by_name.items() if len(part) >= 6 and (n.startswith(part) or part.startswith(n))), None)
        if sig and sig not in out:
            out.append(sig)
    return out


def _quotes(e: dict) -> tuple[str, str]:
    snip, val = str(e.get("snippet") or ""), e.get("value")
    val = val if isinstance(val, str) else ""
    if len(val) >= 6 and (not snip or val[:6] in snip):
        return val, snip
    return snip, val if len(val) >= 6 else ""


def build(task_id: str) -> dict:
    rep = _store().get_report(task_id)
    if not rep:
        raise HTTPException(404, "报告不存在")
    rc = _rc()
    files, by_name = _files(rep, rc)
    items, reqs, refs = [], [], []
    for r in rep.get("rules") or []:
        if (r.get("code") or r.get("status")) not in ATTENTION:
            continue
        evs = []
        for e in r.get("evidence") or []:
            if not isinstance(e, dict):
                continue
            q, alt = _quotes(e)
            cands = _candidates(e, by_name)
            ev = {k: e.get(k) for k in ("label", "file", "snippet", "value", "page", "supplier") if e.get(k) not in (None, "")}
            ev["value"] = ev["value"] if isinstance(ev.get("value"), (str, int, float)) else None
            if cands and (q or alt):
                refs.append(ev)
                reqs.append({"sigs": cands, "quote": q, "alt": alt, "page": e.get("page") if isinstance(e.get("page"), int) else None})
            else:
                ev["loc"] = {"method": "none", "why": "证据不对应任何已下载的材料（如审批表单、天眼查）" if not cands else "证据没有原文片段"}
            evs.append(ev)
        items.append({"rule_id": r["rule_id"], "name": r.get("name"), "code": r.get("code"), "status": r.get("status"),
                      "tier": r.get("tier"), "message": r.get("message"), "suggest": r.get("suggest"),
                      "items": r.get("items") or [], "evidence": evs})
    locs = rc.locate(reqs) if reqs else []
    for ev, loc in zip(refs, locs):
        ev["loc"] = loc
    h = rep.get("header") or {}
    located = sum(1 for it in items for e in it["evidence"] if (e.get("loc") or {}).get("method") in ("text", "ocr", "para"))
    total = sum(len(it["evidence"]) for it in items)
    return {"task_id": task_id, "employee": rep.get("employee"), "request_id": h.get("request_id"),
            "title": h.get("subject") or h.get("request_name") or "", "rules_version": rep.get("rules_version"),
            "files": files, "items": items, "located": located, "evidence_total": total}


@router.get("/api/runs/{task_id}/compare")
def compare(task_id: str, refresh: int = 0):
    with _lock:
        if not refresh and task_id in _cache:
            return _cache[task_id]
    out = build(task_id)
    with _lock:
        _cache[task_id] = out
    return out


@router.get("/api/files/{sig}/pages/{page_no}.png")
def file_page(sig: str, page_no: int, dpi: int = 110):
    r = _rc().page_image(sig, page_no, dpi)
    if r is None:
        raise HTTPException(404, "页面不存在或该文件不是 PDF / 图片")
    png, w, h = r
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=86400", "X-Page-Size": f"{w:.1f},{h:.1f}"})


@router.get("/api/files/{sig}/parsed")
def file_parsed(sig: str):
    """Word / Excel 正文（原文对照中按段落高亮）与 PDF 各页文字层。"""
    doc = _rc().parsed(sig)
    if not doc:
        raise HTTPException(404, "该文件尚未解析")
    return {"kind": doc.get("kind"), "pages": [{"no": p.get("no"), "method": p.get("method"), "text": p.get("text") or ""}
                                              for p in doc.get("pages") or []]}
