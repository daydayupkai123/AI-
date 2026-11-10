"""报销规则共用：取配置、附件、发票证据、连号、陪餐上限、标准天数。"""
from __future__ import annotations

import math
import re

from core.rules import common as C
from core.rules.engine import issue, missing, na, ok

from ..materials import ROLE_LABELS, find
from ..model import Claim, Invoice


def cfg(f) -> dict:
    return f.get("cfg") or {}


def claim(f) -> Claim:
    return f["claim"]


def atts(f, *roles):
    return find(f.get("materials") or [], *roles)


def inv_ev(inv: Invoice, label: str = "", **kw) -> dict:
    snip = f"{inv.kind or '发票'} {inv.number}｜开票 {inv.date or '—'}｜金额 {C.fmt_yuan(inv.amount)}" + \
           (f"｜{'、'.join(inv.items[:3])}" if inv.items else "") + (f"｜备注：{inv.remark[:40]}" if inv.remark else "")
    return C.ev(inv.file or "单据发票信息", None, snip, label=label or inv.label, **kw)


def form_ev(label: str, value) -> dict:
    return C.ev("报销单表单", None, f"{label}：{value}", label=label)


def att_ev(m, label: str = "") -> dict:
    return C.ev(m.name, None, m.text[:120].replace("\n", " "), label=label or ROLE_LABELS.get(m.role, m.role))


def need_invoices(f):
    c = claim(f)
    if not c.invoices:
        return missing("未取得发票信息（单据未提供发票结构化数据，附件中也未识别出文字版发票）。")
    return None


def consecutive(f, message: str, invoices=None):
    c = claim(f)
    flag = c.flags.get("consecutive")
    if flag not in (None, ""):
        yes = str(flag).strip() in ("是", "Y", "y", "true", "True", "1", "存在")
        return (issue(message, [form_ev("存在连号", flag)], ["表单「存在连号」字段为是"]) if yes else
                ok("通过：表单「存在连号」字段为否。", [form_ev("存在连号", flag)]))
    invs = invoices if invoices is not None else c.invoices
    if not invs:
        return missing("未取得发票号码，无法判断连号。")
    groups = C.consecutive_groups([i.number for i in invs])
    if groups:
        by_no = {re.sub(r"\D", "", i.number): i for i in invs}
        ev = [inv_ev(by_no[n], "连号发票") for g in groups for n in g if n in by_no][:6]
        return issue(message, ev, [f"连号：{'、'.join(g)}" for g in groups])
    return ok(f"通过：{len(invs)} 张发票号码不连续。")


def etype(t: str) -> str | None:
    t = t or ""
    if re.search(r"商务|外事", t):
        return "商务外事"
    if re.search(r"其他公务|公务", t):
        return "其他公务"
    return None


def accompany_limit(kind: str, guests: float, conf: dict) -> tuple[int, str]:
    c = (conf.get("accompany") or {}).get(kind) or {}
    g = int(guests)
    if kind == "商务外事":
        if g <= c.get("small_max_guests", 5):
            return g, f"招待对象 {g} 人（≤{c.get('small_max_guests', 5)} 人可对等陪餐）"
        lim = math.ceil(g * c.get("over_ratio", 0.5))
        return lim, f"招待对象 {g} 人（>{c.get('small_max_guests', 5)} 人，陪餐不超过 1/2，向上取整为 {lim} 人）"
    if g <= c.get("small_max_guests", 10):
        lim = int(c.get("small_max_accompany", 3))
        return lim, f"招待对象 {g} 人（≤{c.get('small_max_guests', 10)} 人，陪餐不超过 {lim} 人）"
    lim = math.ceil(g * c.get("over_ratio", 1 / 3) - 1e-9)
    return lim, f"招待对象 {g} 人（>{c.get('small_max_guests', 10)} 人，陪餐不超过 1/3，向上取整为 {lim} 人）"


def accompany_rule(f, message: str):
    c = claim(f)
    e = c.entertain or {}
    kind = etype(e.get("type"))
    if not e:
        return missing("报销单未填写招待信息（招待类型、招待对象人数、陪餐人数）。")
    if not kind:
        return missing(f"招待类型「{e.get('type') or '未填写'}」无法识别为商务/外事招待或其他公务招待。")
    if e.get("guests") is None or e.get("accompany") is None:
        return missing("报销单未填写招待对象人数或陪餐人数。")
    lim, desc = accompany_limit(kind, e["guests"], cfg(f))
    ev = [form_ev("招待类型", e.get("type")), form_ev("招待对象人数", int(e["guests"])), form_ev("陪餐人数", int(e["accompany"]))]
    if e["accompany"] > lim:
        return issue(message, ev, [f"{e.get('type')}：{desc}，实际陪餐 {int(e['accompany'])} 人，超出 {int(e['accompany'] - lim)} 人"])
    return ok(f"通过：{desc}，陪餐 {int(e['accompany'])} 人未超上限。", ev)


def standard_days_rule(f, message: str):
    t = claim(f).travel or {}
    if t.get("subsidy_days") is None or t.get("days") is None:
        return missing("报销单未填写补助天数（标准天数）或出差天数（行程天数）。")
    ev = [form_ev("补助天数（标准天数）", t["subsidy_days"]), form_ev("出差天数（行程天数）", t["days"])]
    if t["subsidy_days"] >= t["days"]:
        return issue(message, ev, [f"标准天数 {t['subsidy_days']:g} 天，行程天数 {t['days']:g} 天"])
    return ok(f"通过：标准天数 {t['subsidy_days']:g} 天少于行程天数 {t['days']:g} 天。", ev)


def has_entertain(f) -> bool:
    c = claim(f)
    return any("招待" in t for t in c.expense_types()) or "招待" in c.doc_type


def not_applicable(why: str):
    return na(why)
