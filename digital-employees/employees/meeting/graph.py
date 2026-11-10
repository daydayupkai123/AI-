"""三会审查数字员工的 LangGraph 流程：取单 → 下载 → 解析 → 归集 → 抽取要素 → 制度检索 → 审查（5 节点并行）→ 报告。

严格模式（config/meeting.yaml strict: true）：任一审查节点因模型调用失败或返回无法解析而中止时，整单审查中止，
不生成新的完整审查结论（需求 7.3、验收 T07）。

来源（source）：
  docflow  公文系统「内部请示」（取数适配器待登录后摸底，见 core/sources/docflow.py）
  local    本地事项（.runtime/cases/meeting/<单号>/case.json）
"""
from __future__ import annotations

from core import ruleconfig

import json
from dataclasses import dataclass
from typing import Callable, TypedDict

from core import report as report_mod
from core import settings
from core.config import REPORTS
from core.errors import DEError
from core.knowledge.base import RegulationBase, get_base
from core.llm.judge import Judge
from core.materials import Material, download_all, materials_table, parse_all, unreadable
from core.rules.common import fmt_wan
from core.rules.engine import run_rules
from core.runtime import Runtime, invoke, linear_graph
from core.session import SessionProvider
from core.sources import docflow, local
from core.sources.contract import RequestData
from core.storage import Store

from . import checks
from . import extract as extract_mod
from .checks.basis import resolve
from .materials import ROLE_LABELS, classify

EMPLOYEE = "meeting"
NODES = ["取单", "下载附件", "解析材料", "归集材料", "抽取要素", "制度检索", "审查", "生成报告"]
NODE_HINTS = {
    "取单": "读取 OA 表单（标题、会议类型、审批/上会依据）", "下载附件": "下载请示正文与附件，计算内容签名",
    "解析材料": "文字层提取，必要时 OCR；命中缓存直接复用", "归集材料": "识别请示正文、公告、评审报告、结果文件等",
    "抽取要素": "事项阶段、项目名称、金额、日期、评审信息", "制度检索": "在四份制度中定位所引用条款与金额档位",
    "审查": "5 个审查节点并行，各出一条综合意见", "生成报告": "按 01–05 固定顺序汇总",
}
SOURCES = (docflow.SOURCE, local.SOURCE)


class StrictAbort(DEError):
    title = "审查中止（严格模式）"
    hint = "大模型调用失败或返回无法解析，未生成新的完整审查结论。请确认 config/llm.yaml 中的模型服务可用后点「重新审查」。"


class State(TypedDict, total=False):
    request_id: str
    task_id: str
    source: str
    request: RequestData
    files: list[dict]
    materials: list[Material]
    facts: dict
    results: list[dict]
    report: dict
    report_path: str


@dataclass
class Deps:
    judge: Callable[[str, str, str], dict] | None = None
    kb: RegulationBase | None = None


def config() -> dict:
    return settings.load("meeting.yaml")


