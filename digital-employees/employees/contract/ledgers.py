"""合同审核需要的台账（2026-11-09 摸底确认）：

  投标及报价台账 customid=86：按合同表单「选择投标项目」匹配「投标项目名称」，取流程 id（投标及报价审批流程 wf=98），
      读取该流程的 附件（招标文件、投标文件、报价）/ 中标证明附件 / 上传最终版投标文件，以及「中标价格（万元）」等字段。
  销售合同（主合同）台账 customid=78：整表用于 R21 合同重复签订（按 config 的列映射规范化）。

台账整表按 cache_hours 缓存（外部查询缓存层），避免每次审查都重读 1.2 万行。
"""
from __future__ import annotations

import re
from dataclasses import replace

from core.runtime import Runtime
from core.sources.contract import Attachment

KIND = "contract.ledger"


def _norm(s: str) -> str:
    return re.sub(r"[\s\u3000（）()]", "", str(s or ""))


def ledger_rows(rt: Runtime, customid: str, hours: float) -> tuple[list[dict], bool]:
    key = f"customid={customid}"
    hit = rt.store.get_external(KIND, key)
    if hit:
        return hit["rows"], True
    rows = rt.with_login(lambda c: c.ledger(str(customid), page_size=500, max_pages=60))
    rt.store.put_external(KIND, key, {"rows": rows}, hours * 3600)
    return rows, False


def bid_record(rt: Runtime, cfg: dict, form: dict) -> dict:
    conf = (cfg.get("ledgers") or {}).get("bid_quote") or {}
    name = (form.get("选择投标项目") or {}).get("value") or ""
    base = {"name": conf.get("name", "投标及报价台账")}
    if not conf.get("customid"):
        return {**base, "available": False, "reason": "投标及报价台账未配置 customid"}
    if not name:
        return {**base, "available": False, "reason": "合同表单未选择投标项目（非投标项目或未关联）"}
    rows, cached = ledger_rows(rt, conf["customid"], float((cfg.get("ledgers") or {}).get("cache_hours", 6)))
    field = conf.get("match_field", "tbxmmc")
    hits = [r for r in rows if _norm(r.get(field)) == _norm(name)]
    if not hits:
        hits = [r for r in rows if _norm(name) and (_norm(name) in _norm(r.get(field)) or _norm(r.get(field)) in _norm(name))
                and len(_norm(r.get(field))) >= 8]
    if not hits:
        return {**base, "available": False, "reason": f"投标及报价台账中未找到投标项目「{name}」"}
    row = hits[0]
    lcid = re.sub(r"\D", "", str(row.get("lcid") or ""))
    if not lcid:
        return {**base, "available": False, "reason": f"投标项目「{name}」在台账中没有流程 id"}
    req = rt.with_login(lambda c: c.fetch(lcid))
    vals = {f["label"]: re.sub(r"<[^>]+>", "", str(f["display"] or "")).strip() for f in req.fields}
    atts = [replace(a, field_label=f"投标报价台账·{a.field_label}") for a in req.attachments]
    price = vals.get("中标价格（万元）")
    try:
        price_yuan = float(price) * 1e4 if price not in (None, "") else None
    except ValueError:
        price_yuan = None
    return {**base, "available": True, "cached": cached, "project": row.get(field), "request_id": lcid,
            "workflow_name": req.workflow_name, "matched_exact": _norm(row.get(field)) == _norm(name),
            "attachments": atts, "award_price_yuan": price_yuan, "fields": vals,
            "consortium": vals.get("是否联合体投标"), "consortium_units": vals.get("联合体单位") or row.get("lhtdw"),
            "won": vals.get("是否中标") or row.get("sfzb")}


def main_contract_rows(rt: Runtime, cfg: dict) -> dict:
    conf = (cfg.get("ledgers") or {}).get("main_contract") or {}
    base = {"name": conf.get("name", "主合同台账")}
    if not conf.get("customid"):
        return {**base, "available": False, "reason": "主合同台账未配置 customid"}
    rows, cached = ledger_rows(rt, conf["customid"], float((cfg.get("ledgers") or {}).get("cache_hours", 6)))
    cols = conf.get("columns") or {}
    norm = [{k: str(r.get(src) or "").strip() for k, src in cols.items()} for r in rows]
    return {**base, "available": True, "cached": cached, "rows": norm}


def attachments_of(bid: dict) -> list[Attachment]:
    return list(bid.get("attachments") or []) if bid.get("available") else []
