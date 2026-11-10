"""本地 OCR 仿真服务（tools/ocr_local_server.py）：资料中心按「客户 OCR」配置走真实 HTTP 链路，扫描页识别、坐标、重试。"""
import importlib.util
import json
import socket
import threading
import time
from pathlib import Path

import pytest

from core.parsing import ocr, ocr_remote

ROOT = Path(__file__).resolve().parents[1]


def _load_server():
    spec = importlib.util.spec_from_file_location("ocr_local_server", ROOT / "tools" / "ocr_local_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def local_ocr(tmp_path, monkeypatch):
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(_load_server().build_app("rapidocr", "", fail_every=2),
                                           host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    t0 = time.time()
    while not server.started and time.time() - t0 < 20:
        time.sleep(0.1)
    cfg = {"engine": "paddleocr_vl", "paddleocr_vl": {
        "url": f"http://127.0.0.1:{port}/paddleocr-vl/layout-parsing", "concurrency": 1, "per_minute": 1000,
        "timeout_s": 60, "retries": 2, "dpi": 150}}
    path = tmp_path / "ocr.yaml"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(ocr, "CONFIG_PATH", path)
    monkeypatch.setattr(ocr_remote.time, "sleep", lambda s: None)
    yield ocr.engine(), port
    server.should_exit = True
    monkeypatch.undo()
    ocr._cfg.update(mtime=None, cfg=None, engine=None)


def test_vlm_output_cleanup_and_degenerate_fallback():
    srv = _load_server()
    md = "```markdown\n# 补充协议\n| 序号 | 金额 |\n| --- | --- |\n|  |  |\n|  |  |\n| 1 | 20.55 |\n| 1 | 20.55 |\n```"
    assert srv.clean_markdown(md) == "# 补充协议\n| 序号 | 金额 |\n| 1 | 20.55 |"
    blocks = [{"block_content": "因本补充协议引起争议，双方优先协商；协商不成，提交甲方所在地仲裁委员会仲裁，裁决为终局裁决。"}]
    assert srv.degenerate(srv.clean_markdown("|  |  |\n| --- | --- |\n|  |  |"), blocks)
    assert not srv.degenerate(blocks[0]["block_content"], blocks)
    assert not srv.degenerate("", [{"block_content": "三、日照建模分析图"}])  # 页面本来就几乎没有字时不算退化


def _scanned_pdf(pages: list[list[str]]) -> bytes:
    """先把文字排版成页面，再栅格化成图片放进新 PDF（无文字层，等同扫描件）。"""
    import pymupdf

    out = pymupdf.open()
    for lines in pages:
        src = pymupdf.open()
        page = src.new_page()
        for i, t in enumerate(lines):
            page.insert_text((72, 120 + i * 60), t, fontsize=28)
        p = out.new_page()
        p.insert_image(p.rect, stream=page.get_pixmap(dpi=150).tobytes("png"))
    return out.tobytes()


def test_scanned_pdf_parsed_through_local_ocr_service(local_ocr, tmp_path):
    from core.parsing.pipeline import Parser
    from core.resource.store import ResourceStore

    import httpx

    eng, port = local_ocr
    assert eng.name == "paddleocr_vl"
    store = ResourceStore(db_path=tmp_path / "rc.sqlite3", root=tmp_path / "store", legacy_db=None)
    pdf = _scanned_pdf([["CONTRACT NO 2026-118", "TOTAL AMOUNT 35000"], ["PAYMENT TERMS MONTHLY"]])
    sig = store.put_blob(pdf, ext="pdf")
    doc = Parser(store).parse(sig, "scan.pdf")
    p1, p2 = doc["pages"]
    t1, t2 = (p["text"].replace(" ", "").upper() for p in (p1, p2))
    assert p1["method"] == p2["method"] == "ocr" and "2026-118" in t1 and "35000" in t1 and "MONTHLY" in t2
    assert p1.get("blocks") and all(len(b["bbox"]) == 4 for b in p1["blocks"])  # 带坐标 → 证据截图可高亮
    # 仿真服务第 2 次请求返回 503：客户端重试后两页都完整入库（共 3 次请求），再次解析命中缓存不再请求
    calls = httpx.get(f"http://127.0.0.1:{port}/health", trust_env=False).json()["calls"]
    assert calls == 3
    again = Parser(store).parse(sig, "scan.pdf")
    assert again.get("_cache") and [p["text"] for p in again["pages"]] == [p1["text"], p2["text"]]
    assert httpx.get(f"http://127.0.0.1:{port}/health", trust_env=False).json()["calls"] == 3