def build_graph(rt: Runtime, deps: Deps):
    cfg = config()

    def fetch(state: State) -> dict:
        req = rt.with_login(lambda c: c.fetch(state["request_id"]))
        return {"request": req, "_summary": f"{req.workflow_name}｜{req.request_name}｜附件 {len(req.attachments)}"}

    def download(state: State) -> dict:
        files, summary = download_all(rt, state["request"], state["task_id"], state["source"])
        return {"files": files, "_summary": summary}

    def parse(state: State) -> dict:
        mats, summary = parse_all(rt, state["task_id"], state["request_id"], state["source"], state["files"], classify)
        return {"materials": mats, "_summary": summary}

    def collect(state: State) -> dict:
        mats = state["materials"]
        roles: dict[str, int] = {}
        for m in mats:
            roles[ROLE_LABELS.get(m.role, m.role)] = roles.get(ROLE_LABELS.get(m.role, m.role), 0) + 1
        bad = unreadable(mats)
        if bad:
            rt.on_event({"type": "node.note", "text": f"{len(bad)} 个文件未能完整识别：{'、'.join(m.name for m in bad[:5])}"})
        return {"materials": mats, "_summary": "、".join(f"{k}{v}" for k, v in roles.items()) or "无附件"}

    def extract(state: State) -> dict:
        req = state["request"]
        form = {f["label"]: f["display"] for f in req.fields if not f["field"].startswith("field-")}
        facts = extract_mod.extract(form, state["materials"], cfg)
        amt = facts.get("case_amount")
        return {"facts": facts, "_summary": f"阶段：{facts.get('stage') or '未识别'}｜会议类型：{facts.get('meeting') or '未填写'}｜"
                                            f"金额：{fmt_wan(amt['value']) if amt else '未识别'}｜"
                                            f"请示正文：{facts['body'].name if facts.get('body') else '未找到'}"}

    def retrieve(state: State) -> dict:
        kb = deps.kb or get_base()
        facts = state["facts"]
        facts["resolution"] = resolve(facts, kb)
        res = facts["resolution"]
        enabled = [d for d in kb.documents() if d["state"] == "enabled"]
        m = res.get("matched")
        desc = {"matched": f"已定位 {m.describe()}" if m else "", "no_basis": "表单未填写依据",
                "not_found": "未能定位所引用条款", "no_amount": "条款分档但正文金额缺失",
                "no_item": f"依据未写明事项编号{('，摘录事项「' + res['quoted_item'] + '」未在制度中找到') if res.get('quoted_item') else ''}",
                "ambiguous_item": "摘录事项对应多项条款"}.get(res["status"], res["status"])
        return {"facts": facts, "_summary": f"已启用制度 {len(enabled)} 份、条款 {len(kb.clauses)} 条｜{desc}"}

    def review(state: State) -> dict:
        facts = state["facts"]
        facts["_judge"] = deps.judge or Judge(rt.store, state["task_id"], prompt_ver=checks.VERSION, trace=rt.trace)

        def emit(r: dict) -> None:
            rt.on_event({"type": "rule.completed", "rule_id": r["rule_id"], "name": r["name"], "code": r["code"],
                         "status": r["status"], "category": r["category"], "message": r["message"],
                         "items": r.get("items") or [], "ms": r["ms"]})

        results = run_rules(EMPLOYEE, checks.VERSION, checks.RULES, facts, on_result=emit, workers=5)
        rt.store.save_rules(state["task_id"], results)
        aborted = [r for r in results if r["code"] == "error"]
        if aborted and cfg.get("strict", True):
            raise StrictAbort("；".join(f"{r['rule_id']} {r['name']}：{r['message']}" for r in aborted))
        n = {c: sum(1 for r in results if r["code"] == c) for c in ("pass", "issue", "review", "missing")}
        return {"results": results, "_summary": f"核查通过 {n['pass']}，发现问题 {n['issue']}，待人工复核 {n['review']}，"
                                                f"待补充 {n['missing']}"}

    def make_report(state: State) -> dict:
        req, tid, facts = state["request"], state["task_id"], state["facts"]
        ff = facts.get("form") or {}
        amt = facts.get("case_amount")
        m = (facts.get("resolution") or {}).get("matched")
        header = {"title": "三会审查数字员工 · 审查报告", "request_id": req.request_id, "request_name": req.request_name,
                  "workflow_name": req.workflow_name, "node_name": req.node_name, "source": state["source"],
                  "subject": facts.get("title") or req.request_name,
                  "facts": [("标题", facts.get("title") or "—"),
                            ("事项类型", (ff.get("事项类型") or {}).get("value") or "—"),
                            ("会议类型", (ff.get("会议类型") or {}).get("value") or "—"),
                            ("审批/上会依据", facts.get("basis") or "—"),
                            ("识别阶段", facts.get("stage") or "未识别"),
                            ("涉及金额", fmt_wan(amt["value"]) if amt else "未识别"),
                            ("核实条款", m.describe() if m else "未定位")]}
        verdict, notes = report_mod.default_verdict(state["results"])
        kb_docs = (facts.get("resolution") or {}).get("docs") or []
        notes.append("制度依据：" + "、".join(f"《{d['name']}》" for d in kb_docs if d["state"] == "enabled") + "。")
        rep = report_mod.build_review(employee=EMPLOYEE, task_id=tid, rules_version=ruleconfig.effective_version(EMPLOYEE, checks.VERSION), header=header,
                                      results=state["results"], materials=materials_table(state["materials"], ROLE_LABELS),
                                      timings=rt.store.node_runs(tid), cache=rt.store.cache_stats(tid),
                                      verdict=verdict, llm=rt.store.llm_stats(tid), notes=notes)
        rt.store.save_report(tid, rep)
        REPORTS.mkdir(parents=True, exist_ok=True)
        path = REPORTS / f"{EMPLOYEE}_{req.request_id}_{tid[:8]}.md"
        path.write_text(report_mod.review_markdown(rep), encoding="utf-8")
        path.with_suffix(".json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return {"report": rep, "report_path": str(path), "_summary": path.name}

    steps = [fetch, download, parse, collect, extract, retrieve, review, make_report]
    return linear_graph(rt, State, list(zip(NODES, steps)))


def create_task(store: Store, request_id: str, trigger_by: str = "cli", source: str = docflow.SOURCE) -> str:
    rid = docflow.canonical_id(str(request_id)) if source == docflow.SOURCE else str(request_id)
    return store.create_task(EMPLOYEE, source, rid, ruleconfig.effective_version(EMPLOYEE, checks.VERSION), trigger_by)


def run(request_id: str, store: Store, sessions: SessionProvider | None, on_event=None, task_id: str | None = None,
        source: str = docflow.SOURCE, client=None, judge=None, kb: RegulationBase | None = None,
        resources=None) -> State:
    if source not in SOURCES:
        raise ValueError(f"不支持的来源：{source}")
    if client is None and source == local.SOURCE:
        client = local.LocalCaseClient(EMPLOYEE)
    if source == docflow.SOURCE:
        request_id = docflow.canonical_id(str(request_id))
    rt = Runtime(store, sessions, on_event, client=client, client_factory=docflow.DocflowClient, host=docflow.HOST,
                 system_name="公文系统", resources=resources)
    task_id = task_id or create_task(store, request_id, source=source)
    return invoke(store, task_id, build_graph(rt, Deps(judge=judge, kb=kb)),
                  {"request_id": str(request_id), "task_id": task_id, "source": source}, rt=rt)
