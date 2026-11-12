"""命令行运行采购审批数字员工。

  ..\\.venv\\Scripts\\python.exe -m procurement_review.run <requestid> [<requestid> ...]

开发期会话来自已登录的调试 Chrome（127.0.0.1:9222）。
"""
from __future__ import annotations

import sys
import time

from shared.session import CdpSessionProvider
from shared.task_store import Store

from .workflow import run


def printer(e: dict) -> None:
    t = time.strftime("%H:%M:%S")
    if e["type"] == "node.started":
        print(f"[{t}] ▶ {e['node']}", flush=True)
    elif e["type"] == "node.completed":
        print(f"[{t}] ✔ {e['node']}  {e['ms'] / 1000:.1f}s  {e['summary']}", flush=True)
    elif e["type"] == "node.failed":
        print(f"[{t}] ✘ {e['node']}  {e['error']}", flush=True)
    elif e["type"] == "rule.completed":
        mark = {"命中": "●", "未命中": "○", "未能识别": "?", "未执行": "-"}.get(e["status"], " ")
        print(f"        {mark} {e['rule_id']} {e['name']} [{e['status']}] {e['message'][:70]}", flush=True)


def main(argv: list[str]) -> int:
    store = Store()
    sessions = CdpSessionProvider()
    for rid in argv:
        t0 = time.time()
        print(f"===== 采购审批 · 单据 {rid} =====", flush=True)
        final = run(rid, store, sessions, on_event=printer)
        s = final["report"]["summary"]
        print(f"===== 完成 {time.time() - t0:.1f}s｜命中 {s['命中']}（一定不通过 {s['一定不通过']}，拿不准 {s['拿不准']}）"
              f"｜未能识别 {s['未能识别']}｜未执行 {s['未执行']}｜报告 {final['report_path']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
