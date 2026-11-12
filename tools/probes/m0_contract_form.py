"""主合同审批摸底：从「销售合同（主合同）台账」(customid=78) 取最近单据的流程 id，读表单字段与附件清单（只读，ismonitor）。

  python tools/probes/m0_contract_form.py [--n 30] [--detail <requestid>]

产物：.runtime/m0/main_contract/（含客户数据，不入库）。
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from shared.session import CdpSessionProvider  # noqa: E402
from shared.source_adapters.contract import ContractClient  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / ".runtime" / "m0" / "main_contract"


def strip(s) -> str:
    return re.sub(r"<[^>]+>", "", str(s or "")).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--detail", default="")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    c = ContractClient(CdpSessionProvider().session())
    if args.detail:
        req = c.fetch(args.detail)
        info = {"request_id": req.request_id, "workflow_id": req.workflow_id, "workflow_name": req.workflow_name,
                "request_name": req.request_name, "node": req.node_name, "via_monitor": req.via_monitor,
                "fields": [{"field": f["field"], "label": f["label"], "htmltype": f["htmltype"],
                            "display": strip(f["display"])[:120]} for f in req.fields],
                "attachments": [{"field": a.field_label, "file": a.filename} for a in req.attachments],
                "log": req.approval_log}
        (OUT / f"form_{args.detail}.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{req.workflow_name}（wf={req.workflow_id}）｜{req.request_name}｜节点 {req.node_name}｜监控 {req.via_monitor}")
        for f in info["fields"]:
            if f["display"] not in ("", None):
                print(f"   {f['field']:>12} [{f['htmltype']}] {f['label']}：{f['display'][:80]}")
        print("   附件：")
        for a in info["attachments"]:
            print(f"      [{a['field']}] {a['file']}")
        print(f"   审批日志 {len(req.approval_log)} 条：" + "；".join(f"{x['node']}·{x['operator']}" for x in req.approval_log[:12]))
        return
    rows = c.ledger("78", page_size=args.n, max_pages=1)
    wf = collections.Counter()
    samples = []
    for r in rows:
        lcid = strip(r.get("lcid"))
        if not lcid.isdigit():
            continue
        try:
            form, mon = c.load_form(lcid)
        except Exception as exc:  # noqa: BLE001
            print("  读取失败", lcid, exc)
            continue
        p = form.get("params") or {}
        wf[(p.get("workflowid"), p.get("workflowname"))] += 1
        samples.append({"lcid": lcid, "wf": p.get("workflowid"), "wfname": p.get("workflowname"),
                        "name": strip(r.get("htmc")), "type": strip(r.get("xhtlxej")), "amount": strip(r.get("htewy")),
                        "party": strip(r.get("xmyzlssj")), "lht": strip(r.get("sflhtqy")), "ztb": strip(r.get("sfztb")),
                        "status": strip(r.get("htzhzt")), "date": strip(r.get("qdrq"))})
    (OUT / "samples.json").write_text(json.dumps(samples, ensure_ascii=False, indent=1), encoding="utf-8")
    print("流程分布：", dict(wf))
    for s in samples[:args.n]:
        print(f"   {s['lcid']} wf={s['wf']} {s['type']:<8} {s['amount']:>12} 万元 联合体:{s['lht'] or '-'} 招投标:{s['ztb'] or '-'} {s['name'][:36]}")


if __name__ == "__main__":
    main()
