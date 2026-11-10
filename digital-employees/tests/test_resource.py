"""资料中心：存储迁移、附件补齐与复用、解析补齐（含压缩包）、解析计划、单据同步与材料指纹、HTTP 接口语义一致。"""
import io
import json
import socket
import sqlite3
import threading
import time
import zipfile
from pathlib import Path

import pytest

from core.errors import NoAccess, SessionExpired
from core.resource import fingerprint
from core.resource.client import HttpResourceClient, LocalResourceClient
from core.resource.service import ResourceService
from core.resource.store import ResourceStore
from core.sources.contract import Attachment, RequestData


def _docx(text: str) -> bytes:
    import docx

    d = docx.Document()
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _pdf(text_pages: int, blank_pages: int) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for i in range(text_pages):
        doc.new_page().insert_text((72, 72), f"Page {i} " + "contract text " * 10)
    for _ in range(blank_pages):
        doc.new_page()
    return doc.tobytes()


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in files.items():
            z.writestr(n, b)
    return buf.getvalue()


class FakeSource:
    """模拟客户系统：fetch 返回表单，download 按 loadlink 返回字节；记录下载次数。"""

    def __init__(self, files: dict[str, bytes], fields=None, fail_download: Exception | None = None):
        self.files, self.downloads, self.fail = files, [], fail_download
        self.fields = fields or [{"field": "f1", "label": "合同名称", "display": "某合同", "value": "某合同"}]

    def atts(self):
        return [Attachment(field_key="f9", field_label="附件", filename=n, ext=n.rsplit(".", 1)[-1], file_id=str(i),
                           image_file_id=f"img{i}", version_id="v1", upload_time="", secret_level="", loadlink=n)
                for i, n in enumerate(self.files, start=1)]

    def fetch(self, rid):
        return RequestData(request_id=rid, workflow_id="99", workflow_name="主合同审批", request_name=f"单据{rid}",
                           node_name="", fields=self.fields, approval_log=[], attachments=self.atts())

    def download(self, att):
        if self.fail:
            raise self.fail
        self.downloads.append(att.filename)
        return self.files[att.loadlink]


def _service(tmp: Path, src: FakeSource) -> ResourceService:
    store = ResourceStore(db_path=tmp / "rc.sqlite3", root=tmp / "store", legacy_db=None)
    return ResourceService(store, None, clients={"contract": src})


def test_migrates_legacy_file_tables(tmp_path):
    legacy = ResourceStore(db_path=tmp_path / "legacy.sqlite3", root=tmp_path / "store", legacy_db=None)
    sig = legacy.put_blob(b"hello", ext="txt")
    legacy.add_occurrence(content_sig=sig, source_system="contract", request_id="1", filename="a.txt",
                          image_file_id="i", version_id="v")
    new = ResourceStore(db_path=tmp_path / "new.sqlite3", root=tmp_path / "store", legacy_db=tmp_path / "legacy.sqlite3")
    assert new.migrated["file_blob"] == 1 and new.migrated["file_occurrence"] == 1
    assert new.known_version("contract", "i", "v") == sig
    again = ResourceStore(db_path=tmp_path / "new.sqlite3", root=tmp_path / "store", legacy_db=tmp_path / "legacy.sqlite3")
    assert again.migrated == {}  # 只在新建库时迁移一次


