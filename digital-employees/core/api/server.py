"""数字员工工作台（测试版）后端：发起审查、SSE 实时进度、历史报告、原件查看。

  .venv\\Scripts\\python.exe -m core.api.server        # http://127.0.0.1:8090
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import threading
import time
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.api.dispatch import AutoDispatcher
from core.chat import CHITCHAT_RE, OUT_OF_SCOPE, guide_text, report_related
from core.config import ROOT
from core.errors import SessionExpired, friendly
from core.parsing import ocr
from core.resource import settings as rc_settings
from core.resource.client import default_client
from core.resource.mask import mask_obj
from core.session import provider_from_config
from core.sources import local
from core.sources.contract import HOST as CONTRACT_HOST
from core.sources.contract import ContractClient
from core.storage import Store
from employees import registry

WEB = ROOT / "web"
store = Store()
sessions = provider_from_config()


class Bus:
    """每个任务的事件缓冲：运行线程写入，SSE 读取；任务结束后仍可回放。"""

    def __init__(self):
        self.events: dict[str, list[dict]] = {}
        self.done: set[str] = set()
        self.lock = threading.Lock()

    def emit(self, task_id: str, ev: dict) -> None:
        ev = {"at": time.time(), **ev}
        with self.lock:
            self.events.setdefault(task_id, []).append(ev)

    def finish(self, task_id: str) -> None:
        with self.lock:
            self.done.add(task_id)

    def read(self, task_id: str, start: int) -> tuple[list[dict], bool]:
        with self.lock:
            return self.events.get(task_id, [])[start:], task_id in self.done


bus = Bus()
run_slots = threading.Semaphore(2)
_samples: dict = {"at": 0, "rows": None, "error": None}


def resources():
    return default_client(sessions)


def launch(emp: registry.Employee, rid: str, source: str, trigger_by: str = "web") -> str:
    """建任务并在后台线程执行审查（人工发起与自动审查共用）。"""
    if emp.id == "procurement":
        task_id = emp.graph.create_task(store, rid, trigger_by=trigger_by)
    else:
        task_id = emp.graph.create_task(store, rid, trigger_by=trigger_by, source=source)
    bus.emit(task_id, {"type": "run.queued", "request_id": rid, "employee": emp.id, "source": source,
                       "trigger_by": trigger_by})
    threading.Thread(target=_run_thread, args=(emp, task_id, rid, source), daemon=True).start()
    return task_id


dispatcher = AutoDispatcher(store, resources, launch, registry.EMPLOYEES)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if rc_settings.mode() == "inprocess" and isinstance(ocr.engine(), ocr.RapidEngine):
        ocr.pool()  # 资料中心在本进程内运行时，主线程预建 OCR 进程池
    store.fail_stale_tasks()
    service = getattr(resources(), "service", None) if rc_settings.mode() == "inprocess" else None
    if service is not None and os.environ.get("DE_COLLECT", "1") != "0":
        service.start_background()  # 单进程模式：采集与同步队列随工作台运行
    if os.environ.get("DE_AUTO_REVIEW", "1") != "0":
        dispatcher.start()
    yield
    dispatcher.stop()
    if service is not None:
        service.stop_background()


app = FastAPI(title="AI 数字员工工作台（测试版）", lifespan=lifespan)


def _include_routers() -> None:
    from core.api.compare_api import router as compare_router
    from core.api.flows_api import router as flows_router

    app.include_router(flows_router)
    app.include_router(compare_router)


_include_routers()


@app.middleware("http")
async def revalidate_static(request, call_next):
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-cache"  # 前端改动后刷新即生效
    return resp


_WEB_AUTH = (os.environ.get("DE_WEB_USER", ""), os.environ.get("DE_WEB_PASSWORD", ""))


@app.middleware("http")
async def basic_auth(request, call_next):
    """对外开放时的访问口令（DE_WEB_USER / DE_WEB_PASSWORD 均设置才启用）。"""
    if not all(_WEB_AUTH):
        return await call_next(request)
    import base64
    import secrets as _secrets

    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    try:
        user, _, pwd = base64.b64decode(token).decode("utf-8").partition(":") if scheme.lower() == "basic" else ("", "", "")
    except Exception:  # noqa: BLE001
        user, pwd = "", ""
    if (_secrets.compare_digest(user.encode(), _WEB_AUTH[0].encode())
            and _secrets.compare_digest(pwd.encode(), _WEB_AUTH[1].encode())):
        return await call_next(request)
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="AI digital employees", charset="UTF-8"'})


class RunIn(BaseModel):
    employee: str = "procurement"
    request_id: str
    source: str | None = None


def _employee(employee_id: str) -> registry.Employee:
    emp = registry.get(employee_id)
    if not emp:
        raise HTTPException(404, f"未知的数字员工：{employee_id}")
    return emp


def _run_thread(emp: registry.Employee, task_id: str, request_id: str, source: str) -> None:
    with run_slots:
        t0 = time.time()
        bus.emit(task_id, {"type": "run.started", "request_id": request_id, "employee": emp.id, "source": source})
        try:
            kw = {} if emp.id == "procurement" else {"source": source}
            final = emp.graph.run(request_id, store, sessions, on_event=lambda e: bus.emit(task_id, e),
                                  task_id=task_id, **kw)
            bus.emit(task_id, {"type": "run.completed", "ms": int((time.time() - t0) * 1000),
                               "report": final["report"]})
        except Exception as exc:  # noqa: BLE001
            info = friendly(exc)
            store.finish_task(task_id, "failed", f"{info['title']}｜{info['detail']}")
            bus.emit(task_id, {"type": "run.failed", "error": info["title"], "hint": info["hint"],
                               "detail": info["detail"], "code": info["code"], "ms": int((time.time() - t0) * 1000)})
        finally:
            bus.finish(task_id)


SOURCE_NAME = {"contract": "合同系统", "docflow": "公文系统", "fincloud": "通财云", "local": "本地事项"}


def _rc_call(fn):
    try:
        return fn(), None
    except Exception as exc:  # noqa: BLE001
        info = friendly(exc)
        return None, f"{info['title']}。{info['hint']}"


@app.get("/api/center/overview")
def center_overview():
    """资料中心全流程演示：采集 → 取单与原件签名 → 解析 / OCR → 自动审查 → 执行档案，各环节的实时数字。"""
    rc = resources()
    stats, err = _rc_call(rc.stats)
    collect, err2 = _rc_call(rc.collect_status)
    tasks = store.task_stats()
    by_trigger: dict[str, int] = {}
    by_emp: dict[str, dict] = {}
    for t in tasks:
        by_trigger[t["trigger_by"] or "web"] = by_trigger.get(t["trigger_by"] or "web", 0) + t["n"]
        e = by_emp.setdefault(t["employee"], {"done": 0, "failed": 0, "running": 0, "superseded": 0})
        e[t["status"]] = e.get(t["status"], 0) + t["n"]
        e["superseded"] += t["superseded"] or 0
    return {"stats": stats, "collect": collect, "error": err or err2, "source_names": SOURCE_NAME,
            "tasks": {"by_trigger": by_trigger, "by_employee": by_emp,
                      "superseded": sum(e["superseded"] for e in by_emp.values())},
            "employees": [{"id": e.id, "persona": e.persona, "title": e.name, "sources": list(e.sources)}
                          for e in registry.EMPLOYEES]}


@app.get("/api/center/requests")
def center_requests(employee: str | None = None, limit: int = 60):
    """资料中心的单据快照（全部员工或指定员工），附工作台最近一次审查结论。"""
    emps = [_employee(employee)] if employee else registry.EMPLOYEES
    rows, err = [], None
    for emp in emps:
        q = _queue(emp, limit)
        err = err or q["error"]
        rows += [{**r, "employee": emp.id} for r in q["rows"]]
    rows.sort(key=lambda r: r.get("synced_at") or r.get("listed_at") or 0, reverse=True)
    return {"rows": rows[:limit], "error": err}


@app.get("/api/center/requests/{source}/{request_id:path}")
def center_request(source: str, request_id: str):
    """一笔单据在资料中心的全流程：采集登记 → 表单快照 → 附件（签名 / 解析 / OCR）→ 审查记录 → 执行档案。"""
    snap, err = _rc_call(lambda: resources().request(source, request_id))
    if err:
        raise HTTPException(503, err)
    if not snap:
        raise HTTPException(404, "资料中心没有这笔单据")
    snap["fields"] = mask_obj(snap.get("fields") or [])  # 演示页面与执行档案同样脱敏
    return {"snapshot": snap, "tasks": store.tasks_for(source, request_id), "source_name": SOURCE_NAME.get(source, source)}


@app.get("/api/employees")
def employees():
    out = []
    for e in registry.EMPLOYEES:
        last = store.list_tasks(e.id, 1)
        from core import ruleconfig

        out.append({**e.public(), "last_run": last[0]["created_at"] if last else None,
                    "effective_version": ruleconfig.effective_version(e.id, e.rules_version)})
    return out


@app.get("/api/{employee}/samples")
def samples(employee: str, refresh: bool = False):
    emp = _employee(employee)
    if emp.id == "procurement":
        return procurement_samples(refresh)
    cases = local.LocalCaseClient(emp.id).list()
    return {"rows": cases, "error": None if cases else "本地还没有样例事项，请运行 tools/make_demo_cases.py 生成。",
            "total": len(cases), "source": local.SOURCE, "live_ready": emp.live_ready, "live_note": emp.live_note}


def procurement_samples(refresh: bool = False):
    if _samples["rows"] is None or refresh or time.time() - _samples["at"] > 600:
        try:
            try:
                rows = ContractClient(sessions.session()).ledger("83")
            except SessionExpired:
                sessions.warmup(CONTRACT_HOST)
                rows = ContractClient(sessions.session()).ledger("83")
            rows = [r for r in rows if r.get("lcid")]
            rows.sort(key=lambda r: r.get("sqsj", ""), reverse=True)
            pick = [r for r in rows if "直接" not in r.get("cgfs", "")][:10]
            pick += [r for r in rows if r.get("cgfs") in ("竞争性谈判", "公开招标", "邀请招标")][:3]
            pick += [r for r in rows if "直接" in r.get("cgfs", "")][:2]
            seen, uniq = set(), []
            for r in pick:
                if r["lcid"] not in seen:
                    seen.add(r["lcid"])
                    uniq.append({"request_id": r["lcid"], "date": r.get("sqsj", "")[:10], "method": r.get("cgfs"),
                                 "amount": r.get("cgjg"), "content": r.get("cgnr"), "supplier": r.get("hxgyszb"),
                                 "applicant": r.get("sqr")})
            _samples.update(at=time.time(), rows=uniq, error=None, total=len(rows))
        except Exception as exc:  # noqa: BLE001
            info = friendly(exc)
            _samples.update(at=time.time(), error=f"{info['title']}。{info['hint']}")
            if _samples["rows"] is None:
                _samples["rows"] = [{"request_id": "1674771", "date": "2026-11-03", "method": "询价采购", "amount": "28.7",
                                     "content": "2026年11月绿色开采设计项目专家论证咨询服务", "supplier": "济宁华擎工程管理有限公司"}]
    return {"rows": _samples["rows"], "error": _samples["error"], "total": _samples.get("total")}


class ChatIn(BaseModel):
    employee: str = "procurement"
    message: str
    history: list[dict] = []
    task_id: str | None = None


@app.get("/api/llm/status")
def llm_status():
    from core.llm import client as llm

    try:
        return llm.status("chat")
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}


@app.post("/api/chat")
def chat(body: ChatIn):
    from core.llm import client as llm

    spec = _employee(body.employee)
    emp = spec.public()
    cfg = llm.config().get("chat") or {}
    report = store.get_report(body.task_id) if body.task_id else None
    if report and report.get("employee", "procurement") != spec.id:
        report = None
    if report is None or CHITCHAT_RE.match(body.message.strip()) or not report_related(body.message, report):
        # 受限对话：没有可追问的报告、闲聊、或问题与报告无关时不调模型，固定回复
        text = guide_text(emp, spec.chat.INPUT_HINT) if report is None or CHITCHAT_RE.match(body.message.strip()) \
            else OUT_OF_SCOPE

        def guide():
            yield f"data: {json.dumps({'type': 'guide', 'text': text}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'ms': 0, 'guide': True})}\n\n"

        return StreamingResponse(guide(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    history = [m for m in body.history if m.get("role") in ("user", "assistant") and m.get("content")]
    history = history[-int(cfg.get("max_history", 12)):]
    messages = [{"role": "system", "content": spec.chat.system_prompt(emp, report, body.message)},
                *[{"role": m["role"], "content": str(m["content"])[:4000]} for m in history],
                {"role": "user", "content": body.message}]

    def gen():
        t0 = time.time()
        try:
            p = llm.provider("chat")
            yield f"data: {json.dumps({'type': 'start', 'model': p.get('model'), 'provider': p['name']}, ensure_ascii=False)}\n\n"
            for ev in llm.stream(messages, "chat"):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'ms': int((time.time() - t0) * 1000)})}\n\n"
        except Exception as exc:  # noqa: BLE001
            msg = f"{type(exc).__name__}: {exc}"
            if "11434" in msg or "Connection" in type(exc).__name__ or "ConnectionError" in msg:
                ev = {"error": "无法连接本地大模型", "hint": "请打开 Ollama 客户端（模型目录 D:\\Model），看到右上角模型状态变绿后再发送。"}
            elif "not found" in msg.lower() and "model" in msg.lower():
                ev = {"error": "配置的模型不存在", "hint": "请检查 config/llm.yaml 中的 model 名称是否与 Ollama 中已有模型一致。"}
            else:
                ev = {"error": "对话模型返回了错误", "hint": "可以点「重新生成」再试；如反复出现，请检查 config/llm.yaml 配置。"}
            yield f"data: {json.dumps({'type': 'error', 'detail': msg, **ev}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/{employee}/rules")
def employee_rules(employee: str):
    emp = _employee(employee)
    if emp.id == "procurement":
        from employees.procurement import rules as rules_mod

        impl = {"P01", "P02", "P03", "P06", "P07", "P08", "P09", "P10", "P11", "P12", "P16", "P18"}
        return {"version": rules_mod.RULES_VERSION,
                "rules": [{"rule_id": rid, "name": name, "tier": tier,
                           "state": "已上线" if rid in impl else "待接入"} for rid, name, tier in rules_mod.META]}
    states = {}
    if emp.id == "reimburse":
        from core import settings

        for rid, conf in (settings.load("reimburse.yaml").get("rules") or {}).items():
            if not conf.get("enabled", True):
                states[rid] = "待业务口径"
            elif conf.get("threshold_pending"):
                states[rid] = "部分上线"
    return {"version": emp.rules_version, "layout": emp.layout,
            "rules": [{**r, "state": states.get(r["rule_id"], "已上线")} for r in emp.catalog()]}


@app.get("/api/knowledge")
def knowledge():
    from core.knowledge.base import get_base

    return {"documents": get_base().documents()}


@app.post("/api/runs")
def start_run(body: RunIn):
    emp = _employee(body.employee)
    rid = body.request_id.strip()
    source = body.source or emp.live_source
    if source not in emp.sources:
        raise HTTPException(400, f"{emp.name}不支持来源 {source}")
    if source == local.SOURCE:
        if rid not in {c["request_id"] for c in local.LocalCaseClient(emp.id).list()}:
            raise HTTPException(400, f"本地事项 {rid} 不存在，请在「样例单据」中选择")
    elif not emp.valid_live_id(rid):
        raise HTTPException(400, f"请输入{emp.id_hint}")
    return {"task_id": launch(emp, rid, source, "web"), "source": source}


@app.get("/api/runs/{task_id}/events")
async def run_events(task_id: str):
    if not store.get_task(task_id):
        raise HTTPException(404, "任务不存在")

    async def gen():
        idx = 0
        while True:
            evs, done = bus.read(task_id, idx)
            for ev in evs:
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
            idx += len(evs)
            if done and not evs:
                yield "event: end\ndata: {}\n\n"
                return
            if not evs and task_id not in bus.events:
                # 历史任务（非本次服务启动内运行）：直接回放报告
                rep = store.get_report(task_id)
                t = store.get_task(task_id)
                if rep:
                    yield f"data: {json.dumps({'type': 'run.completed', 'report': rep, 'replay': True}, ensure_ascii=False, default=str)}\n\n"
                elif t and t["status"] == "failed":
                    title, _, detail = (t["error"] or "审查过程中出现异常").partition("｜")
                    yield f"data: {json.dumps({'type': 'run.failed', 'error': title, 'detail': detail, 'hint': '可以点「重新审查」再试。'}, ensure_ascii=False)}\n\n"
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs")
def list_runs(employee: str = "procurement", limit: int = 30):
    return store.list_tasks(employee, limit)


@app.get("/api/runs/{task_id}")
def get_run(task_id: str):
    rep = store.get_report(task_id)
    if not rep:
        raise HTTPException(404, "报告不存在")
    return rep


def _queue(emp: registry.Employee, limit: int = 100) -> dict:
    """资料中心采集到的待审单据 + 工作台最近一次审查结论；runnable 表示可直接发起审查。"""
    cfg = rc_settings.collect()
    enabled = bool((cfg.get("auto_review") or {}).get(emp.id))
    paused = enabled and cfg.get("auto_review_concurrency") is not None and int(cfg["auto_review_concurrency"]) == 0
    auto = enabled and not paused
    try:
        snaps = resources().requests(employee=emp.id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        info = friendly(exc)
        return {"rows": [], "auto_review": auto, "auto_paused": paused, "error": f"{info['title']}。{info['hint']}"}
    rows = []
    for s in snaps:
        if s["source"] not in emp.sources:
            continue
        t = store.latest_task(emp.id, s["source"], s["request_id"])
        rep = store.get_report(t["task_id"]) if t and t["status"] == "done" else None
        locked = s.get("list_scope") == "pending" and not s.get("open_detail")
        changed = bool(t and t.get("material_fp") and s.get("material_fp") and t["material_fp"] != s["material_fp"])
        rows.append({
            "request_id": s["request_id"], "source": s["source"], "title": s.get("title"),
            "list_name": s.get("list_name"), "list_scope": s.get("list_scope"), "status": s["status"],
            "open_detail": bool(s.get("open_detail")), "files_total": s.get("files_total"),
            "parsed_ready": s.get("parsed_ready"), "error": s.get("error"), "synced_at": s.get("synced_at"),
            "listed_at": s.get("listed_at"), "stale": bool(s.get("stale")), "pending_locked": locked,
            "material_changed": changed,
            "runnable": not locked and not s.get("stale"),
            "needs_review": (not locked and not s.get("stale") and s["status"] == "ready"
                             and (t is None or changed or t["status"] == "failed")),
            "latest": None if not t else {
                "task_id": t["task_id"], "status": t["status"], "trigger_by": t["trigger_by"],
                "created_at": t["created_at"], "error": t.get("error"),
                "verdict": (rep or {}).get("verdict"), "summary": (rep or {}).get("summary")}})
    return {"rows": rows, "auto_review": auto, "auto_paused": paused, "error": None,
            "dispatcher_error": dispatcher.last_error}


@app.get("/api/{employee}/queue")
def employee_queue(employee: str, limit: int = 100):
    """任务台：资料中心采集到的待审单据 + 工作台最近一次审查结论。"""
    return _queue(_employee(employee), limit)


@app.get("/api/{employee}/tasks")
def employee_tasks(employee: str):
    """开场任务清单：数字员工可执行的流程与待审单据，前端点击即执行（不需要自由对话）。"""
    emp = _employee(employee)
    q = _queue(emp)
    rows = q["rows"]
    todo = [r for r in rows if r["needs_review"]]
    running = [r for r in rows if r.get("latest") and r["latest"]["status"] == "running"]
    cfg = rc_settings.collect()
    sources = {s for s in emp.sources
               if ((cfg.get("sources") or {}).get(s) or {}).get("enabled")
               and any(lst.get("employee") == emp.id for lst in ((cfg.get("sources") or {}).get(s) or {}).get("lists") or [])}
    stats = {"total": len(rows), "ready": sum(1 for r in rows if r["status"] == "ready"), "todo": len(todo),
             "running": len(running), "reviewed": sum(1 for r in rows if r.get("latest") and r["latest"]["status"] == "done"),
             "changed": sum(1 for r in rows if r["material_changed"]),
             "pending_locked": sum(1 for r in rows if r["pending_locked"]), "stale": sum(1 for r in rows if r["stale"]),
             "syncing": sum(1 for r in rows if r["open_detail"] and not r["stale"]
                            and r["status"] not in ("ready", "failed", "excluded"))}
    src_names = "、".join(SOURCE_NAME.get(s, s) for s in sorted(sources)) or "来源系统"
    auto_txt = "资料就绪后我也会自动审查" if q["auto_review"] else "自动审查已暂停" if q.get("auto_paused") else "需手动发起"

    def act(id_, title, desc, *, group="do", enabled=True, badge=None, off=None, **kw):
        return {"id": id_, "title": title, "desc": desc if enabled else (off or desc), "group": group,
                "enabled": enabled, "badge": badge, "label": f"{title}：{desc}", **kw}

    from employees import scenes

    scene_acts = []
    for sc in scenes.SCENES.get(emp.id, []):
        n: dict = {}
        if sc["kind"] == "list":
            in_list = [r for r in rows if r.get("list_name") == sc["list"]]
            n = {"total": len(in_list), "todo": sum(1 for r in in_list if r["needs_review"]),
                 "reviewed": sum(1 for r in in_list if r.get("latest") and r["latest"]["status"] == "done")}
            n["next"] = "；点开可一键审查待审单据" if n["todo"] else "；点开查看每笔结论与档案"
        elif sc["kind"] == "insight":
            n = {"hits": scenes.hit_count(store, sc["id"])}
        badge = n.get("todo") if sc["kind"] == "list" else n.get("hits")
        scene_acts.append(act(f"scene:{sc['id']}", sc["title"], sc["desc"].format(**n) if n else sc["desc"],
                              group="scene", badge=badge or None, kind=sc["kind"], list=sc.get("list"), counts=n))
    actions = scene_acts + [
        act("batch", "批量审查待审单据", f"一键审查 {len(todo)} 笔（资料已就绪、尚未审查或材料已变化），逐笔出报告并入档",
            enabled=bool(todo), badge=len(todo) or None, count=len(todo),
            off=f"暂无待审单据（{auto_txt}）"),
        act("run", "按单号审查一笔", f"输入{emp.id_hint}，立即取单、解析材料、逐条核验并出报告" if emp.live_ready
            else f"{emp.live_note.split('，')[0]}：当前只能输入本地事项编号（如 {(emp.examples or ['DEMO'])[0]}）审查",
            hint=emp.id_hint),
        act("collect", "立即采集最新单据", f"从{src_names}读取列表，提前下载附件、签名、解析入库，完成后刷新本清单",
            enabled=bool(sources), sources=sorted(sources), off="该员工的来源系统未开启采集"),
        act("queue", "待审单据与审查结果", f"共 {len(rows)} 笔：资料状态、最近结论、材料是否变化", group="view",
            badge=len(rows) or None),
        act("flow", "资料中心全流程", "演示：采集 → 签名入库 → 解析 / OCR → 自动审查 → 执行档案", group="view"),
        act("history", "历史报告与执行档案", "查看过往报告，回放每次执行的完整过程", group="view"),
        act("samples", "样例单据", "用本地样例体验完整审查流程", group="view"),
        act("rules", "规则清单", f"我核验的 {len(emp.catalog())} 条规则与上线状态", group="view"),
    ]
    return {"employee": emp.id, "actions": actions, "todo": todo[:8], "running": running[:5], "stats": stats,
            "auto_review": q["auto_review"], "auto_paused": q.get("auto_paused", False), "error": q["error"]}


@app.get("/api/{employee}/insights/{name}")
def employee_insight(employee: str, name: str):
    """场景汇总：跨单据汇总最近一次审查中指定规则的命中（只读已有报告）。"""
    from employees import scenes

    emp = _employee(employee)
    spec = scenes.INSIGHTS.get(name)
    if not spec or spec["employee"] != emp.id:
        raise HTTPException(404, f"{emp.persona}没有「{name}」汇总")
    return scenes.insight(store, name)


class AuthorityIn(BaseModel):
    matter: str
    amount: str | None = None


@app.post("/api/meeting/authority")
def meeting_authority(body: AuthorityIn):
    """事项审批权限查询：按四份制度检索条款，按金额落档，给出审批 / 决策主体与应上的会议。"""
    from core.knowledge.base import get_base
    from employees import scenes

    matter = body.matter.strip()
    if len(matter) < 2:
        raise HTTPException(400, "请填写事项，例如「信息化项目采购结果」「对外捐赠」")
    amount = None
    if body.amount and body.amount.strip():
        amount = scenes.parse_amount_wan(body.amount)
        if amount is None:
            raise HTTPException(400, "金额格式不对，例如 80、80万、1200000元、1.2亿")
    return scenes.authority(get_base(), matter, amount)


class BatchIn(BaseModel):
    request_ids: list[str] | None = None   # 不给则审查全部待审单据


BATCH_MAX = 20
batches: dict[str, dict] = {}


@app.post("/api/{employee}/batch")
def employee_batch(employee: str, body: BatchIn):
    """批量审查：逐笔发起（与人工发起共用并发上限），返回批次号，进度经 /api/batches/{id} 查询。"""
    emp = _employee(employee)
    q = _queue(emp)
    if q["error"]:
        raise HTTPException(503, q["error"])
    by_id = {r["request_id"]: r for r in q["rows"]}
    if body.request_ids:
        picked = [by_id[r] for r in body.request_ids if r in by_id and by_id[r]["runnable"]]
    else:
        picked = [r for r in q["rows"] if r["needs_review"]]
    picked = [r for r in picked if not (r.get("latest") and r["latest"]["status"] == "running")][:BATCH_MAX]
    if not picked:
        raise HTTPException(400, "没有可审查的单据（资料未就绪、待办只读或都已审查过且材料未变化）")
    bid = f"b{int(time.time() * 1000):x}"
    items = [{"request_id": r["request_id"], "source": r["source"], "title": r.get("title"),
              "task_id": launch(emp, r["request_id"], r["source"], "batch")} for r in picked]
    batches[bid] = {"batch_id": bid, "employee": emp.id, "created_at": time.time(), "items": items}
    return batch_status(bid)


@app.get("/api/batches/{batch_id}")
def batch_status(batch_id: str):
    b = batches.get(batch_id)
    if not b:
        raise HTTPException(404, "批次不存在（工作台重启后批次进度不保留，可在历史报告中查看结果）")
    items = []
    for it in b["items"]:
        t = store.get_task(it["task_id"]) or {}
        rep = store.get_report(it["task_id"]) if t.get("status") == "done" else None
        items.append({**it, "status": t.get("status"), "error": t.get("error"),
                      "verdict": (rep or {}).get("verdict"), "summary": (rep or {}).get("summary")})
    done = sum(1 for i in items if i["status"] in ("done", "failed"))
    return {**b, "items": items, "done": done, "total": len(items), "finished": done == len(items)}


@app.get("/api/collect/status")
def collect_status():
    try:
        return resources().collect_status()
    except Exception as exc:  # noqa: BLE001
        info = friendly(exc)
        raise HTTPException(503, f"{info['title']}。{info['hint']}") from exc


@app.post("/api/collect/run")
def collect_run(source: str):
    return resources().collect_run(source)


@app.get("/api/runs/{task_id}/archive")
def run_archive(task_id: str, kinds: str | None = None):
    """执行档案（时间线、版本、表单快照、接口报文、模型调用、证据截图）；数据在资料中心。"""
    d = resources().archive(task_id, kinds.split(",") if kinds else None)
    if not d:
        raise HTTPException(404, "该次审查没有执行档案")
    return d


@app.get("/api/archive/shots/{shot_id}.png")
def archive_shot(shot_id: str):
    png = resources().shot_png(shot_id)
    if png is None:
        raise HTTPException(404, "截图不存在")
    return Response(png, media_type="image/png")


@app.get("/api/archive/pages/{page_id}.png")
def archive_page(page_id: str, w: int | None = None):
    """平台页面截图：工作台只提供打码版（身份证号 / 手机号 / 银行账号位置涂黑），原图留在资料中心。"""
    png = resources().page_png(page_id, masked=True, max_width=w)
    if png is None:
        raise HTTPException(404, "截图不存在")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/files/{sig_prefix}")
def get_file(sig_prefix: str, name: str = ""):
    """原件查看：经资料中心读取。"""
    rc = resources()
    sig = rc.blob_by_prefix(sig_prefix) if len(sig_prefix) >= 12 else None
    if not sig:
        raise HTTPException(404, "文件不存在")
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    inline = ctype.startswith("image/") or ctype == "application/pdf"
    disp = "inline" if inline else "attachment"
    fname = quote(name or sig)
    return Response(rc.read_blob(sig), media_type=ctype,
                    headers={"Content-Disposition": f"{disp}; filename*=UTF-8''{fname}"})


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("DE_HOST", "127.0.0.1"), port=int(os.environ.get("DE_PORT", "8090")),
                log_level="warning")
