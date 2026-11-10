"""多份材料比对：R01–R08、R20、R24、R30。

确定性比对（金额、期限、比例、日期）直接计算；范围、人员、付款、违约责任、实质性条款、联合体分工、技术参数
交给模型比对，并要求双方原文引用（core.rules.semantic.compare）。
"""
from __future__ import annotations

from collections import Counter

from core.rules import semantic
from core.rules.engine import issue, missing, na, ok, review

from ._util import (CONSORTIUM_KW, PAY_KW, PENALTY_KW, PERSON_KW, SCOPE_KW, SUBST_KW, TECH_KW, biz_text,
                    contract_docs, fev, form, form_ev, has, is_yes, judge_of, money, needs_contract, no_award, non_bid,
                    pcts, window)


def _ledger_award_price(f):
    bid = (f.get("ledgers") or {}).get("bid_quote") or {}
    if bid.get("available") and bid.get("award_price_yuan"):
        return {"value": bid["award_price_yuan"], "file": f"{bid.get('workflow_name') or '投标及报价审批流程'} {bid.get('request_id')}",
                "snippet": f"中标价格（万元）：{bid['fields'].get('中标价格（万元）')}"}
    return None


@needs_contract
def r01(f):
    p, a = f.get("price"), f.get("award_price") or _ledger_award_price(f)
    if no_award(f):
        return na("表单注明无中标通知书。")
    if not f.get("awards") and not a:
        return missing("未提供中标通知书（成交通知书），无法比对中标价；如本合同非招标项目，可忽略本条。")
    if not p:
        return missing("未在合同正文中识别出合同价款。", [fev(a, "中标价")] if a else [])
    if not a:
        return missing("未在中标通知书中识别出中标价。", [fev(p, "合同价款")])
    ev = [fev(p, "合同价款"), fev(a, "中标价")]
    if abs(p["value"] - a["value"]) > 0.01:
        return issue(f"合同约定价款为 {money(p['value'])}、中标通知书中标价为 {money(a['value'])}，数据不一致。", ev)
    return ok(f"无异常：合同价款与中标价均为 {money(p['value'])}。", ev)


GUIDANCE = {
    "R02": "只有合同工作范围小于投标承诺的范围（删减、排除了投标承诺的工作项），或合同新增了投标文件未包含的工程/服务项目，"
           "才判为不一致；一方表述更具体、一方更笼统，或只是引用的标准规范写法不同，不算不一致。",
    "R08": "只比较双方对同一事项的约定：履行地点对履行地点、交付方式对交付方式、质量标准对质量标准；"
           "一方有约定而另一方未涉及该事项的，不列为差异。",
}


def _sem(f, rule: str, focus: str, a_label: str, a_mats, b_label: str, b_mats, kw: str, issue_msg: str,
         pass_msg: str, missing_b: str):
    a, b = window(a_mats, kw), window(b_mats, kw)
    if not b_mats and non_bid(f):
        return na(f"表单注明投标方式为非投标，无{b_label}可比。")
    if not b_mats:
        return missing(missing_b)
    if not a:
        return missing(f"{a_label}中未找到与「{focus}」相关的条款。")
    if not b:
        return missing(f"{b_label}中未找到与「{focus}」相关的内容。")
    return semantic.compare(judge_of(f), f"contract.{rule}", focus, {"label": a_label, **a}, {"label": b_label, **b},
                            issue_msg, pass_msg, GUIDANCE.get(rule, ""))


@needs_contract
def r02(f):
    return _sem(f, "R02", "工作范围/服务范围（项目对象、工作项、服务边界、排除项、新增项）",
                "合同", contract_docs(f) + f.get("tech_docs", []), "投标文件", f.get("bids"), SCOPE_KW,
                "合同约定的工作范围与投标文件承诺的工作范围不一致，存在实质性变更风险。",
                "无异常：合同工作范围与投标文件承诺一致。", "未提供投标文件，无法比对工作范围。")


@needs_contract
def r03(f):
    c = f.get("duration")
    base, label = (f.get("bid_duration"), "投标文件") if f.get("bid_duration") else (f.get("award_duration"), "中标通知书")
    if not f.get("bids") and not f.get("awards"):
        if non_bid(f) or no_award(f):
            return na("非投标项目且无中标通知书，无工期承诺可比。")
        return missing("未提供投标文件或中标通知书，无法比对工期/服务期限。")
    if not c or not base:
        hits = [fev(h, "合同·工期表述") for h in f.get("duration_hits") or []] + \
               [fev(h, "投标文件·工期表述") for h in f.get("bid_duration_hits") or []]
        if c:
            hits.insert(0, fev(c, "合同工期"))
        if base:
            hits.insert(0, fev(base, f"{label}工期"))
        if hits:
            return review("工期/服务期限为相对时间描述（如「完工后若干天」「收到通知后若干天」）或只在一方给出天数，"
                          "无法直接换算比对，请人工核对。", hits)
        return missing("未在合同或投标文件中识别出工期/服务期限。")
    ev = [fev(c, "合同工期"), fev(base, f"{label}工期")]
    if c["unit"] == base["unit"] and abs(c["value"] - base["value"]) < 0.5:
        return ok(f"无异常：合同工期与{label}一致（{c['raw']}）。", ev)
    if c.get("approx") or base.get("approx"):
        if abs(c["value"] - base["value"]) < 0.5:
            return ok(f"无异常：合同工期（{c['raw']}）与{label}（{base['raw']}）折算后一致。", ev)
        return review(f"合同工期（{c['raw']}）与{label}（{base['raw']}）单位不同、折算后不一致，请人工核对。", ev)
    return issue(f"合同约定工期（{c['raw']}）与{label}承诺工期（{base['raw']}）不一致，存在实质性变更风险。", ev)


