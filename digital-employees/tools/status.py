"""一键查看资料中心与工作台状态：采集轮次、同步队列、单据资料状态、自动审查。python tools/status.py"""
from __future__ import annotations

from collections import Counter

import httpx

RC, WB = "http://127.0.0.1:8091", "http://127.0.0.1:8090"


def main() -> None:
    c = httpx.Client(trust_env=False, timeout=20)
    try:
        h = c.get(f"{RC}/v1/health").json()
        print("资料中心：", h.get("ocr_engine"), h.get("db"))
        s = c.get(f"{RC}/v1/collect/status").json()
        print("队列：", s["queue"], "工作线程：", s.get("workers_alive"))
        for k, v in s["sources"].items():
            print(f"  {k}: enabled={v['enabled']} running={v['running']} error={v.get('last_error')}")
        for r in s["rounds"][:6]:
            print(f"  轮次 {r['source']} 列出 {r['listed']} 入队 {r['queued']} 失败 {r['failed']} {(r['error'] or '')[:100]}")
        rows = c.get(f"{RC}/v1/requests", params={"limit": 300}).json()
        print("单据：", dict(Counter((r["employee"], r["status"]) for r in rows)))
        for r in rows:
            if r["status"] in ("failed", "excluded", "partial", "syncing"):
                print(f"  {r['request_id']} {r['status']} {(r.get('error') or '')[:120]}")
    except Exception as exc:  # noqa: BLE001
        print("资料中心不可用：", type(exc).__name__, exc)
    try:
        for emp in ("contract", "meeting", "procurement"):
            runs = c.get(f"{WB}/api/runs", params={"employee": emp, "limit": 15}).json()
            auto = [r for r in runs if r.get("trigger_by") == "auto"]
            print(f"工作台 {emp}：最近 {len(runs)} 条，其中自动 {len(auto)}",
                  dict(Counter(r["status"] for r in auto)))
            for r in auto[:6]:
                print(f"  {r['request_id']} {r['status']} {(r.get('verdict') or {}).get('title') or (r.get('error') or '')[:80]}")
    except Exception as exc:  # noqa: BLE001
        print("工作台不可用：", type(exc).__name__, exc)


if __name__ == "__main__":
    main()
