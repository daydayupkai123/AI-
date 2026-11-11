"""合同审核数字员工的 LangGraph 流程：取单 → 下载 → 解析 → 归集 → 台账 → 抽取 → 外部查询 → 规则 → 报告。

来源（source）：
  contract  合同管理系统（借用门户会话、接口回放；主合同审批流程）
  local     本地事项（.runtime/cases/contract/<单号>/case.json，联调与导入用）
"""
from __future__ import annotations

from core import ruleconfig

import json
from dataclasses import dataclass, replace
from typing import Any, Callable, TypedDict

from core import report as report_mod
from core import settings
from core.config import REPORTS
from core.errors import SessionExpired, WrongWorkflow
from core.external import ExternalUnavailable
from core.external.lists import NameList
from core.external.tianyancha import CachedTianyancha
from core.llm.judge import Judge
from core.materials import Material, download_all, materials_table, parse_all, unreadable
from core.rules.common import fmt_yuan
from core.rules.engine import run_rules
from core.runtime import Runtime, invoke, linear_graph
from core.session import SessionProvider
from core.sources import local
from core.sources.contract import HOST as CONTRACT_HOST
from core.sources.contract import SOURCE as CONTRACT_SOURCE
from core.sources.contract import ContractClient, RequestData
from core.storage import Store

from . import extract as extract_mod
from . import ledgers as ledgers_mod
from . import rules as rules_mod
from .materials import ROLE_LABELS, classify

EMPLOYEE = "contract"
NODES = ["取单", "读取台账", "下载附件", "解析材料", "归集材料", "抽取事实", "外部查询", "规则校验", "生成报告"]
NODE_HINTS = {
    "取单": "读取主合同审批表单与审批日志", "读取台账": "投标及报价台账（招标文件、投标文件、中标证明）、主合同台账",
    "下载附件": "下载合同正文、中标通知书与投标流程附件，计算内容签名",
    "解析材料": "文字层提取 / OCR / 解压，命中缓存直接复用", "归集材料": "识别合同正文、中标通知书、投标文件等",
    "抽取事实": "价款、主体、期限、付款、违约、仲裁等要素",
    "外部查询": "天眼查工商与风险、不合格供应商名单", "规则校验": "30 条规则并行执行", "生成报告": "汇总结论、证据与耗时",
}
SOURCES = (CONTRACT_SOURCE, local.SOURCE)


class State(TypedDict, total=False):
    request_id: str
    task_id: str
    source: str
    request: RequestData
    files: list[dict]
    materials: list[Material]
    ledgers: dict
    facts: dict
    external: dict
    results: list[dict]
    report: dict
    report_path: str


@dataclass
class Deps:
    judge: Callable[[str, str, str], dict] | None = None
    tianyancha: Any = None
    lists: dict | None = None
    tianyancha_injected: bool = False


def config() -> dict:
    return settings.load("contract.yaml")


def _form(req: RequestData) -> dict:
    return {f["label"]: f["display"] for f in req.fields if not f["field"].startswith("field-")}


def _check_workflow(req: RequestData, cfg: dict) -> None:
    wf = cfg.get("workflow") or {}
    ids = [str(x) for x in wf.get("workflow_ids") or []]
    ok = req.workflow_id in ids if ids else (wf.get("name_contains") or "主合同") in (req.workflow_name or "")
    if not ok:
        raise WrongWorkflow(f"单据 {req.request_id} 属于「{req.workflow_name or req.workflow_id}」"
                            f"（workflowid={req.workflow_id}），不是主合同审批流程",
                            title="该单号不是主合同审批流程",
                            hint="合同审核数字员工只审查合同管理系统中的「主合同审批」流程单据，请换一个单号。")


