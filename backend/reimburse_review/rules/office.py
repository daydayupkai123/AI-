"""办公费 OFF-01–05（需求 3.3）。问题集中在票面看不出买了什么。"""
from __future__ import annotations

import re

from shared.rule_framework import common as C
from shared.rule_framework.engine import issue, missing, ok

from ._util import att_ev, atts, cfg, claim, consecutive, inv_ev, need_invoices

GENERIC = re.compile(r"^\*?[\u4e00-\u9fa5]*\*?(办公用品|办公耗材|文具|用品)$")


def _quota(i) -> bool:
    return "定额" in i.kind


def off01(f):
    if (r := need_invoices(f)):
        return r
    invs = claim(f).invoices
    lists = atts(f, "purchase_list")
    bad = []
    for i in invs:
        if _quota(i):
            if not lists:
                bad.append(f"{i.number}：定额发票未另附明细单")
        elif not i.items or all(GENERIC.match(x.replace(" ", "")) for x in i.items):
            if i.detail_total is None and not lists:
                bad.append(f"{i.number}：票面仅为「{'、'.join(i.items) or '未列明'}」，未列明商品明细")
    if bad:
        return issue("办公费发票未列明商品名称、型号、数量、单价及金额。", [inv_ev(i) for i in invs[:4]], bad)
    return ok(f"通过：{len(invs)} 张发票已列明商品明细或附有清单。")


def off02(f):
    if (r := need_invoices(f)):
        return r
    c, lists = claim(f), atts(f, "purchase_list")
    items, compared = [], 0
    for i in c.invoices:
        if i.detail_total is not None and i.amount is not None:
            compared += 1
            if abs(i.detail_total - i.amount) > 0.01:
                items.append(f"①{i.number}：销货清单合计 {C.fmt_yuan(i.detail_total)}，票面价税合计 {C.fmt_yuan(i.amount)}")
    quota = [i for i in c.invoices if _quota(i)]
    if quota:
        compared += 1
        total = sum(i.amount or 0 for i in quota)
        list_total = None
        if lists:
            a = C.amount_after(lists[0].text, r"(合计|总计|总金额)", 30)
            list_total = a.yuan if a else None
        if c.amount is not None and total + 1e-6 < c.amount:
            items.append(f"②定额发票合计 {C.fmt_yuan(total)} 小于报销金额 {C.fmt_yuan(c.amount)}")
        if c.amount is not None and list_total is not None and abs(list_total - c.amount) > 0.01:
            items.append(f"②报销金额 {C.fmt_yuan(c.amount)} 与附件清单合计 {C.fmt_yuan(list_total)} 不一致")
        if list_total is None:
            items.append("②定额发票场景未识别出附件清单合计金额")
    if items:
        msg = "办公费配套销货清单合计金额与发票票面金额不一致，请核实。" if any(x.startswith("①") for x in items) else \
            "定额发票金额小于报销金额，或报销金额与附件清单金额不一致，请核实。"
        return issue(msg, [inv_ev(i) for i in c.invoices[:3]] + [att_ev(m) for m in lists[:1]], items)
    if not compared:
        return missing("发票未附税控销货清单合计，且无定额发票，无法比对清单与发票金额。")
    return ok("通过：清单合计与发票金额、报销金额一致。")


def off03(f):
    return consecutive(f, "本次办公费报销存在连号发票，请核实业务真实性。")


def off04(f):
    neg = cfg(f).get("office_negative_list") or {}
    words = [w for w in neg.get("words") or [] if w]
    if not neg.get("maintained") or not words:
        return missing("发票内容负面清单尚未由财务提供（config/reimburse.yaml office_negative_list），本条暂无法判断。")
    if (r := need_invoices(f)):
        return r
    hits = [(i, w) for i in claim(f).invoices for x in i.items for w in words if w in x]
    if hits:
        return issue("发票开具内容与本次办公费报销业务用途不匹配，请核实业务及票据。", [inv_ev(i) for i, _ in hits[:4]],
                     [f"{i.number}：「{w}」在负面清单中" for i, w in hits])
    return ok("通过：发票内容未命中办公费负面清单。")


def off05(f):
    c, words = claim(f), cfg(f).get("prepaid_words") or []
    flag = str(c.flags.get("prepaid") or "")
    texts = [(f"发票 {i.number}", " ".join(i.items) + i.remark) for i in c.invoices] + [("报销事由", c.reason)]
    hits = [(src, w) for src, t in texts for w in words if w in t]
    if hits or flag in ("是", "Y", "1"):
        return issue("预付储值支出不得作为办公费报销凭证，请更换合规报销材料。", [inv_ev(i) for i in c.invoices[:3]],
                     [f"{src}含「{w}」" for src, w in hits] + (["表单「是否预付储值」为是"] if flag in ("是", "Y", "1") else []))
    return ok("通过：未发现预付、储值类支出。")
