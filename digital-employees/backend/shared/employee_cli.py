"""审查类数字员工的命令行运行：打印节点进度与规则结果。"""
from __future__ import annotations

import argparse
import time

from .session import CdpSessionProvider
from .task_store import Store

MARK = {"issue": "●", "review": "◐", "missing": "?", "error": "✘", "pass": "○", "na": "·", "notrun": "-"}


def printer(e: dict) -> None:
    t = time.strftime("%H:%M:%S")
    if e["type"] == "node.started":
        print(f"[{t}] ▶ {e['node']}", flush=True)
    elif e["type"] == "node.completed":
        print(f"[{t}] ✔ {e['node']}  {e['ms'] / 1000:.1f}s  {e['summary']}", flush=True)
    elif e["type"] == "node.failed":
        print(f"[{t}] ✘ {e['node']}  {e['error']}：{e.get('detail', '')}", flush=True)
    elif e["type"] == "node.note":
        print(f"        · {e['text']}", flush=True)
    elif e["type"] == "rule.completed":
        print(f"        {MARK.get(e.get('code'), ' ')} {e['rule_id']} {e['name']} [{e['status']}] {e['message'][:80]}",
              flush=True)


def main(title: str, run, sources: tuple[str, ...], argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=f"运行{title}数字员工")
    ap.add_argument("ids", nargs="+", help="单号；本地事项用 --source local")
    ap.add_argument("--source", default=sources[0], choices=sources)
    args = ap.parse_args(argv)
    store = Store()
    sessions = CdpSessionProvider() if args.source != "local" else None
    for rid in args.ids:
        t0 = time.time()
        print(f"===== {title} · {rid}（{args.source}）=====", flush=True)
        final = run(rid, store, sessions, on_event=printer, source=args.source)
        rep = final["report"]
        codes = rep["summary"]["codes"]
        print(f"===== 完成 {time.time() - t0:.1f}s｜{rep['verdict']['title']}｜"
              + "，".join(f"{rep['labels'][c]} {n}" for c, n in codes.items() if n)
              + f"｜报告 {final['report_path']}", flush=True)
    return 0
