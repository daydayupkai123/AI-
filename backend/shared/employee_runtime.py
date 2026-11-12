"""数字员工运行时：取数客户端与自动重登、节点包装（留痕 + 实时事件）、线性流程图组装。"""
from __future__ import annotations

import time
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from .errors import SessionExpired, friendly
from .session import SessionProvider
from .task_store import Store


class Runtime:
    """一次运行的上下文。

    client：直接给定取数客户端（本地样例、离线重放）；不给则用 client_factory(sessions.session()) 按需创建。
    host：取数遇到 SessionExpired 时经统一认证自动单点登录的子系统；直接给定 client 时不重登。
    """

    def __init__(self, store: Store, sessions: SessionProvider | None, on_event: Callable[[dict], None] | None = None,
                 *, client: Any = None, client_factory: Callable[[Any], Any] | None = None, host: str | None = None,
                 system_name: str = "合同系统", resources: Any = None):
        self.store = store
        self.sessions = sessions
        self.on_event = on_event or (lambda e: None)
        self._client = client
        self._fixed = client is not None
        self._factory = client_factory
        self._host = host
        self.system_name = system_name
        self._resources = resources
        self.archive = None  # 执行档案记录器（invoke 时建立）

    def trace(self, kind: str, title: str, body) -> None:
        """写一条执行档案过程记录（未建档时忽略）。"""
        if self.archive is not None:
            self.archive.add(kind, title, body)

    @property
    def resources(self):
        """资料中心客户端：未显式给定时按 config/resource.yaml 取默认（独立进程或进程内）。"""
        if self._resources is None:
            from storage_service.client import default_client

            self._resources = default_client(self.sessions)
        return self._resources

    def client(self):
        if self._client is None:
            if self._factory is None or self.sessions is None:
                raise RuntimeError("未配置取数客户端")
            self._client = self._factory(self.sessions.session())
            if self.archive is not None and hasattr(self._client, "s"):
                self._client.s.hooks["response"].append(self.archive.api_hook)
        return self._client

    def with_login(self, fn):
        """执行取数；若子系统要求重新认证，后台自动完成单点登录后重试一次。"""
        try:
            return fn(self.client())
        except SessionExpired:
            if self._fixed or not self._host or self.sessions is None:
                raise
            self.on_event({"type": "node.note", "text": f"{self.system_name}会话未建立，正在经统一认证自动登录…"})
            self.sessions.warmup(self._host)
            self._client = None
            return fn(self.client())


def node(rt: Runtime, name: str, fn: Callable[[dict], dict]):
    """包装节点：落 node_run 记录、推送 started/completed/failed 事件；fn 返回值里的 _summary 作为节点摘要。"""
    def run(state: dict) -> dict:
        run_id = rt.store.node_start(state["task_id"], name)
        t0 = time.time()
        rt.on_event({"type": "node.started", "node": name, "at": t0})
        try:
            out = fn(state)
        except Exception as exc:
            info = friendly(exc)
            rt.store.node_end(run_id, "failed", t0, error=f"{info['title']}｜{info['detail']}")
            rt.on_event({"type": "node.failed", "node": name, "error": info["title"], "detail": info["detail"],
                         "ms": int((time.time() - t0) * 1000)})
            raise
        summary = out.pop("_summary", "")
        rt.store.node_end(run_id, "ok", t0, summary=summary)
        _record(rt, state["task_id"], out)
        rt.on_event({"type": "node.completed", "node": name, "summary": summary, "ms": int((time.time() - t0) * 1000)})
        return out
    return run


# OA 同一账号只允许一处在线：截图浏览器的单点登录会挤掉资料中心下载本单附件的会话，等附件下载完再截图
DEFER_CAPTURE = {"docflow"}