def test_ensure_files_reuses_known_version_and_parses_archives(tmp_path):
    src = FakeSource({"合同.docx": _docx("合同正文 价款 100 万元"), "附件包.zip": _zip({"报价单.docx": _docx("报价单 99 万")})})
    svc = _service(tmp_path, src)
    req = src.fetch("100")
    looked = svc.lookup("contract", req.attachments)
    assert [x["stored"] for x in looked] == [False, False]
    events = []
    files = svc.ensure_files("contract", "100", "99", req.attachments, progress=events.append)
    assert [f["reused"] for f in files] == [False, False] and len(src.downloads) == 2
    assert any(e["type"] == "file.downloading" for e in events)
    again = svc.ensure_files("contract", "100", "99", req.attachments)
    assert [f["reused"] for f in again] == [True, True] and len(src.downloads) == 2
    plan = svc.parse_plan("contract", files)
    assert [i["parsed"] for i in plan["items"]] == [None, None] and plan["ocr_pages"] == 0
    infos = svc.ensure_parsed("contract", "100", files, progress=events.append)
    child = [i for i in infos if i["parent_sig"]]
    assert len(infos) == 3 and len(child) == 1 and child[0]["filename"] == "报价单.docx"
    assert all(i["cache"] == "miss" for i in infos)
    assert "报价单 99 万" in svc.parsed(child[0]["sig"])["pages"][0]["text"]
    assert all(i["cache"] == "hit" for i in svc.ensure_parsed("contract", "100", files))
    assert svc.parse_plan("contract", files)["items"][0]["parsed"]["status"] == "ok"
    assert [s["status"] for s in [svc.job(j["job_id"]) for j in [dict(r) for r in svc.store._all(
        "SELECT job_id FROM sync_job")]]] == ["done"] * 4


def test_parse_plan_estimates_scanned_pages(tmp_path):
    src = FakeSource({"扫描件.pdf": _pdf(2, 3)})
    svc = _service(tmp_path, src)
    files = svc.ensure_files("contract", "7", "99", src.atts())
    plan = svc.parse_plan("contract", files)
    assert plan["ocr_pages"] == 3 and plan["eta_s"] > 0


def test_sync_request_snapshot_and_fingerprint(tmp_path):
    src = FakeSource({"合同.docx": _docx("正文")})
    svc = _service(tmp_path, src)
    snap = svc.sync_request("contract", "200", "contract")
    assert snap["status"] == "ready" and snap["files_total"] == 1 and snap["parsed_ready"] == 1
    assert snap["material_fp"] == fingerprint.of_request(src.fetch("200"))
    assert "loadlink" not in snap["attachments"][0]
    assert svc.requests("contract")[0]["request_id"] == "200"
    detail = svc.request("contract", "200")
    assert detail["files"][0]["parsed"]["status"] == "ok"
    # 附件换版本或字段变化 → 指纹变化
    src.fields = [{"field": "f1", "label": "合同名称", "display": "改了名字"}]
    assert svc.sync_request("contract", "200", "contract")["material_fp"] != snap["material_fp"]


def test_fingerprint_ignores_configured_fields():
    a = [{"field_key": "f", "image_file_id": "1", "version_id": "v", "filename": "x.pdf"}]
    f1 = [{"label": "合同名称", "display": "A"}, {"label": "审批意见", "display": "同意"}]
    f2 = [{"label": "合同名称", "display": "A"}, {"label": "审批意见", "display": "退回修改"}]
    assert fingerprint.material_fp(f1, a, ignore=[]) != fingerprint.material_fp(f2, a, ignore=[])
    assert fingerprint.material_fp(f1, a, ignore=["审批意见"]) == fingerprint.material_fp(f2, a, ignore=["审批意见"])
    b = [{**a[0], "version_id": "v2"}]
    assert fingerprint.material_fp(f1, a, ignore=[]) != fingerprint.material_fp(f1, b, ignore=[])


def test_sync_failure_marks_job_and_snapshot(tmp_path):
    src = FakeSource({"合同.docx": _docx("正文")}, fail_download=NoAccess("无权限", title="当前账号无权查看该单据"))
    svc = _service(tmp_path, src)
    svc.store.upsert_listed(source="contract", request_id="300", employee="contract", list_name="已办", list_scope="done",
                            title="单据300", open_detail=True)
    with pytest.raises(NoAccess):
        svc.sync_request("contract", "300", "contract")
    snap = svc.store.get_snapshot("contract", "300")
    assert snap["status"] == "failed" and "无权查看" in snap["error"]
    job = svc.store._one("SELECT status, error FROM sync_job WHERE kind='request'")
    assert job["status"] == "failed"