@needs_contract
def r04(f):
    return _sem(f, "R04", "项目负责人及主要履约人员名单（姓名与岗位）", "合同", contract_docs(f), "投标文件",
                f.get("bids"), PERSON_KW, "合同约定的履约人员名单与投标文件载明的人员名单不一致。",
                "无异常：合同履约人员与投标文件一致。", "未提供投标文件，无法比对履约人员名单。")


@needs_contract
def r05(f):
    pc, pb = f.get("payment_contract"), f.get("payment_bid")
    out = _sem(f, "R05", "付款节点、付款条件及各节点付款比例", "合同", contract_docs(f), "投标文件", f.get("bids"), PAY_KW,
               "合同付款节点/比例与投标文件不一致，存在背离中标合同实质性内容的风险。",
               "无异常：合同付款节点及比例与投标文件一致。", "未提供投标文件，无法比对付款节点。")
    if pc and pb:
        out.message += f" 识别到的付款比例：合同 {pcts(pc['value'])}；投标文件 {pcts(pb['value'])}。"
    return out


def _is_consortium(f) -> bool:
    v = form(f, "是否联合体")
    amount = form(f, "联合体中标合同额")
    return is_yes(v) or (amount not in ("", "0", "0.00", "无", "/")) or bool(f.get("consortium_docs")) \
        or (has(r"总承包|EPC", biz_text(f)) and "联合体" in (f["contract"].text if f.get("contract") else ""))


@needs_contract
def r06(f):
    if not _is_consortium(f):
        return na("非联合体项目。")
    docs = f.get("consortium_docs") or []
    division = [m for m in docs if has(r"分工", m.name)] or [m for m in docs if not has(r"标前", m.name)]
    pre = [m for m in docs if has(r"标前", m.name)]
    ledger_pre = ((f.get("ledgers") or {}).get("bid_quote") or {}).get("consortium_text")
    sources = []
    if division:
        w = window(division, CONSORTIUM_KW)
        if w:
            sources.append({"label": "联合体分工协议", **w})
    cw = window([f["contract"]], CONSORTIUM_KW)
    if cw:
        sources.append({"label": "合同", **cw})
    if pre:
        w = window(pre, CONSORTIUM_KW)
        if w:
            sources.append({"label": "标前联合体协议", **w})
    elif ledger_pre:
        sources.append({"label": "标前联合体协议（投标报价台账）", "text": ledger_pre[:3000], "file": "投标报价台账"})
    absent = [x for x in ("联合体分工协议", "合同", "标前联合体协议") if not any(s["label"].startswith(x) for s in sources)]
    if len(sources) < 2:
        return missing(f"可比较的联合体分工内容不足两份，缺少{'、'.join(absent)}。")
    results = []
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            results.append(semantic.compare(
                judge_of(f), "contract.R06", "联合体各方工作范围及安全、环保、质量责任边界", sources[i], sources[j],
                f"合同约定的联合体分工与{sources[j]['label']}不一致。" if sources[i]["label"] == "合同"
                else f"{sources[i]['label']}与{sources[j]['label']}的联合体分工不一致。", "一致"))
    bad = [r for r in results if r.code == "issue"]
    note = f"（缺少{'、'.join(absent)}）" if absent else ""
    if bad:
        return issue("；".join(r.message for r in bad) + note, [e for r in bad for e in r.evidence][:8],
                     [i for r in bad for i in r.items], llm=True)
    if any(r.code != "pass" for r in results):
        r = next(r for r in results if r.code != "pass")
        return review(r.message + note, r.evidence, llm=True)
    return ok(f"无异常：{'、'.join(s['label'] for s in sources)}的联合体分工一致{note}。",
              [e for r in results for e in r.evidence][:4], llm=True)


def _tenders(f) -> list:
    return f.get("tenders") or []


def _tender_sem(f, rule, focus, kw, issue_msg, pass_msg, missing_msg):
    if not _tenders(f) and non_bid(f):
        return na("表单注明投标方式为非投标，无招标文件可比。")
    return _sem(f, rule, focus, "合同", contract_docs(f), "招标文件", _tenders(f), kw, issue_msg, pass_msg, missing_msg)


