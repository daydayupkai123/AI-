"""03 审批/上会依据：拆解人工填写的依据 → 制度条款定位 → 事项与阶段 → 金额档位 → 审批动作与最终主体。

resolve() 在「制度检索」节点执行一次，结果供 02 会议类型共用。
输出示例（需求 6.2）：
  核查通过：本次事项及XX万元金额符合已核实条款规定，由总经理办公会审批。
  发现问题：金额满足该档位，但该条款适用事项与本次采购结果阶段不一致，建议核实条款适用范围。
  待人工复核：未能定位所引用条款，暂不能确认审批依据及审批主体。
  发现问题：制度条款规定的审批主体与表单所选会议类型不一致，请核实。
"""
from __future__ import annotations

import re

from shared.regulation_kb.base import RegulationBase
from shared.regulation_kb.regulations import Clause, describe_range, in_range, meeting_of
from shared.rule_framework import common as C
from shared.rule_framework.engine import issue, missing, ok, review
from shared.rule_framework.semantic import quote_found

from .. import prompts
from ..extract import stage_of


def clause_ev(c: Clause, label: str = "制度条款") -> dict:
    return C.ev(c.doc_name, c.page, c.describe(), label=label, ref=c.ref)


def quoted_item(basis: str) -> str | None:
    """依据中以引号摘录的事项名称（引号内第一个逗号前），如 “信息化数字化项目建设/…（含软件），5万元…” → 事项名称。"""
    m = re.search(r"[“\"「『]([^”\"」』]{4,160})[”\"」』]", basis or "")
    if not m:
        return None
    item = re.split(r"[，,；;。]", m.group(1))[0].strip()
    return item if len(item) >= 4 else None


def _norm(s: str) -> str:
    return re.sub(r"[\s（）()·\-—/、，,。]", "", s or "")


def item_matches(item: str, c: Clause) -> bool:
    """事项名称（或其以「/」「、」分隔的任一部分）与条款标题互相包含或高度相似。"""
    parts = [p for p in re.split(r"[/、]", item) if len(_norm(p)) >= 4] or [item]
    title = _norm(c.title + c.sub)
    return any(_norm(p) in title or (len(title) >= 4 and title in _norm(p)) or C.ratio(_norm(p), _norm(c.title)) >= 0.85
               for p in parts)


def match_item(kb: RegulationBase, doc_id: str, item: str, amount: dict | None = None) -> set[tuple]:
    """按事项名称在指定制度中定位，返回 {(部门, 项号)}；同名事项按金额拆成多项时（如 20 万以上 / 以下各一项）按金额收窄。"""
    hits = [c for c in kb.lookup(doc_id) if item_matches(item, c)]
    groups = {(c.dept, c.no) for c in hits}
    if len(groups) > 1 and amount:
        fit = {(c.dept, c.no) for c in hits if c.range and in_range(c.range, amount["value"])}
        groups = fit or groups
    return groups


def _rank(kb: RegulationBase, cands: list[Clause], amount: dict | None) -> list[Clause]:
    """候选条款换成金额所落档位的同项条款，并把金额落在档位内的排前面。"""
    if not amount:
        return cands
    out = []
    for c in cands:
        fit = [s for s in kb.lookup(c.doc_id, c.dept, c.no) if s.range and in_range(s.range, amount["value"])]
        out.append(fit[0] if fit else c)
    return sorted(out, key=lambda c: 0 if c.range and in_range(c.range, amount["value"]) else 1)


