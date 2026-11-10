"""采集用的列表读取：各来源按 config/collect.yaml 的列表配置返回 [{request_id, title, date}]，只读列表不打开单据。

合同系统：reqlist（本账号待办 / 已办 / 我的请求，可按流程过滤）、ledger（cube 台账，如主合同台账 78、采购结果审批台账 83）
公文系统：portal（门户工作台列表 doneSent / donePending / doneRead / pending，按标题关键字）、
         query（公司数据查询 → 内部请示查询，只取流程已结束的）
"""
from __future__ import annotations

import re

from ..sources import docflow

PENDING_SCOPES = {"doing", "pending", "pendingRead"}


def is_pending(lst: dict) -> bool:
    return str(lst.get("scope") or lst.get("type") or "") in PENDING_SCOPES


def contract_rows(client, lst: dict) -> list[dict]:
    kind = lst.get("kind") or "reqlist"
    limit = int(lst.get("max") or 50)
    if kind == "reqlist":
        rows = client.list_requests(lst.get("scope") or "done", lst.get("workflow_ids"), page_size=limit)
    elif kind == "ledger":
        f = lst.get("fields") or {}
        raw = client.ledger(str(lst["customid"]), page_size=limit, max_pages=1)
        rows = [{"request_id": str(r.get(f.get("id", "lcid")) or ""), "title": r.get(f.get("title", "")) or "",
                 "date": r.get(f.get("date", "")) or ""} for r in raw]
    else:
        raise ValueError(f"合同系统列表类型 {kind} 不支持（reqlist / ledger）")
    rows = [r for r in rows if r["request_id"] and r["request_id"] != "None"]
    if lst.get("title_keyword"):
        rows = [r for r in rows if re.search(lst["title_keyword"], r["title"])]
    return rows[:limit]


def docflow_query_rows(client, lst: dict) -> list[dict]:
    """公司数据查询 → 内部请示查询：只取流程已结束的请示（未结束的可能是他人待办），可按标题正则再筛。"""
    limit = int(lst.get("max") or 20)
    out, page = [], 1
    while len(out) < limit and page <= int(lst.get("max_pages") or 5):
        rows, total = client.query(keyword=lst.get("keyword") or "", page=page, size=100)
        for r in rows:
            if r.get("flow_state") != docflow.FINISHED or not r.get("mark"):
                continue
            if lst.get("title_keyword") and not re.search(lst["title_keyword"], r.get("subject") or ""):
                continue
            out.append({"request_id": docflow.canonical_id(r["mark"]), "title": r.get("subject") or "",
                        "date": r.get("created") or ""})
        if page * 100 >= total:
            break
        page += 1
    return out[:limit]


def docflow_rows(client, lst: dict) -> list[dict]:
    if lst.get("kind") == "query":
        return docflow_query_rows(client, lst)
    typ = lst.get("type") or "doneSent"
    rows, seen = [], set()
    for r in client._list(typ, lst.get("keyword") or "", int(lst.get("max") or 50)):
        subject = r.get("subject") or ""
        if lst.get("template") and lst["template"] not in (r.get("templateName") or ""):
            continue
        key = str(r.get("objectId") or r.get("affairId"))
        if key in seen:
            continue
        seen.add(key)
        m = re.search(docflow.MARK_RE, subject)
        rid = docflow.canonical_id(m.group(0)) if m else str(r.get("affairId"))
        rows.append({"request_id": rid, "title": subject, "date": r.get("createDate") or r.get("receiveTime") or ""})
    return rows


def local_rows(client, lst: dict) -> list[dict]:
    """本地事项（.runtime/cases/<员工>/）：客户系统无法访问时，用样例 / 导入事项走完整的采集与自动审查链路。"""
    from ..sources.local import CASES, LocalCaseClient

    rows = LocalCaseClient(lst["employee"], root=getattr(client, "root", None) or CASES).list()
    return [{"request_id": r["request_id"], "title": r.get("title") or "", "date": ""} for r in rows][:int(lst.get("max") or 50)]


def _filtered(fn):
    """列表通用过滤：title_exclude（标题正则，命中的不采集，如人事议题）。"""
    def run(client, lst: dict) -> list[dict]:
        rows = fn(client, lst)
        if lst.get("title_exclude"):
            rows = [r for r in rows if not re.search(lst["title_exclude"], r.get("title") or "")]
        return rows
    return run


LISTERS = {"contract": _filtered(contract_rows), "docflow": _filtered(docflow_rows), "local": _filtered(local_rows)}
