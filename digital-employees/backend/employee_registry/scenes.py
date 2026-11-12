"""四个数字员工的场景专属能力：开场任务清单里的专属卡片，及其背后的汇总 / 查询。

全部基于已有的审查结论与制度知识库，只读：
- insight：跨单据汇总最近一次（未被取代的）审查报告中指定规则的命中，附证据与报告入口
- authority：事项审批权限查询（与三会审查「制度检索」节点同一套制度知识库与金额档位判断）
"""
from __future__ import annotations

import re

from shared.regulation_kb.base import RegulationBase
from shared.regulation_kb.regulations import describe_range, in_range, meeting_of

# 每个员工的专属卡片（顺序即展示顺序）。kind：list 采集列表 / insight 汇总 / authority 权限查询 /
# regs 制度依据 / standards 报销标准
SCENES: dict[str, list[dict]] = {
    "procurement": [
        {"id": "list", "kind": "list", "list": "采购结果审批台账·最近", "title": "采购结果台账 · 最近单据",
         "desc": "合同系统采购结果审批台账最近 {total} 笔：已审查 {reviewed}，待审 {todo}{next}"},
        {"id": "collusion", "kind": "insight", "title": "串标线索汇总",
         "desc": "跨单据汇总投标文件作者相同、材料信息雷同、报价规律性差异等线索（{hits} 条命中），附证据"},
    ],
    "contract": [
        {"id": "list", "kind": "list", "list": "主合同台账·最近", "title": "主合同台账 · 最近单据",
         "desc": "合同系统主合同台账最近 {total} 笔：已审查 {reviewed}，待审 {todo}{next}"},
        {"id": "credit", "kind": "insight", "title": "主体资信与授权风险汇总",
         "desc": "按单据汇总合同主体资信、分公司授权、重复签订等外部数据核查结果（{hits} 条需关注）"},
        {"id": "clauses", "kind": "insight", "title": "条款比对问题汇总",
         "desc": "汇总价款、范围、工期、人员、付款、违约等条款与中标文件不一致之处（{hits} 条需关注）"},
    ],
    "meeting": [
        {"id": "authority", "kind": "authority", "title": "事项审批权限查询",
         "desc": "输入事项与金额，按四份制度查出该上什么会、由谁审批，并引用原文条款"},
        {"id": "regs", "kind": "regs", "title": "四份制度依据",
         "desc": "权责手册、重大经营管理事项清单、党委决定事项清单、董事会授权方案的启用状态与条款数"},
    ],
    "reimburse": [
        {"id": "list", "kind": "list", "list": "本地事项·报销", "title": "本地报销事项",
         "desc": "通财云外网不可达，当前审查本地导入的报销单 {total} 笔：已审查 {reviewed}，待审 {todo}{next}"},
        {"id": "standards", "kind": "standards", "title": "按单据类别查看报销标准",
         "desc": "差旅、招待、办公、车辆、交通、会议、培训、通用、资产九类单据各自的核对项"},
        {"id": "invoice", "kind": "insight", "title": "票据风险汇总",
         "desc": "汇总连号发票、上年度发票、敏感单位、预付储值等票据风险（{hits} 条命中）"},
    ],
}

# 汇总口径：哪些规则、哪些结论算「需关注」
INSIGHTS: dict[str, dict] = {
    "collusion": {"employee": "procurement", "rules": ["P10", "P11", "P12", "P13", "P14"],
                  "title": "串标线索汇总", "hit": {"命中"}},
    "credit": {"employee": "contract", "rules": ["R16", "R17", "R21"], "title": "主体资信与授权风险汇总",
               "hit": {"issue", "review"}},
    "clauses": {"employee": "contract", "rules": ["R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R30"],
                "title": "条款比对问题汇总", "hit": {"issue", "review"}},
    "invoice": {"employee": "reimburse", "category": "风险", "title": "票据风险汇总", "hit": {"issue", "review"}},
}


def latest_reports(store, employee: str, limit: int = 200) -> list[tuple[dict, dict]]:
    """每笔单据最近一次已完成、未被取代的审查报告。"""
    out, seen = [], set()
    for t in store.list_tasks(employee, limit):
        key = (t["source"], t["request_id"])
        if key in seen or t["status"] != "done" or t.get("superseded_by"):
            continue
        rep = store.get_report(t["task_id"])
        if rep:
            seen.add(key)
            out.append((t, rep))
    return out


def _rule_selected(spec: dict, r: dict) -> bool:
    if spec.get("rules"):
        return r.get("rule_id") in spec["rules"]
    return r.get("category") == spec.get("category")


