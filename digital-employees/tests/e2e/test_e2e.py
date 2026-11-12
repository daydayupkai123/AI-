"""四个数字员工端到端（临时环境，进程内资料中心）：采集 → 提前入库 → 自动审查派发 → 报告 / 执行档案 / 材料指纹 → 改附件自动重审取代。

合同、三会、报销走本地事项来源；采购用本地已缓存的真实单据离线重放（无缓存时跳过采购部分）。
"""
import copy
import shutil
import time

import pytest

from workbench_service.auto_review import AutoDispatcher
from storage_service import collector as col
from storage_service import settings
from storage_service.client import LocalResourceClient
from storage_service.service import LocalFileClient, ResourceService
from storage_service.store import ResourceStore
from shared.source_adapters.local import LocalCaseClient
from employee_registry import registry
from tests.support.env import temp_store
from tests.support.fakes import FakeJudge, FakeTianyancha

CFG = {
    "enabled": True, "interval_minutes": 30, "max_requests_per_round": 50, "sync_workers": 1, "resync_hours": 12,
    "failed_retry_minutes": 60, "fingerprint": {"ignore_fields": []}, "auto_review_concurrency": 10,
    "auto_review": {"contract": True, "meeting": True, "reimburse": True, "procurement": True},
    "sources": {"local": {"enabled": True, "lists": [
        {"name": "本地事项·合同", "kind": "cases", "employee": "contract", "open_detail": True},
        {"name": "本地事项·三会", "kind": "cases", "employee": "meeting", "open_detail": True},
        {"name": "本地事项·报销", "kind": "cases", "employee": "reimburse", "open_detail": True}]}},
}


def _drain(c):
    while True:
        job = c._claim()
        if not job:
            return
        snap = c.store.get_snapshot(job["source"], job["request_id"]) or {}
        c.service.run_request_job(job["job_id"], job["source"], job["request_id"], snap.get("employee"))


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from contract_review import workflow as cg
    from contract_review import samples as cs
    from meeting_review import workflow as mg
    from meeting_review import samples as ms
    from reimburse_review import workflow as rg
    from reimburse_review import samples as rs

    cases = tmp_path / "cases"
    for w in (cs.write, ms.write, rs.write):
        w(cases)
    for g in (cg, mg, rg):
        monkeypatch.setattr(g, "REPORTS", tmp_path / "reports")
    cfg = copy.deepcopy(CFG)
    monkeypatch.setattr(settings, "collect", lambda: cfg)
    store = temp_store(tmp_path)
    rstore = ResourceStore(db_path=tmp_path / "rc" / "resource.sqlite3", root=tmp_path / "store", legacy_db=None)
    svc = ResourceService(rstore, None, clients={"local": LocalFileClient(cases)})
    rc = LocalResourceClient(svc)
    ran = []

    def launch(emp, rid, source, trigger_by):
        tid = emp.graph.create_task(store, rid, trigger_by=trigger_by, source=source)
        kw = {"client": LocalCaseClient(emp.id, root=cases), "resources": rc, "source": source, "task_id": tid}
        if emp.id in ("contract", "meeting"):
            kw["judge"] = FakeJudge()
        if emp.id == "contract":
            kw.update(tianyancha=FakeTianyancha(), lists={})
        emp.graph.run(rid, store, None, **kw)
        ran.append((emp.id, rid, trigger_by))
        return tid

    disp = AutoDispatcher(store, lambda: rc, launch, registry.EMPLOYEES)
    return {"store": store, "rc": rc, "svc": svc, "collector": col.Collector(svc), "disp": disp, "ran": ran,
            "cases": cases, "cfg": cfg}


def test_local_employees_full_chain(world):
    w = world
    stats = w["collector"].run_round("local")
    assert stats["listed"] == 7 and stats["queued"] == 7 and not stats["error"]  # 合同 2 + 三会 2 + 报销 3
    _drain(w["collector"])
    snaps = w["rc"].requests(limit=50)
    assert {s["status"] for s in snaps} == {"ready"} and all(not s["stale"] for s in snaps)
    started = w["disp"].tick()
    assert sorted((s["employee"], s["request_id"]) for s in started) == sorted(
        (s["employee"], s["request_id"]) for s in snaps)
    for emp_id in ("contract", "meeting", "reimburse"):
        tasks = w["store"].list_tasks(emp_id)
        assert tasks and all(t["status"] == "done" and t["trigger_by"] == "auto" for t in tasks), emp_id
        for t in tasks:
            arc = w["rc"].archive(t["task_id"])
            kinds = {i["kind"] for i in arc["items"]}
            assert arc["status"] == "done" and {"snapshot", "rules", "report"} <= kinds, (emp_id, kinds)
            snap = w["svc"].store.get_snapshot("local", t["request_id"])
            # 审查时取单算出的材料指纹与资料中心快照一致 → 下一轮派发不会重复审查
            assert w["store"].get_task(t["task_id"])["material_fp"] == snap["material_fp"]
            # 资料已提前入库：审查时没有当场同步
            notes = [i for i in arc["items"] if i["kind"] == "event" and i["body"].get("type") == "sync.notice"]
            assert not notes, (emp_id, t["request_id"])
    assert w["disp"].tick() == []


