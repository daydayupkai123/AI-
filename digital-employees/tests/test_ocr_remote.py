"""客户 PaddleOCR-VL 引擎：输出归一、重试与失败页、只重试失败页、整份 PDF 模式、优先级限流。用本地模拟服务。"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.parsing import ocr, ocr_remote
from core.parsing.ocr_remote import Gate, markdown_text, page_from_result, table_text

TABLE = ("<table border=1><tr><td>序号</td><td>商品名称</td><td>数量</td></tr>"
         "<tr><td>1.</td><td>数码摄像机</td><td>1</td></tr></table>")


def _result(text: str, blocks=None) -> dict:
    return {"markdown": {"text": text}, "prunedResult": {"parsing_res_list": blocks or [], "width": 1240, "height": 1754}}


def test_table_and_markdown_normalised():
    assert table_text(TABLE) == "序号 | 商品名称 | 数量\n1. | 数码摄像机 | 1"
    md = "## 采购合同\n\n**甲方**：某公司\n\n" + TABLE + "\n\n![](imgs/a.png)"
    assert markdown_text(md) == "采购合同\n甲方：某公司\n序号 | 商品名称 | 数量\n1. | 数码摄像机 | 1"


def test_blocks_preferred_and_bbox_kept():
    res = _result("忽略", [{"block_label": "doc_title", "block_content": "# 中标通知书", "block_bbox": [1, 2, 3, 4]},
                         {"block_label": "table", "block_content": TABLE, "block_bbox": [5, 6, 7, 8]}])
    p = page_from_result(res)
    assert p["text"] == "中标通知书\n序号 | 商品名称 | 数量\n1. | 数码摄像机 | 1"
    assert p["blocks"][1]["bbox"] == [5, 6, 7, 8] and p["size"] == [1240, 1754]
    assert page_from_result(_result("只有 Markdown"))["text"] == "只有 Markdown"


class FakeOcr:
    """模拟 layout-parsing：按配置返回 429 / 500 / 正常结果，记录每次请求的 fileType。"""

    def __init__(self):
        self.calls: list[int] = []
        self.plan: list[int] = []  # 依次返回的状态码，用完后一律 200
        self.always: int | None = None
        self.pdf_pages = 1
        fake = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.calls.append(body["fileType"])
                code = fake.always or (fake.plan.pop(0) if fake.plan else 200)
                if code != 200:
                    self.send_response(code)
                    self.end_headers()
                    self.wfile.write(b'{"message":"busy"}')
                    return
                n = fake.pdf_pages if body["fileType"] == 0 else 1
                out = {"result": {"layoutParsingResults": [_result(f"第{i + 1}段 识别文字") for i in range(n)]}}
                data = json.dumps(out, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/paddleocr-vl/layout-parsing"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture()
def fake_ocr(tmp_path, monkeypatch):
    fake = FakeOcr()

    def use(**kw):
        cfg = {"engine": "paddleocr_vl", "paddleocr_vl": {"url": fake.url, "concurrency": 2, "per_minute": 1000,
                                                          "timeout_s": 5, "retries": 2, "dpi": 72, **kw}}
        path = tmp_path / f"ocr_{time.time_ns()}.yaml"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setattr(ocr, "CONFIG_PATH", path)
        monkeypatch.setattr(ocr_remote.time, "sleep", lambda s: None)  # 退避不真等
        return ocr.engine()

    yield fake, use
    fake.server.shutdown()
    monkeypatch.undo()
    ocr._cfg.update(mtime=None, cfg=None, engine=None)


def _scan_pdf(blank: int, text: int = 1) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for i in range(text):
        doc.new_page().insert_text((72, 72), "text layer page " * 5)
    for _ in range(blank):
        doc.new_page()
    return doc.tobytes()


def _parser(tmp_path):
    from core.parsing.pipeline import Parser
    from core.resource.store import ResourceStore

    store = ResourceStore(db_path=tmp_path / "rc.sqlite3", root=tmp_path / "store", legacy_db=None)
    return store, Parser(store)


def test_engine_params_and_retry_on_429(fake_ocr):
    fake, use = fake_ocr
    eng = use()
    assert eng.params() == {"ocr": "paddleocr_vl", "dpi": 72, "layout": True}
    fake.plan = [429, 503]
    res = eng.ocr_images([b"png"])
    assert res[0]["text"] == "第1段 识别文字" and len(fake.calls) == 3


def test_persistent_failure_marks_page_then_retries_only_failed(fake_ocr, tmp_path):
    fake, use = fake_ocr
    use()
    store, parser = _parser(tmp_path)
    sig = store.put_blob(_scan_pdf(blank=2), ext="pdf")
    fake.always = 500
    doc = parser.parse(sig, "扫描件.pdf")
    assert doc["status"] == "partial" and "OCR 失败" in doc["error"]
    assert [p["method"] for p in doc["pages"]] == ["text", "ocr-failed", "ocr-failed"]
    assert parser.cached(sig) is None and parser.cached(sig, allow_failed_pages=True)["status"] == "partial"
    fake.always, fake.calls = None, []
    events = []
    doc2 = parser.parse(sig, "扫描件.pdf", progress=events.append)
    assert doc2["status"] == "ok" and [p["method"] for p in doc2["pages"]] == ["text", "ocr", "ocr"]
    assert len(fake.calls) == 2  # 只重试失败的 2 页，文字层页不调 OCR
    assert [e["done"] for e in events if e["type"] == "file.ocr"] == [1, 2]
    assert parser.cached(sig)["_cache"] == "hit"


def test_send_pdf_mode_sends_only_scanned_pages(fake_ocr, tmp_path):
    fake, use = fake_ocr
    use(send_pdf=True)
    store, parser = _parser(tmp_path)
    sig = store.put_blob(_scan_pdf(blank=3, text=2), ext="pdf")
    fake.pdf_pages = 3
    doc = parser.parse(sig, "混合.pdf")
    assert fake.calls == [0]  # 一次整份子 PDF 请求
    assert [p["method"] for p in doc["pages"]] == ["text", "text", "ocr", "ocr", "ocr"]
    assert doc["pages"][4]["text"] == "第3段 识别文字"


def test_switching_engine_rekeys_cache(fake_ocr, tmp_path, monkeypatch):
    fake, use = fake_ocr
    store, parser = _parser(tmp_path)
    sig = store.put_blob(_scan_pdf(blank=1), ext="pdf")
    use()
    k_paddle = parser.key_for(sig)
    parser.parse(sig, "a.pdf")
    path = tmp_path / "rapid.yaml"
    path.write_text(json.dumps({"engine": "rapidocr"}), encoding="utf-8")
    monkeypatch.setattr(ocr, "CONFIG_PATH", path)
    assert parser.key_for(sig) != k_paddle and parser.cached(sig) is None


def test_gate_serves_high_priority_first():
    gate = Gate(concurrency=1, per_minute=1000)
    order, hold = [], threading.Event()

    def holder():
        with gate.slot(1):
            hold.wait(2)

    def waiter(name, level):
        with gate.slot(level):
            order.append(name)

    t0 = threading.Thread(target=holder)
    t0.start()
    time.sleep(0.05)
    low = threading.Thread(target=waiter, args=("采集", 1))
    low.start()
    time.sleep(0.05)
    high = threading.Thread(target=waiter, args=("当场同步", 10))
    high.start()
    time.sleep(0.05)
    hold.set()
    for t in (t0, low, high):
        t.join(5)
    assert order == ["当场同步", "采集"]


def test_gate_per_minute_limit_blocks(monkeypatch):
    gate = Gate(concurrency=5, per_minute=2)
    with gate.slot(1):
        pass
    with gate.slot(1):
        pass
    got = threading.Event()

    def third():
        with gate.slot(1):
            got.set()

    threading.Thread(target=third, daemon=True).start()
    assert not got.wait(0.3)  # 第 3 次在一分钟窗口内被挡住
