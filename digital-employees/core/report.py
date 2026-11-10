"""把规则结果组织成报告（JSON + Markdown）。档位顺序：一定不通过 → 拿不准；未能识别单列。"""
from __future__ import annotations

from datetime import datetime

TIER_ORDER = ["一定不通过", "拿不准"]


def build(*, employee: str, task_id: str, rules_version: str, header: dict, results: list[dict],
          materials: list[dict], timings: list[dict], cache: dict) -> dict:
    hits = [r for r in results if r["status"] == "命中"]
    return {
        "employee": employee,
        "task_id": task_id,
        "rules_version": rules_version,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "header": header,
        "summary": {
            "规则总数": len(results),
            "命中": len(hits),
            "一定不通过": sum(1 for r in hits if r["tier"] == "一定不通过"),
            "拿不准": sum(1 for r in hits if r["tier"] == "拿不准"),
            "未命中": sum(1 for r in results if r["status"] == "未命中"),
            "未能识别": sum(1 for r in results if r["status"] == "未能识别"),
            "未执行": sum(1 for r in results if r["status"] == "未执行"),
        },
        "findings": sorted(hits, key=lambda r: (TIER_ORDER.index(r["tier"]), r["rule_id"])),
        "rules": results,
        "materials": materials,
        "timings": timings,
        "cache": cache,
    }


def _src(e: dict) -> str:
    parts = [e.get("file") or ""]
    if e.get("page"):
        parts.append(f"第{e['page']}页")
    return " ".join(p for p in parts if p)


def to_markdown(rep: dict) -> str:
    h, s = rep["header"], rep["summary"]
    lines = [f"# {h.get('title', '数字员工报告')}", "",
             f"- 单据：{h.get('request_name')}（{h.get('request_id')}）　流程：{h.get('workflow_name')}　当前节点：{h.get('node_name')}",
             f"- 采购内容：{h.get('采购内容')}　采购方式：{h.get('采购方式')}　预算：{h.get('预算')} 万元　采购价格：{h.get('采购价格')} 万元",
             f"- 候选供应商：{h.get('候选供应商')}　参与供应商：{'、'.join(h.get('suppliers') or []) or '—'}",
             f"- 任务：{rep['task_id']}　规则版本：{rep['rules_version']}　生成时间：{rep['generated_at']}", "",
             f"**结论概况**：规则 {s['规则总数']} 条，命中 {s['命中']}（一定不通过 {s['一定不通过']}、拿不准 {s['拿不准']}），"
             f"未命中 {s['未命中']}，未能识别 {s['未能识别']}，未执行 {s['未执行']}。", ""]
    for tier in TIER_ORDER:
        items = [r for r in rep["findings"] if r["tier"] == tier]
        lines.append(f"## {tier}（{len(items)}）")
        if not items:
            lines.append("无。")
        for r in items:
            lines.append(f"- **{r['rule_id']} {r['name']}**：{r['message']}")
            for e in (r.get("evidence") or [])[:4]:
                if isinstance(e, dict) and (e.get("file") or e.get("sources")):
                    src = _src(e) if e.get("file") else "；".join(_src(x) + f"（{x.get('supplier')}）" for x in e["sources"][:3])
                    snip = e.get("snippet") or e.get("value") or ""
                    lines.append(f"  - 依据：{src} {('「' + str(snip)[:80] + '」') if snip else ''}")
        lines.append("")
    unread = [r for r in rep["rules"] if r["status"] == "未能识别"]
    lines.append(f"## 未能识别（{len(unread)}）")
    lines += [f"- {r['rule_id']} {r['name']}：{r['message']}" for r in unread] or ["无。"]
    lines += ["", "## 规则执行情况", "", "| 规则 | 名称 | 档位 | 结果 | 说明 |", "|---|---|---|---|---|"]
    for r in rep["rules"]:
        lines.append(f"| {r['rule_id']} | {r['name']} | {r['tier']} | {r['status']} | {r['message'][:60]} |")
    lines += ["", "## 材料", "", "| 类型 | 文件 | 供应商 | 解析 | 页数 | 缓存 |", "|---|---|---|---|---|---|"]
    for m in rep["materials"]:
        lines.append(f"| {m['role']} | {m['filename']} | {m.get('supplier') or ''} | {m.get('status')} | "
                     f"{m.get('pages')} | {m.get('cache')} |")
    lines += ["", "## 节点耗时", ""]
    lines += [f"- {t['node']}：{(t['duration_ms'] or 0) / 1000:.1f}s {t.get('summary') or ''}"
              for t in rep["timings"] if t.get("duration_ms") is not None]
    return "\n".join(lines) + "\n"


# ====================================================================== 统一状态的报告（合同 / 三会 / 报销）

