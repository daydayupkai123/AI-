"""依赖外部数据或台账：R16、R17、R21、R22、R29。

数据源不可用、未接入或名单未提供时，一律记「待补充」或「人工复核」并写明原因，不当作通过。
"""
from __future__ import annotations

import re

from shared.rule_framework import common as C
from shared.rule_framework.engine import aborted, issue, missing, na, ok, review

from ._util import BRANCH_RE, fev, form, form_ev, has, needs_contract


def _cp_name(f) -> str | None:
    return (f.get("counterparty") or {}).get("name") or form(f, "甲方单位名称") or None


def _tyc(f) -> dict:
    return ((f.get("external") or {}).get("tianyancha")) or {"error": "未执行天眼查查询"}


@needs_contract
def r16(f):
    name = _cp_name(f)
    if not name:
        return missing("未识别出合同相对方名称。")
    if not has(BRANCH_RE, name):
        return na(f"合同相对方「{name}」不是分公司或项目部。")
    auth = list(f.get("auth_docs") or [])
    if not auth:
        auth = [m for m in f.get("materials") or [] if m.readable and m is not f["contract"]
                and has(r"授权委托书|授权书|兹授权|特此授权", m.text[:3000])]
    tyc = _tyc(f)
    tyc_note = (f"天眼查：{tyc.get('name')}，登记状态 {tyc.get('reg_status') or '—'}，负责人 {tyc.get('legal_person') or '—'}。"
                if not tyc.get("error") else f"天眼查核实未完成（{tyc['error']}）。")
    occ = [o for o in (f.get("counterparty") or {}).get("occurrences") or [] if o["name"] == name]
    ev = [fev(o, f"合同相对方（{o['where']}）") for o in occ[:2]]
    ev += [C.ev(m.name, None, m.text[:120], label="授权文件") for m in auth[:3]]
    if tyc.get("url"):
        ev.append(C.ev("天眼查", None, tyc.get("name", ""), url=tyc["url"], label="工商登记"))
    if not auth:
        checked = [m.name for m in f.get("materials") or [] if not m.is_archive]
        ev.append(C.ev("附件清单", None, "、".join(checked)[:200], label=f"已查验附件 {len(checked)} 份"))
        return issue(f"合同相对方为“分公司”“项目部”（{name}），查验附件无总公司授权文件。{tyc_note}", ev)
    return ok(f"无异常：合同相对方为分支机构（{name}），已上传授权文件 {len(auth)} 份。{tyc_note}", ev)


@needs_contract
def r17(f):
    name = _cp_name(f)
    if not name:
        return missing("未识别出合同相对方名称，无法查询资信。")
    lists = f.get("lists") or {}
    unq = lists.get("unqualified")
    problems, notes, ev = [], [], []
    if unq is not None and unq.available:
        hit = unq.find(name)
        if hit:
            problems.append(f"列入不合格供应商名单（{hit.get('reason') or '原因未注明'}，{hit.get('since') or ''}）")
            ev.append(C.ev("不合格供应商名单", None, hit["name"], label="名单命中"))
    else:
        notes.append("不合格供应商名单未提供，名单比对未完成")
    tyc = _tyc(f)
    if tyc.get("failed"):
        return aborted(f"天眼查查询失败，本条未能审查。{tyc['error']}。处理：{tyc.get('hint') or ''}", ev,
                       failure={"system": "天眼查", "error": tyc["error"], "hint": tyc.get("hint")})
    if tyc.get("error"):
        notes.append(f"天眼查查询未完成（{tyc['error']}）")
    elif not tyc.get("risks"):
        notes.append("未能从天眼查页面读取风险信息")
    else:
        r = tyc["risks"]
        ev.append(C.ev("天眼查", None, f"{tyc.get('name')}：失信被执行人 {r.get('失信被执行人', 0)}，被执行人 "
                       f"{r.get('被执行人', 0)}，破产案件 {r.get('破产案件', 0)}，注册资本 {tyc.get('reg_capital') or '—'}",
                       url=tyc.get("url"), label="资信"))
        if tyc.get("_name_mismatch"):
            notes.append(f"天眼查匹配到的公司名称为「{tyc.get('name')}」，与合同相对方不完全一致")
        if r.get("失信被执行人"):
            problems.append(f"失信被执行人记录 {r['失信被执行人']} 条")
        if r.get("破产案件"):
            problems.append(f"破产案件 {r['破产案件']} 条")
        if r.get("被执行人"):
            notes.append(f"存在被执行记录 {r['被执行人']} 条，需人工核对执行标的额是否超过注册资本（{tyc.get('reg_capital') or '未知'}）")
    notes.append("全国企业破产重整案件信息网尚未接入，破产信息以天眼查为准")
    if problems:
        return issue("合同相对方存在失信被执行记录或大额被执行案件、破产案件，资信风险较高，请谨慎评估："
                     + "；".join(problems) + "。", ev, problems + notes)
    if any(n for n in notes if "破产重整案件信息网" not in n):
        return review(f"合同相对方「{name}」资信核验未全部完成：" + "；".join(notes) + "。", ev, notes)
    return ok(f"无异常：合同相对方「{name}」未列入不合格供应商名单，天眼查未见失信、破产记录。", ev, notes)


def _ledger(f, key: str) -> dict:
    return ((f.get("ledgers") or {}).get(key)) or {"available": False, "reason": "台账未读取"}


