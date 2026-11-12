"""采购审批 18 条规则（需求：需求场景/采购审批数字员工需求方案.docx 第四章）。

状态：命中 / 未命中 / 未能识别 / 未执行。档位：一定不通过 / 拿不准（命中后决定报告中的排列）。
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime

RULES_VERSION = "procurement-2026.11.06-r1"

CERTAIN, DOUBT = "一定不通过", "拿不准"
HIT, PASS, UNREAD, NOTRUN = "命中", "未命中", "未能识别", "未执行"

GENERIC_AUTHORS = {"", "admin", "administrator", "user", "微软用户", "microsoft", "microsoft office user",
                   "lenovo", "dell", "hp", "un-named", "unknown", "owner", "win", "pc", "abc"}

META = [
    ("P01", "采购申请表单填写的规范性与完整性", CERTAIN),
    ("P02", "采购公告的完整性", CERTAIN),
    ("P03", "采购公告与采购需求的一致性", CERTAIN),
    ("P04", "供应商资格条件设置的合理性", DOUBT),
    ("P05", "不得设置限制和排斥潜在供应商的条件", DOUBT),
    ("P06", "采购公告发布时间应晚于需求审批通过日期", CERTAIN),
    ("P07", "采购文件的完整性", CERTAIN),
    ("P08", "采购文件发出到截止时间的间隔", CERTAIN),
    ("P09", "最高限价不应高于采购预算", CERTAIN),
    ("P10", "不同供应商的投标文件作者不应为同一人", DOUBT),
    ("P11", "不同供应商的材料不应存在信息雷同", DOUBT),
    ("P12", "不同供应商的报价不应存在规律性差异", DOUBT),
    ("P13", "不同供应商之间不应存在关联关系", DOUBT),
    ("P14", "不同供应商之间主要人员不应重叠", DOUBT),
    ("P15", "供应商应具备良好资信", DOUBT),
    ("P16", "评审报告应明确采购方式", CERTAIN),
    ("P17", "邀请采购或直接采购应说明原因", DOUBT),
    ("P18", "评审日期应合理合规", CERTAIN),
]
NAMES = {rid: (name, tier) for rid, name, tier in META}


def _r(rid, status, message, evidence=None, **extra):
    name, tier = NAMES[rid]
    return {"rule_id": rid, "rule_ver": RULES_VERSION, "name": name, "tier": tier, "status": status,
            "message": message, "evidence": evidence or [], **extra}


def _cfg() -> dict:
    from shared import settings

    return settings.load("procurement.yaml")


def _ev(f):
    return {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in (f or {}).items()}


def _num(s) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


METHOD_EQUIV = [{"询比", "询价"}, {"竞争性谈判", "谈判"}, {"公开招标"}, {"邀请招标"}, {"直接采购", "单一来源"}]


def _same_method(a: str, b: str) -> bool:
    a, b = a or "", b or ""
    for group in METHOD_EQUIV:
        if any(w in a for w in group) and any(w in b for w in group):
            return True
    return False


def p01(f):
    form = f["form"]
    need = {"合同名称": form.get("合同名称"), "采购内容": form.get("采购内容"), "采购方式": form.get("采购方式"),
            "预算金额": form.get("预算价格（万元）")}
    missing = [k for k, v in need.items() if not str(v or "").strip()]
    ev = [{"file": "OA 表单", "snippet": f"{k}：{v}"} for k, v in need.items()]
    if missing:
        return _r("P01", HIT, f"表单填写不完整，缺少：{'、'.join(missing)}。", ev)
    return _r("P01", PASS, "四项均已填写（需求审批表单比对待接入）。", ev)


def p02(f):
    items = f.get("ann_items")
    if items is None:
        return _r("P02", UNREAD, "未找到采购公告。")
    missing = [k for k, v in items.items() if not v]
    ev = [{"item": k, **_ev(v)} for k, v in items.items() if v]
    if missing:
        return _r("P02", HIT, f"采购公告内容不完整，缺少“{'、'.join(missing)}”。", ev)
    return _r("P02", PASS, "八项要素均已出现。", ev)


def p03(f):
    form, diffs, ev = f["form"], [], []
    am = f.get("ann_method")
    if am:
        ev.append(_ev(am))
        if not _same_method(am["value"], form.get("采购方式", "")):
            diffs.append(f"采购方式：公告为“{am['value']}”，表单为“{form.get('采购方式')}”")
    mp, budget = f.get("max_price_wan"), _num(form.get("预算价格（万元）"))
    if mp and budget is not None:
        ev.append(_ev(mp))
        if abs(mp["value"] - budget) > 0.0001 and mp["value"] > budget:
            diffs.append(f"金额：公告限价 {mp['value']} 万元，表单预算 {budget} 万元")
    if not ev:
        return _r("P03", UNREAD, "未从公告中识别出采购方式或金额。")
    if diffs:
        return _r("P03", HIT, "采购公告与需求不一致：" + "；".join(diffs) + "。", ev)
    return _r("P03", PASS, "采购方式、金额与表单一致（以表单代替需求审批信息，待接入需求流程）。", ev)


def p06(f):
    return _r("P06", UNREAD, "需求审批流程（审批日期）尚未接入，无法比对。",
              [_ev(f.get("ann_publish_date"))] if f.get("ann_publish_date") else [])


def p07(f):
    items = f.get("pdoc_items")
    if items is None:
        return _r("P07", UNREAD, "未找到采购文件。")
    missing = [k for k, v in items.items() if not v]
    ev = [{"item": k, **_ev(v)} for k, v in items.items() if v]
    if missing:
        return _r("P07", HIT, f"采购文件缺少“{'、'.join(missing)}”。", ev)
    return _r("P07", PASS, "十项要素均已出现。", ev)


def p08(f):
    pub, dl = f.get("pdoc_publish_date"), f.get("deadline")
    if not pub or not dl:
        return _r("P08", UNREAD, "未识别出采购文件发布时间或截止时间。", [_ev(x) for x in (pub, dl) if x])
    days = (dl["value"].date() - pub["value"]).days + 1
    ev = [_ev(pub), _ev(dl)]
    need = int(_cfg().get("p08_min_days", 3))
    if days < need:
        return _r("P08", HIT, f"采购文件从发出到截止仅 {days} 个自然日（含发布当日），不足 {need} 日。", ev)
    return _r("P08", PASS, f"发出到截止共 {days} 个自然日（含发布当日）。", ev)


def p09(f):
    mp, budget = f.get("max_price_wan"), _num(f["form"].get("预算价格（万元）"))
    if not mp:
        return _r("P09", PASS, "采购文件未设置最高限价。")
    if budget is None:
        return _r("P09", UNREAD, "表单预算金额缺失。", [_ev(mp)])
    if mp["value"] > budget + 1e-6:
        return _r("P09", HIT, f"最高限价 {mp['value']} 万元大于预算金额 {budget} 万元。", [_ev(mp)])
    return _r("P09", PASS, f"最高限价 {mp['value']} 万元，不高于预算 {budget} 万元。", [_ev(mp)])


def p10(f):
    metas = f.get("office_meta") or {}
    have = {s: m for s, m in metas.items() if m}
    if len(have) < 2:
        return _r("P10", UNREAD, "可读取文档属性的供应商电子文件不足两家（扫描件无作者信息）。")
    owners: dict[tuple, list] = {}
    created: dict[str, list] = {}
    for s, docs in have.items():
        for d in docs:
            for field in ("author", "last_modified_by"):
                v = (d.get(field) or "").strip()
                if v.lower() not in GENERIC_AUTHORS and len(v) >= 1:
                    owners.setdefault((field, v), []).append((s, d["file"]))
            if d.get("created"):
                created.setdefault(d["created"], []).append(s)
    dup = {k: v for k, v in owners.items() if len({s for s, _ in v}) >= 2}
    ev = [{"file": d["file"], "supplier": s, "author": d.get("author"), "last_modified_by": d.get("last_modified_by"),
           "created": d.get("created")} for s, docs in have.items() for d in docs]
    if not dup:
        return _r("P10", PASS, "各供应商电子文件作者/最后修改人未发现相同（已忽略 admin 等通用名）。", ev)
    parts = []
    for (field, v), lst in dup.items():
        who = "、".join(sorted({s for s, _ in lst}))
        parts.append(f"{'作者' if field == 'author' else '最后修改人'}“{v}”同时出现在：{who}")
    same_created = [c for c, ss in created.items() if len(set(ss)) >= 2]
    note = "；其中部分文件创建时间完全相同，可能源自采购方下发的同一模板" if same_created else ""
    return _r("P10", HIT, "不同供应商的文件作者为同一人，请核实：" + "；".join(parts) + note + "。", ev)


def p11(f):
    vals = f.get("supplier_values") or {}
    if sum(1 for v in vals.values() if any(v.values())) < 2:
        return _r("P11", UNREAD, "可比对的供应商材料不足两家。")
    hits = []
    kinds = ("电话", "邮箱", "银行账号", "地址")
    for kind in kinds:
        seen: dict[str, list] = {}
        for s, v in vals.items():
            for value, src in v.get(kind, {}).items():
                seen.setdefault(value, []).append((s, src))
        for value, lst in seen.items():
            if len({s for s, _ in lst}) >= 2:
                hits.append({"kind": kind, "value": value, "suppliers": sorted({s for s, _ in lst}),
                             "sources": [{"supplier": s, **src} for s, src in lst]})
    counts = {s: {k: len(v.get(k, {})) for k in kinds} for s, v in vals.items()}
    if hits:
        desc = "；".join(f"{h['kind']}“{h['value']}”同时出现在 {'、'.join(h['suppliers'])}" for h in hits[:6])
        return _r("P11", HIT, f"不同供应商的材料存在雷同，请核实：{desc}。", hits, counts=counts)
    return _r("P11", PASS, "电话、邮箱、银行账号、地址未发现跨供应商雷同。", [], counts=counts)


def p12(f):
    q = f.get("quotes") or {}
    n_sup = len(f.get("suppliers") or [])
    if n_sup < 3:
        return _r("P12", UNREAD, f"供应商仅 {n_sup} 家，不足三家，无法判断报价规律性。")
    if len(q) < 3:
        return _r("P12", UNREAD, f"仅识别出 {len(q)} 家报价，无法判断。", [{"supplier": s, **v} for s, v in q.items()])
    vals = sorted(v["value"] for v in q.values())
    diffs = [round(b - a, 2) for a, b in zip(vals, vals[1:])]
    ev = [{"supplier": s, **v} for s, v in q.items()]
    tol = max(1.0, float(_cfg().get("p12_tolerance_ratio", 0.005)) * max(vals))
    if all(abs(d - diffs[0]) <= tol for d in diffs) and diffs[0] > 0:
        return _r("P12", HIT, f"各家报价构成等差数列（差值约 {diffs[0]:,.2f} 元）：{', '.join(f'{v:,.2f}' for v in vals)}。", ev)
    return _r("P12", PASS, f"报价 {', '.join(f'{v:,.2f}' for v in vals)}，相邻差值 {diffs}，不构成等差。", ev)


def p16(f):
    m = f.get("review_method")
    if m is None:
        return _r("P16", HIT if f.get("has_review") else UNREAD,
                  "评审报告未明确采购方式。" if f.get("has_review") else "未找到评审报告。")
    return _r("P16", PASS, f"评审报告载明采购方式：{m['value']}。", [_ev(m)])


def p18(f):
    rd, dl = f.get("review_date"), f.get("deadline")
    if not rd or not dl:
        return _r("P18", UNREAD, "未识别出评审日期或递交截止时间。", [_ev(x) for x in (rd, dl) if x])
    ev = [_ev(rd), _ev(dl)]
    if rd["value"] < dl["value"].date():
        return _r("P18", HIT, f"评审日期 {rd['value']} 早于报价递交截止 {dl['value']:%Y-%m-%d %H:%M}。", ev)
    return _r("P18", PASS, f"评审日期 {rd['value']} 不早于递交截止 {dl['value']:%Y-%m-%d %H:%M}。", ev)


def not_run(rid, why):
    return lambda f: _r(rid, NOTRUN, why)


RULES = [
    p01, p02, p03,
    not_run("P04", "语义规则：关键词定位后需大模型确认，待接入。"),
    not_run("P05", "语义规则：关键词定位后需大模型确认，待接入。"),
    p06, p07, p08, p09, p10, p11, p12,
    not_run("P13", "天眼查关联关系查询待接入（账号已验证可用）。"),
    not_run("P14", "天眼查主要人员查询待接入。"),
    not_run("P15", "天眼查失信/破产查询待接入。"),
    p16,
    not_run("P17", "语义规则：需求审批「是否邀请/直接采购」与评审说明，待接入。"),
    p18,
]


def run_all(facts: dict) -> list[dict]:
    from shared import rule_config

    out = []
    for (rid, _name, _tier), fn in zip(META, RULES):
        t0 = time.time()
        off = rule_config.disabled_reason("procurement", rid)
        if off:
            r = _r(rid, NOTRUN, f"未执行：{off}")
        else:
            try:
                r = fn(facts)
            except Exception as exc:  # noqa: BLE001
                r = _r(rid, UNREAD, f"规则执行异常：{type(exc).__name__}: {exc}")
        r["ms"] = int((time.time() - t0) * 1000)
        out.append(rule_config.apply_result("procurement", r))
    return out