def resolve(facts: dict, kb: RegulationBase) -> dict:
    basis = facts.get("basis") or ""
    parts = facts.get("basis_parts") or {}
    res: dict = {"status": "", "refs": parts.get("refs") or [], "tiers": [], "matched": None, "candidates": [],
                 "amount": facts.get("case_amount"), "docs": kb.documents(), "quoted_item": quoted_item(basis)}
    if not basis:
        res["status"] = "no_basis"
        return res
    enabled = {d["id"] for d in kb.documents() if d["state"] == "enabled"}
    refs = [r for r in res["refs"] if r["doc_id"] in enabled]
    query = (facts.get("title_core") or "") + " " + basis
    if not refs:
        res["status"] = "no_doc" if not res["refs"] else "doc_disabled"
        res["candidates"] = _rank(kb, [c for _, c in kb.search(query, 8)], res["amount"])[:5]
        return res
    ref = next((r for r in refs if r["no"]), refs[0])
    res["ref"] = ref
    item = res["quoted_item"]
    if not ref["no"] and item:
        groups = match_item(kb, ref["doc_id"], item, res["amount"])
        if len(groups) == 1:
            dept, no = next(iter(groups))
            ref = res["ref"] = dict(ref, dept=dept, no=no, by_name=True)
        elif groups:
            res["status"] = "ambiguous_item"
            hits = [c for g in groups for c in kb.lookup(ref["doc_id"], *g)]
            res["candidates"] = _rank(kb, hits, res["amount"])[:8]
            return res
    if not ref["no"]:
        res["status"] = "no_item"
        res["candidates"] = _rank(kb, [c for _, c in kb.search(query, 8, [ref["doc_id"]])], res["amount"])[:5]
        return res
    clauses = kb.lookup(ref["doc_id"], ref.get("dept"), ref["no"])
    if item and clauses and not ref.get("by_name") and not any(item_matches(item, c) for c in clauses):
        # 依据写的项号与摘录的事项名称对不上（常见于引用旧版编号）：事项名称能唯一定位时以名称为准，并报项号有误
        groups = match_item(kb, ref["doc_id"], item, res["amount"])
        if len(groups) == 1:
            dept, no = next(iter(groups))
            res["number_mismatch"] = {"cited": f"{ref.get('dept') or ''}第{ref['no']}项", "cited_title": clauses[0].title,
                                      "actual": f"{dept}第{no}项", "item": item}
            ref = res["ref"] = dict(ref, dept=dept, no=no, by_name=True)
            clauses = kb.lookup(ref["doc_id"], dept, no)
    if ref["doc_id"] == "authority_manual" and not ref.get("dept"):
        depts = {c.dept for c in clauses}
        if len(depts) > 1:
            res["status"] = "ambiguous_dept"
            res["candidates"] = clauses[:8]
            return res
    if not clauses:
        res["status"] = "not_found"
        res["candidates"] = [c for _, c in kb.search(query, 5, [ref["doc_id"]])]
        return res
    tiers, seen = [], set()
    for c in clauses:
        key = (c.tier, c.sub, tuple(c.final))
        if key not in seen:
            seen.add(key)
            tiers.append(c)
    res["tiers"] = tiers
    ranged = [c for c in tiers if c.range]
    amount = res["amount"]
    if len(tiers) == 1 and not ranged:
        res.update(status="matched", matched=tiers[0])
    elif not ranged:
        res.update(status="multi_tier_unranged")
    elif amount is None:
        res.update(status="no_amount")
    else:
        hit = [c for c in ranged if in_range(c.range, amount["value"])]
        finals = {tuple(c.meetings) for c in hit}
        if hit and len(finals) == 1:
            res.update(status="matched", matched=hit[0])
        elif hit:
            res.update(status="ambiguous_tier", candidates=hit)
        else:
            res.update(status="no_tier")
    return res