def _record(rt: Runtime, task_id: str, out: dict) -> None:
    """节点产出入档：取单后的表单快照与材料指纹（任务也记下指纹，供自动重审比对）、规则结论、报告。"""
    req = out.get("request")
    if req is not None and hasattr(req, "fields") and hasattr(req, "attachments") and not getattr(rt, "_fp_done", False):
        # 只取第一次取单的表单与附件（合同流程之后会并入投标台账附件，不属于本单据自身材料）
        from storage_service.fingerprint import of_request

        fp = of_request(req)
        rt._fp_done = True
        rt.store.set_task_fp(task_id, fp)
        if rt.archive is not None:
            rt.archive.snapshot(req, fp)
            if not rt._fixed and rt.sessions is not None:
                if (rt.store.get_task(task_id) or {}).get("source_system") in DEFER_CAPTURE:
                    rt._page_deferred = req
                else:
                    _start_page_capture(rt, task_id, req)
    if rt.archive is None:
        return
    if out.get("files") is not None and getattr(rt, "_page_deferred", None) is not None:
        req0, rt._page_deferred = rt._page_deferred, None
        _start_page_capture(rt, task_id, req0)
    if out.get("results") is not None:
        rt.archive.add("rules", "规则结论", out["results"])
    if out.get("report") is not None:
        rt.archive.add("report", "审查报告", out["report"])


def linear_graph(rt: Runtime, state_type: type, steps: list[tuple[str, Callable[[dict], dict]]]):
    g = StateGraph(state_type)
    for name, fn in steps:
        g.add_node(name, node(rt, name, fn))
    order = [name for name, _ in steps]
    g.add_edge(START, order[0])
    for a, b in zip(order, order[1:]):
        g.add_edge(a, b)
    g.add_edge(order[-1], END)
    return g.compile()


def invoke(store: Store, task_id: str, graph, state: dict, rt: Runtime | None = None) -> dict:
    """执行流程图并把任务标记为 done / failed；给定 rt 时建立执行档案，完成后渲染证据截图，并把同一单据的旧报告标记为被取代。"""
    arc = _open_archive(store, task_id, rt) if rt is not None else None
    try:
        final = graph.invoke(state)
    except Exception as exc:
        store.finish_task(task_id, "failed", f"{type(exc).__name__}: {exc}")
        if arc is not None:
            _finish_page_capture(rt, arc)
            info = friendly(exc)
            arc.finish("failed", error=f"{info['title']}｜{info['detail']}")
        raise
    store.finish_task(task_id, "done")
    store.supersede_previous(task_id)
    if arc is not None:
        _finish_page_capture(rt, arc)
        _shots(rt, arc, task_id, final)
        rep = final.get("report") or {}
        arc.finish("done", verdict=rep.get("verdict") or {"summary": rep.get("summary")})
    return final


def _open_archive(store: Store, task_id: str, rt: Runtime):
    from .run_archive import RunArchive

    task = store.get_task(task_id)
    if not task:
        return None
    original = rt.on_event

    def warn(text: str) -> None:
        original({"type": "node.note", "text": text})

    arc = RunArchive(rt.resources, task, on_warning=warn)
    rt.archive = arc

    def on_event(ev: dict) -> None:
        arc.event(ev)
        original(ev)

    rt.on_event = on_event
    return arc


def _start_page_capture(rt: Runtime, task_id: str, req) -> None:
    """后台只读打开该单据的平台页面截图（失败只记入档案，不影响审查）。"""
    from .portal_snapshot import PageCapture

    task = rt.store.get_task(task_id) or {}
    try:
        rt._page = PageCapture(rt, task.get("source_system") or "", req).start()
    except Exception as exc:  # noqa: BLE001
        rt.archive.add("page", "平台页面截图未能启动", {"error": f"{type(exc).__name__}: {exc}"})


def _finish_page_capture(rt: Runtime, arc) -> None:
    cap = getattr(rt, "_page", None)
    if cap is None:
        return
    rt._page = None
    try:
        cap.finish(arc)
    except Exception as exc:  # noqa: BLE001
        arc.add("page", "平台页面截图入档失败", {"error": f"{type(exc).__name__}: {exc}"})


def _shots(rt: Runtime, arc, task_id: str, final: dict) -> None:
    from .run_archive import shot_items

    items = shot_items(final)
    if not items or not arc.ok:
        return
    try:
        shots = rt.resources.archive_shots(task_id, items)
        arc.add("shots", "证据截图", shots)
        rt.on_event({"type": "archive.shots", "count": len(shots), "located": sum(1 for s in shots if s["method"] in
                                                                                   ("text", "ocr"))})
    except Exception as exc:  # noqa: BLE001
        arc.add("shots", "证据截图生成失败", {"error": f"{type(exc).__name__}: {exc}"})
