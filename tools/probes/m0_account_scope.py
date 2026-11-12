"""当前登录账号可见的单据范围摸底（只读列表，不打开单据）：python tools/probes/m0_account_scope.py

公文：门户工作台各列表（app=4 公文、app=1 协同含通财云）的数量与模板分布；合同：待办 / 已办 / 我的请求按流程分布。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from shared.session import CdpSessionProvider  # noqa: E402
from shared.source_adapters.contract import CONTRACT_BASE, ContractClient  # noqa: E402
from shared.source_adapters.docflow import PORTAL_LIST  # noqa: E402


def portal(s, typ: str, app: str, size: int = 100) -> tuple[int, list[dict]]:
    body = {"type": typ, "memberId": "", "isLeader": False, "subject": "", "templeteId": "", "mark": "", "summaryState": "",
            "sender": "", "department": "", "app": app, "preApprover": "", "pageNo": 1, "pageSize": size, "sequence": 0,
            "timeType": None, "platform": "PC"}
    r = s.post(PORTAL_LIST, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=30,
               headers={"Content-Type": "application/json;charset=UTF-8", "Origin": "https://i.gt.cn", "Referer": "https://i.gt.cn/"})
    res = r.json().get("result")
    d = ((res.get("data") or {}).get(typ) or {}) if isinstance(res, dict) else {}
    return d.get("total") or 0, d.get("data") or []


def main() -> None:
    s = CdpSessionProvider().session()
    for app in ("4", "1"):
        for typ in ("pending", "pendingRead", "donePending", "doneRead", "doneSent"):
            total, rows = portal(s, typ, app)
            tpl = Counter((r.get("templateName") or r.get("appId") or "")[:24] for r in rows)
            print(f"门户 app={app} {typ:12s} 共 {total:4d}  模板：{dict(tpl.most_common(6))}")
    c = ContractClient(s)
    for scope in ("doing", "done", "mine"):
        r = s.post(f"{CONTRACT_BASE}/api/workflow/reqlist/{scope}BaseInfo", data={}, timeout=60).json()
        tops = []

        def walk(nodes):
            for n in nodes or []:
                if n.get("count") or n.get("num"):
                    tops.append((n.get("domid") or n.get("key"), n.get("name"), n.get("count") or n.get("num")))
                walk(n.get("childs") or n.get("children"))

        walk(r.get("treedata"))
        print(f"合同 {scope}：", [t for t in tops if str(t[0]).startswith("wf_")][:15])
    for wf in ("99", "100"):
        print(f"合同 wf={wf} 待办：", [(x["request_id"], x["title"][:30]) for x in c.list_requests("doing", [wf], 20)])


if __name__ == "__main__":
    main()
