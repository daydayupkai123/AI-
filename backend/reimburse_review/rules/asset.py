"""资产采购 AST-01–03（需求 3.9）。买的是什么、有没有入库、谁签的字。"""
from __future__ import annotations

from shared.rule_framework import common as C
from shared.rule_framework.engine import issue, missing, ok, review

from ..materials import ROLE_LABELS, signature_state
from ._util import att_ev, atts, cfg, claim, form_ev, inv_ev, need_invoices


def ast01(f):
    c = claim(f)
    if not c.assets:
        return missing("报销单未填写资产信息。")
    if (r := need_invoices(f)):
        return r
    unmatched = []
    pool = list(c.invoices)
    for a in c.assets:
        hit = next((i for i in pool if i.amount is not None and a.get("amount") is not None
                    and abs(i.amount - a["amount"]) < 0.01
                    and (not i.items or any(C.jaccard(a.get("name", ""), x) >= 0.2 or a.get("name", "") in x for x in i.items))),
                   None)
        if hit:
            pool.remove(hit)
        else:
            unmatched.append(a)
    if unmatched:
        return issue("资产信息与发票信息校验不一致，请核实。", [inv_ev(i) for i in c.invoices[:4]],
                     [f"资产「{a.get('name')}」{C.fmt_yuan(a.get('amount'))} 未找到名称、金额对应的发票" for a in unmatched])
    return ok(f"通过：{len(c.assets)} 项资产信息与发票名称、金额对应。")


def ast02(f):
    tier = claim(f).asset_tier
    req = (cfg(f).get("asset_required") or {}).get(tier)
    if not req:
        return missing(f"资产档位「{tier or '未填写'}」无法识别（应为必备 / 专项 / 重大）。")
    lacking = [ROLE_LABELS[r] for r in req if not atts(f, r)]
    if lacking:
        return issue(f"{'、'.join(lacking)} 附件未上传，请补充。", [form_ev("资产档位", tier)], [f"{tier}档缺少{x}" for x in lacking])
    return ok(f"通过：{tier}档必备附件已齐全。")


def ast03(f):
    docs = atts(f, "asset_inbound")
    if not docs:
        return missing("未上传资产入库单（见 AST-02），无法核对签字。")
    state, empty = signature_state(docs[0])
    if state == "missing":
        return issue(f"资产入库单 {'、'.join(empty)} 签字不全，请补充。", [att_ev(docs[0])], [f"{x}未签字" for x in empty])
    if state == "unknown":
        return review("资产入库单为扫描件或无签字栏，签字是否齐全无法自动识别，请人工核对。", [att_ev(docs[0])])
    return ok("通过：资产入库单签字栏均已签署。", [att_ev(docs[0])])
