"""差旅费 TRV-01–08（需求 3.1）。初审以日期核对为主：报销单行程期间、行程单出差日期、发票乘车日期三者对得上。"""
from __future__ import annotations

import re

from core.rules import common as C
from core.rules.engine import issue, missing, na, notrun, ok

from ._util import (accompany_rule, att_ev, atts, cfg, claim, consecutive, form_ev, has_entertain, inv_ev,
                    need_invoices, standard_days_rule)


def _period(f):
    t = claim(f).travel or {}
    return t.get("start"), t.get("end")


def trv01(f):
    s, e = _period(f)
    if not s or not e:
        return missing("报销单未填写行程期间。")
    its = atts(f, "itinerary")
    if not its:
        return missing("未上传出差行程单，无法比对行程期间。", [form_ev("行程期间", f"{s} 至 {e}")])
    dates = sorted(d for m in its for d, _, _ in C.find_dates(m.text))
    if not dates:
        return missing("出差行程单中未识别出出差日期。", [att_ev(its[0])])
    ev = [form_ev("行程期间", f"{s} 至 {e}"), att_ev(its[0], "出差行程单")]
    if dates[0] != s or dates[-1] != e:
        return issue("报销单行程期间与附件出差行程单出差日期不一致，请核实。", ev,
                     [f"报销单 {s} 至 {e}；行程单 {dates[0]} 至 {dates[-1]}"])
    return ok(f"通过：行程期间与出差行程单一致（{s} 至 {e}）。", ev)


def _in_period(d, s, e) -> bool:
    return s <= d <= e


def trv02(f):
    s, e = _period(f)
    tickets = [i for i in claim(f).invoices if "铁路电子客票" in i.kind]
    if not tickets:
        return na("本单无数电票铁路电子客票。")
    if not s or not e:
        return missing("报销单未填写行程期间。")
    bad, unknown = [], []
    for i in tickets:
        if "退票" in i.remark or any("退票" in x for x in i.items):
            continue
        if not i.travel_date:
            unknown.append(i)
        elif not _in_period(i.travel_date, s, e):
            bad.append(i)
    if bad:
        return issue("铁路电子客票乘车/乘机日期不在报销行程期间内，请核实。", [inv_ev(i, "铁路电子客票") for i in bad[:4]],
                     [f"{i.number}：乘车 {i.travel_date}，行程期间 {s} 至 {e}" for i in bad])
    if unknown:
        return missing(f"{len(unknown)} 张铁路电子客票未识别出乘车日期。", [inv_ev(i) for i in unknown[:3]])
    return ok(f"通过：{len(tickets)} 张铁路电子客票乘车日期均在行程期间内。")


TRIP = r"出行|乘车|旅客|客运|运输服务|行程|起点|终点|机票|航班|乘机"


def _ordinary(f):
    """出行类数电普通发票：备注或商品名称体现出行信息（住宿、餐饮等发票不在此列）。"""
    return [i for i in claim(f).invoices if "普通发票" in i.kind and "铁路" not in i.kind
            and re.search(TRIP, i.remark + " ".join(i.items))]


def trv03(f):
    s, e = _period(f)
    invs = _ordinary(f)
    if not invs:
        return na("本单无出行类数电发票普通发票。")
    if not s or not e:
        return missing("报销单未填写行程期间。")
    bad, checked = [], 0
    for i in invs:
        ds = [d for d, _, _ in C.find_dates(i.remark)]
        if not ds:
            continue
        checked += 1
        out = [d for d in ds if not _in_period(d, s, e)]
        if out:
            bad.append((i, out))
    if bad:
        return issue("数电普通发票备注的出行日期不在报销行程期间内，请核实。", [inv_ev(i, "数电普通发票") for i, _ in bad[:4]],
                     [f"{i.number}：备注出行日期 {'、'.join(map(str, out))}，行程期间 {s} 至 {e}" for i, out in bad])
    if not checked:
        return missing("出行类数电普通发票备注中未识别出出行日期。", [inv_ev(i) for i in invs[:3]])
    return ok(f"通过：{checked} 张数电普通发票备注出行日期均在行程期间内。")


def trv04(f):
    return need_invoices(f) or consecutive(f, "本次报销存在连号发票，请核实业务真实性。")


def trv05(f):
    invs = [i for i in _ordinary(f) if C.find_dates(i.remark)]
    if not invs:
        return na("本单无备注出行人、出行日期的数电普通发票。")
    its = atts(f, "itinerary", "ride_detail")
    missing_list = []
    for i in invs:
        amt = f"{i.amount:.2f}" if i.amount is not None else None
        ok_doc = any(amt and (amt in m.text or f"{i.amount:,.2f}" in m.text) for m in its)
        if not ok_doc:
            missing_list.append(i)
    if missing_list:
        return issue("该数电普通发票无对应的出行行程单附件，请补充上传。", [inv_ev(i, "数电普通发票") for i in missing_list[:4]],
                     [f"{i.number}（{C.fmt_yuan(i.amount)}，备注：{i.remark[:30]}）未找到金额一致的行程单" for i in missing_list])
    return ok(f"通过：{len(invs)} 张数电普通发票均有金额一致的行程单。")


def trv06(f):
    rule = (cfg(f).get("rules") or {}).get("TRV-06") or {}
    if not rule.get("enabled", False):
        return notrun(rule.get("reason") or "判定口径待业务确认。")
    t = claim(f).travel or {}
    if "院车" not in (t.get("reason") or claim(f).reason):
        return na("出差事由不含“院车”。")
    amt = t.get("subsidy_amount")
    if amt is None:
        return missing("报销单未填写出差补助金额。")
    if amt % 100:
        return issue("出差事由包含院车，出差补助金额需为 100 的倍数，请调整补助金额。", [form_ev("出差补助金额", amt)])
    return ok(f"通过：出差补助金额 {amt:g} 元为 100 的倍数。")


def trv07(f):
    if not has_entertain(f):
        return na("费用明细不含业务招待费。")
    return accompany_rule(f, "业务招待陪餐人数超出该招待类型规定上限，请核实调整陪餐人数。")


def trv08(f):
    if not has_entertain(f):
        return na("费用明细不含业务招待费。")
    return standard_days_rule(f, "本次报销含有业务招待费，标准天数不应与行程天数相等，请核实补助天数。")