def _hit(spec: dict, r: dict) -> bool:
    return (r.get("code") or r.get("status")) in spec["hit"]


def insight(store, name: str) -> dict:
    spec = INSIGHTS[name]
    reports = latest_reports(store, spec["employee"])
    rows, checked = [], 0
    for t, rep in reports:
        sel = [r for r in rep.get("rules") or [] if _rule_selected(spec, r)]
        if not sel:
            continue
        checked += 1
        hits = [r for r in sel if _hit(spec, r)]
        if not hits:
            continue
        h = rep.get("header") or {}
        rows.append({"task_id": t["task_id"], "request_id": t["request_id"], "source": t["source"],
                     "subject": h.get("subject") or h.get("采购内容") or h.get("request_name") or "",
                     "created_at": t["created_at"], "trigger_by": t["trigger_by"],
                     "hits": [{"rule_id": r["rule_id"], "name": r["name"], "status": r.get("status"), "code": r.get("code"),
                               "message": r.get("message"), "evidence": (r.get("evidence") or [])[:3]} for r in hits]})
    by_rule: dict[str, dict] = {}
    for row in rows:
        for hh in row["hits"]:
            b = by_rule.setdefault(hh["rule_id"], {"rule_id": hh["rule_id"], "name": hh["name"], "n": 0})
            b["n"] += 1
    return {"name": name, "title": spec["title"], "reviewed": len(reports), "checked": checked, "rows": rows,
            "by_rule": sorted(by_rule.values(), key=lambda b: (-b["n"], b["rule_id"])),
            "hits": sum(len(r["hits"]) for r in rows)}


def hit_count(store, name: str) -> int:
    try:
        return insight(store, name)["hits"]
    except Exception:  # noqa: BLE001
        return 0


# ------------------------------------------------------------------ 三会：事项审批权限查询
def parse_amount_wan(text: str) -> float | None:
    """「80」「80万」「80万元」「1200000元」「1.2亿」→ 万元。"""
    s = re.sub(r"[\s,，]", "", str(text or ""))
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(亿元|亿|万元|万|元)?", s)
    if not m:
        return None
    v, unit = float(m.group(1)), m.group(2) or "万元"
    return v * 1e4 if unit.startswith("亿") else v / 1e4 if unit == "元" else v


def authority(kb: RegulationBase, matter: str, amount_wan: float | None, top: int = 5) -> dict:
    """按事项描述检索制度条款，并按金额落档，给出审批 / 决策主体与应上的会议。"""
    yuan = amount_wan * 1e4 if amount_wan is not None else None
    out = []
    for score, c in kb.search(matter, top * 2):
        tiers, seen = [], set()
        same = kb.lookup(c.doc_id, c.dept or None, c.no) if c.no is not None else []
        for t in same or [c]:
            key = (t.tier, t.sub, tuple(t.final))
            if key in seen:
                continue
            seen.add(key)
            fit = in_range(t.range, yuan) if (yuan is not None and t.range) else None
            steps = sorted((s for s in t.steps or [] if isinstance(s, dict)),
                           key=lambda s: (s.get("order") is None, s.get("order") or 0))
            tiers.append({"tier": t.tier or "（不分档）", "sub": t.sub, "range": describe_range(t.range),
                          "final": t.final, "meetings": t.meetings, "fit": fit, "page": t.page,
                          "steps": [{"subject": s.get("subject"), "mark": s.get("mark") or "", "final": bool(s.get("red"))}
                                    for s in steps]})
        fits = [t for t in tiers if t["fit"]]
        if yuan is not None and any(t["range"] for t in tiers):
            status = "matched" if len({tuple(t["meetings"]) for t in fits}) == 1 and fits else \
                "ambiguous" if fits else "no_tier"
        else:
            status = "matched" if len(tiers) == 1 else "need_amount" if any(t["range"] for t in tiers) else "multi"
        pick = fits[0] if fits else tiers[0] if len(tiers) == 1 else None
        meetings = (pick or {}).get("meetings") or ([meeting_of(x) for x in (pick or {}).get("final") or []])
        out.append({"doc": c.doc_name, "doc_id": c.doc_id, "ref": c.ref, "dept": c.dept, "title": c.title,
                    "category": c.category, "score": score, "page": c.page, "status": status, "tiers": tiers[:8],
                    "final": (pick or {}).get("final") or [], "meetings": meetings})
        if len(out) >= top:
            break
    return {"matter": matter, "amount_wan": amount_wan, "results": out,
            "docs": [d for d in kb.documents() if d["state"] == "enabled"]}