def test_changed_attachment_triggers_rereview_and_supersede(world):
    w = world
    w["collector"].run_round("local")
    _drain(w["collector"])
    w["disp"].tick()
    first = w["store"].latest_task("reimburse", "local", "DEMO-BX-001")
    # 替换一份附件 → 定时轮在 resync_hours 内不重同步；人工「立即采集」强制重同步 → 指纹变化 → 自动重审，旧报告被取代
    case = w["cases"] / "reimburse" / "DEMO-BX-001"
    f = next(p for p in (case / "files").iterdir() if p.is_file())
    time.sleep(0.01)
    f.write_bytes(f.read_bytes() + b"\n")
    assert w["collector"].run_round("local")["queued"] == 0
    assert w["svc"].collect_run("local")["queued"] == 7
    _drain(w["collector"])
    again = w["disp"].tick()
    assert [(s["employee"], s["request_id"], s["reason"]) for s in again] == [("reimburse", "DEMO-BX-001", "changed")]
    assert w["store"].get_task(first["task_id"])["superseded_by"] == again[0]["task_id"]


def test_removed_case_becomes_stale_and_is_not_reviewed(world):
    w = world
    w["collector"].run_round("local")
    _drain(w["collector"])
    shutil.rmtree(w["cases"] / "meeting" / "DEMO-SH-002")
    w["collector"].run_round("local")
    snap = {s["request_id"]: s for s in w["rc"].requests(employee="meeting")}
    assert snap["DEMO-SH-002"]["stale"] and not snap["DEMO-SH-001"]["stale"]
    started = w["disp"].tick()
    assert "DEMO-SH-002" not in [s["request_id"] for s in started]


def test_procurement_replay_through_collector(tmp_path, monkeypatch):
    """采购：用本地已缓存的真实单据，经资料中心同步 + 自动派发完成审查（离线，不访问合同系统）。"""
    from procurement_review import workflow as pg
    from tests.support.replay import ReplayClient, comparable, latest_report, rebuild_request, replay_resources

    history = latest_report("1674771")
    if not history:
        pytest.skip("本地没有 1674771 的历史报告")
    rc, rc_db = replay_resources(tmp_path)
    req = rebuild_request("1674771", history, rc_db)
    rc.service._fixed["contract"] = ReplayClient(req)
    store = temp_store(tmp_path)
    monkeypatch.setattr(pg, "REPORTS", tmp_path / "reports")
    cfg = {"auto_review": {"procurement": True}, "auto_review_concurrency": 2, "fingerprint": {"ignore_fields": []}}
    monkeypatch.setattr(settings, "collect", lambda: cfg)
    snap = rc.sync_request("contract", "1674771", "procurement", trigger="collect")
    assert snap["status"] == "ready" and snap["files_total"] == len(req.attachments)
    # 复制来的正式库里该单可能已滑出台账「最近」列表（被标为不可见）；这里按刚采集到登记，不依赖正式环境状态
    rc.service.store.upsert_listed(source="contract", request_id="1674771", employee="procurement", list_name="回放测试",
                                   list_scope="done", title="", open_detail=True)

    def launch(emp, rid, source, trigger_by):
        tid = emp.graph.create_task(store, rid, trigger_by=trigger_by)
        final = emp.graph.run(rid, store, None, task_id=tid, client=ReplayClient(req), resources=rc)
        assert comparable(final["results"]) == comparable(history["rules"])
        return tid

    started = AutoDispatcher(store, lambda: rc, launch, registry.EMPLOYEES).tick()
    assert [s["request_id"] for s in started] == ["1674771"]
    t = store.latest_task("procurement", "contract", "1674771")
    assert t["status"] == "done" and t["trigger_by"] == "auto" and rc.archive(t["task_id"])["status"] == "done"