def _ledgers(rt: Runtime, source: str, req: RequestData, cfg: dict) -> dict:
    out = {}
    if source == local.SOURCE:
        given = req.extra.get("ledgers") or {}
        for key in ("bid_quote", "main_contract", "people"):
            out[key] = {"available": True, **given[key]} if key in given else \
                {"available": False, "reason": "本地事项未提供该台账"}
        return out
    ff = extract_mod.form_fields(_form(req), cfg.get("form_fields") or {})
    for key, fn in (("bid_quote", lambda: ledgers_mod.bid_record(rt, cfg, ff)),
                    ("main_contract", lambda: ledgers_mod.main_contract_rows(rt, cfg))):
        try:
            out[key] = fn()
        except SessionExpired:
            raise
        except Exception as exc:  # noqa: BLE001
            out[key] = {"available": False, "reason": f"读取失败：{type(exc).__name__}: {exc}"}
            rt.on_event({"type": "node.note", "text": f"{key} 读取失败：{exc}"})
    out["people"] = {"available": False, "reason": "通用人数据（人员所属部门）尚未接入"}
    return out


def build_graph(rt: Runtime, deps: Deps):
    cfg = config()

    def fetch(state: State) -> dict:
        req = rt.with_login(lambda c: c.fetch(state["request_id"]))
        if state["source"] == CONTRACT_SOURCE:
            _check_workflow(req, cfg)
        return {"request": req, "_summary": f"{req.workflow_name}｜{req.request_name}｜节点 {req.node_name}｜"
                                            f"附件 {len(req.attachments)}｜日志 {len(req.approval_log)}"
                                            f"{'｜监控方式' if req.via_monitor else ''}"}

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

    def read_ledgers(state: State) -> dict:
        req = state["request"]
        led = _ledgers(rt, state["source"], req, cfg)
        extra_atts = ledgers_mod.attachments_of(led.get("bid_quote") or {})
        if extra_atts:
            req = replace(req, attachments=list(req.attachments) + extra_atts)
        bid = led.get("bid_quote") or {}
        parts = []
        for k, v in led.items():
            label = v.get("name") or {"people": "人员数据"}.get(k, k)
            parts.append(f"{label} {'已读取' + ('（缓存）' if v.get('cached') else '') if v.get('available') else '不可用'}")
        if bid.get("available"):
            parts.append(f"投标流程 {bid['request_id']} 附件 {len(extra_atts)} 份")
        return {"request": req, "ledgers": led, "_summary": "；".join(parts)}

    def extract(state: State) -> dict:
        facts = extract_mod.extract(_form(state["request"]), state["materials"], cfg)
        facts["ledgers"] = state["ledgers"]
        facts["_request_id"] = state["request_id"]
        cp = (facts.get("counterparty") or {}).get("name")
        p = facts.get("price")
        return {"facts": facts, "_summary": (f"合同正文：{facts['contract'].name}｜相对方：{cp or '未识别'}｜"
                                             f"价款：{fmt_yuan(p['value']) if p else '未识别'}")
                if facts.get("contract") else "未找到可读取的合同正文"}

    def external(state: State) -> dict:
        facts = state["facts"]
        name = (facts.get("counterparty") or {}).get("name") or (facts.get("form", {}).get("甲方单位名称") or {}).get("value")
        ext: dict = {}
        extra = state["request"].extra
        if not name:
            ext["tianyancha"] = {"error": "未识别出合同相对方名称"}
        elif state["source"] == local.SOURCE and not extra.get("external_live") and not deps.tianyancha_injected:
            ext["tianyancha"] = extra.get("tianyancha") or {"error": "本地事项未附天眼查数据（本地事项默认不对外查询）"}
        else:
            try:
                ext["tianyancha"] = deps.tianyancha.profile(name)
            except ExternalUnavailable as exc:
                ext["tianyancha"] = {"error": f"{exc.title}：{exc.detail}", "failed": True, "hint": exc.hint}
                rt.on_event({"type": "node.note", "text": f"{exc.title}：{exc.detail}。{exc.hint}"})
        facts["external"] = ext
        facts["lists"] = deps.lists if deps.lists is not None else {
            "unqualified": NameList("unqualified_suppliers"), "standards": NameList("standards")}
        t = ext["tianyancha"]
        return {"facts": facts, "external": ext,
                "_summary": f"天眼查：{t.get('name') or name}{'（缓存）' if t.get('_cached_at') else ''}"
                if not t.get("error") else f"天眼查未完成：{t['error']}"}

    def check(state: State) -> dict:
        facts = state["facts"]
        facts["_judge"] = deps.judge or Judge(rt.store, state["task_id"], prompt_ver=rules_mod.VERSION, trace=rt.trace)

        def emit(r: dict) -> None:
            rt.on_event({"type": "rule.completed", "rule_id": r["rule_id"], "name": r["name"], "code": r["code"],
                         "status": r["status"], "category": r["category"], "message": r["message"], "ms": r["ms"]})

        results = run_rules(EMPLOYEE, rules_mod.VERSION, rules_mod.RULES, facts, on_result=emit)
        rt.store.save_rules(state["task_id"], results)
        n = {c: sum(1 for r in results if r["code"] == c) for c in ("issue", "review", "missing", "error")}
        return {"results": results, "_summary": f"30 条规则：发现问题 {n['issue']}，人工复核 {n['review']}，"
                                                f"待补充 {n['missing']}，审查中止 {n['error']}"}

    def make_report(state: State) -> dict:
        req, tid, facts = state["request"], state["task_id"], state["facts"]
        ff = facts.get("form") or {}
        cp = (facts.get("counterparty") or {}).get("name")
        header = {"title": "合同审核数字员工 · 审核报告", "request_id": req.request_id, "request_name": req.request_name,
                  "workflow_name": req.workflow_name, "node_name": req.node_name, "source": state["source"],
                  "subject": (ff.get("合同名称") or {}).get("value") or req.request_name,
                  "facts": [("合同名称", (ff.get("合同名称") or {}).get("value") or "—"),
                            ("业务类型", (ff.get("业务类型") or {}).get("value") or "—"),
                            ("合同额（表单）", ((ff.get("合同额") or {}).get("value") or "—")
                             + (" 万元" if "万元" in (ff.get("合同额") or {}).get("label", "") else "")),
                            ("合同价款（正文）", fmt_yuan(facts["price"]["value"]) if facts.get("price") else "未识别"),
                            ("合同相对方", cp or "未识别")]}
        verdict, notes = report_mod.default_verdict(state["results"])
        bad = unreadable(state["materials"])
        if bad:
            notes.append(f"{len(bad)} 个文件未能完整识别，相关规则可能为待补充：{'、'.join(m.name for m in bad[:6])}。")
        rep = report_mod.build_review(employee=EMPLOYEE, task_id=tid, rules_version=ruleconfig.effective_version(EMPLOYEE, rules_mod.VERSION), header=header,
                                      results=state["results"], materials=materials_table(state["materials"], ROLE_LABELS),
                                      timings=rt.store.node_runs(tid), cache=rt.store.cache_stats(tid),
                                      verdict=verdict, llm=rt.store.llm_stats(tid), notes=notes)
        rt.store.save_report(tid, rep)
        REPORTS.mkdir(parents=True, exist_ok=True)
        path = REPORTS / f"{EMPLOYEE}_{req.request_id}_{tid[:8]}.md"
        path.write_text(report_mod.review_markdown(rep), encoding="utf-8")
        path.with_suffix(".json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return {"report": rep, "report_path": str(path), "_summary": path.name}

    steps = [fetch, read_ledgers, download, parse, collect, extract, external, check, make_report]
    return linear_graph(rt, State, list(zip(NODES, steps)))


def create_task(store: Store, request_id: str, trigger_by: str = "cli", source: str = CONTRACT_SOURCE) -> str:
    return store.create_task(EMPLOYEE, source, str(request_id), ruleconfig.effective_version(EMPLOYEE, rules_mod.VERSION), trigger_by)


def run(request_id: str, store: Store, sessions: SessionProvider | None, on_event=None, task_id: str | None = None,
        source: str = CONTRACT_SOURCE, client=None, judge=None, tianyancha=None, lists: dict | None = None,
        resources=None) -> State:
    if source not in SOURCES:
        raise ValueError(f"不支持的来源：{source}")
    if client is None and source == local.SOURCE:
        client = local.LocalCaseClient(EMPLOYEE)
    rt = Runtime(store, sessions, on_event, client=client, client_factory=ContractClient, host=CONTRACT_HOST,
                 resources=resources)
    deps = Deps(judge=judge, tianyancha=tianyancha or CachedTianyancha(store), lists=lists,
                tianyancha_injected=tianyancha is not None)
    task_id = task_id or create_task(store, request_id, source=source)
    return invoke(store, task_id, build_graph(rt, deps),
                  {"request_id": str(request_id), "task_id": task_id, "source": source}, rt=rt)
