"""通过工作台接口发起一次审查并打印事件流（验证错误提示与自动单点登录）。"""
import json
import sys

import requests

rid = sys.argv[1] if len(sys.argv) > 1 else "1674771"
s = requests.Session()
s.trust_env = False
task = s.post("http://127.0.0.1:8090/api/runs", json={"employee": "procurement", "request_id": rid}, timeout=30).json()["task_id"]
with s.get(f"http://127.0.0.1:8090/api/runs/{task}/events", stream=True, timeout=600) as r:
    for line in r.iter_lines(decode_unicode=True):
        if not line.startswith("data:"):
            continue
        ev = json.loads(line[5:])
        if not ev:
            continue
        if ev["type"] in ("node.completed", "node.failed", "node.note", "run.failed"):
            print({k: v for k, v in ev.items() if k not in ("at", "report")})
        elif ev["type"] == "run.completed":
            print("run.completed", ev["report"]["summary"])
