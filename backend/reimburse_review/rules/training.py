"""培训费 TRN-01（需求 3.7）。报销单与发票的商品名称必须都是指定写法，精确匹配。"""
from __future__ import annotations

from shared.rule_framework.engine import issue, missing, ok

from ._util import cfg, claim, form_ev, inv_ev, need_invoices


def _norm(s: str) -> str:
    return (s or "").replace(" ", "").replace("＊", "*")


def trn01(f):
    want = _norm(cfg(f).get("training_item_name") or "生产生活费服务*培训费")
    c = claim(f)
    form_names = [str(x.get("name") or "") for x in c.expenses if x.get("name")]
    if not form_names:
        return missing("报销单未填写培训费用明细的商品名称。")
    if (r := need_invoices(f)):
        return r
    inv_names = [x for i in c.invoices for x in i.items]
    bad = [f"报销单商品名称「{n}」" for n in form_names if _norm(n).strip("*") != want.strip("*")]
    bad += [f"发票商品名称「{n}」" for n in inv_names if _norm(n).strip("*") != want.strip("*")]
    if not inv_names:
        bad.append("发票未识别出商品名称")
    if bad:
        return issue(f"报销单商品名称与发票商品名称不一致，或名称不是“{want}”，请核实。",
                     [form_ev("商品名称", "、".join(form_names))] + [inv_ev(i) for i in c.invoices[:3]], bad)
    return ok(f"通过：报销单与发票商品名称均为“{want}”。")
