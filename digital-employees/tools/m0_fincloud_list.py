"""列出门户工作台中本人发起的通财云单据（只读，app=1 协同类）：python tools/m0_fincloud_list.py [关键字]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.session import CdpSessionProvider  # noqa: E402
from core.sources.docflow import PORTAL_LIST  # noqa: E402

if __name__ == "__main__":
    s = CdpSessionProvider().session()
    kw = sys.argv[1] if len(sys.argv) > 1 else "报销"
    out = ROOT / ".runtime" / "probe" / "fincloud_list.json"
    rows_all = []
    for app in ("1", "4"):
        body = {"type": "doneSent", "memberId": "", "isLeader": False, "subject": kw, "templeteId": "", "mark": "",
                "summaryState": "", "sender": "", "department": "", "app": app, "preApprover": "", "pageNo": 1,
                "pageSize": 50, "sequence": 0, "timeType": None, "platform": "PC"}
        r = s.post(PORTAL_LIST, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=30,
                   headers={"Content-Type": "application/json;charset=UTF-8", "Origin": "https://i.gt.cn",
                            "Referer": "https://i.gt.cn/"})
        d = r.json()
        res = d.get("result")
        rows = ((res.get("data") or {}).get("doneSent") or {}).get("data") or [] if isinstance(res, dict) else []
        print("app", app, "rows", len(rows), "" if isinstance(res, dict) else res)
        for x in rows:
            rows_all.append(x)
            print("  ", x.get("appId"), x.get("source"), x.get("affairId"), "|", x.get("subject"), "|",
                  (x.get("url") or x.get("webUrl") or "")[:160])
    out.write_text(json.dumps(rows_all, ensure_ascii=False, indent=1), encoding="utf-8")
