"""采购审批数字员工的 LangGraph 流程：取单 → 下载 → 解析 → 归集 → 抽取 → 规则 → 报告。"""
from __future__ import annotations

from shared import rule_config

import json
from typing import TypedDict

from shared import report_builder as report_mod
from shared.env_config import REPORTS
from shared.errors import WrongWorkflow
from shared.material_nodes import download_all, fetch_docs
from shared.parsing.pipeline import full_text
from shared.employee_runtime import Runtime, invoke, linear_graph
from shared.session import SessionProvider
from shared.source_adapters.contract import HOST as CONTRACT_HOST
from shared.source_adapters.contract import SOURCE, ContractClient, RequestData
from shared.task_store import Store

from . import extract as extract_mod
from . import rules as rules_mod
from .materials import (Material, classify, expand_names, looks_like_announcement, match_supplier,
                        supplier_from_response)

EMPLOYEE = "procurement"


class State(TypedDict, total=False):
    request_id: str
    task_id: str
    request: RequestData
    files: list[dict]
    materials: list[Material]
    suppliers: list[str]
    facts: dict
    results: list[dict]
    report: dict
    report_path: str


NODES = ["取单", "下载附件", "解析材料", "归集材料", "抽取事实", "规则校验", "生成报告"]


def build_graph(rt: Runtime):
    def fetch(state: State) -> dict:
        req = rt.with_login(lambda c: c.fetch(state["request_id"]))
        if req.workflow_id != "100":
            raise WrongWorkflow(f"单据 {req.request_id} 属于「{req.workflow_name or req.workflow_id}」"
                                f"（workflowid={req.workflow_id}），不是采购结果审批流程（workflowid=100）")
        return {"request": req, "_summary": f"{req.workflow_name}｜{req.request_name}｜节点 {req.node_name}｜"
                                            f"附件 {len(req.attachments)}｜日志 {len(req.approval_log)}"
                                            f"{'｜监控方式' if req.via_monitor else ''}"}

    def download(state: State) -> dict:
        files, summary = download_all(rt, state["request"], state["task_id"], SOURCE)
        return {"files": files, "_summary": summary}

    def parse(state: State) -> dict:
        infos = fetch_docs(rt, state["task_id"], state["request_id"], SOURCE, state["files"])
        by_sig = {}
        for i in infos:
            by_sig.setdefault((i["sig"], i.get("parent_sig")), i["doc"])
        tops = [Material(sig=f["sig"], filename=f["filename"], role=classify(f["filename"], f["field_label"]),
                         field_label=f["field_label"], doc=by_sig.get((f["sig"], None), {})) for f in state["files"]]
        children = []
        for m in tops:
            for c in m.doc.get("children", []):
                children.append(Material(sig=c["sig"], filename=c["name"], parent_sig=m.sig,
                                         role=m.role if m.role != "other" else classify(c["name"]),
                                         field_label=f"{m.filename} 内", doc=by_sig.get((c["sig"], m.sig), {})))
        mats = tops + children
        hits = sum(1 for m in mats if m.doc.get("_cache") == "hit")
        ocr_pages = sum(1 for m in mats for p in m.doc.get("pages", []) if p.get("method") == "ocr")
        failed = [m.filename for m in mats if m.doc.get("status") != "ok" and m.doc.get("kind") not in ("zip", "rar", "7z")]
        return {"materials": mats, "_summary": f"{len(mats)} 个文件（含压缩包内 {len(children)}）；缓存命中 {hits}；"
                                               f"OCR 页 {ocr_pages}；未完整识别 {len(failed)}"}

    def collect(state: State) -> dict:
        mats = state["materials"]
        if not any(m.role == "announcement" for m in mats):
            for m in mats:
                if m.role in ("publicity", "other") and looks_like_announcement(full_text(m.doc)):
                    m.role = "announcement"
                    break
        shorts = []
        for m in mats:
            if m.role == "response" and not m.parent_sig:
                s = supplier_from_response(m.filename)
                if s and s not in shorts:
                    shorts.append(s)
        ref_texts = [full_text(m.doc) for m in mats if m.role in ("review_report", "publicity", "announcement")]
        ref_texts.append(state["request"].value("候选供应商"))
        names = expand_names(shorts, ref_texts)
        suppliers = []
        for s in shorts:
            if names[s] not in suppliers:
                suppliers.append(names[s])
        cand = state["request"].value("候选供应商")
        for s in [x for x in cand.split("、") if x]:
            if s not in suppliers and not suppliers:
                suppliers.append(s)
        for m in mats:
            if m.role == "response" and not m.parent_sig:
                s = supplier_from_response(m.filename)
                m.supplier = names.get(s, s) if s else None
            elif m.parent_sig and m.role == "registration":
                folder = m.filename.split("/")[-2] if "/" in m.filename else m.filename
                m.supplier = match_supplier(folder, suppliers) or match_supplier(m.filename.rsplit("/", 1)[-1], suppliers)
        roles: dict[str, int] = {}
        for m in mats:
            roles[m.role_label] = roles.get(m.role_label, 0) + 1
        return {"suppliers": suppliers, "materials": mats,
                "_summary": f"供应商 {len(suppliers)} 家；" + "、".join(f"{k}{v}" for k, v in roles.items())}

    def extract(state: State) -> dict:
        req = state["request"]
        form = {f["label"]: f["display"] for f in req.fields if not f["field"].startswith("field-")}
        facts = extract_mod.extract(form, state["materials"], state["suppliers"])
        facts["has_review"] = any(m.role == "review_report" for m in state["materials"])
        facts["approval_log"] = req.approval_log
        got = [k for k in ("ann_publish_date", "deadline", "max_price_wan", "pdoc_publish_date", "review_date",
                           "review_method") if facts.get(k)]
        return {"facts": facts, "_summary": f"已识别 {len(got)}/6 项关键时间与金额；报价 {len(facts['quotes'])} 家"}

    def check(state: State) -> dict:
        results = rules_mod.run_all(state["facts"])
        rt.store.save_rules(state["task_id"], results)
        for r in results:
            rt.on_event({"type": "rule.completed", "rule_id": r["rule_id"], "name": r["name"], "status": r["status"],
                         "tier": r["tier"], "message": r["message"]})
        hits = sum(1 for r in results if r["status"] == "命中")
        return {"results": results, "_summary": f"18 条规则：命中 {hits}"}

    def make_report(state: State) -> dict:
        req, tid = state["request"], state["task_id"]
        header = {"title": "采购审批数字员工 · 分析报告", "request_id": req.request_id, "request_name": req.request_name,
                  "workflow_name": req.workflow_name, "node_name": req.node_name,
                  "采购内容": req.value("采购内容"), "采购方式": req.value("采购方式"),
                  "预算": req.value("预算价格（万元）"), "采购价格": req.value("采购价格（万元）"),
                  "候选供应商": req.value("候选供应商"), "suppliers": state["suppliers"]}
        mats = [{"role": m.role_label, "filename": m.filename, "supplier": m.supplier, "sig": m.sig[:16],
                 "status": m.doc.get("status"), "pages": len(m.doc.get("pages", [])), "cache": m.doc.get("_cache"),
                 "kind": m.doc.get("kind")} for m in state["materials"]]
        rep = report_mod.build(employee=EMPLOYEE, task_id=tid, rules_version=rule_config.effective_version(EMPLOYEE, rules_mod.RULES_VERSION), header=header,
                               results=state["results"], materials=mats, timings=rt.store.node_runs(tid),
                               cache=rt.store.cache_stats(tid))
        rt.store.save_report(tid, rep)
        REPORTS.mkdir(parents=True, exist_ok=True)
        path = REPORTS / f"procurement_{req.request_id}_{tid[:8]}.md"
        path.write_text(report_mod.to_markdown(rep), encoding="utf-8")
        (path.with_suffix(".json")).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str),
                                               encoding="utf-8")
        return {"report": rep, "report_path": str(path), "_summary": path.name}

    steps = [fetch, download, parse, collect, extract, check, make_report]
    return linear_graph(rt, State, list(zip(NODES, steps)))


def create_task(store: Store, request_id: str, trigger_by: str = "cli") -> str:
    return store.create_task(EMPLOYEE, SOURCE, str(request_id), rule_config.effective_version(EMPLOYEE, rules_mod.RULES_VERSION), trigger_by)


def run(request_id: str, store: Store, sessions: SessionProvider | None, on_event=None, task_id: str | None = None,
        client=None, resources=None) -> State:
    """client：直接给定取数客户端（离线重放用）；默认借用会话访问合同系统。"""
    rt = Runtime(store, sessions, on_event, client=client, client_factory=ContractClient, host=CONTRACT_HOST,
                 resources=resources)
    task_id = task_id or create_task(store, request_id)
    return invoke(store, task_id, build_graph(rt), {"request_id": str(request_id), "task_id": task_id}, rt=rt)
