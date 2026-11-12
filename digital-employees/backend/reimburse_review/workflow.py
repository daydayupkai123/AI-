"""财务报销初审数字员工的 LangGraph 流程：取单 → 下载 → 解析 → 归集 → 抽取要素 → 规则校验（按单据类别）→ 报告。

结果两态（需求 4「结果怎么给人看」）：AI 初审通过 / AI 初审存在风险提示 N 项；需人工确认或补充的事项单独说明。
只出报告，不回写通财云、不做退回或加签（2026-11-09 决策：四个场景统一只读）。

来源（source）：
  fincloud  通财云（取数适配器待登录后摸底，见 shared/source_adapters/fincloud.py）
  local     本地事项（.runtime/cases/reimburse/<单号>/case.json，extra.claim 为单据结构化数据）
"""
from __future__ import annotations

from shared import rule_config

import json
from typing import TypedDict

from shared import report_builder as report_mod
from shared import settings
from shared.env_config import REPORTS
from shared.material_nodes import Material, download_all, materials_table, parse_all, unreadable
from shared.rule_framework.common import fmt_yuan
from shared.rule_framework.engine import run_rules
from shared.employee_runtime import Runtime, invoke, linear_graph
from shared.session import SessionProvider
from shared.source_adapters import fincloud, local
from shared.source_adapters.contract import RequestData
from shared.task_store import Store

from . import extract as extract_mod
from . import rules as rules_mod
from .materials import ROLE_LABELS, classify

EMPLOYEE = "reimburse"
NODES = ["取单", "下载附件", "解析材料", "归集材料", "抽取要素", "规则校验", "生成报告"]
NODE_HINTS = {
    "取单": "读取报销单表单、费用明细与发票信息", "下载附件": "下载发票、行程单、清单等附件",
    "解析材料": "文字层提取 / OCR，命中缓存直接复用", "归集材料": "识别行程单、招待清单、公函、维修清单等",
    "抽取要素": "确定适用的单据类别，补全发票要素", "规则校验": "按单据类别执行对应规则（共 43 条）",
    "生成报告": "两态结论 + 逐条提示",
}
SOURCES = (fincloud.SOURCE, local.SOURCE)


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


def config() -> dict:
    return settings.load("reimburse.yaml")


def verdict(results: list[dict]) -> tuple[dict, list[str]]:
    base, notes = report_mod.default_verdict(results)
    n = base["counts"]
    other = n["review"] + n["missing"] + n["error"]
    tail = f"另有 {other} 项需人工确认或补充材料" if other else "已执行的规则均未命中"
    if n["issue"]:
        v = {"level": "bad", "title": f"AI 初审存在风险提示 {n['issue']} 项", "subtitle": f"请逐条核实后再决定通过或退回；{tail}"}
    else:
        v = {"level": "warn" if other else "good", "title": "AI 初审通过",
             "subtitle": f"{tail}；通过只表示规则未命中，不代表业务真实合规"}
    v["counts"] = n
    return v, notes


