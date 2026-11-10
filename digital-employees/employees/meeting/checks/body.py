"""04 请示正文：事项与阶段、项目名称、金额、占位符、引用制度与表单依据一致性、文本完整性（模型，引用原文校验）。

多个问题合并为一条综合意见，按（1）（2）（3）列示。不做无依据的业务补写。
"""
from __future__ import annotations

import re

from core.rules import common as C
from core.rules.engine import issue, missing, ok, review
from core.rules.semantic import quote_exact, quote_found

from .. import prompts
from .title import _contains_core


def _ref_key(r: dict) -> tuple:
    return (r["doc_id"], r.get("dept"), r.get("no"))


def check(f):
    body = f.get("body")
    if not body:
        return missing("待补充：未读取到请示正文（DOC/DOCX/PDF），无法核验。")
    text = body.text
    problems, notes, ev = [], [], [C.ev(body.name, None, text[:120], label="请示正文")]
    stage = f.get("stage")
    if not stage:
        notes.append("未能识别请示的事项阶段（立项、采购过程、采购结果、制度制定修订、人员事项等），请人工确认")
    bt, core = f.get("body_title"), f.get("title_core")
    if bt and core and not _contains_core(core, bt):
        problems.append(f"正文标题「{bt}」与 OA 标题所述事项「{core}」不一致")
    amount = f.get("case_amount")
    if stage in ("采购结果", "立项", "采购过程") and not amount:
        problems.append(f"正文为{stage}事项，但未写明可识别的{'成交/采购' if stage == '采购结果' else '预算'}金额")
    elif amount:
        ev.append(C.ev(amount.get("file", ""), amount.get("page"), amount.get("snippet", ""), label="涉及金额"))
    for p in f.get("placeholders") or []:
        problems.append(f"正文存在未填写的占位内容「{p['value']}」：…{p['snippet'][:40]}…")
        ev.append(C.ev(p["file"], p.get("page"), p["snippet"], label="占位内容"))
    body_refs = {_ref_key(r): r for r in f.get("body_refs") or [] if r.get("no")}
    basis_refs = {_ref_key(r): r for r in (f.get("basis_parts") or {}).get("refs") or [] if r.get("no")}
    if body_refs and basis_refs and not set(body_refs) & set(basis_refs):
        problems.append(f"正文引用的制度条款（{'、'.join(r['raw'] for r in body_refs.values())}）与表单审批/上会依据"
                        f"（{'、'.join(r['raw'] for r in basis_refs.values())}）不一致")
    res = f["_judge"]("meeting.N04.text", prompts.BODY, text[:3500])
    dropped, off_scope = 0, 0
    for p in res.get("problems") or []:
        if not isinstance(p, dict):
            continue
        q, kind = str(p.get("quote") or ""), str(p.get("issue") or "").strip()
        q = re.sub(r"\s*(/no_think|/think|</?think>)\s*", "", q)  # 模型偶尔把思考开关标记抄进引用
        if kind not in prompts.BODY_ISSUES:
            off_scope += 1
        elif (quote_exact if kind == "语句残缺" else quote_found)(q, text):
            problems.append(f"{kind}：「{q}」{('，' + p['explain']) if p.get('explain') else ''}")
            ev.append(C.ev(body.name, None, q, label=kind))
        else:
            dropped += 1
    if dropped:
        notes.append(f"模型另提出 {dropped} 处文本问题，但引用原文无法在正文中定位，未采信")
    if off_scope:
        notes.append(f"模型另提出 {off_scope} 处不属于文本完整性检查范围的意见，未采信")
    if problems:
        return issue(f"发现问题：请示正文存在 {len(problems)} 处问题。", ev, problems + notes, llm=True)
    if notes and not stage:
        return review("待人工复核：" + "；".join(notes) + "。", ev, notes, llm=True)
    amt = f"，金额 {C.fmt_wan(amount['value'])}" if amount else ""
    return ok(f"核查通过：正文为{stage or '—'}事项{amt}，项目名称与标题一致，未发现占位内容、引用冲突或文本缺失。"
              + (f"（{notes[0]}）" if notes else ""), ev, llm=True)
