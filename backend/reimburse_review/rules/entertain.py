"""业务招待费 ENT-01–12（需求 3.2）。职级 × 招待类型 × 人数，先算再判。"""
from __future__ import annotations

import re
from datetime import date

from shared.rule_framework import common as C
from shared.rule_framework.engine import issue, missing, na, ok, review

from ._util import (accompany_rule, att_ev, atts, cfg, claim, consecutive, etype, form_ev, inv_ev, need_invoices,
                    standard_days_rule)


def _e(f) -> dict:
    return claim(f).entertain or {}


FOOD = r"餐饮|餐费|酒水|招待|食品|饮品|宴"


def ent_invoices(f):
    """招待费发票：纯招待单取全部发票；混合单（如差旅含招待）按商品名称识别餐饮类发票。"""
    c = claim(f)
    if "招待" in c.doc_type:
        return list(c.invoices)
    return [i for i in c.invoices if re.search(FOOD, " ".join(i.items) + i.seller)]


def _need_ent_invoices(f):
    if (r := need_invoices(f)):
        return r
    if not ent_invoices(f):
        return missing("未从发票中识别出招待费（餐饮类）发票。")
    return None


def ent01(f):
    e = _e(f)
    if etype(e.get("type")) != "其他公务":
        return na("招待类型不是其他公务招待。")
    letters = atts(f, "official_letter")
    if letters:
        return ok(f"通过：已上传派出单位公函（{letters[0].name}）。", [att_ev(letters[0])])
    c = claim(f)
    if re.search(r"特殊情况|事后补|后补", c.remark):
        return ok("通过：未附公函，但已在报销单备注说明特殊情况。", [form_ev("备注", c.remark)])
    return issue("其他公务招待需提供派出单位公函，无公函请在报销单备注特殊情况，请核实补充。", [form_ev("招待类型", e.get("type"))])


def ent02(f):
    return accompany_rule(f, "业务招待陪餐人数超出该招待类型规定上限，请核实调整陪餐人数。")


def ent03(f):
    e, c, conf = _e(f), claim(f), cfg(f)
    kind = etype(e.get("type"))
    if not kind:
        return missing(f"招待类型「{e.get('type') or '未填写'}」无法识别。")
    if not e.get("total") or not e.get("guests"):
        return missing("报销单未填写招待总金额或招待对象人数。")
    pc = conf.get("per_capita") or {}
    per = e["total"] / e["guests"]
    high_lim, normal_lim = (pc.get("high") or {}).get(kind, 500), (pc.get("normal") or {}).get(kind, 400)
    is_high = any(g in (c.grade or "") for g in pc.get("high_grades") or [])
    ev = [form_ev("招待总金额", C.fmt_yuan(e["total"])), form_ev("招待对象人数", int(e["guests"])),
          form_ev("岗位职级", c.grade or "未填写")]
    lim = high_lim if is_high else normal_lim
    detail = f"人均 {per:,.2f} 元（{C.fmt_yuan(e['total'])} ÷ {int(e['guests'])} 人），{c.grade or '职级未填写'}·{e.get('type')}标准 {lim} 元"
    if per <= lim + 1e-9:
        return ok(f"通过：{detail}。", ev)
    if not is_high and per <= high_lim + 1e-9:
        return review("本次业务招待人均金额超出一般员工档招待标准；职级与审批身份的映射待确认，若报销人属高档职级则未超标，请人工确认。",
                      ev, [detail + f"；高档职级标准 {high_lim} 元"])
    return issue("本次业务招待人均金额超出岗位职级对应招待标准，请核实。", ev, [detail])


def _has_gift(f) -> bool:
    e, c = _e(f), claim(f)
    return bool(e.get("gift")) or bool(atts(f, "gift_detail")) or any("纪念品" in str(x.get("item") or x.get("name") or "")
                                                                        for x in c.expenses)


def ent04(f):
    if etype(_e(f).get("type")) != "其他公务":
        return na("招待类型不是其他公务招待。")
    if _has_gift(f):
        return issue("其他公务招待不允许赠送纪念品，请核实业务内容。", [form_ev("招待类型", _e(f).get("type"))])
    return ok("通过：未发现纪念品赠送记录。")


def ent05(f):
    e, conf = _e(f), cfg(f).get("gift") or {}
    if etype(e.get("type")) != "商务外事" or not _has_gift(f):
        return na("非商务/外事招待，或未发生纪念品支出。")
    items, ev = [], []
    per = e.get("gift_per_person")
    if per is not None and per > conf.get("per_person_max", 300):
        items.append(f"商务、外事招待赠送纪念品人均不得超过 {conf.get('per_person_max', 300)} 元（本次 {per:g} 元），请核实调整。")
        ev.append(form_ev("纪念品人均金额", per))
    if not atts(f, "gift_detail"):
        items.append("外购纪念品报销需上传原始购物明细，请补充附件。")
    times = e.get("gift_times")
    if times is not None and times > conf.get("max_times", 1):
        items.append(f"单次商务、外事招待纪念品赠送仅限 {conf.get('max_times', 1)} 次（本次 {times:g} 次），请核实业务真实性。")
        ev.append(form_ev("纪念品赠送次数", times))
    if items:
        return issue("商务/外事招待纪念品不符合标准或缺少附件。", ev, items)
    if per is None:
        return missing("报销单未填写纪念品人均金额。")
    return ok(f"通过：纪念品人均 {per:g} 元，已附购物明细，赠送次数未超限。")


