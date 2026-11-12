"""02 会议类型：表单所选会议类型 vs 请示正文提请的会议 vs 已核实条款的决策主体；兼顾「三重一大」属性。

不因某个词语命中就直接判定：条款未核实时只提示复核，不下结论（需求 4.1）。
"""
from __future__ import annotations

from shared.rule_framework import common as C
from shared.rule_framework.engine import issue, missing, ok, review

from .basis import clause_ev


def check(f):
    raw = ((f.get("form") or {}).get("会议类型") or {}).get("value")
    fm = f.get("meeting")
    if not raw:
        return missing("待补充：OA 表单未填写会议类型。")
    form_ev = C.ev("OA 表单", None, f"会议类型：{raw}", label="会议类型")
    if not fm:
        return review(f"待人工复核：表单会议类型「{raw}」无法识别为党委会、董事会、总经理办公会、专题会或不上会。", [form_ev])
    problems, notes, ev, checked = [], [], [form_ev], []
    bm = f.get("body_meeting")
    if bm and bm.get("value"):
        ev.append(C.ev(bm["file"], bm.get("page"), bm["snippet"], label="请示正文"))
        checked.append("请示正文")
        if bm["value"] != fm:
            problems.append(f"请示正文提请「{bm['value']}」审议，与表单所选会议类型「{fm}」不一致")
    elif f.get("body"):
        notes.append("请示正文未写明提请哪个会议审议")
    res = f.get("resolution") or {}
    c = res.get("matched")
    if c and c.meetings:
        ev.append(clause_ev(c, "已核实条款"))
        checked.append("制度条款")
        if fm not in c.meetings:
            problems.append(f"按已核实条款（《{c.doc_name}》{c.ref}{('，档位' + c.tier) if c.tier else ''}），本事项由"
                            f"{'、'.join(c.final)}审批/决策（{'、'.join(c.meetings)}），与表单所选「{fm}」不一致")
        if c.major == "是" and fm == "不上会（签批）":
            problems.append("该事项在权责手册中标为“三重一大”事项，应履行集体决策程序，表单却选择不上会")
    else:
        notes.append("审批/上会依据未能核实到具体条款与档位（见 03），会议类型与制度条款的一致性需人工确认")
    if problems:
        return issue(f"发现问题：表单会议类型为「{fm}」，" + f"存在 {len(problems)} 处不一致。", ev, problems + notes)
    if not checked:
        return review(f"待人工复核：表单会议类型为「{fm}」，" + "；".join(notes) + "。", ev, notes)
    if notes:
        return review(f"待人工复核：表单会议类型「{fm}」与{'、'.join(checked)}一致，但" + "；".join(notes) + "。", ev, notes)
    return ok(f"核查通过：表单会议类型「{fm}」与{'、'.join(checked)}一致。", ev)