# ------------------------------------------------------------------ HTTP 接口（真实进程内 uvicorn）
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def http_rc(tmp_path):
    import uvicorn

    from core.resource.api import build_app

    src = FakeSource({"合同.docx": _docx("合同正文 HTTP"), "包.zip": _zip({"内.docx": _docx("压缩包内")})})
    svc = _service(tmp_path, src)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(build_app(svc, start_background=False), host="127.0.0.1", port=port,
                                           log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield HttpResourceClient(f"http://127.0.0.1:{port}", poll_s=0.05), svc, src
    server.should_exit = True
    th.join(5)


def test_http_client_matches_local_semantics(http_rc):
    http, svc, src = http_rc
    local = LocalResourceClient(svc)
    atts = src.atts()
    assert http.health()["ok"] is True
    assert [x["stored"] for x in http.lookup("contract", atts)] == [False, False]
    events = []
    files = http.ensure_files("contract", "500", "99", atts, progress=events.append)
    assert [f["reused"] for f in files] == [False, False]
    assert [e["type"] for e in events if e["type"] == "file.downloaded"] == ["file.downloaded"] * 2
    infos = http.ensure_parsed("contract", "500", files, progress=events.append)
    assert len(infos) == 3 and any(e["type"] == "file.parsed" for e in events)
    doc = http.parsed(files[0]["sig"])
    assert doc == local.parsed(files[0]["sig"]) and "合同正文 HTTP" in doc["pages"][0]["text"]
    assert http.read_blob(files[0]["sig"]) == src.files["合同.docx"]
    assert http.blob_by_prefix(files[0]["sig"][:16]) == files[0]["sig"]
    assert http.parsed("0" * 64) is None
    snap = http.sync_request("contract", "500", "contract")
    assert snap["status"] == "ready" and http.requests("contract")[0]["request_id"] == "500"
    assert http.request("contract", "500")["files"]


def test_http_client_transports_error_class(http_rc):
    http, _svc, src = http_rc
    src.fail = SessionExpired("会话失效")
    with pytest.raises(SessionExpired) as ei:
        http.ensure_files("contract", "600", "99", src.atts())
    assert ei.value.title == "门户登录已失效"


def test_http_unreachable_is_explicit():
    from core.resource.client import ResourceUnavailable

    with pytest.raises(ResourceUnavailable) as ei:
        HttpResourceClient(f"http://127.0.0.1:{_free_port()}").health()
    assert "core.resource.api" in ei.value.hint


# ------------------------------------------------------------------ 审查流程中的当场同步提示
def test_run_emits_inline_sync_notice_then_reuses(tmp_path, monkeypatch):
    from core.sources.local import LocalCaseClient
    from employees.meeting import graph as mgraph
    from employees.meeting import samples
    from tests.support.env import temp_resources, temp_store
    from tests.support.fakes import FakeJudge

    cases = tmp_path / "cases"
    samples.write(cases)
    monkeypatch.setattr(mgraph, "REPORTS", tmp_path / "reports")
    store, rc = temp_store(tmp_path), temp_resources(tmp_path)
    client = LocalCaseClient("meeting", root=cases)

    def run():
        ev = []
        mgraph.run("DEMO-SH-002", store, None, on_event=ev.append, source="local", client=client, resources=rc,
                   judge=FakeJudge())
        return ev

    first = run()
    notices = [e for e in first if e["type"] == "sync.notice"]
    assert {n["stage"] for n in notices} == {"download", "parse"}
    assert "正在现场同步" in notices[0]["text"] and "不等下一轮采集" in notices[0]["text"]
    second = run()
    assert not [e for e in second if e["type"] == "sync.notice"]
    assert any(e["type"] == "sync.ready" for e in second)
    assert all(e["cache"] == "hit" for e in second if e["type"] == "file.parsed")
    tid = store.list_tasks("meeting", 1)[0]["task_id"]
    assert store.cache_stats(tid)["L1"]["hit"] == store.cache_stats(tid)["L1"]["total"] > 0
