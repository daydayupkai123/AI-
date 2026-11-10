"""会议费 MTG-01–03（需求 3.6）。核实会议是否真实召开、参会人员是谁；附件读取不完整不猜测。"""
from __future__ import annotations

import re

from core.rules import common as C
from core.rules.engine import issue, missing, ok, review

from ._util import att_ev, claim, form_ev

NAME_SEP = r"[、，,；;\s]"


def _docs(f):
    return [m for m in f.get("materials") or [] if not m.is_archive]


def mtg01(f):
    docs = _docs(f)
    unreadable = [m.name for m in docs if not m.readable]
    hits = [m for m in docs if m.readable and re.search(r"公文流转|会议的?通知|关于.{1,40}会议的请示|内请报告", m.name + m.text[:2000])]
    if hits:
        return ok(f"通过：已提供 {'、'.join(m.name for m in hits)}。", [att_ev(m) for m in hits[:3]])
    if unreadable:
        return review(f"附件无法识别，请人工核对是否包含会议通知、公文流转单或内请报告：{'、'.join(unreadable)}。")
    names = [m.name for m in docs]
    return issue("附件缺少会议通知、公文流转单或内请报告（三者至少提供其一），请核实。",
                 [C.ev("附件清单", None, "、".join(names) or "无附件", label=f"已查验附件 {len(names)} 份")],
                 [f"已查验：{'、'.join(names) or '无附件'}"])


def attendees(text: str) -> set[str]:
    names = set()
    for m in re.finditer(r"(参会人员|参加人员|与会人员|参会名单|参会人|安排)[^：:\n]{0,10}[:：]?\s*([^\n。]{2,200})", text):
        for part in re.split(NAME_SEP, m.group(2)):
            part = re.sub(r"(同志|等\d*人|参会|参加|等)$", "", part.strip())
            if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", part):
                names.add(part)
    return names


def _approval_docs(f):
    return [m for m in _docs(f) if m.readable and re.search(r"公文流转|内请|请示", m.name + m.text[:300])]


def mtg02(f):
    docs = _approval_docs(f)
    if not docs:
        return missing("未找到公文流转单或内请报告，无法核对参会人员名单。")
    found = {m.name: attendees(m.text) for m in docs}
    if any(found.values()):
        names = sorted(set().union(*found.values()))
        return ok(f"通过：审批件中列明参会人员 {len(names)} 人（{'、'.join(names[:8])}）。", [att_ev(m) for m in docs[:2]])
    return issue("公文流转单、内请报告缺少参会人员名单，请核实。", [att_ev(m) for m in docs[:2]])


def mtg03(f):
    persons = sorted({str(x.get("person")).strip() for x in claim(f).expenses if x.get("person")})
    if not persons:
        return missing("报销单未填写会议费用明细的费用人。")
    docs = _approval_docs(f)
    names = set().union(*[attendees(m.text) for m in docs]) if docs else set()
    if not names:
        return missing("审批件中未识别出参会人员，无法比对费用人。", [form_ev("费用人", "、".join(persons))])
    absent = [p for p in persons if p not in names]
    ev = [form_ev("费用人", "、".join(persons))] + [att_ev(m) for m in docs[:2]]
    if absent:
        return issue("【公文流转单】或【内请报告】中参会人与表单中费用人不一致，请核实。", ev,
                     [f"费用人「{p}」不在参会人员名单中" for p in absent])
    return ok(f"通过：费用人（{'、'.join(persons)}）均在参会人员名单中。", ev)
