"""合同系统待办 / 已办列表读取摸底（只读，只调列表接口，不打开单据）：
python tools/probes/m0_contract_list.py done 99 [pageSize]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from shared.session import CdpSessionProvider  # noqa: E402
from shared.source_adapters.contract import CONTRACT_BASE  # noqa: E402


def main(scope: str, wf: str, size: str = "10") -> None:
    s = CdpSessionProvider().session()
    for extra in ({"workflowid": wf}, {"workflowid": wf, "wfid": wf}, {}):
        r = s.post(f"{CONTRACT_BASE}/api/workflow/reqlist/splitPageKey", data={"viewScope": scope, **extra}, timeout=60)
        d = r.json()
        key = d.get("sessionkey")
        print("== params", extra, "keys", list(d.keys())[:10], "sessionkey", str(key)[:40])
        if not key:
            continue
        page = s.post(f"{CONTRACT_BASE}/api/ec/dev/table/datas",
                      data={"dataKey": key, "current": "1", "pageSize": size, "sortParams": "[]"}, timeout=60).json()
        cnt = s.post(f"{CONTRACT_BASE}/api/ec/dev/table/counts", data={"dataKey": key}, timeout=60).json()
        rows = page.get("datas") or []
        print("   total", cnt.get("count") or cnt, "rows", len(rows))
        for x in rows[:size and int(size)]:
            print("   ", x.get("requestid"), x.get("workflowid"), "|", (x.get("requestnamespan") or x.get("requestname") or "")[:60],
                  "|", x.get("createdate"), x.get("receivedate") or x.get("operatedate"))
        if rows:
            Path(ROOT / ".runtime" / "m0").mkdir(parents=True, exist_ok=True)
            (ROOT / ".runtime" / "m0" / f"list_{scope}_{wf}.json").write_text(
                json.dumps(rows[:3], ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:])
