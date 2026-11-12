"""Inspect a captured e-cology loadForm response: fields, values, attachments, details."""
import json
import sys
from pathlib import Path

d = Path(sys.argv[1])
idx = json.loads((d / "index.json").read_text(encoding="utf-8"))
rec = next(r for r in idx["records"] if "/reqform/loadForm" in r["url"])
data = json.loads((d / rec["file"]).read_text(encoding="utf-8"))
print("top keys:", list(data.keys()))
params = data.get("params") or {}
print("params:", {k: params.get(k) for k in ("requestid", "workflowid", "nodeid", "formid", "isbill", "requestname", "workflowname", "nodename", "creater", "createdate") if k in params})

table_info = data.get("tableInfo") or {}
main = (table_info.get("main") or {}).get("fieldinfomap") or {}
maindata = data.get("maindata") or {}
print(f"\n== main fields: {len(main)} defined, {len(maindata)} values")
HT = {"1": "文本", "2": "多行", "3": "浏览", "4": "勾选", "5": "下拉", "6": "附件", "7": "特殊", "8": "单选", "9": "位置"}
attach_fields = []
for fid, f in sorted(main.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
    key = f"field{fid}"
    v = maindata.get(key) or {}
    val = v.get("showname") or v.get("value") or ""
    ht = str(f.get("htmltype"))
    label = f.get("fieldlabel") or f.get("fieldname")
    if ht == "6":
        files = ((v.get("specialobj") or {}).get("filedatas")) or []
        attach_fields.append((fid, label, files))
        print(f"  [附件] {key:12} {label} -> {len(files)} file(s)")
    else:
        sval = str(val).replace("\n", " ")
        print(f"  [{HT.get(ht, ht)}] {key:12} {label}: {sval[:80]}")

print("\n== attachments")
for fid, label, files in attach_fields:
    for f in files:
        print(f"  field{fid} {label} | {f.get('filename')} | size={f.get('filesize')} | fileid={f.get('fileid')} imgid={f.get('imagefileid')} docid={f.get('docid') or f.get('acclink')}")
    if files:
        print("    sample keys:", sorted(files[0].keys()))
        print("    sample:", json.dumps({k: files[0][k] for k in list(files[0])[:25]}, ensure_ascii=False)[:900])

details = {k: v for k, v in table_info.items() if k.startswith("detail")}
dd = data.get("detailData") or {}
for dk, dv in details.items():
    fmap = dv.get("fieldinfomap") or {}
    rows = (dd.get(dk) or {}).get("rowDatas") or {}
    print(f"\n== {dk}: {len(fmap)} fields, {len(rows)} rows")
    for fid, f in list(fmap.items())[:30]:
        print(f"   field{fid} {f.get('fieldlabel') or f.get('fieldname')} (htmltype={f.get('htmltype')})")
    for rk, row in list(rows.items())[:3]:
        brief = {}
        for k, v in row.items():
            if k.startswith("field") and isinstance(v, dict):
                lab = (fmap.get(k[5:]) or {}).get("fieldlabel") or k
                brief[lab] = (v.get("showname") or v.get("value") or "")[:40]
        print("   row", rk, json.dumps(brief, ensure_ascii=False)[:600])
