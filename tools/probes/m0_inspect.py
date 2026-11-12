"""Summarise captured e-cology list responses (todo/done) for M0."""
import json
import sys
from pathlib import Path

d = Path(sys.argv[1])
idx = json.loads((d / "index.json").read_text(encoding="utf-8"))
by_url = {}
for r in idx["records"]:
    key = r["url"].split("?")[0].replace("https://contract.gt.cn", "")
    by_url.setdefault(key, []).append(r)


def load(rec):
    p = d / rec["file"]
    return json.loads(p.read_text(encoding="utf-8")) if p.suffix == ".json" else None


for key in ("/api/workflow/reqlist/doingBaseInfo", "/api/workflow/reqlist/doneBaseInfo"):
    for rec in by_url.get(key, []):
        data = load(rec)
        tree = data.get("treedata") or data.get("tree") or []
        print("==", key, "keys:", list(data.keys())[:20])
        def walk(nodes, depth=0):
            for n in nodes or []:
                name = n.get("name") or n.get("domid")
                cnt = n.get("count") or n.get("num") or ""
                print("  " * depth + f"- {name} id={n.get('domid') or n.get('id')} {cnt}")
                walk(n.get("childs") or n.get("children"), depth + 1)
        walk(tree)

for key in ("/api/workflow/reqlist/splitPageKey",):
    for rec in by_url.get(key, []):
        print("==", key, "post:", rec["post"][:300])
        print("   resp:", json.dumps(load(rec), ensure_ascii=False)[:400])

for rec in by_url.get("/api/ec/dev/table/datas", []):
    data = load(rec)
    cols = data.get("columns") or []
    print("== table/datas columns:")
    for c in cols:
        if c.get("hide") == "true":
            continue
        print(f"   {c.get('dataIndex')!s:28} {c.get('title')}")
    rows = data.get("datas") or []
    print(f"== rows: {len(rows)}")
    for r in rows[:20]:
        keep = {k: v for k, v in r.items() if not k.endswith("span") and k not in ("randomFieldId",)}
        brief = {k: keep.get(k) for k in ("requestid", "workflowid", "requestname", "createdate", "currentnodeid", "nodeid", "workflowname") if k in keep}
        print("   ", json.dumps(brief, ensure_ascii=False)[:300])
    if rows:
        print("   all keys:", sorted(rows[0].keys()))
