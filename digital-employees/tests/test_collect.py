"""采集：时间段、列表登记与入队（待办只登记不打开）、队列同步、重复与重同步判定、公文列表、保留期清理、登录方式。"""
import io
import time
from datetime import datetime

import pytest

from core.resource import collector as col
from core.resource import listers, settings
from core.resource.service import ResourceService
from core.resource.store import ResourceStore
from core.sources.contract import Attachment, RequestData


def _docx(text):
    import docx

    d = docx.Document()
    d.add_paragraph(text)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


class FakeContract:
    def __init__(self):
        self.fetched, self.listed = [], []
        self.ledger_rows = [{"lcid": "901", "htmc": "主合同A", "qdrq": "2026-11-01"},
                            {"lcid": "902", "htmc": "主合同B", "qdrq": "2026-11-02"}]
        self.pending = [{"request_id": "950", "workflow_id": "99", "title": "待办主合同", "date": ""}]

    def ledger(self, customid, page_size=50, max_pages=1):
        self.listed.append(("ledger", customid))
        return self.ledger_rows[:page_size]

    def list_requests(self, scope, workflow_ids=None, page_size=50):
        self.listed.append((scope, tuple(workflow_ids or [])))
        return self.pending if scope == "doing" else []

    def fetch(self, rid):
        self.fetched.append(rid)
        att = Attachment(field_key="f", field_label="合同文本", filename=f"{rid}.docx", ext="docx", file_id="1",
                         image_file_id=f"img{rid}", version_id="v1", upload_time="", secret_level="", loadlink=rid)
        return RequestData(request_id=rid, workflow_id="99", workflow_name="主合同审批", request_name=f"合同{rid}",
                           node_name="", fields=[{"label": "合同名称", "display": f"合同{rid}"}], approval_log=[],
                           attachments=[att])

    def download(self, att):
        return _docx(f"合同正文 {att.loadlink}")


CFG = {
    "enabled": True, "interval_minutes": 30, "max_requests_per_round": 50, "sync_workers": 1, "resync_hours": 12,
    "failed_retry_minutes": 60, "fingerprint": {"ignore_fields": []},
    "sources": {"contract": {"enabled": True, "lists": [
        {"name": "主合同台账", "kind": "ledger", "customid": 78, "fields": {"id": "lcid", "title": "htmc"},
         "max": 10, "employee": "contract", "open_detail": True},
        {"name": "主合同审批·待办", "kind": "reqlist", "scope": "doing", "workflow_ids": [99], "employee": "contract",
         "open_detail": False}]}},
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import copy

    cfg = copy.deepcopy(CFG)
    monkeypatch.setattr(settings, "collect", lambda: cfg)
    src = FakeContract()
    store = ResourceStore(db_path=tmp_path / "rc.sqlite3", root=tmp_path / "store", legacy_db=None)
    svc = ResourceService(store, None, clients={"contract": src})
    return svc, src, cfg


def _drain(c: col.Collector):
    while True:
        job = c._claim()
        if not job:
            return
        snap = c.store.get_snapshot(job["source"], job["request_id"]) or {}
        try:
            c.service.run_request_job(job["job_id"], job["source"], job["request_id"], snap.get("employee"))
        except Exception:  # noqa: BLE001
            pass


def test_active_hours():
    assert col.in_active_hours("07:00-22:00", datetime(2026, 11, 9, 8, 0))
    assert not col.in_active_hours("07:00-22:00", datetime(2026, 11, 9, 23, 0))
    assert col.in_active_hours("22:00-06:00", datetime(2026, 11, 9, 23, 30))
    assert col.in_active_hours(None)


def test_round_lists_queues_and_pending_only_listed(env):
    svc, src, _cfg = env
    c = col.Collector(svc)
    stats = c.run_round("contract")
    assert stats["listed"] == 3 and stats["queued"] == 2 and not stats["error"]
    pend = svc.store.get_snapshot("contract", "950")
    assert pend["status"] == "listed" and pend["list_scope"] == "pending" and pend["open_detail"] == 0
    assert svc.store.queue_counts() == {"queued": 2}
    _drain(c)
    assert sorted(src.fetched) == ["901", "902"]  # 待办 950 没有被打开
    snaps = {s["request_id"]: s for s in svc.requests("contract")}
    assert snaps["901"]["status"] == "ready" and snaps["901"]["employee"] == "contract"
    assert snaps["901"]["list_name"] == "主合同台账" and snaps["901"]["title"] == "主合同A"  # 保留台账中的合同名称
    assert svc.store.recent_rounds(1)[0]["listed"] == 3


def test_no_requeue_until_resync_interval(env):
    svc, src, cfg = env
    c = col.Collector(svc)
    c.run_round("contract")
    _drain(c)
    assert c.run_round("contract")["queued"] == 0  # 已同步且未到 resync_hours
    cfg["resync_hours"] = 0
    assert c.run_round("contract")["queued"] == 2
    _drain(c)
    assert src.fetched.count("901") == 2


def test_failed_sync_waits_for_retry_interval(env):
    svc, src, cfg = env
    src.fetch = lambda rid: (_ for _ in ()).throw(RuntimeError("系统维护中"))
    c = col.Collector(svc)
    c.run_round("contract")
    _drain(c)
    assert svc.store.get_snapshot("contract", "901")["status"] == "failed"
    assert c.run_round("contract")["queued"] == 0
    cfg["failed_retry_minutes"] = 0
    assert c.run_round("contract")["queued"] == 2


def test_queued_job_rechecked_against_current_config(env):
    svc, src, cfg = env
    c = col.Collector(svc)
    c.run_round("contract")
    cfg["sources"]["contract"]["lists"][0]["title_exclude"] = "主合同A"
    c.start = lambda: None
    job = c._claim()
    c.store.update_job(job["job_id"], status="queued")
    # 走工作线程同样的判断
    snap = svc.store.get_snapshot("contract", "901")
    assert c._excluded("contract", snap) and not c._excluded("contract", svc.store.get_snapshot("contract", "902"))
    rows = listers.LISTERS["contract"](src, cfg["sources"]["contract"]["lists"][0])
    assert [r["request_id"] for r in rows] == ["902"]


def test_restart_requeues_collect_jobs_and_fails_inline(env):
    svc, _src, _cfg = env
    j1 = svc.store.create_job(kind="request", source="contract", request_id="1", task_id=None, priority=1,
                              trigger="collect")
    svc.store.update_job(j1, status="running")
    j2 = svc.store.create_job(kind="parse", source="contract", request_id="1", task_id="t", priority=10,
                              trigger="inline")
    svc.store.update_job(j2, status="running")
    svc.store.fail_stale_jobs()
    assert svc.store.get_job(j1)["status"] == "queued" and svc.store.get_job(j2)["status"] == "failed"


def test_round_records_list_errors(env):
    svc, src, _cfg = env
    src.ledger = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("台账不可用"))
    stats = col.Collector(svc).run_round("contract")
    assert stats["failed"] == 1 and stats["listed"] == 1
    assert "台账不可用" in svc.store.recent_rounds(1)[0]["error"]