@needs_contract
def r21(f):
    led = _ledger(f, "main_contract")
    if not led.get("available"):
        return missing(f"主合同全条件查询台账不可用（{led.get('reason')}），无法核查重复签订。")
    name, party = form(f, "合同名称"), _cp_name(f) or ""
    if not name:
        return missing("审批表单未填写合同名称。")
    self_ids = {str(x) for x in (f.get("_request_id"), form(f, "合同编号")) if x}

    def core(s: str, owner: str) -> str:
        """去掉业主名称再比较：同一业主的不同项目共用很长的名称前缀，整串相似度会虚高。"""
        s = C.norm_name(s)
        return s.replace(C.norm_name(owner), "") if owner and C.norm_name(owner) in s else s

    hits = []
    for row in led.get("rows") or []:
        if str(row.get("id") or "") in self_ids or str(row.get("request_id") or "") in self_ids:
            continue
        rp = C.ratio(party, row.get("party", "")) if party and row.get("party") else 1.0
        rn = C.ratio(core(name, party), core(row.get("name", ""), row.get("party") or party))
        if rn >= 0.9 and rp >= 0.8:
            hits.append((rn, row))
    hits.sort(key=lambda x: -x[0])
    if hits:
        items = [f"{r.get('name')}｜{r.get('party') or '—'}｜{r.get('id') or r.get('request_id') or ''}｜"
                 f"{r.get('date') or ''}｜相似度 {s:.0%}" for s, r in hits[:5]]
        return issue("存在重复签订合同或重复提交审批流程情况。",
                     [form_ev(f, "合同名称")] + [C.ev(led.get("name", "主合同台账"), None, i) for i in items[:3]], items)
    return ok(f"无异常：在主合同台账 {len(led.get('rows') or [])} 条记录中未发现相同或高度相似的合同。", [form_ev(f, "合同名称")])


PERSON_RE = re.compile(r"(项目负责人|项目经理|设计总负责人|总监理工程师|总监|专业负责人|技术负责人)(?:姓名)?\s*(?:[:：]|为)\s*"
                       r"([\u4e00-\u9fa5]{2,4})(?=[\s，,。；;、（(]|身份证|注册|电话|联系|$|\d)")
NOT_NAME = re.compile(r"的|和|及|与|应|由|等|人员|负责|工程|监理|项目|经理|按照|根据|担任|姓名")


@needs_contract
def r22(f):
    sign = form(f, "会签部门")
    if not sign:
        return missing("审批表单未填写会签部门。")
    people = _ledger(f, "people")
    names = {}
    for page, text in f["contract"].pages:
        for m in PERSON_RE.finditer(C.flat(text)):
            if not NOT_NAME.search(m.group(2)):
                names.setdefault(m.group(2), m.group(1))
    if not names:
        return review("未从合同中识别出履约人员姓名，无法核对会签部门，请人工核对。", [form_ev(f, "会签部门")])
    if not people.get("available"):
        return missing(f"人员所属部门数据（通用人数据）不可用（{people.get('reason')}），无法核对会签部门。"
                       f"合同履约人员：{'、'.join(f'{k}（{v}）' for k, v in names.items())}。", [form_ev(f, "会签部门")])
    dept_of = people.get("map") or {}
    need = {dept_of[n] for n in names if dept_of.get(n)}
    unknown = [n for n in names if not dept_of.get(n)]
    lacking = sorted(d for d in need if d not in sign)
    ev = [form_ev(f, "会签部门")] + [C.ev("人员数据", None, f"{n}：{dept_of.get(n) or '未查到'}") for n in names]
    if lacking:
        return issue(f"会签部门选择与合同约定的履约人员不匹配，缺少：{'、'.join(lacking)}。", ev,
                     [f"{n}（{names[n]}）所属 {dept_of[n]}" for n in names if dept_of.get(n) in lacking])
    if unknown:
        return review(f"履约人员 {'、'.join(unknown)} 未查到所属部门，其余人员部门已覆盖，请人工核对。", ev)
    return ok(f"无异常：履约人员所属部门（{'、'.join(sorted(need))}）均在会签部门中。", ev)


def r29(f):
    stds = f.get("standards") or []
    if not stds:
        return na("合同、技术协议中未引用标准规范编号。")
    lst = (f.get("lists") or {}).get("standards")
    codes = "、".join(s["value"] for s in stds[:10])
    if lst is None or not lst.available:
        return missing(f"标准规范有效/失效清单未提供，暂无法核对有效性。已识别引用标准 {len(stds)} 项：{codes}。",
                       [fev(s, "引用标准") for s in stds[:5]])
    bad, unknown = [], []
    for s in stds:
        hit = lst.find(s["value"])
        if not hit:
            unknown.append(s["value"])
        elif str(hit.get("status", "")).strip() in ("废止", "作废", "被代替", "被替代"):
            bad.append((s, hit))
    if bad:
        items = [f"{s['value']} 已{h.get('status')}" + (f"，现行为 {h['replaced_by']}" if h.get("replaced_by") else "")
                 for s, h in bad]
        return issue("引用的标准已废止/被代替，请更新为现行有效版本。", [fev(s, "引用标准") for s, _ in bad[:5]], items)
    if unknown:
        return review(f"以下标准不在有效/失效清单中，请人工核对：{'、'.join(unknown)}。", [fev(s, "引用标准") for s in stds[:5]])
    return ok(f"无异常：引用的 {len(stds)} 项标准均为现行有效。", [fev(s, "引用标准") for s in stds[:5]])
