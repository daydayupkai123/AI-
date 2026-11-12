"""工作台任务列表与详情：把审查记录、采集快照合成为「一张单据的一个版本 = 一个任务」。

任务编号按员工顺序分配（SH-001、CG-001、CT-001、BX-001），首次出现时写入 work_item；同一单据材料指纹变化后
新开一个任务编号（V2）。状态：待执行（资料就绪且尚未审查）→ 执行中 → 已完成 / 失败。
结论文案统一为：建议驳回、风险提示、初审通过、无法校验、不适用、审查中止、未执行。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from workbench_service.auth import require
from storage_service import settings as rc_settings
from storage_service.client import default_client
from shared.task_store import Store
from employee_registry import registry

router = APIRouter()
store = Store()


def resources():
    return default_client()

PREFIX = {"procurement": "CG", "contract": "CT", "meeting": "SH", "reimburse": "BX"}
REVIEW_STATUS = ("待复核", "确认问题", "误报", "已忽略")
# 一期工作台只展示真实采集单据：排除本地样例 / DEMO mock
EXCLUDE_SOURCES = frozenset({"local"})


def _is_real_work_item(item: dict) -> bool:
    src = (item.get("source_system") or "").strip()
    rid = str(item.get("request_id") or "").strip()
    if src in EXCLUDE_SOURCES:
        return False
    if rid.upper().startswith("DEMO-"):
        return False
    return True

# 各员工原 status / code → 统一文案。采购还没有 code，用旧 status 名映射。
LABEL = {
    "issue": "建议驳回", "review": "风险提示", "pass": "初审通过", "missing": "无法校验",
    "na": "不适用", "error": "审查中止", "notrun": "未执行",
    "命中": "风险提示", "一定不通过": "建议驳回", "拿不准": "风险提示", "未命中": "初审通过",
    "未能识别": "无法校验", "未执行": "未执行", "发现问题": "建议驳回", "人工复核": "风险提示",
    "核查通过": "初审通过", "待补充": "无法校验", "存在风险": "风险提示", "通过": "初审通过",
}


def _label(code: str | None, status: str | None = None) -> str:
    return LABEL.get(code or "") or LABEL.get(status or "") or (status or code or "—")


def _employee(employee_id: str) -> registry.Employee:
    emp = registry.get(employee_id)
    if not emp:
        raise HTTPException(404, f"未知数字员工：{employee_id}")
    return emp


def _ensure_work_items(employee: str) -> list[dict]:
    """首次访问时把历史审查记录与采集快照登记为工作台任务；之后只补新出现的。"""
    items = store.work_items(employee)
    known = {(i["source_system"], i["request_id"], i["material_fp"]) for i in items}
    known_open = {(i["source_system"], i["request_id"]) for i in items if not i["material_fp"]}
    for t in store.employee_tasks(employee):
        if (t.get("source_system") or "") in EXCLUDE_SOURCES:
            continue
        if str(t.get("request_id") or "").upper().startswith("DEMO-"):
            continue
        fp = t.get("material_fp")
        key = (t["source_system"], t["request_id"], fp)
        if key in known:
            continue
        open_key = (t["source_system"], t["request_id"])
        if not fp and open_key in known_open:
            continue
        if fp and open_key in known_open:
            for it in items:
                if (it["source_system"], it["request_id"]) == open_key and not it["material_fp"]:
                    store.bind_work_item(employee, it["seq"], fp)
                    it["material_fp"] = fp
                    known.add((it["source_system"], it["request_id"], fp))
                    known_open.discard(open_key)
                    break
            continue
        seq = store.add_work_item(employee, t["source_system"], t["request_id"], fp, t["created_at"])
        store.add_op_log(employee, seq, t["task_id"], "system", "创建任务",
                         f"审查 {t['task_id'][:8]} · 状态 {t['status']}", "系统")
        items.append({"employee": employee, "seq": seq, "source_system": t["source_system"],
                      "request_id": t["request_id"], "material_fp": fp, "created_at": t["created_at"]})
        known.add(key)
        if not fp:
            known_open.add(open_key)
    try:
        snaps = resources().requests(employee=employee, limit=500)
    except Exception:  # noqa: BLE001
        snaps = []
    for s in snaps:
        if s.get("stale") or s.get("list_scope") == "pending":
            continue
        if s.get("status") not in ("ready", "listed", "syncing", "failed"):
            continue
        if (s.get("source") or "") in EXCLUDE_SOURCES:
            continue
        if str(s.get("request_id") or "").upper().startswith("DEMO-"):
            continue
        key = (s["source"], s["request_id"])
        if any(i["source_system"] == key[0] and i["request_id"] == key[1] for i in items):
            continue
        # 资料就绪且未审查过 → 待执行任务
        if store.latest_task(employee, s["source"], s["request_id"]):
            continue
        seq = store.add_work_item(employee, s["source"], s["request_id"], s.get("material_fp"),
                                  s.get("listed_at") or s.get("first_seen_at") or 0)
        store.add_op_log(employee, seq, None, "system", "创建任务",
                         f"采集登记 · {s.get('list_name') or s['source']}", "系统")
        items.append({"employee": employee, "seq": seq, "source_system": s["source"],
                      "request_id": s["request_id"], "material_fp": s.get("material_fp"),
                      "created_at": s.get("listed_at") or s.get("first_seen_at") or 0})
    return items


def _task_of(item: dict) -> dict | None:
    """选该工作台任务对应的审查记录：优先匹配材料指纹，否则取最新一次。"""
    rows = [t for t in store.employee_tasks(item["employee"])
            if t["source_system"] == item["source_system"] and t["request_id"] == item["request_id"]]
    if not rows:
        return None
    if item.get("material_fp"):
        hit = [t for t in rows if t.get("material_fp") == item["material_fp"]]
        if hit:
            return max(hit, key=lambda t: t["created_at"])
    return max(rows, key=lambda t: t["created_at"])


def _snap_of(item: dict) -> dict | None:
    try:
        return resources().request(item["source_system"], item["request_id"])
    except Exception:  # noqa: BLE001
        return None


def _report_of(task: dict | None) -> dict | None:
    return store.get_report(task["task_id"]) if task and task["status"] == "done" else None


def _status_of(task: dict | None, snap: dict | None) -> tuple[str, str | None]:
    if task:
        if task["status"] == "running":
            return "执行中", None
        if task["status"] == "failed":
            return "失败", task.get("error")
        if task["status"] == "done":
            return "已完成", None
    if snap and snap.get("status") == "failed":
        return "失败", snap.get("error") or "资料同步失败"
    return "待执行", None


def _header(rep: dict | None, snap: dict | None, item: dict) -> dict:
    h = (rep or {}).get("header") or {}
    facts = {k: v for k, v in (h.get("facts") or [])}
    return {
        "title": h.get("subject") or h.get("request_name") or h.get("采购内容") or (snap or {}).get("title")
                 or item["request_id"],
        "request_id": item["request_id"],
        "source": item["source_system"],
        "list_name": (snap or {}).get("list_name"),
        "workflow_name": h.get("workflow_name") or (snap or {}).get("workflow_name"),
        "facts": facts,
        "applicant": facts.get("申请人") or facts.get("报销人"),
        "category": facts.get("事项类型") or facts.get("单据类型") or facts.get("业务类型")
                    or facts.get("采购方式"),
        "meeting_type": facts.get("会议类型"),
        "amount": facts.get("涉及金额") or facts.get("合同额（表单）") or facts.get("报销金额")
                  or h.get("预算") or h.get("采购价格"),
    }


def _row(employee: str, item: dict) -> dict:
    task, snap = _task_of(item), _snap_of(item)
    rep = _report_of(task)
    status, reason = _status_of(task, snap)
    h = _header(rep, snap, item)
    codes = ((rep or {}).get("summary") or {}).get("codes") or {}
    return {
        "id": f"{PREFIX[employee]}-{item['seq']:03d}",
        "seq": item["seq"],
        "employee": employee,
        "version": sum(1 for i in store.work_items(employee)
                       if i["source_system"] == item["source_system"] and i["request_id"] == item["request_id"]
                       and i["seq"] <= item["seq"]),
        "status": status,
        "reason": reason,
        "created_at": item["created_at"],
        "started_at": task["created_at"] if task else None,
        "finished_at": task.get("finished_at") if task else None,
        "task_id": task["task_id"] if task else None,
        "trigger_by": task.get("trigger_by") if task else None,
        "title": h["title"],
        "request_id": item["request_id"],
        "source": item["source_system"],
        "list_name": h["list_name"],
        "applicant": h["applicant"],
        "category": h["category"],
        "meeting_type": h["meeting_type"],
        "amount": h["amount"],
        "hint_count": int(codes.get("issue") or 0) + int(codes.get("review") or 0)
                      + int(codes.get("missing") or 0) + int(codes.get("error") or 0),
        "verdict": (rep or {}).get("verdict"),
    }


def _suggestion(rules: list[dict]) -> str:
    points = []
    for r in rules:
        if r["label"] in ("建议驳回", "风险提示", "无法校验", "审查中止"):
            for it in r.get("items") or []:
                if it and it not in points:
                    points.append(it)
            if not r.get("items") and r.get("message") and r["message"] not in points:
                # 去掉状态前缀，只保留说明
                msg = r["message"]
                for p in ("建议驳回：", "风险提示：", "无法校验：", "审查中止：", "发现问题：", "待人工复核：",
                          "待补充：", "核查通过：", "通过："):
                    if msg.startswith(p):
                        msg = msg[len(p):]
                        break
                if msg and msg not in points:
                    points.append(msg)
    if not points:
        return "各审查节点已完成初审，未发现需补充或更正的事项。请结合原始材料复核后作出审批决定。"
    return "请复核以下事项，并按需补充或更正材料。\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(points, 1))


def _rules(rep: dict | None, marks: dict) -> list[dict]:
    out = []
    for i, r in enumerate((rep or {}).get("rules") or [], 1):
        code, status = r.get("code"), r.get("status")
        mark = marks.get(r["rule_id"]) or {}
        out.append({
            "no": f"{i:02d}", "rule_id": r["rule_id"], "name": r.get("name") or r["rule_id"],
            "code": code, "label": _label(code, status), "message": r.get("message") or "",
            "evidence": r.get("evidence") or [], "items": r.get("items") or [],
            "review_status": mark.get("status") or "待复核", "review_note": mark.get("note") or "",
            "review_by": mark.get("updated_by"), "review_at": mark.get("updated_at"),
        })
    return out


@router.get("/api/{employee}/worklist")
def worklist(employee: str, request: Request):
    require(request)
    emp = _employee(employee)
    items = [i for i in _ensure_work_items(emp.id) if _is_real_work_item(i)]
    rows = [_row(emp.id, i) for i in items]
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    cfg = rc_settings.collect()
    src = emp.live_source
    scfg = (cfg.get("sources") or {}).get(src) or {}
    live = _collect_live(src)
    return {
        "employee": emp.id, "prefix": PREFIX[emp.id], "rows": rows,
        "metrics": {
            "total": len(rows),
            "pending": sum(r["status"] == "待执行" for r in rows),
            "running": sum(r["status"] == "执行中" for r in rows),
            "done": sum(r["status"] == "已完成" for r in rows),
            "failed": sum(r["status"] == "失败" for r in rows),
        },
        "collect": {
            "enabled": bool(scfg.get("enabled")),
            "interval_minutes": cfg.get("interval_minutes"),
            "active_hours": cfg.get("active_hours"),
            "auto_review": bool((cfg.get("auto_review") or {}).get(emp.id)),
            "source": src,
            **live,
        },
    }


def _collect_live(source: str) -> dict:
    """附带资料中心实时采集状态，供列表页展示进度。"""
    try:
        st = resources().collect_status() or {}
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "error": str(exc), "running": False, "queue_done": 0, "last_round": None}
    src = ((st.get("sources") or {}).get(source) or {})
    rounds = [r for r in (st.get("rounds") or []) if r.get("source") == source]
    last = rounds[0] if rounds else None
    return {
        "reachable": True,
        "active_now": bool(st.get("active_now")),
        "running": bool(src.get("running")),
        "last_error": src.get("last_error") or st.get("error"),
        "last_round_at": src.get("last_round_at"),
        "next_round_at": src.get("next_round_at"),
        "queue_done": int(((st.get("queue") or {}).get("done") or 0)),
        "lists": src.get("lists") or [],
        "last_round": None if not last else {
            "id": last.get("id"), "started_at": last.get("started_at"), "finished_at": last.get("finished_at"),
            "listed": last.get("listed"), "queued": last.get("queued"), "synced": last.get("synced"),
            "failed": last.get("failed"), "error": last.get("error"),
        },
    }


@router.get("/api/{employee}/worklist/{work_id}")
def work_detail(employee: str, work_id: str, request: Request):
    require(request)
    emp = _employee(employee)
    items = [i for i in _ensure_work_items(emp.id) if _is_real_work_item(i)]
    try:
        seq = int(work_id.split("-")[-1])
    except ValueError:
        raise HTTPException(404, "任务编号无效") from None
    item = next((i for i in items if i["seq"] == seq), None)
    if not item:
        raise HTTPException(404, "任务不存在")
    task, snap = _task_of(item), _snap_of(item)
    rep = _report_of(task)
    status, reason = _status_of(task, snap)
    marks = store.review_marks(task["task_id"]) if task else {}
    rules = _rules(rep, marks)
    counts: dict[str, int] = {}
    for r in rules:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    timings = store.node_runs(task["task_id"]) if task else []
    return {
        "id": f"{PREFIX[emp.id]}-{seq:03d}", "seq": seq, "employee": emp.id, "status": status, "reason": reason,
        "version": sum(1 for i in items if i["source_system"] == item["source_system"]
                       and i["request_id"] == item["request_id"] and i["seq"] <= seq),
        "created_at": item["created_at"], "started_at": task["created_at"] if task else None,
        "finished_at": task.get("finished_at") if task else None,
        "task_id": task["task_id"] if task else None, "trigger_by": task.get("trigger_by") if task else None,
        "info": _header(rep, snap, item),
        "timings": [{"node": t["node"], "status": t["status"], "ms": t.get("duration_ms"),
                     "summary": t.get("summary"), "error": t.get("error")} for t in timings],
        "result": None if not rep else {
            "counts": counts, "suggestion": _suggestion(rules), "rules": rules,
            "verdict": rep.get("verdict"), "summary": rep.get("summary"),
        },
        "materials": (rep or {}).get("materials") or [
            {"filename": f.get("filename"), "sig": (f.get("content_sig") or "")[:16],
             "status": (f.get("parsed") or {}).get("status"), "pages": (f.get("parsed") or {}).get("pages"),
             "kind": (f.get("parsed") or {}).get("kind"), "role": None}
            for f in (snap or {}).get("files") or []
        ],
        "logs": [{"at": l["at"], "kind": l["kind"], "action": l["action"], "detail": l["detail"],
                  "actor": l["actor"]} for l in store.op_logs(emp.id, seq)],
    }


class MarkIn(BaseModel):
    rule_id: str
    status: str
    note: str = ""


class MarksIn(BaseModel):
    marks: list[MarkIn] = Field(default_factory=list)


@router.put("/api/{employee}/worklist/{work_id}/marks")
def save_marks(employee: str, work_id: str, body: MarksIn, request: Request):
    user = require(request, "admin", "reviewer")
    emp = _employee(employee)
    detail = work_detail(employee, work_id, request)
    if detail["status"] != "已完成" or not detail["task_id"]:
        raise HTTPException(400, "只有已完成的任务可以保存复核标注")
    marks = []
    for m in body.marks:
        if m.status not in REVIEW_STATUS:
            raise HTTPException(400, f"复核状态「{m.status}」不支持")
        marks.append({"rule_id": m.rule_id, "status": m.status, "note": (m.note or "")[:1000]})
    if not marks:
        raise HTTPException(400, "没有可保存的复核改动")
    store.save_review_marks(detail["task_id"], marks, user["username"])
    note = "、".join(f"{m['rule_id']} · {m['status']}" for m in marks)
    store.add_op_log(emp.id, detail["seq"], detail["task_id"], "review", "保存复核", note,
                     f"{user['name']}（{user['username']}）")
    return work_detail(employee, work_id, request)


@router.post("/api/{employee}/worklist/{work_id}/retry")
def retry(employee: str, work_id: str, request: Request):
    user = require(request, "admin", "reviewer")
    from workbench_service.server import launch

    emp = _employee(employee)
    detail = work_detail(employee, work_id, request)
    if detail["status"] != "失败":
        raise HTTPException(400, "只有失败的任务可以重新发起")
    tid = launch(emp, detail["request_id"], detail["info"]["source"], trigger_by=f"retry:{user['username']}")
    store.add_op_log(emp.id, detail["seq"], tid, "system", "提交重试",
                     f"由 {user['name']} 重新发起", f"{user['name']}（{user['username']}）")
    return {"task_id": tid, "id": detail["id"]}