def ent06(f):
    e = _e(f)
    units = e.get("units") or []
    if not units:
        return missing("报销单未填写招待对象单位。")
    if not re.search(r"商务", e.get("type") or ""):
        return ok(f"通过：招待类型为{e.get('type') or '未填写'}，非商务招待。")
    soe = cfg(f).get("central_soes") or {}
    hits = [u for u in units for k in soe.get("keywords") or [] if k in u]
    if hits:
        return issue("中央企业之间不得开展商务宴请，请核实招待类型。", [form_ev("招待对象单位", "、".join(units))],
                     [f"「{u}」属于中央企业" for u in dict.fromkeys(hits)])
    likely = [u for u in units if re.search(r"^中国|集团", u)]
    if likely and not soe.get("maintained"):
        return review("招待对象单位疑似中央企业，央企名录待财务确认，请人工核实招待类型。", [form_ev("招待对象单位", "、".join(units))],
                      [f"「{u}」" for u in likely])
    return ok(f"通过：招待对象单位（{'、'.join(units)}）未匹配央企名录。")


def _num_after(text: str, kw: str):
    m = re.search(kw + r"[^\d\n]{0,8}(\d+)", text)
    return int(m.group(1)) if m else None


def ent07(f):
    e = _e(f)
    lists = atts(f, "entertain_list")
    if not lists:
        return missing("未上传业务招待清单（代预算审批单），无法比对。")
    t = lists[0].text
    doc = {"招待对象人数": _num_after(t, r"实际参加人数"), "陪餐人数": _num_after(t, r"陪同人数"),
           "招待总金额": (lambda a: a.yuan if a else None)(C.amount_after(t, r"实际费用总额", 30))}
    form = {"招待对象人数": e.get("guests"), "陪餐人数": e.get("accompany"), "招待总金额": e.get("total")}
    diffs, compared = [], 0
    for k in form:
        if form[k] is None or doc[k] is None:
            continue
        compared += 1
        if abs(float(form[k]) - float(doc[k])) > 0.01:
            fmt = (lambda v: C.fmt_yuan(v)) if k == "招待总金额" else (lambda v: f"{v:g} 人")
            diffs.append(f"{k}：表单 {fmt(form[k])}，招待清单 {fmt(doc[k])}")
    ev = [att_ev(lists[0], "业务招待清单")]
    if diffs:
        return issue("报销表单填报招待信息与业务招待清单附件信息不一致，请核实。", ev, diffs)
    if not compared:
        return missing("业务招待清单中未识别出实际参加人数、陪同人数或实际费用总额。", ev)
    return ok(f"通过：表单与业务招待清单的 {compared} 项数据一致。", ev)


def ent08(f):
    return _need_ent_invoices(f) or consecutive(f, "本次业务招待报销存在连号发票，请核实业务真实性。", ent_invoices(f))


def ent09(f):
    if (r := _need_ent_invoices(f)):
        return r
    c = claim(f)
    today = c.submit_date or date.today()
    cutoff = int(cfg(f).get("prior_year_cutoff_month", 2))
    if today.month < cutoff:
        return ok(f"通过：报销日期 {today} 在 {cutoff} 月之前，上年度发票仍可报销。")
    old = [i for i in ent_invoices(f) if i.date and i.date.year < today.year]
    if old:
        return issue("该发票为上年度发票，本年度 2 月之后不允许报销，请更换合规发票。", [inv_ev(i, "上年度发票") for i in old[:4]],
                     [f"{i.number}：开票 {i.date}（报销日期 {today}）" for i in old])
    return ok(f"通过：发票均为 {today.year} 年度开具。")


def ent10(f):
    e = _e(f)
    if (r := _need_ent_invoices(f)):
        return r
    if not e.get("date"):
        return missing("报销单未填写招待发生日期。")
    lim = int(cfg(f).get("entertain_invoice_days", 1))
    bad = [i for i in ent_invoices(f) if i.date and abs((i.date - e["date"]).days) > lim]
    if bad:
        return issue("招待费发票开票日期与招待发生日期不一致，请核实业务真实性。", [form_ev("招待日期", e["date"])] +
                     [inv_ev(i) for i in bad[:4]], [f"{i.number}：开票 {i.date}，招待 {e['date']}，相差 {abs((i.date - e['date']).days)} 天"
                                                    for i in bad])
    return ok(f"通过：发票开票日期与招待日期（{e['date']}）相差不超过 {lim} 天。")


def ent11(f):
    c = claim(f)
    if not ("差旅" in c.doc_type or any("差旅" in t for t in c.expense_types())):
        return na("本笔报销不同时包含差旅费与业务招待费。")
    return standard_days_rule(f, "本次报销含有业务招待费，补助天数不应与出差天数相等，请核实补助天数。")


def ent12(f):
    words = cfg(f).get("sensitive_words") or []
    text = claim(f).text_fields()
    hits = [w for w in words if w in text]
    if hits:
        return issue(f"招待{'、'.join(hits)}，请核实业务合理性。", [form_ev("命中字段内容", text[:120])],
                     [f"命中敏感字眼「{w}」" for w in hits])
    return ok("通过：报销填报内容未出现敏感单位字眼。")
