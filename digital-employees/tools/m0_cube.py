"""读取合同系统 cube 台账（只读）：getList → counts → table/datas。

  python tools/m0_cube.py <customid> [--pages N] [--page-size N]
"""
import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://contract.gt.cn"
OUT = Path(__file__).resolve().parent.parent / ".runtime" / "m0"

ap = argparse.ArgumentParser()
ap.add_argument("customid")
ap.add_argument("--pages", type=int, default=1)
ap.add_argument("--page-size", type=int, default=100)
args = ap.parse_args()
out = OUT / f"cube_{args.customid}"
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    req = b.contexts[0].request
    ts = int(time.time() * 1000)
    r = req.post(f"{BASE}/api/cube/search/getList?customid={args.customid}&guid=search&canIsQuickSearch=1"
                 f"&isNewTableSearch=1&windowWidth=1600&__random__={ts}").json()
    print("getList status:", r.get("status"), "title:", r.get("windowTitle"))
    key = r.get("datas")
    if not key:
        print(json.dumps(r, ensure_ascii=False)[:500])
        raise SystemExit(1)
    cnt = req.post(f"{BASE}/api/ec/dev/table/counts", form={"dataKey": key}).json()
    print("count:", cnt.get("count"))
    rows, cols = [], []
    for cur in range(1, args.pages + 1):
        page = req.post(f"{BASE}/api/ec/dev/table/datas",
                        form={"dataKey": key, "current": str(cur), "pageSize": str(args.page_size),
                              "sortParams": "[]"}).json()
        cols = cols or page.get("columns") or []
        datas = page.get("datas") or []
        rows += datas
        if len(datas) < args.page_size:
            break
    (out / "columns.json").write_text(json.dumps(cols, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    vis = [(c.get("dataIndex"), c.get("title")) for c in cols if c.get("hide") != "true"]
    print("columns:", " | ".join(f"{t}({d})" for d, t in vis)[:1500])
    print("rows fetched:", len(rows))
