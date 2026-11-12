"""「流程与规则」页接口：流程线、规则挂载与依赖、规则配置（草稿 / 发布 / 版本 / 回退 / 导入导出）、旧版规则报告。"""
from __future__ import annotations

import time

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from shared import rule_config, settings
from employee_registry import registry
from employee_registry.flows import FLOWS, deps_of, params_of

router = APIRouter()
TRIGGERS = ("auto", "batch", "web", "cli")


def _emp(employee: str):
    emp = registry.get(employee)
    if not emp or employee not in FLOWS:
        raise HTTPException(404, f"未知的数字员工：{employee}")
    return emp


def _store():
    from workbench_service import server

    return server.store


def _rule_states(emp) -> dict:
    from workbench_service import server

    return {r["rule_id"]: r for r in server.employee_rules(emp.id)["rules"]}


def _code_version(emp) -> str:
    return emp.rules_version


def _param_view(spec: dict, yaml_raw: dict, pub: dict, drf: dict) -> dict:
    p = spec["path"]
    return {**spec, "default": rule_config.get_path(yaml_raw, p),
            "published": (pub.get("params") or {}).get(p), "draft": (drf.get("params") or {}).get(p)}


def _rule_hits(employee: str) -> dict:
    from employee_registry.scenes import latest_reports

    out: dict[str, dict] = {}
    for _t, rep in latest_reports(_store(), employee, 100):
        for r in rep.get("rules") or []:
            k = r.get("code") or r.get("status") or ""
            d = out.setdefault(r["rule_id"], {})
            d[k] = d.get(k, 0) + 1
    return out


def flow_view(employee: str) -> dict:
    emp = _emp(employee)
    f = FLOWS[employee]
    raw = settings.load(f["config"], raw=True)
    n, pub_body = rule_config.published(employee)
    drf_body = rule_config.draft(employee)
    states = _rule_states(emp)
    hits = _rule_hits(employee)
    rules = []
    for c in emp.catalog():
        rid = c["rule_id"]
        pub, drf = (pub_body.get("rules") or {}).get(rid) or {}, (drf_body.get("rules") or {}).get(rid) or {}
        st = states.get(rid) or {}
        rules.append({**c, "exec": f["exec"], "deps": deps_of(employee, c), "state": st.get("state", "已上线"),
                      "tier": st.get("tier") or c.get("category"), "shared_with": (f.get("shared") or {}).get(rid),
                      "params": [_param_view(s, raw, pub, drf) for s in params_of(employee, rid)],
                      "published": pub, "draft": drf, "changed": pub != drf, "hits": hits.get(rid, {})})
    node_stats = _store().node_stats(employee)
    nodes = []
    for nd in f["nodes"]:
        nodes.append({**nd, "exec_rules": [r["rule_id"] for r in rules if r["exec"] == nd["name"]],
                      "dep_rules": [r["rule_id"] for r in rules if nd["name"] in r["deps"]],
                      "stats": node_stats.get(nd["name"])})
    flow_params = [{**s, "default": rule_config.get_path(raw, s["path"]),
                    "published": (pub_body.get("flow_params") or {}).get(s["path"]),
                    "draft": (drf_body.get("flow_params") or {}).get(s["path"])} for s in f.get("flow_params") or []]
    graph_nodes = list(emp.graph.NODES)
    return {"employee": {"id": emp.id, "persona": emp.persona, "name": emp.name, "status": emp.status, "dept": emp.dept},
            "code_version": _code_version(emp), "effective_version": rule_config.effective_version(employee, _code_version(emp)),
            "published_n": n, "has_draft": rule_config.has_draft(employee),
            "draft_changes": [list(x) for x in rule_config.diff(pub_body, drf_body)],
            "requirement": f["requirement"], "config_file": f"config/{f['config']}", "exec": f["exec"],
            "rules_are_nodes": bool(f.get("rules_are_nodes")), "tiers": f.get("tiers") or [],
            "nodes": nodes, "graph_nodes": graph_nodes, "plan": f["plan"], "flow_params": flow_params, "rules": rules,
            "outdated": len(outdated(employee)["rows"])}


@router.get("/api/flows")
def flows_index():
    out = []
    for e in registry.EMPLOYEES:
        if e.id not in FLOWS:
            continue
        n, _ = rule_config.published(e.id)
        out.append({"id": e.id, "persona": e.persona, "name": e.name, "status": e.status, "nodes": len(FLOWS[e.id]["nodes"]),
                    "rules": len(e.catalog()), "published_n": n, "has_draft": rule_config.has_draft(e.id),
                    "effective_version": rule_config.effective_version(e.id, e.rules_version)})
    return out


@router.get("/api/flows/{employee}")
def flow_detail(employee: str):
    return flow_view(employee)


class DraftIn(BaseModel):
    rules: dict = {}
    flow_params: dict = {}
    author: str = ""
    note: str = ""


def _check_value(spec: dict, v):
    t, label = spec["type"], spec["label"]
    if v is None:
        return None
    try:
        if t == "int":
            v = int(v)
        elif t == "number":
            v = float(v)
        elif t == "bool":
            v = bool(v) if isinstance(v, bool) else str(v).lower() in ("1", "true", "是", "yes", "on")
        elif t == "text":
            v = str(v).strip()
        elif t == "list":
            v = [str(x).strip() for x in (v if isinstance(v, list) else str(v).replace("，", ",").replace("\n", ",").split(","))
                 if str(x).strip()]
    except (TypeError, ValueError):
        raise HTTPException(400, f"「{label}」应为{ {'int': '整数', 'number': '数字'}.get(t, t) }") from None
    if t in ("int", "number"):
        if spec.get("min") is not None and v < spec["min"] or spec.get("max") is not None and v > spec["max"]:
            raise HTTPException(400, f"「{label}」应在 {spec.get('min')}–{spec.get('max')} 之间")
    return v


