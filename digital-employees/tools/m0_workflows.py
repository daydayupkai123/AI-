"""合同系统摸底：列出待办 / 已办 / 我的请求中的流程分类（workflowid、名称、数量），可按名称关键字过滤。

  python tools/m0_workflows.py [关键字]

只读：只调列表分类接口，不打开任何单据。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.session import CdpSessionProvider  # noqa: E402
from core.sources.contract import CONTRACT_BASE  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / ".runtime" / "m0" / "workflows"


def walk(nodes, path=""):
    for n in nodes or []:
        name = n.get("name") or n.get("title") or ""
        yield {"key": n.get("domid") or n.get("key") or n.get("id"), "name": name, "path": f"{path}/{name}",
               "count": n.get("count") or n.get("num")}
        yield from walk(n.get("childs") or n.get("children"), f"{path}/{name}")


def main(kw: str = "") -> None:
    s = CdpSessionProvider().session()
    OUT.mkdir(parents=True, exist_ok=True)
    for scope in ("doingBaseInfo", "doneBaseInfo", "mineBaseInfo"):
        r = s.post(f"{CONTRACT_BASE}/api/workflow/reqlist/{scope}", data={}, timeout=60)
        try:
            data = r.json()
        except ValueError:
            print(scope, "非 JSON：", r.text[:120])
            continue
        (OUT / f"{scope}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        rows = list(walk(data.get("treedata") or []))
        hits = [x for x in rows if kw in x["name"]] if kw else rows
        print(f"== {scope}：{len(rows)} 个分类，匹配 {len(hits)}")
        for x in hits[:60]:
            print(f"   {x['key']}  {x['path']}  {x['count'] if x['count'] is not None else ''}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
