"""交通费 TRA-01–02（需求 3.5）。"""
from __future__ import annotations

from shared.rule_framework import common as C
from shared.rule_framework.engine import issue, na, ok

from ._util import atts, cfg, claim, consecutive, inv_ev, need_invoices


def tra01(f):
    if (r := need_invoices(f)):
        return r
    plats = cfg(f).get("ride_platforms") or []
    invs = [i for i in claim(f).invoices if any(p in " ".join(i.items) + i.seller + i.remark for p in plats)]
    if not invs:
        return na("本单无网约车、租车类第三方平台发票。")
    details = atts(f, "ride_detail", "itinerary")
    bad = [i for i in invs if i.amount is None or not any(f"{i.amount:.2f}" in m.text or f"{i.amount:,.2f}" in m.text
                                                          for m in details)]
    if bad:
        return issue("该第三方平台交通费发票未上传对应出行明细清单，请补充上传明细清单。", [inv_ev(i) for i in bad[:4]],
                     [f"{i.number}（{i.seller or '平台'}，{C.fmt_yuan(i.amount)}）未找到金额一致的出行明细" for i in bad])
    return ok(f"通过：{len(invs)} 张第三方平台发票均有金额一致的出行明细。")


def tra02(f):
    return need_invoices(f) or consecutive(f, "本次报销交通费存在连号发票，请核实业务真实性。")
