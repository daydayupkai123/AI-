"""经工作台接口发起一次真实取数审查并跟随事件流到结束：python tools/checks/ui_live_run_check.py meeting "通设请字[2026]115号" """
from __future__ import annotations

import json
import sys

import httpx

BASE = "http://127.0.0.1:8090"

if __name__ == "__main__":
    emp, rid = sys.argv[1], sys.argv[2]
    with httpx.Client(base_url=BASE, timeout=600, trust_env=False) as c:
        info = c.get(f"/api/{emp}/samples").json()
        print("live_ready:", info.get("live_ready"), "|", info.get("live_note"))
        r = c.post("/api/runs", json={"employee": emp, "request_id": rid})
        print("POST /api/runs", r.status_code, r.text[:200])
        r.raise_for_status()
        tid = r.json()["task_id"]
        with c.stream("GET", f"/api/runs/{tid}/events") as s:
            for line in s.iter_lines():
                if not line.startswith("data:"):
                    continue
                e = json.loads(line[5:])
                t = e.get("type")
                if t in ("node.completed", "node.failed"):
                    print(f"  {t:15s} {e.get('node')}  {e.get('summary') or e.get('error') or ''}"[:200])
                elif t in ("run.completed", "run.failed"):
                    print(" ", t, e.get("title") or e.get("error") or "", (e.get("detail") or "")[:200])
                    break
        rep = c.get(f"/api/runs/{tid}").json()
        print("report kind:", rep.get("kind"), "| verdict:", (rep.get("verdict") or {}).get("title"))
