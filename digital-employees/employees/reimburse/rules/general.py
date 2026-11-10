"""通用报销单 GEN-01–06（需求 3.8）。按费用项目再分流：邮递费、房屋租赁费、车辆租赁费、修理费。"""
from __future__ import annotations

from core.rules import common as C
from core.rules.engine import issue, missing, na, ok, review

from ..materials import ROLE_LABELS, signature_state
from ._util import att_ev, atts, cfg, claim, form_ev

SEAL_RATIO = 0.002


def _items(f) -> set[str]:
    return claim(f).items_of()


def _amount_of(f, *names) -> float | None:
    vals = [x["amount"] for x in claim(f).expenses if x.get("item") in names and x.get("amount") is not None]
    return sum(vals) if vals else claim(f).amount


def _is_public(f) -> bool:
    return "对公" in claim(f).doc_type


def gen01(f):
    c = claim(f)
    if "邮递费" not in _items(f) or c.dept != "综合管理部" or not _is_public(f):
        return na("非综合管理部使用对公报销单报销邮递费。")
    docs = atts(f, "courier_split")
    if not docs:
        return issue("未上传“快递费结算分摊表”或签字不全，请核实。", [form_ev("申请人主职部门", c.dept)], ["未上传快递费结算分摊表"])
    state, empty = signature_state(docs[0])
    if state == "missing":
        return issue("未上传“快递费结算分摊表”或签字不全，请核实。", [att_ev(docs[0])], [f"签字栏未签：{'、'.join(empty)}"])
    if state == "unknown":
        return review("已上传快递费结算分摊表，签字是否齐全无法自动识别（扫描件/无签字栏），请人工核对。", [att_ev(docs[0])])
    return ok("通过：已上传快递费结算分摊表，签字栏均已签署。", [att_ev(docs[0])])


def gen02(f):
    c = claim(f)
    if "邮递费" not in _items(f) or (c.dept == "综合管理部" and _is_public(f)):
        return na("非「非综合管理部或对私报销单」的邮递费报销。")
    docs = atts(f, "waybill")
    if not docs:
        return issue("附件缺少“运单明细”等文件，请核实。", [form_ev("费用项目", "邮递费")])
    a = C.amount_after(docs[0].text, r"(合计|总计|总金额)", 30)
    amt = _amount_of(f, "邮递费")
    if not a or amt is None:
        return missing("运单明细或报销单中未识别出合计金额，无法比对。", [att_ev(docs[0])])
    if abs(a.yuan - amt) > 0.01:
        return issue("运单明细合计数与报销金额不一致，请核实。", [att_ev(docs[0]), form_ev("邮递费报销金额", C.fmt_yuan(amt))],
                     [f"运单明细合计 {C.fmt_yuan(a.yuan)}，报销金额 {C.fmt_yuan(amt)}"])
    return ok(f"通过：运单明细合计与报销金额一致（{C.fmt_yuan(amt)}）。", [att_ev(docs[0])])


def gen03(f):
    if "房屋及建筑物租赁费" not in _items(f):
        return na("费用项目不是房屋及建筑物租赁费。")
    lacking = [ROLE_LABELS[r] for r in ("internal_request", "house_lease") if not atts(f, r)]
    if lacking:
        return issue("附件缺少“内请报告”和“租房协议”，请核实。", [form_ev("费用项目", "房屋及建筑物租赁费")],
                     [f"缺少{x}" for x in lacking])
    return ok("通过：已上传内请报告和租房协议。")


def gen04(f):
    if "车辆租赁费" not in _items(f):
        return na("费用项目不是车辆租赁费。")
    rule = (cfg(f).get("rules") or {}).get("GEN-04") or {}
    if not atts(f, "car_application"):
        return issue("附件缺少“租车申请”和“租车协议”，请核实。", [form_ev("费用项目", "车辆租赁费")],
                     ["缺少租车申请（长期、临时租车均须提供）"])
    if rule.get("threshold_pending", True):
        return review(f"已上传租车申请。{rule.get('reason') or '长期/临时租车分界未确定，租车协议是否必需请人工判断。'}",
                      [att_ev(atts(f, 'car_application')[0])])
    return ok("通过：已上传租车申请。")


def _repair_docs(f):
    return atts(f, "repair_list")


def gen05(f):
    if "修理费" not in _items(f):
        return na("费用项目不是修理费。")
    docs = _repair_docs(f)
    if not docs:
        return issue("附件缺少维修清单，维修清单未盖章，请核实。", [form_ev("费用项目", "修理费")], ["未上传维修清单"])
    ratio = (f.get("seals") or {}).get(docs[0].name)
    if ratio is None:
        return review("已上传维修清单，文件格式无法判断是否加盖公章，请人工核对。", [att_ev(docs[0])])
    if ratio < SEAL_RATIO:
        return issue("附件缺少维修清单，维修清单未盖章，请核实。", [att_ev(docs[0])], [f"维修清单未检测到红色印章（红色占比 {ratio:.4f}）"])
    return ok("通过：已上传维修清单，并检测到印章。", [att_ev(docs[0])])


def gen06(f):
    if "修理费" not in _items(f):
        return na("费用项目不是修理费。")
    docs = _repair_docs(f)
    if not docs:
        return na("未上传维修清单（见 GEN-05）。")
    a = C.amount_after(docs[0].text, r"(合计|总计|总金额|结算金额)", 30)
    amt = _amount_of(f, "修理费")
    if not a or amt is None:
        return missing("维修清单或报销单中未识别出合计金额。", [att_ev(docs[0])])
    if abs(a.yuan - amt) > 0.01:
        return issue("附件上传的“维修清单”合计数与报销金额不一致，请核实。", [att_ev(docs[0]), form_ev("修理费报销金额", C.fmt_yuan(amt))],
                     [f"维修清单合计 {C.fmt_yuan(a.yuan)}，报销金额 {C.fmt_yuan(amt)}"])
    return ok(f"通过：维修清单合计与报销金额一致（{C.fmt_yuan(amt)}）。", [att_ev(docs[0])])
