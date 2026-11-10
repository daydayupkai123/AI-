"""合同正文条款核验：R09–R15、R18、R19、R23、R25–R28。"""
from __future__ import annotations

import re
from datetime import timedelta

from core.rules import common as C
from core.rules import semantic
from core.rules.engine import issue, missing, na, ok, review

from ._util import biz_text, fev, form, form_ev, has, judge_of, money, needs_contract


@needs_contract
def r09(f):
    caps = f.get("cap_hits") or []
    if caps:
        return ok(f"无异常：合同已约定责任限额（「{caps[0]['value']}」）。", [fev(c, "责任限额") for c in caps[:3]])
    hits = f.get("liability_hits") or []
    if not hits:
        return review("未定位到乙方违约责任条款，无法判断是否约定责任限额，请人工核对。")
    formula = f.get("liability_formula") or []
    if formula:
        return review(f"合同按公式约定乙方赔偿金额（「{formula[0]['value'][:60]}」），未明确以合同额为限，"
                      f"请人工判断该公式是否构成责任限额。", [fev(x, "赔偿金额约定") for x in formula]
                      + [fev(h, "乙方违约责任条款") for h in hits[:2]])
    return issue("合同违约责任条款未约定责任限额，建议增加“赔偿数额原则上限于所签订的合同额”的约定。",
                 [fev(h, "乙方违约责任条款") for h in hits[:3]])


@needs_contract
def r10(f):
    pens = f.get("penalties") or []
    if not pens:
        return na("合同未约定可计算的违约金比例。")
    limit = float((f.get("cfg") or {}).get("penalty_limit_ratio", 0.30))
    over = [p for p in pens if (not p["daily"] or p["cap"]) and p["value"] > limit + 1e-9]
    if over:
        items = [f"违约金比例 {p['value'] * 100:g}%：「{p['snippet'][:80]}」" for p in over]
        return issue(f"合同约定违约金比例为 {max(p['value'] for p in over) * 100:g}%，过高（超过合同总价的 "
                     f"{limit * 100:g}%）。", [fev(p, "违约金条款") for p in over[:4]], items)
    uncapped_daily = [p for p in pens if p["daily"] and not p["cap"]]
    if uncapped_daily and not any(p["cap"] for p in pens):
        return review("违约金按日计算且未约定累计上限，无法折算为占合同总价的比例，请人工核对。",
                      [fev(p, "按日违约金") for p in uncapped_daily[:3]])
    top = max(p["value"] for p in pens if not p["daily"] or p["cap"]) if any(not p["daily"] or p["cap"] for p in pens) \
        else None
    msg = f"无异常：违约金比例最高 {top * 100:g}%，未超过 {limit * 100:g}%。" if top is not None else \
        "无异常：按日违约金已约定累计上限。"
    return ok(msg, [fev(p, "违约金条款") for p in pens[:3]])


@needs_contract
def r11(f):
    ups = f.get("price_upper") or []
    if not ups:
        return na("合同价款条款未出现中文大写金额。")
    paired = [u for u in ups if u.get("lower") is not None]
    if not paired:
        return review("合同中有大写金额，但附近未找到对应的阿拉伯数字金额，请人工核对。", [fev(u, "大写金额") for u in ups[:3]])
    bad = [u for u in paired if abs(u["value"] - u["lower"]) > 0.005]
    if bad:
        items = [f"大写「{u['raw']}」= {money(u['value'])}，小写「{u['lower_raw']}」= {money(u['lower'])}" for u in bad]
        return issue("合同价款大小写金额不一致。", [fev(u, "大写金额") for u in bad[:4]], items)
    return ok(f"无异常：{len(paired)} 处大写金额与小写金额一致。", [fev(u, "大写金额") for u in paired[:3]])


@needs_contract
def r12(f):
    tax = f.get("tax") or {}
    if not f.get("price"):
        return missing("未识别出合同价款，无法判断是否价税分离。")
    lacking = [k for k in ("不含税金额", "税率", "税额") if not tax.get(k)]
    ev = [fev(v, k) for k, v in tax.items() if v] + [fev(f["price"], "合同价款")]
    if lacking:
        listed = [f"{k} {tax[k].get('raw') or tax[k]['value']}" for k in ("不含税金额", "税率", "税额") if tax.get(k)]
        done = f"已列明{'、'.join(listed)}，但" if listed else ""
        return issue(f"合同价款未完整进行价税分离（{done}未列明{'、'.join(lacking)}），建议分别列明不含税金额、税率及税额。", ev)
    return ok("无异常：合同价款已分别列明不含税金额、税率及税额。", ev)


@needs_contract
def r13(f):
    mix = f.get("currency_mix") or []
    if mix:
        return issue("合同价格条款中货币符号“￥/¥”与“元”同时出现，建议统一使用“XX 元”的表述方式。",
                     [fev(m, "价格表述") for m in mix[:4]], [f"「{m['value']}」" for m in mix])
    return ok("无异常：未发现货币符号与“元”同时出现的价格表述。")


