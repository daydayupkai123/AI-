"""04 请示正文：事项与阶段、项目名称、金额、占位符、引用制度与表单依据一致性、文本完整性（模型，引用原文校验）。

多个问题合并为一条综合意见，按（1）（2）（3）列示。不做无依据的业务补写。
"""
from __future__ import annotations

import re

from shared.rule_framework import common as C
from shared.rule_framework.engine import issue, missing, ok, review
from shared.rule_framework.semantic import quote_exact, quote_found

from .. import prompts
from .title import _contains_core


THINK_TOKEN = re.compile(r"/no_think|/think|</?think>")
ORG_RE = re.compile(r"[\u4e00-\u9fa5（）()]{2,30}?(有限责任公司|股份有限公司|有限公司|集团公司|研究院|设计院)")
ORG_LEAD = re.compile(r"^(委托|推荐|同意|确定|选定|邀请|建议|向|由|与|和|及|为|对|给|经|是|将|在|从|被|请|即|系)+")


def _one_edit(a: str, b: str) -> bool:
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1


def org_variants(text: str) -> list[tuple[str, str, int]]:
    """正文中同一单位的不同写法：字序颠倒（如「悦幕 / 幕悦」）或同长度仅一字之差。包含关系（总公司 / 分公司）不算。"""
    flat = re.sub(r"\s+", "", text or "")
    seen: dict[str, int] = {}
    for m in ORG_RE.finditer(flat):
        lead = ORG_LEAD.match(m.group(0))
        name = m.group(0)[lead.end() if lead else 0:]
        seen.setdefault(name, m.start() + (lead.end() if lead else 0))
    names = list(seen)
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if len(a) < 8 or a in b or b in a:
                continue
            if (sorted(a) == sorted(b) and a != b) or _one_edit(a, b):
                out.append((a, b, seen[b]))
    return out


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
    for a, b, pos in org_variants(text):
        problems.append(f"前后矛盾：单位名称写法不一致「{a}」/「{b}」，请核实是否为同一单位")
        ev.append(C.ev(body.name, None, C.around(text, pos, pos + len(b)), label="单位名称"))
    res = f["_judge"]("meeting.N04.text", prompts.BODY, f"【事项阶段】{stage or '未识别'}\n\n【请示正文】\n{text[:3500]}")
    dropped, off_scope = 0, 0
    for p in res.get("problems") or []:
        if not isinstance(p, dict):
            continue
        q, kind = str(p.get("quote") or ""), str(p.get("issue") or "").strip()
        if kind not in prompts.BODY_ISSUES:
            off_scope += 1
        elif THINK_TOKEN.search(q):
            dropped += 1  # 模型把思考开关标记抄进了引用，所指「残缺」多半就是这个标记本身
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