def check(f):
    res = f.get("resolution") or {}
    basis = f.get("basis")
    st = res.get("status")
    form_ev = C.ev("OA 表单", None, f"审批/上会依据：{basis}", label="审批/上会依据") if basis else {}
    cands = res.get("candidates") or []
    cand_items = [f"可能相关：{c.describe()}" for c in cands[:3]]
    if st == "no_basis":
        return missing("待补充：OA 表单未填写审批/上会依据。")
    if st in ("no_doc", "doc_disabled"):
        return review("待人工复核：未能从审批/上会依据中识别出已启用的制度文件，暂不能确认审批依据及审批主体。",
                      [form_ev] + [clause_ev(c, "检索候选") for c in cands[:3]], cand_items)
    if st in ("no_item", "ambiguous_item"):
        doc = next((d["name"] for d in res.get("docs") or [] if d["id"] == res["ref"]["doc_id"]), res["ref"]["doc_id"])
        item = res.get("quoted_item")
        if st == "ambiguous_item":
            why = f"依据摘录的事项「{item}」在《{doc}》中对应多项条款，且依据未写明事项编号"
        elif item:
            why = f"依据摘录的事项「{item}」在已启用的《{doc}》中未找到（可能引用了旧版制度条款）"
        else:
            why = f"依据引用了《{doc}》，但未写明事项编号/条款号，也未摘录事项名称"
        return review(f"待人工复核：{why}，暂不能确认审批主体。",
                      [form_ev] + [clause_ev(c, "检索候选") for c in cands[:3]], cand_items)
    if st == "ambiguous_dept":
        return review(f"待人工复核：权责手册第{res['ref']['no']}项在多个部门下都存在，依据未写明部门。",
                      [form_ev] + [clause_ev(c, "同号条款") for c in cands[:4]])
    if st == "not_found":
        r = res["ref"]
        return review(f"待人工复核：未能定位所引用条款（{r['raw']}），暂不能确认审批依据及审批主体。",
                      [form_ev] + [clause_ev(c, "检索候选") for c in cands[:3]], cand_items)
    tiers = res.get("tiers") or []
    tier_items = [f"{c.tier or '（不分档）'}：{('、'.join(c.final) or '未识别')}" for c in tiers[:6]]
    nm = res.get("number_mismatch")
    nm_text = (f"依据写明{nm['cited']}，但所摘录事项「{nm['item']}」在现行制度中为{nm['actual']}"
               f"（{nm['cited']}为「{nm['cited_title']}」），条款号引用有误，以下按{nm['actual']}核验") if nm else ""
    if nm_text:
        tier_items.insert(0, nm_text)
    amount = res.get("amount")
    amount_txt = C.fmt_wan(amount["value"]) if amount else "—"
    if st == "no_amount":
        return missing("待补充：所引用条款按金额分档，但请示正文未写明可用于判定档位的金额，无法核验档位与审批主体。",
                       [form_ev] + [clause_ev(c) for c in tiers[:4]], tier_items)
    if st in ("no_tier", "multi_tier_unranged", "ambiguous_tier"):
        why = {"no_tier": f"金额 {amount_txt} 未落入条款列明的任何档位（或档位边界在原文中不明确）",
               "multi_tier_unranged": "条款分为多个非金额档位，需人工确认本次事项适用哪一档",
               "ambiguous_tier": f"金额 {amount_txt} 同时落入多个档位且审批主体不同"}[st]
        return review(f"待人工复核：{why}。", [form_ev] + [clause_ev(c) for c in tiers[:4]], tier_items)

    c: Clause = res["matched"]
    problems, notes = ([nm_text] if nm_text else []), []
    ev = [form_ev, clause_ev(c, "已核实条款")]
    if amount:
        ev.append(C.ev(amount.get("file", ""), amount.get("page"), amount.get("snippet", ""), label="请示金额"))
    # 事项与阶段
    body_stage, clause_stage = f.get("stage"), stage_of(c.title + c.sub)
    if body_stage and clause_stage and body_stage != clause_stage:
        problems.append(f"该条款适用事项为「{c.title}」（{clause_stage}阶段），与本次{body_stage}阶段不一致，建议核实条款适用范围")
    elif f.get("body") and not (body_stage and clause_stage):
        res_scope = f["_judge"]("meeting.N03.scope", prompts.SCOPE,
                                f"【制度条款】{c.describe()}\n\n【请示正文】\n{f['body'].text[:2500]}")
        ans, quote = str(res_scope.get("answer") or ""), str(res_scope.get("quote") or "")
        if ans == "否" and quote_found(quote, f["body"].text):
            problems.append(f"本次事项与条款「{c.title}」的适用范围不一致：{res_scope.get('reason') or ''}")
            ev.append(C.ev(f["body"].name, None, quote, label="请示事项"))
        elif ans != "是":
            notes.append(f"事项是否属于条款适用范围未能确认（{res_scope.get('reason') or '模型无法判断'}）")
    # 金额档位：依据中写的档位与原文档位
    br = (f.get("basis_parts") or {}).get("range")
    if br and amount and in_range(br, amount["value"]) is False:
        problems.append(f"依据中写明的金额条件（{describe_range(br)}）与请示金额 {amount_txt} 不符，按金额应适用档位「{c.tier}」")
    elif c.range and br and (br.get("lo") != c.range.get("lo") or br.get("hi") != c.range.get("hi")):
        problems.append(f"依据中写明的金额条件（{describe_range(br)}）与条款原文档位（{c.tier}）不一致")
    # 审批主体
    finals = c.meetings or []
    if not c.final:
        notes.append("未能从条款原文识别最终审批主体（红色标识）")
    form_meeting = f.get("meeting")
    stated = (f.get("basis_parts") or {}).get("subject")
    stated_m = meeting_of(stated) if stated else None
    if form_meeting and finals and form_meeting not in finals:
        problems.append(f"制度条款规定的审批主体为{'、'.join(c.final)}（{'、'.join(finals)}），与表单所选会议类型「{form_meeting}」不一致，请核实")
    if stated and c.final and stated_m not in finals and stated not in c.final:
        problems.append(f"依据中写明由「{stated}」{(f.get('basis_parts') or {}).get('action') or '审批'}，与条款原文的审批主体"
                        f"「{'、'.join(c.final)}」不一致")
    head = f"{c.describe()}"
    if problems:
        amt = f"金额 {amount_txt} " if amount else ""
        return issue(f"发现问题：{amt}已定位条款 {head}，存在 {len(problems)} 处不一致。", ev, problems + notes, llm=True)
    if notes:
        return review(f"待人工复核：已定位条款 {head}，" + "；".join(notes) + "。", ev, notes, llm=True)
    amt = f"及{amount_txt}金额" if amount else ""
    return ok(f"核查通过：本次事项{amt}符合已核实条款规定（《{c.doc_name}》{c.ref}「{c.title}」"
              f"{('，档位' + c.tier) if c.tier else ''}），由{'、'.join(c.final)}审批。", ev, llm=True)