@needs_contract
def r14(f):
    arbs = f.get("arbitration") or []
    if not arbs:
        choice = f.get("dispute_choice")
        if choice == "诉讼":
            return na("合同约定的争议解决方式为向人民法院提起诉讼，未采用仲裁。")
        if choice == "仲裁":
            return review("合同选择以仲裁方式解决争议，但未识别出具体仲裁机构名称，请人工核对（未约定明确仲裁机构的仲裁条款可能无效）。")
        if not f.get("has_arbitration"):
            return na("合同争议解决条款未采用仲裁方式。")
        return na("合同仅一般性提及仲裁，未约定具体仲裁机构，不涉及仲裁机构名称规范性。")
    bad = [a for a in arbs if a["bad"]]
    if bad:
        return issue("；".join(f"仲裁机构名称“{a['value']}”表述不规范，正式名称应为“{a['place']}仲裁委员会”" for a in bad[:3]) + "。",
                     [fev(a, "仲裁条款") for a in bad[:3]])
    return ok(f"无异常：仲裁机构名称为“{arbs[0]['value']}”。", [fev(arbs[0], "仲裁条款")])


@needs_contract
def r15(f):
    cp = f.get("counterparty") or {}
    occ = list(cp.get("occurrences") or [])
    srcs = {}
    for o in occ:
        srcs.setdefault(o["where"], set()).add(re.sub(r"\s", "", o["name"]).replace("（", "(").replace("）", ")"))
    fv = form(f, "甲方单位名称")
    if fv:
        srcs["审批流程"] = {re.sub(r"\s", "", fv).replace("（", "(").replace("）", ")")}
    names = set().union(*srcs.values()) if srcs else set()
    if not cp.get("name"):
        return missing("未从合同中识别出合同相对方名称。", [form_ev(f, "甲方单位名称")] if fv else [])
    if sum(len(v) for v in srcs.values()) < 2 and len(srcs) < 2:
        return review(f"合同相对方名称仅识别到 1 处（{'、'.join(srcs)}），可比较的来源不足，请人工核对。",
                      [fev(o, o["where"]) for o in occ[:3]])
    ev = [fev(o, f"{o['where']}·{cp['side']}") for o in occ[:6]] + ([form_ev(f, "甲方单位名称")] if fv else [])
    if len(names) > 1:
        items = [f"{where}：{'、'.join(sorted(v))}" for where, v in srcs.items()]
        return issue("合同相对方名称在合同正文、首页、签章页、审批流程中不一致。", ev, items)
    return ok(f"无异常：合同相对方名称在{'、'.join(srcs)}中一致（{next(iter(names))}）。", ev)


@needs_contract
def r18(f):
    hits = f.get("reduction_hits") or []
    if not hits:
        return ok("无异常：合同条款未出现“核减”“减少合同价款”等表述。")
    ans, reason, src = semantic.confirm(judge_of(f), "contract.R18", "合同条款约定核减或减少主合同价款", hits)
    ev = [src] if src else [fev(h, "关键词命中") for h in hits[:3]]
    if ans == "是":
        return issue("主合同核减合同额，请先就分包合同核减合同额。" + (f"（{reason}）" if reason else ""), ev, llm=True)
    if ans == "否":
        return ok(f"无异常：出现“核减/减少”字样，但不涉及核减主合同价款（{reason}）。", ev, llm=True)
    return review(f"出现“核减/减少”字样，模型无法确认是否核减主合同价款，请人工核对。{reason}", ev, llm=True)


BIZ_WORDS = r"(设计|咨询|勘察|测量|测绘|监理|项目管理|全过程|总承包|EPC|技术服务|评价|评估|造价|施工|采购|框架|战略合作|服务|研究|规划|审查|检测)"


@needs_contract
def r19(f):
    name = form(f, "合同名称")
    if not name:
        return missing("审批表单未填写合同名称。")
    owner = (f.get("counterparty") or {}).get("name") or form(f, "甲方单位名称")
    lacking = []
    owner_ok = False
    if owner:
        core = re.sub(r"(股份)?有限(责任)?公司|集团|分公司|公司$", "", C.norm_name(owner))
        owner_ok = any(core[i:i + 4] in C.norm_name(name) for i in range(max(1, len(core) - 3))) if len(core) >= 4 \
            else core in name
    if not owner_ok:
        lacking.append("业主名称")
    biz = re.findall(BIZ_WORDS, name)
    if not biz:
        lacking.append("业务类型/合同性质")
    rest = C.norm_name(name)
    if owner:
        rest = rest.replace(C.norm_name(owner), "")
    rest = re.sub(BIZ_WORDS + r"|合同|协议|书|项目$", "", rest)
    if len(rest) < 4 and not re.search(r"项目|工程", name):
        lacking.append("项目名称")
    ev = [form_ev(f, "合同名称")] + ([C.ev("合同正文", None, owner, label="合同相对方")] if owner else [])
    if lacking:
        return issue(f"合同名称未完整写明{'、'.join(lacking)}，请补充（应包含业主名称、项目名称、业务类型/合同性质）。", ev)
    return ok(f"无异常：合同名称包含业主名称、项目名称与业务类型（{'、'.join(dict.fromkeys(biz))}）。", ev)