def validate(employee: str, body: dict) -> dict:
    emp = _emp(employee)
    ids = {c["rule_id"] for c in emp.catalog()}
    f = FLOWS[employee]
    rules = {}
    for rid, rc in (body.get("rules") or {}).items():
        if rid not in ids:
            raise HTTPException(400, f"规则 {rid} 不存在")
        rc = dict(rc or {})
        if rc.get("enabled") is False and not str(rc.get("reason") or "").strip():
            raise HTTPException(400, f"{rid} 停用时必须填写原因（报告中显示）")
        if rc.get("tier") and rc["tier"] not in (f.get("tiers") or []):
            raise HTTPException(400, f"{rid} 档位只能是 {'、'.join(f.get('tiers') or []) or '（该员工不支持调整档位）'}")
        specs = {s["path"]: s for s in params_of(employee, rid)}
        params = {}
        for p, v in (rc.get("params") or {}).items():
            if p not in specs:
                raise HTTPException(400, f"{rid} 没有可配置参数 {p}")
            if v is not None and v != "":
                params[p] = _check_value(specs[p], v)
        rc["params"] = params
        if rc.get("enabled") is True:
            rc.pop("enabled")  # 默认即启用，不单独存
            rc.pop("reason", None)
        rules[rid] = rc
    fspecs = {s["path"]: s for s in f.get("flow_params") or []}
    flow_params = {}
    for p, v in (body.get("flow_params") or {}).items():
        if p not in fspecs:
            raise HTTPException(400, f"流程没有可配置参数 {p}")
        if v is not None and v != "":
            flow_params[p] = _check_value(fspecs[p], v)
    return {"rules": rules, **({"flow_params": flow_params} if flow_params else {})}


@router.put("/api/flows/{employee}/draft")
def save_draft(employee: str, body: DraftIn):
    clean = validate(employee, body.model_dump())
    rule_config.save_draft(employee, clean, body.author, body.note)
    return flow_view(employee)


class PublishIn(BaseModel):
    author: str = ""
    note: str = ""


@router.post("/api/flows/{employee}/publish")
def publish(employee: str, body: PublishIn):
    _emp(employee)
    if not body.note.strip():
        raise HTTPException(400, "请填写发布说明（改了什么、为什么）")
    try:
        n = rule_config.publish(employee, body.author, body.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"n": n, **flow_view(employee)}


@router.post("/api/flows/{employee}/discard")
def discard(employee: str, body: PublishIn):
    _emp(employee)
    rule_config.discard_draft(employee, body.author)
    return flow_view(employee)


@router.get("/api/flows/{employee}/versions")
def versions(employee: str):
    _emp(employee)
    return {"versions": rule_config.versions(employee), "log": rule_config.log(employee, 60)}


@router.get("/api/flows/{employee}/versions/{n}")
def version(employee: str, n: int):
    _emp(employee)
    body = rule_config.version_body(employee, n)
    if body is None:
        raise HTTPException(404, "版本不存在")
    prev = rule_config.version_body(employee, n - 1) if n > 1 else rule_config.EMPTY
    return {"n": n, "body": body, "diff": [list(x) for x in rule_config.diff(prev, body)]}


@router.post("/api/flows/{employee}/rollback/{n}")
def rollback(employee: str, n: int, body: PublishIn):
    _emp(employee)
    try:
        rule_config.rollback_to(employee, n, body.author)
    except KeyError:
        raise HTTPException(404, "版本不存在") from None
    return flow_view(employee)


@router.get("/api/flows/{employee}/export")
def export(employee: str, which: str = "published"):
    emp = _emp(employee)
    body = rule_config.draft(employee) if which == "draft" else rule_config.published(employee)[1]
    doc = {"employee": employee, "persona": emp.persona, "code_version": emp.rules_version,
           "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"), "which": which, **body}
    text = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    return Response(text, media_type="text/yaml; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=rules_{employee}_{which}.yaml"})


class ImportIn(BaseModel):
    yaml_text: str
    author: str = ""


@router.post("/api/flows/{employee}/import")
def import_yaml(employee: str, body: ImportIn):
    try:
        doc = yaml.safe_load(body.yaml_text) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(400, f"YAML 格式错误：{exc}") from None
    if doc.get("employee") not in (None, employee):
        raise HTTPException(400, f"文件属于 {doc.get('employee')}，不能导入到 {employee}")
    clean = validate(employee, {"rules": doc.get("rules") or {}, "flow_params": doc.get("flow_params") or {}})
    rule_config.save_draft(employee, clean, body.author, note="导入 YAML")
    return flow_view(employee)


@router.get("/api/flows/{employee}/outdated")
def outdated(employee: str):
    """最近一次审查报告的规则版本与当前生效版本不同（按旧版规则生成）且可重审的单据。"""
    from workbench_service import server
    from employee_registry.scenes import latest_reports

    emp = _emp(employee)
    cur = rule_config.effective_version(employee, emp.rules_version)
    runnable = {(r["source"], r["request_id"]): r for r in server._queue(emp)["rows"] if r["runnable"]}
    rows = []
    for t, rep in latest_reports(_store(), employee, 200):
        if rep.get("rules_version") != cur:
            rows.append({"request_id": t["request_id"], "source": t["source"], "task_id": t["task_id"],
                         "rules_version": rep.get("rules_version"), "runnable": (t["source"], t["request_id"]) in runnable
                         or t["source"] == "local"})
    return {"current": cur, "rows": rows}