def test_round_not_concurrent_for_same_source(env):
    svc, _src, _cfg = env
    c = col.Collector(svc)
    c._running.add("contract")
    assert c.run_round("contract")["skipped"]


def test_docflow_lister_marks_and_dedupes():
    class FakeDoc:
        def _list(self, typ, kw, size):
            return [{"affairId": "1", "objectId": "S1", "subject": "内部请示：通设请字〔2026〕76号关于大赛的请示",
                     "templateName": "通用设计内部请示"},
                    {"affairId": "2", "objectId": "S1", "subject": "内部请示：通设请字〔2026〕76号关于大赛的请示",
                     "templateName": "通用设计内部请示"},
                    {"affairId": "3", "objectId": "S3", "subject": "公文流转测试", "templateName": "公文流转"},
                    {"affairId": "4123236229515985642", "objectId": "S4", "subject": "内部请示：无编号",
                     "templateName": "通用设计内部请示"}]

    rows = listers.docflow_rows(FakeDoc(), {"type": "doneSent", "template": "内部请示"})
    assert [r["request_id"] for r in rows] == ["通设请字[2026]76号", "4123236229515985642"]
    assert listers.is_pending({"type": "pending"}) and not listers.is_pending({"type": "doneSent"})


def test_retention_purges_old_files_and_archives(env):
    svc, src, _cfg = env
    c = col.Collector(svc)
    c.run_round("contract")
    _drain(c)
    svc.store.archive_start(task_id="t1", employee="contract", source="contract", request_id="901",
                            trigger_by="auto", versions={})
    assert svc.store.purge_files(time.time() - 3600) == 0  # 近期出现的保留
    assert svc.store.purge_files(time.time() + 1) == 2
    assert svc.requests("contract") and not svc.store.occurrences("contract", "901")
    assert svc.store.purge_archive(time.time() + 1) == 1 and svc.store.get_archive("t1") is None


def test_session_modes(tmp_path, monkeypatch):
    from core import session
    from core.session import PasswordSessionProvider, ServiceAccountNotReady

    cfg = tmp_path / "accounts.yaml"
    cfg.write_text("mode: password\npassword: {username: '', password: ''}\n", encoding="utf-8")
    monkeypatch.setattr(session, "ACCOUNTS_PATH", cfg)
    monkeypatch.delenv("DE_SERVICE_USER", raising=False)
    monkeypatch.delenv("DE_SESSION_MODE", raising=False)
    with pytest.raises(ServiceAccountNotReady):
        session.provider_from_config()
    monkeypatch.setenv("DE_SERVICE_USER", "svc")
    monkeypatch.setenv("DE_SERVICE_PASSWORD", "pwd")
    p = session.provider_from_config()
    assert isinstance(p, PasswordSessionProvider) and p.username == "svc"
    monkeypatch.delenv("DE_SERVICE_USER")
    cfg.write_text("mode: cdp\n", encoding="utf-8")
    assert isinstance(session.provider_from_config(), session.CdpSessionProvider)