@needs_contract
def r23(f):
    laws = f.get("laws") or []
    if not laws:
        return na("合同正文未引用法律法规名称。")
    bad = [x for x in laws if x.get("wrong")]
    if bad:
        items = [f"《{x['value']}》{x['wrong']}" for x in bad]
        return issue("合同引用的法律名称有误，应为《中华人民共和国民法典》。", [fev(x, "法律引用") for x in bad[:4]], items)
    names = "、".join(dict.fromkeys(f"《{x['value']}》" for x in laws))
    return ok(f"无异常：合同引用的法律名称为 {names}。", [fev(laws[0], "法律引用")])


@needs_contract
def r25(f):
    sign = f.get("sign_date") or f.get("sign_date_form")
    start, end = f.get("start_date"), f.get("end_date")
    vfrom, vto, dur = f.get("valid_from"), f.get("valid_to"), f.get("duration")
    if start and not end and dur and not dur.get("approx"):
        end = {**start, "value": start["value"] + timedelta(days=int(dur["value"]) - 1), "derived": True,
               "snippet": f"开工 {start['value']} + 工期 {dur.get('raw')}"}
    probs = []
    if sign and start and start["value"] < sign["value"]:
        probs.append(f"合同签订日期（{sign['value']}）晚于工期开始时间（{start['value']}）")
    if sign and vto and sign["value"] > vto["value"]:
        probs.append(f"合同签订日期（{sign['value']}）晚于合同有效期（至 {vto['value']}）")
    if end and vto and end["value"] > vto["value"]:
        probs.append(f"工期结束（{end['value']}{'，按工期推算' if end.get('derived') else ''}）晚于合同有效期（至 {vto['value']}）")
    if start and vfrom and start["value"] < vfrom["value"]:
        probs.append(f"工期开始（{start['value']}）早于合同有效期起始（{vfrom['value']}）")
    ev = [fev(x, k) for k, x in (("签订日期", sign), ("开工日期", start), ("竣工日期", end), ("有效期起", vfrom),
                                ("有效期至", vto)) if x]
    if probs:
        return issue("工期未在签订日期、合同有效期内：" + "；".join(probs) + "。", ev, probs)
    compared = sum(1 for a, b in ((sign, start), (sign, vto), (end, vto), (start, vfrom)) if a and b)
    if not compared:
        return missing("缺少可比较的签订日期、工期起止或合同有效期，无法核验日期顺序。", ev)
    return ok(f"无异常：已比较 {compared} 组日期，顺序合规。", ev)


def _is_framework(f) -> bool:
    return has(r"框架|战略合作", biz_text(f))


@needs_contract
def r26(f):
    if not _is_framework(f):
        return na("业务类型不是框架协议或战略合作协议。")
    hits = f.get("exclusive_hits") or []
    if not hits:
        return ok("无异常：协议文本未出现“唯一”“排他”“独家”“仅能与”等排他性表述。")
    ans, reason, src = semantic.confirm(judge_of(f), "contract.R26", "协议约定了排他性合作（限定只能与一方合作）", hits)
    ev = [src] if src else [fev(h, "关键词命中") for h in hits[:3]]
    if ans == "是":
        return issue(f"框架协议中存在排他性条款，具体为「{src['snippet']}」。", ev, llm=True)
    if ans == "否":
        return ok(f"无异常：出现排他相关字样但不构成排他性条款（{reason}）。", ev, llm=True)
    return review(f"出现排他相关字样，模型无法确认是否构成排他性条款，请人工核对。{reason}", ev, llm=True)


def _is_supervision(f) -> bool:
    return has(r"监理|项目管理|全过程", biz_text(f))


@needs_contract
def r27(f):
    if not _is_supervision(f):
        return na("业务类型不含监理、项目管理、全过程咨询。")
    hits = f.get("price_change_hits") or []
    if hits:
        return ok(f"无异常：合同已约定价款变更相关条款（「{hits[0]['value']}」）。", [fev(h, "价款变更条款") for h in hits[:3]])
    ev = [e for e in (form_ev(f, "业务类型"), fev(f.get("price"), "合同价款条款")) if e]
    return issue("监理/项目管理合同未约定合同价款变更相关条款（如附加工作酬金计算方式）。", ev)


def r28(f):
    if not _is_supervision(f):
        return na("业务类型不是监理、项目管理、全过程工程咨询。")
    return review("该项目类型为监理/项目管理/全过程工程咨询，发起流程时需线下向运营管理部报送项目履约人员情况表，"
                  "请确认是否已报送。", [form_ev(f, "业务类型")] if form(f, "业务类型") else [])