def build_graph(rt: Runtime):
    cfg = config()

    def fetch(state: State) -> dict:
        req = rt.with_login(lambda c: c.fetch(state["request_id"]))
        claim = req.extra.get("claim") or {}
        return {"request": req, "_summary": f"{claim.get('doc_type') or req.workflow_name}｜{req.request_name}｜"
                                            f"附件 {len(req.attachments)}｜发票 {len(claim.get('invoices') or [])}"}

    def download(state: State) -> dict:
        files, summary = download_all(rt, state["request"], state["task_id"], state["source"])
        return {"files": files, "_summary": summary}

    def parse(state: State) -> dict:
        mats, summary = parse_all(rt, state["task_id"], state["request_id"], state["source"], state["files"], classify)
        return {"materials": mats, "_summary": summary}

    def collect(state: State) -> dict:
        mats = state["materials"]
        bad = unreadable(mats)
        if bad:
            rt.on_event({"type": "node.note", "text": f"{len(bad)} 个附件无法识别，相关规则将提示人工核对：{'、'.join(m.name for m in bad[:5])}"})
        return {"materials": mats, "_summary": f"{len(mats)} 个附件，无法识别 {len(bad)} 个"}

    def extract(state: State) -> dict:
        facts = extract_mod.extract(state["request"].extra.get("claim"), state["materials"], rt.resources.read_blob)
        facts["cfg"] = cfg
        roles: dict[str, int] = {}
        for m in facts["materials"]:
            roles[ROLE_LABELS.get(m.role, m.role)] = roles.get(ROLE_LABELS.get(m.role, m.role), 0) + 1
        groups = "、".join(rules_mod.GROUP_NAMES[g] for g in facts["groups"]) or "未识别"
        return {"facts": facts, "_summary": f"适用：{groups}｜发票 {len(facts['claim'].invoices)} 张｜"
                                            + "、".join(f"{k}{v}" for k, v in roles.items())}

    def check(state: State) -> dict:
        facts = state["facts"]
        rules = rules_mod.select(facts["groups"])

        def emit(r: dict) -> None:
            rt.on_event({"type": "rule.completed", "rule_id": r["rule_id"], "name": r["name"], "code": r["code"],
                         "status": r["status"], "category": r["category"], "group": r["group"],
                         "message": r["message"], "ms": r["ms"]})

        results = run_rules(EMPLOYEE, rules_mod.VERSION, rules, facts, on_result=emit) if rules else []
        rt.store.save_rules(state["task_id"], results)
        n = sum(1 for r in results if r["code"] == "issue")
        return {"results": results, "_summary": f"执行 {len(results)} 条（共 43 条，按单据类别），风险提示 {n}"}

    def make_report(state: State) -> dict:
        req, tid, facts = state["request"], state["task_id"], state["facts"]
        c = facts["claim"]
        groups = [rules_mod.GROUP_NAMES[g] for g in facts["groups"]]
        header = {"title": "财务报销初审数字员工 · 初审提示单", "request_id": req.request_id,
                  "request_name": req.request_name, "workflow_name": req.workflow_name, "node_name": req.node_name,
                  "source": state["source"], "subject": f"{c.doc_type or '报销单'}｜{c.reason or req.request_name}",
                  "facts": [("单据类型", c.doc_type or "—"), ("单据编码", c.code or req.request_id),
                            ("报销人", f"{c.applicant or '—'}（{c.dept or '—'}，{c.identity or '身份未填'}）"),
                            ("报销金额", fmt_yuan(c.amount)), ("报销事由", c.reason or "—"),
                            ("适用规则类别", "、".join(groups) or "未识别"), ("发票", f"{len(c.invoices)} 张")]}
        v, notes = verdict(state["results"])
        if not facts["groups"]:
            notes.append("未能从单据类型与费用明细识别出适用的报销类别，未执行任何规则，请人工审核。")
            v = {"level": "warn", "title": "未能识别单据类别", "subtitle": "未执行规则，请人工审核", "counts": v["counts"]}
        if not facts["has_claim"]:
            notes.append("未取得单据结构化数据（表单字段、费用明细），依赖表单的规则均为待补充。")
        if any(i.source == "text" for i in c.invoices):
            notes.append("部分发票要素由发票文件文字识别得到，请以原票为准。")
        rep = report_mod.build_review(employee=EMPLOYEE, task_id=tid, rules_version=rule_config.effective_version(EMPLOYEE, rules_mod.VERSION), header=header,
                                      results=state["results"], materials=materials_table(state["materials"], ROLE_LABELS),
                                      timings=rt.store.node_runs(tid), cache=rt.store.cache_stats(tid),
                                      verdict=v, llm=rt.store.llm_stats(tid), notes=notes)
        rt.store.save_report(tid, rep)
        REPORTS.mkdir(parents=True, exist_ok=True)
        path = REPORTS / f"{EMPLOYEE}_{req.request_id}_{tid[:8]}.md"
        path.write_text(report_mod.review_markdown(rep), encoding="utf-8")
        path.with_suffix(".json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return {"report": rep, "report_path": str(path), "_summary": path.name}

    steps = [fetch, download, parse, collect, extract, check, make_report]
    return linear_graph(rt, State, list(zip(NODES, steps)))


def create_task(store: Store, request_id: str, trigger_by: str = "cli", source: str = fincloud.SOURCE) -> str:
    return store.create_task(EMPLOYEE, source, str(request_id), rule_config.effective_version(EMPLOYEE, rules_mod.VERSION), trigger_by)


def run(request_id: str, store: Store, sessions: SessionProvider | None, on_event=None, task_id: str | None = None,
        source: str = fincloud.SOURCE, client=None, resources=None) -> State:
    if source not in SOURCES:
        raise ValueError(f"不支持的来源：{source}")
    if client is None and source == local.SOURCE:
        client = local.LocalCaseClient(EMPLOYEE)
    rt = Runtime(store, sessions, on_event, client=client, client_factory=fincloud.FincloudClient, host=fincloud.HOST,
                 system_name="通财云", resources=resources)
    task_id = task_id or create_task(store, request_id, source=source)
    return invoke(store, task_id, build_graph(rt), {"request_id": str(request_id), "task_id": task_id, "source": source},
                  rt=rt)
