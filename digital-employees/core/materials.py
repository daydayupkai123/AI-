"""通用材料节点（经资料中心）：附件补齐、解析补齐、读取解析结果、压缩包展开。

资料中心已预取的附件与解析结果直接复用；缺失的当场同步，并向界面推送提示（sync.notice）与逐文件进度。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .parsing.pipeline import full_text
from .runtime import Runtime

ARCHIVES = ("zip", "rar", "7z")


@dataclass
class Material:
    sig: str
    filename: str
    role: str = "other"
    field_label: str = ""
    parent_sig: str | None = None
    doc: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.filename.rsplit("/", 1)[-1]

    @property
    def text(self) -> str:
        return full_text(self.doc)

    @property
    def pages(self) -> list[tuple[int, str]]:
        return [(p.get("no", 1), p.get("text", "")) for p in self.doc.get("pages", [])]

    @property
    def readable(self) -> bool:
        return self.doc.get("status") == "ok" and bool(self.text.strip())

    @property
    def is_archive(self) -> bool:
        return self.doc.get("kind") in ARCHIVES


def _fmt_eta(seconds: float) -> str:
    if seconds < 90:
        return f"约 {max(1, round(seconds))} 秒"
    return f"约 {round(seconds / 60)} 分钟"


def download_all(rt: Runtime, req, task_id: str, source: str, attachments: list | None = None) -> tuple[list[dict], str]:
    atts = list(req.attachments if attachments is None else attachments)
    looked = rt.resources.lookup(source, atts)
    missing = [x for x in looked if not x["stored"]]
    if missing:
        names = "、".join(x["filename"] for x in missing[:3]) + ("等" if len(missing) > 3 else "")
        rt.on_event({"type": "sync.notice", "stage": "download", "missing": len(missing), "total": len(atts),
                     "text": f"资料中心尚未同步该单据的 {len(missing)} 份附件（{names}），正在现场同步，不等下一轮采集。"})
    elif atts:
        rt.on_event({"type": "sync.ready", "stage": "download", "total": len(atts),
                     "text": f"资料中心已预取全部 {len(atts)} 份附件，直接复用。"})
    files = rt.resources.ensure_files(source, req.request_id, req.workflow_id, atts, task_id, rt.on_event)
    reused = sum(1 for f in files if f["reused"])
    nbytes = sum(f.get("size") or 0 for f in files if not f["reused"])
    return ([{"sig": f["sig"], "filename": f["filename"], "field_label": f["field_label"]} for f in files],
            f"{len(files)} 份；复用已下载 {reused} 份；新下载 {nbytes / 1048576:.1f} MB")


def fetch_docs(rt: Runtime, task_id: str, request_id: str, source: str, files: list[dict]) -> list[dict]:
    """确保文件已解析（含压缩包内文件），返回解析概要，每项带 doc（统一文档 JSON）。"""
    plan = rt.resources.parse_plan(source, files)
    todo = [p for p in plan["items"] if not p["parsed"]]
    if todo:
        ocr_txt = (f"，其中扫描页约 {plan['ocr_pages']} 页需要 OCR，预计{_fmt_eta(plan['eta_s'])}"
                   if plan["ocr_pages"] else "，均可直接读取文字")
        rt.on_event({"type": "sync.notice", "stage": "parse", "missing": len(todo), "total": len(files),
                     "ocr_pages": plan["ocr_pages"], "eta_s": plan["eta_s"],
                     "text": f"资料中心尚未解析 {len(todo)} 份文件{ocr_txt}，正在现场解析。"})
    infos = rt.resources.ensure_parsed(source, request_id, files, task_id, rt.on_event)
    for i in infos:
        doc = rt.resources.parsed(i["sig"], source) or {
            "content_sig": i["sig"], "kind": i.get("kind"), "status": i.get("status") or "failed",
            "error": i.get("error"), "pages": [], "children": []}
        doc["_cache"] = i.get("cache")
        i["doc"] = doc
        if i.get("proc_key"):
            rt.store.log_cache(task_id, "L1", i["proc_key"], i.get("cache") == "hit", i.get("verified"), i.get("ms") or 0)
    return infos


def parse_all(rt: Runtime, task_id: str, request_id: str, source: str, files: list[dict],
              classify: Callable[[str, str], str]) -> tuple[list[Material], str]:
    infos = fetch_docs(rt, task_id, request_id, source, files)
    by_sig = {}
    for i in infos:
        by_sig.setdefault((i["sig"], i.get("parent_sig")), i)
    tops = []
    for f in files:
        i = by_sig.get((f["sig"], None))
        tops.append(Material(sig=f["sig"], filename=f["filename"], role=classify(f["filename"], f["field_label"]),
                             field_label=f["field_label"], doc=i["doc"] if i else {}))
    children = []
    for m in tops:
        for c in m.doc.get("children", []):
            i = by_sig.get((c["sig"], m.sig))
            children.append(Material(sig=c["sig"], filename=c["name"], parent_sig=m.sig,
                                     role=classify(c["name"], m.field_label) if m.role == "other" else m.role,
                                     field_label=f"{m.filename} 内", doc=i["doc"] if i else {}))
    mats = tops + children
    hits = sum(1 for m in mats if m.doc.get("_cache") == "hit")
    ocr_pages = sum(1 for m in mats for p in m.doc.get("pages", []) if str(p.get("method", "")).startswith("ocr"))
    failed = [m.filename for m in mats if m.doc.get("status") != "ok" and not m.is_archive]
    return mats, (f"{len(mats)} 个文件（含压缩包内 {len(children)}）；缓存命中 {hits}；OCR 页 {ocr_pages}；"
                  f"未完整识别 {len(failed)}")


def materials_table(mats: list[Material], labels: dict[str, str]) -> list[dict]:
    return [{"role": labels.get(m.role, m.role), "role_code": m.role, "filename": m.filename, "sig": m.sig[:16],
             "status": m.doc.get("status"), "pages": len(m.doc.get("pages", [])), "cache": m.doc.get("_cache"),
             "kind": m.doc.get("kind"), "error": m.doc.get("error")} for m in mats]


def unreadable(mats: list[Material]) -> list[Material]:
    return [m for m in mats if not m.is_archive and not m.readable]
