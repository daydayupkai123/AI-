"""平台页面留档：打开规则（不开待办）、只读拦截规则、敏感信息定位、截图原样入库与展示打码、审查结束时入档。"""
import io
from types import SimpleNamespace

from PIL import Image

from shared import portal_snapshot
from storage_service.client import LocalResourceClient
from storage_service.desensitize import sensitive_spans
from storage_service.service import ResourceService
from storage_service.store import ResourceStore


def _req(rid="1671817", **raw):
    return SimpleNamespace(request_id=rid, raw_params=raw, via_monitor=raw.pop("_monitor", False))


def test_contract_pending_is_never_opened():
    assert portal_snapshot.target("contract", _req(isremark="0", isviewonly=0, requestType=1)).get("skip")
    assert portal_snapshot.target("contract", _req(isremark="", isviewonly="", requestType=0)).get("skip")  # 无法确认只读
    t = portal_snapshot.target("contract", _req(isremark="", isviewonly="1", requestType=0, _monitor=True))
    assert t["url"].endswith("#/main/workflow/req?requestid=1671817&ismonitor=1")


def test_contract_fetch_stops_at_pending_before_detail(monkeypatch):
    """手工输入当前账号的待办单号：loadForm 后即停止，不读审批日志、不进入附件下载。"""
    import pytest

    from shared.errors import NoAccess
    from storage_service import settings
    from shared.source_adapters.contract import ContractClient

    calls = []

    class Resp:
        def __init__(self, url, data):
            self.url, self.status_code, self._d = url, 200, data
            self.request = SimpleNamespace(method="POST")

        def json(self):
            return self._d

    class Sess:
        def post(self, url, data=None, timeout=None):
            calls.append(url.split("/api/")[-1])
            return Resp(url, {"params": {"workflowid": "99", "isremark": "0", "requestType": 1, "isviewonly": 0}})

    monkeypatch.setattr(settings, "collect", lambda: {"allow_pending_detail": False})
    with pytest.raises(NoAccess) as e:
        ContractClient(Sess(), base="https://contract.example").fetch("1656669")
    assert e.value.title == "待办单据暂不打开" and calls == ["workflow/reqform/loadForm"]


def test_docflow_opens_done_view_only_and_local_has_no_page():
    t = portal_snapshot.target("docflow", _req(rid="通设请字[2026]76号", affairId="-123"))
    assert "openFrom%3DlistDone" in t["url"] and "affairId%3D-123" in t["url"]
    assert portal_snapshot.target("docflow", _req()).get("skip")
    assert portal_snapshot.target("local", _req()).get("skip")


def test_write_requests_are_blocked_but_reads_pass():
    w = lambda path, body="": bool(portal_snapshot.WRITE.search(path) or portal_snapshot.WRITE_BODY.search(body))  # noqa: E731
    assert w("/api/systemViewLog/home/InsertSystemPageViewLog")
    assert w("/api/workflow/reqform/updateReqInfo")
    assert w("/api/workflow/request/doSubmit")
    assert w("/kapi/app/form/batchInvokeAction", '{"actionId":"bar_submit"}')
    # 只读请求即使请求体里有 submit=0 也不拦
    assert not w("/api/workflow/reqform/getRequestLogBaseInfo", "requestid=1&submit=0&isprint=0")
    assert not w("/api/workflow/reqform/loadForm", "requestid=1671817")


def test_sensitive_spans():
    s = "联系人电话 13812345678，身份证 11010519491231002X，账号 6222020200112233445 金额 210.000000 单号 1671817"
    got = [s[a:b] for a, b in sensitive_spans(s)]
    assert got == ["13812345678", "11010519491231002X", "6222020200112233445"]
    assert sensitive_spans("合同额 210000.00 万元，编号 TYSJ-FW26114019") == []


def _png(w=200, h=100):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, "PNG")
    return buf.getvalue()