def default_verdict(results: list[dict]) -> tuple[dict, list[str]]:
    """整单结论 + 提示：有问题 → bad；有中止 → warn 并提示结论不完整；有复核/待补充 → warn；否则 good。"""
    n = {c: sum(1 for r in results if r["code"] == c) for c in ("issue", "review", "missing", "error")}
    notes = []
    if n["error"]:
        notes.append(f"{n['error']} 条规则因模型调用、外部查询或执行失败未形成结论（审查中止），本报告结论不完整，"
                     f"请处理后点「重新审查」。")
    if n["issue"]:
        v = {"level": "bad", "title": f"发现 {n['issue']} 项问题", "subtitle": "请逐条核实，每项问题均附原文依据"}
    elif n["error"]:
        v = {"level": "warn", "title": "部分规则未完成", "subtitle": f"{n['error']} 条规则审查中止，结论不完整"}
    elif n["review"] or n["missing"]:
        v = {"level": "warn", "title": "未发现明确问题，有事项需要确认",
             "subtitle": f"{n['review']} 项需人工复核、{n['missing']} 项待补充材料或数据"}
    else:
        v = {"level": "good", "title": "未发现异常", "subtitle": "已执行的规则均核查通过，仍请结合原件审核"}
    v["counts"] = n
    return v, notes


def build_review(*, employee: str, task_id: str, rules_version: str, header: dict, results: list[dict],
                 materials: list[dict], timings: list[dict], cache: dict, verdict: dict, llm: dict | None = None,
                 notes: list[str] | None = None) -> dict:
    from .rules import status as st
    from .rules.engine import summarize

    return {
        "employee": employee,
        "kind": "review",
        "task_id": task_id,
        "rules_version": rules_version,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "header": header,
        "verdict": verdict,
        "summary": summarize(employee, results),
        "labels": {code: st.label(employee, code) for code in st.CODES},
        "findings": [r for r in results if st.is_attention(r["code"])],
        "rules": results,
        "materials": materials,
        "timings": timings,
        "cache": cache,
        "llm": llm or {},
        "notes": notes or [],
    }


def review_markdown(rep: dict) -> str:
    from .rules import status as st

    h, s, v, labels = rep["header"], rep["summary"], rep.get("verdict") or {}, rep["labels"]
    lines = [f"# {h.get('title', '数字员工报告')}", "",
             f"- 单据：{h.get('request_name') or ''}（{h.get('request_id')}）　流程：{h.get('workflow_name') or ''}"
             f"　当前节点：{h.get('node_name') or ''}"]
    for k, val in (h.get("facts") or []):
        lines.append(f"- {k}：{val}")
    lines += [f"- 任务：{rep['task_id']}　规则版本：{rep['rules_version']}　生成时间：{rep['generated_at']}", "",
              f"**结论**：{v.get('title', '')}。{v.get('subtitle', '')}", "",
              "**统计**：" + "，".join(f"{labels[c]} {s['codes'].get(c, 0)}" for c in st.CODES if s["codes"].get(c)), ""]
    for note in rep.get("notes") or []:
        lines.append(f"> {note}")
    if rep.get("notes"):
        lines.append("")
    for code in (st.ISSUE, st.REVIEW, st.MISSING, st.ERROR):
        items = [r for r in rep["rules"] if r["code"] == code]
        lines.append(f"## {labels[code]}（{len(items)}）")
        if not items:
            lines.append("无。")
        for r in items:
            lines.append(f"- **{r['rule_id']} {r['name']}**：{r['message']}")
            for i, it in enumerate(r.get("items") or [], start=1):
                lines.append(f"  - （{i}）{it}")
            for e in (r.get("evidence") or [])[:4]:
                if isinstance(e, dict) and (e.get("file") or e.get("snippet")):
                    src = " ".join(x for x in (e.get("file") or "", f"第{e['page']}页" if e.get("page") else "") if x)
                    snip = e.get("snippet") or ""
                    lines.append(f"  - 依据：{src} {('「' + str(snip)[:100] + '」') if snip else ''}".rstrip())
        lines.append("")
    lines += ["## 规则执行情况", "", "| 编号 | 名称 | 类别 | 结果 | 说明 |", "|---|---|---|---|---|"]
    for r in rep["rules"]:
        msg = r["message"].replace("|", "｜").replace("\n", " ")
        lines.append(f"| {r['rule_id']} | {r['name']} | {r.get('group') or r.get('category') or ''} | {r['status']} | "
                     f"{msg[:80]} |")
    lines += ["", "## 材料", "", "| 类型 | 文件 | 解析 | 页数 | 缓存 |", "|---|---|---|---|---|"]
    for m in rep["materials"]:
        lines.append(f"| {m['role']} | {m['filename']} | {m.get('status')} | {m.get('pages')} | {m.get('cache')} |")
    lines += ["", "## 节点耗时", ""]
    lines += [f"- {t['node']}：{(t['duration_ms'] or 0) / 1000:.1f}s {t.get('summary') or ''}"
              for t in rep["timings"] if t.get("duration_ms") is not None]
    return "\n".join(lines) + "\n"
