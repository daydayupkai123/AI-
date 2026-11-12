"""验证「读取待办详情是否改变单据状态」（只读：只调列表与表单读取接口，不提交、不审批）。

  python tools/probes/m0_pending_check.py 1656669

步骤：读取前记录待办列表中该单据的全部字段与审批日志条数 → 按数字员工的方式读取表单（loadForm）与审批日志
→ 读取后再记录一次 → 对比差异。结果写入 .runtime/m0/pending_check_<单号>.json。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from shared.session import CdpSessionProvider  # noqa: E402
from shared.source_adapters.contract import ContractClient  # noqa: E402
from shared.source_adapters.docflow import PORTAL_LIST  # noqa: E402

OUT = ROOT / ".runtime" / "m0"


def list_row(c: ContractClient, rid: str) -> dict | None:
    key = c._post("/api/workflow/reqlist/splitPageKey", {"viewScope": "doing", "workflowid": "99"})["sessionkey"]
    page = c._post("/api/ec/dev/table/datas", {"dataKey": key, "current": "1", "pageSize": "50", "sortParams": "[]"})
    return next((d for d in page.get("datas") or [] if str(d.get("requestid")) == rid), None)


def portal_row(s, rid: str) -> dict | None:
    body = {"type": "pending", "memberId": "", "isLeader": False, "subject": "", "templeteId": "", "mark": "",
            "summaryState": "", "sender": "", "department": "", "app": "1", "preApprover": "", "pageNo": 1,
            "pageSize": 50, "sequence": 0, "timeType": None, "platform": "PC"}
    r = s.post(PORTAL_LIST, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=30,
               headers={"Content-Type": "application/json;charset=UTF-8", "Origin": "https://i.gt.cn", "Referer": "https://i.gt.cn/"})
    rows = (((r.json().get("result") or {}).get("data") or {}).get("pending") or {}).get("data") or []
    return next((x for x in rows if rid in json.dumps(x, ensure_ascii=False)), None)


def counts(c: ContractClient, rid: str) -> dict:
    # 统计计数接口：待办 / 未读数量
    out = {}
    for path in ("/api/workflow/reqlist/doingCountInfo", "/api/workflow/reqlist/doingBaseInfo"):
        try:
            d = c._post(path, {})
            out[path.rsplit("/", 1)[-1]] = {k: v for k, v in d.items() if isinstance(v, (int, str)) and len(str(v)) < 80}
        except Exception as exc:  # noqa: BLE001
            out[path.rsplit("/", 1)[-1]] = f"{type(exc).__name__}: {exc}"
    return out


def diff(a: dict | None, b: dict | None) -> dict:
    a, b = a or {}, b or {}
    return {k: {"before": a.get(k), "after": b.get(k)} for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}


def main(rid: str) -> None:
    s = CdpSessionProvider().session()
    c = ContractClient(s)
    before = {"list": list_row(c, rid), "portal": portal_row(s, rid), "counts": counts(c, rid)}
    req = c.fetch(rid)  # 数字员工取单的同一调用：loadForm + 审批日志
    log_before = len(req.approval_log)
    time.sleep(3)
    req2 = c.fetch(rid)
    after = {"list": list_row(c, rid), "portal": portal_row(s, rid), "counts": counts(c, rid)}
    result = {"request_id": rid, "via_monitor": req.via_monitor, "node": req.node_name,
              "approval_log": {"first_read": log_before, "second_read": len(req2.approval_log),
                               "last_entries": req2.approval_log[-3:]},
              "list_diff": diff(before["list"], after["list"]), "portal_diff": diff(before["portal"], after["portal"]),
              "counts_diff": diff(before["counts"].get("doingCountInfo") if isinstance(before["counts"].get("doingCountInfo"), dict) else {},
                                  after["counts"].get("doingCountInfo") if isinstance(after["counts"].get("doingCountInfo"), dict) else {}),
              "before": before, "after": after}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"pending_check_{rid}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("读取方式：", "监控" if req.via_monitor else "本人待办", "｜当前节点：", req.node_name)
    print("审批日志条数：", log_before, "→", len(req2.approval_log))
    print("待办列表字段变化：", json.dumps(result["list_diff"], ensure_ascii=False)[:800])
    print("门户待办字段变化：", json.dumps(result["portal_diff"], ensure_ascii=False)[:800])
    print("计数变化：", json.dumps(result["counts_diff"], ensure_ascii=False)[:400])
    print("列表中仍存在：", bool(after["list"]), bool(after["portal"]))


if __name__ == "__main__":
    main(sys.argv[1])