def test_trim_bottom_whitespace_removes_tall_blank():
    import io

    from PIL import Image

    from storage_service.image_trim import trim_bottom_whitespace

    # 纯白底 + 顶部内容
    im = Image.new("RGB", (200, 2000), (255, 255, 255))
    for y in range(0, 120):
        for x in range(20, 180):
            im.putpixel((x, y), (30, 30, 30))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    out, w, h = trim_bottom_whitespace(buf.getvalue(), pad=12)
    assert h < 400 and w <= 200
    assert Image.open(io.BytesIO(out)).size == (w, h)

    # 门户浅灰底 + 中间表单块 + 右侧细线噪声
    im = Image.new("RGB", (800, 3000), (240, 243, 245))
    for y in range(40, 280):
        for x in range(80, 520):
            im.putpixel((x, y), (40, 40, 40))
    for y in range(0, 3000):
        im.putpixel((799, y), (200, 200, 200))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    out, w, h = trim_bottom_whitespace(buf.getvalue(), pad=12)
    assert h < 400 and w < 600, (w, h)


def test_page_saved_raw_and_masked_on_display(tmp_path):
    svc = ResourceService(ResourceStore(db_path=tmp_path / "rc.sqlite3", root=tmp_path / "store", legacy_db=None), None)
    svc.archive_start("t1", "contract", "contract", "1671817", "web", {})
    pid = svc.archive_page("t1", {"title": "合同系统", "url": "https://x", "width": 200, "height": 100}, _png(),
                           [[10, 10, 60, 30]])
    raw = Image.open(io.BytesIO(svc.page_png(pid, masked=False)))
    masked = Image.open(io.BytesIO(svc.page_png(pid)))
    assert raw.getpixel((30, 20)) == (255, 255, 255)          # 原图未改动
    assert masked.getpixel((30, 20)) == (46, 50, 56)          # 展示版涂黑
    assert masked.getpixel((100, 60)) == (255, 255, 255)
    assert Image.open(io.BytesIO(svc.page_png(pid, max_width=100))).width == 100
    arc = svc.archive("t1")
    assert arc["pages"] == [{"page_id": pid, "title": "合同系统", "url": "https://x", "width": 200, "height": 100,
                             "created_at": arc["pages"][0]["created_at"], "pii_count": 1}]


def test_capture_result_archived_at_finish(tmp_path, monkeypatch):
    svc = ResourceService(ResourceStore(db_path=tmp_path / "rc.sqlite3", root=tmp_path / "store", legacy_db=None), None)
    rc = LocalResourceClient(svc)
    svc.archive_start("t2", "contract", "contract", "1671817", "auto", {})
    monkeypatch.setattr(portal_snapshot, "capture", lambda session, url: {
        "png": _png(), "pii": [[1, 1, 5, 5]], "ops": [{"method": "POST", "url": "https://contract.gt.cn/api/workflow/reqform/loadForm",
                                                        "status": 200, "type": "fetch", "at": 1.0}],
        "blocked": [{"method": "POST", "url": "https://contract.gt.cn/api/systemViewLog/home/InsertSystemPageViewLog"}],
        "width": 200, "height": 100, "truncated": False, "final_url": url, "error": None, "ms": 1200})
    events = []
    rt = SimpleNamespace(sessions=SimpleNamespace(session=lambda: object()), resources=rc, on_event=events.append)
    arc = SimpleNamespace(ok=True, task_id="t2", items=[], add=lambda kind, title, body: arc.items.append((kind, title, body)))
    portal_snapshot.PageCapture(rt, "contract", _req(isremark="", isviewonly="1", requestType=0)).start().finish(arc)
    kind, title, body = arc.items[0]
    assert kind == "page" and body["page_id"] and body["blocked"][0]["url"].endswith("InsertSystemPageViewLog")
    assert events == [{"type": "archive.page", "ok": True, "skip": None, "error": None}]
    # 待办：不启动浏览器，档案写明原因
    monkeypatch.setattr(portal_snapshot, "capture", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应打开待办")))
    arc.items.clear()
    portal_snapshot.PageCapture(rt, "contract", _req(isremark="0", isviewonly=0, requestType=1)).start().finish(arc)
    assert arc.items[0][2]["skip"] and not arc.items[0][2].get("page_id")
