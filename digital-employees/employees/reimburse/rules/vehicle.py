"""车辆使用费 VEH-01–03（需求 3.4）。按费用项目分流：维修/保养要清单和送修单，租车要审批表和合同。"""
from __future__ import annotations

from core.rules import common as C
from core.rules.engine import issue, missing, na, ok

from ..materials import ROLE_LABELS
from ._util import att_ev, atts, cfg, claim, form_ev, inv_ev, need_invoices

REPAIR = ("车辆修理费", "维修费", "修理费", "保养费")


def _item(f) -> str:
    c = claim(f)
    return (c.vehicle or {}).get("item") or next(iter(c.items_of()), "")


def veh01(f):
    if (r := need_invoices(f)):
        return r
    item = _item(f)
    if not item:
        return missing("报销单未选择费用项目。")
    words = (cfg(f).get("vehicle_items") or {}).get(item)
    if not words:
        return missing(f"费用项目「{item}」未配置对应的发票名称关键词（config/reimburse.yaml vehicle_items）。")
    bad = [i for i in claim(f).invoices if not any(w in " ".join(i.items) for w in words)]
    if bad:
        return issue("发票名称与选择费用项目不匹配，请核实。", [form_ev("费用项目", item)] + [inv_ev(i) for i in bad[:4]],
                     [f"{i.number}：发票名称「{'、'.join(i.items) or '未识别'}」，费用项目「{item}」" for i in bad])
    return ok(f"通过：发票名称与费用项目「{item}」匹配。")


def veh02(f):
    item, plate = _item(f), str((claim(f).vehicle or {}).get("plate") or "")
    need = []
    if any(k in item for k in REPAIR):
        need = ["repair_list", "repair_order"]
    elif plate == "其他":
        need = ["rental_approval", "rental_contract"]
    else:
        return na("费用项目不是维修费、保养费，且车牌号不是「其他」（非租赁车辆）。")
    lacking = [r for r in need if not atts(f, r)]
    if r := [ROLE_LABELS[x] for x in lacking]:
        return issue(f"{'、'.join(r)} 附件未上传，请补充。", [form_ev("费用项目", item), form_ev("车牌号", plate or "—")], r)
    return ok(f"通过：已上传{'、'.join(ROLE_LABELS[x] for x in need)}。")


def veh03(f):
    item = _item(f)
    if not any(k in item for k in REPAIR):
        return na("费用项目不是维修费、保养费。")
    orders = atts(f, "repair_order")
    if not orders:
        return missing("未上传公务用车车辆维修/保养送修单，无法比对预算。")
    a = C.amount_after(orders[0].text, r"(费用预算|预算金额|预算)", 30)
    if not a:
        return missing("送修单中未识别出预算金额。", [att_ev(orders[0])])
    amt = claim(f).amount
    if amt is None:
        return missing("报销单未填写报销金额。")
    ev = [form_ev("报销金额", C.fmt_yuan(amt)), att_ev(orders[0], "送修单")]
    if amt > a.yuan + 0.01:
        return issue("报销金额超预算金额，请核实。", ev, [f"报销 {C.fmt_yuan(amt)}，送修单预算 {C.fmt_yuan(a.yuan)}"])
    return ok(f"通过：报销金额 {C.fmt_yuan(amt)} 未超送修单预算 {C.fmt_yuan(a.yuan)}。", ev)