def _tender_missing(f, what: str) -> str:
    bid = (f.get("ledgers") or {}).get("bid_quote") or {}
    why = bid.get("reason") or "台账对应投标流程的【附件】中未识别出招标文件"
    return f"未取得招标文件（{why}），无法比对{what}。"


@needs_contract
def r07(f):
    return _tender_sem(f, "R07", "违约责任（违约情形、责任主体、责任方式、违约金/赔偿计算方式、上限及免责条件）", PENALTY_KW,
                       "合同存在对中标合同约定违约责任的变更。", "无异常：合同违约责任与招标文件一致。",
                       _tender_missing(f, "违约责任"))


@needs_contract
def r08(f):
    return _tender_sem(f, "R08", "履行地点、履行方式、服务质量要求、服务标准", SUBST_KW,
                       "合同与招标文件在履行地点、履行方式、质量要求或服务标准上存在描述不一致。",
                       "无异常：履行地点、方式、质量要求与服务标准与招标文件一致。", _tender_missing(f, "实质性条款"))


@needs_contract
def r20(f):
    pf, pc = f.get("payment_form"), f.get("payment_contract")
    if not pf:
        return missing("审批表单未填写项目阶段及付款节点明细。")
    if not pf["value"]:
        return issue("审批表单的项目阶段及付款节点明细未写明各节点付款比例。", [form_ev(f, "付款节点明细")])
    if not pc:
        return review("未从合同付款条款中识别出付款比例，请人工核对表单填写。", [form_ev(f, "付款节点明细")])
    ev = [form_ev(f, "付款节点明细"), fev(pc, "合同付款条款")]
    fc, cc = Counter(pf["value"]), Counter(pc["value"])
    if fc == cc:
        return ok(f"无异常：表单付款节点比例与合同一致（{pcts(pf['value'])}）。", ev)
    items = [f"合同付款比例：{pcts(pc['value'])}；表单填写：{pcts(pf['value'])}"]
    if cc - fc:
        items.append(f"合同有而表单未填写的比例：{pcts(sorted((cc - fc).elements()))}")
    if fc - cc:
        items.append(f"表单有而合同未约定的比例：{pcts(sorted((fc - cc).elements()))}")
    if abs(sum(pf["value"]) - 100) > 0.01 and not pc.get("cumulative"):
        items.append(f"表单比例合计为 {sum(pf['value']):g}%")
    return issue("未按照合同约定填写项目阶段及付款节点明细，若同一阶段分为不同付款节点，可分列并写明该节点付款比例。", ev, items)


@needs_contract
def r24(f):
    award = f.get("award_date") or ((f.get("ledgers") or {}).get("bid_quote") or {}).get("award_date")
    sign = f.get("sign_date") or f.get("sign_date_form")
    if not award and no_award(f):
        return na("表单注明无中标通知书。")
    if not award:
        return missing("缺少中标通知书发出日期（投标报价台账未显示该字段，且未在中标通知书中识别到），不比对。")
    if not sign:
        return missing("未识别出合同签订日期。", [fev(award, "中标通知书发出日期")])
    days = (sign["value"] - award["value"]).days
    limit = int((f.get("cfg") or {}).get("award_sign_days", 30))
    note = "（发出日期取自中标通知书落款日期）" if award.get("approx") else ""
    ev = [fev(award, "中标通知书发出日期"), fev(sign, "合同签订日期")]
    if days > limit:
        return issue(f"合同签订时间（{sign['value']}）超过中标通知书发出之日（{award['value']}）起 {limit} 日（相差 {days} 日），"
                     f"请予以说明。{note}", ev)
    if days < 0:
        return review(f"合同签订日期（{sign['value']}）早于中标通知书发出日期（{award['value']}），请人工核对。{note}", ev)
    return ok(f"无异常：合同于中标通知书发出后第 {days} 日签订，未超过 {limit} 日。{note}", ev)


@needs_contract
def r30(f):
    has_flag = is_yes(form(f, "是否含技术协议"))
    tech = f.get("tech_docs") or []
    if not has_flag and not tech:
        return na("表单未勾选含技术协议，且未上传技术协议。")
    if not tech:
        return missing("表单显示含技术协议，但未找到技术协议附件。", [form_ev(f, "是否含技术协议")])
    base_mats = (f.get("bids") or []) + contract_docs(f)
    base = window(base_mats, TECH_KW)
    t = window(tech, TECH_KW)
    if not t:
        return missing("技术协议中未识别出技术参数、供货范围或接口等内容。")
    if not base:
        return missing("主合同和投标文件中没有可比较的技术参数，无法比对。")
    return semantic.compare(judge_of(f), "contract.R30", "技术参数、供货范围、接口等技术要求",
                            {"label": "技术协议", **t}, {"label": "主合同/投标文件", **base},
                            "技术参数与主合同/投标文件不一致，请补充偏差说明或修正。",
                            "无异常：技术协议参数与主合同/投标文件一致。")
