"""合同系统 cube 台账摸底：名称、总条数、列定义、前几行（只取第一页）。

  python tools/m0_ledger_peek.py <customid> [<customid> ...] [--rows 5]

产物写到 .runtime/m0/ledger_<customid>.json（含客户数据，不入库）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.session import CdpSessionProvider  # noqa: E402
from core.sources.contract import CONTRACT_BASE  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / ".runtime" / "m0"


def strip(s) -> str:
    return re.sub(r"<[^>]+>", "", str(s or "")).strip()


def peek(s, customid: str, rows: int) -> dict:
    ts = int(time.time() * 1000)
    r = s.post(f"{CONTRACT_BASE}/api/cube/search/getList?customid={customid}&guid=search&canIsQuickSearch=1"
               f"&isNewTableSearch=1&windowWidth=1600&__random__={ts}", timeout=60).json()
    key = r.get("datas")
    if not key:
        return {"customid": customid, "error": str(r)[:300]}
    cnt = s.post(f"{CONTRACT_BASE}/api/ec/dev/table/counts", data={"dataKey": key}, timeout=60).json()
    page = s.post(f"{CONTRACT_BASE}/api/ec/dev/table/datas",
                  data={"dataKey": key, "current": "1", "pageSize": str(rows), "sortParams": "[]"}, timeout=120).json()
    cols = [{"field": c.get("dataIndex") or c.get("dbField"), "title": strip(c.get("title"))}
            for c in page.get("columns") or [] if c.get("display") != "false"]
    data = page.get("datas") or []
    return {"customid": customid, "title": r.get("windowTitle"), "count": cnt.get("count"), "columns": cols,
            "rows": data}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--rows", type=int, default=5)
    args = ap.parse_args()
    s = CdpSessionProvider().session()
    OUT.mkdir(parents=True, exist_ok=True)
    for cid in args.ids:
        res = peek(s, cid, args.rows)
        (OUT / f"ledger_{cid}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        if res.get("error"):
            print(f"== {cid}：读取失败 {res['error']}")
            continue
        print(f"== {cid} {res['title']}：{res['count']} 条，{len(res['columns'])} 列")
        print("   列：" + "、".join(f"{c['title']}({c['field']})" for c in res["columns"]))
        for row in res["rows"][:3]:
            brief = {c["title"]: strip(row.get(f"{c['field']}span") or row.get(c["field"]))[:30] for c in res["columns"][:12]}
            print("   行：", json.dumps(brief, ensure_ascii=False))


if __name__ == "__main__":
    main()
