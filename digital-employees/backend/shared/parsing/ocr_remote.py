"""客户 PaddleOCR-VL 版面解析服务（layout-parsing）引擎。

- 限流：资料中心进程内全局生效——同时在途请求数（concurrency）+ 每分钟调用上限（per_minute）；
  当场同步（priority 高）排在采集之前。
- 重试：网络错误、超时、429、5xx 按指数退避重试；仍失败的页标记 ocr-failed（文档状态 partial），不阻断其他页。
- 输出归一：Markdown / HTML 表格转为与 Word 解析一致的纯文本（段落按行，表格每行「单元格 | 单元格」），
  版面块（类型、文字、坐标）保存在页数据中供证据高亮。
- send_pdf：把需要 OCR 的页抽成子 PDF 分批发送（fileType=0），客户确认支持后在 config/ocr.yaml 打开。
"""
from __future__ import annotations

import base64
import heapq
import itertools
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from html.parser import HTMLParser
from typing import Callable

import requests

NAME = "paddleocr_vl"
PDF_BATCH = 20
_local = threading.local()


@contextmanager
def priority(level: int):
    """在当前线程内设定 OCR 调用优先级（数值大者先获得配额）。"""
    old = getattr(_local, "priority", 1)
    _local.priority = level
    try:
        yield
    finally:
        _local.priority = old


class Gate:
    """优先级 + 并发 + 每分钟次数限流。"""

    def __init__(self, concurrency: int, per_minute: int):
        self.concurrency = max(1, concurrency)
        self.per_minute = max(1, per_minute)
        self.cv = threading.Condition()
        self.running = 0
        self.calls: list[float] = []
        self.waiting: list[tuple[int, int]] = []
        self.seq = itertools.count()

    def _rate_wait(self) -> float:
        now = time.time()
        self.calls = [t for t in self.calls if now - t < 60]
        if len(self.calls) < self.per_minute:
            return 0.0
        return 60 - (now - self.calls[0]) + 0.01

    @contextmanager
    def slot(self, level: int):
        ticket = (-level, next(self.seq))
        with self.cv:
            heapq.heappush(self.waiting, ticket)
            while True:
                if self.waiting[0] == ticket and self.running < self.concurrency:
                    wait = self._rate_wait()
                    if wait <= 0:
                        break
                    self.cv.wait(timeout=wait)
                    continue
                self.cv.wait(timeout=1)
            heapq.heappop(self.waiting)
            self.running += 1
            self.calls.append(time.time())
            self.cv.notify_all()
        try:
            yield
        finally:
            with self.cv:
                self.running -= 1
                self.cv.notify_all()


_gates: dict[tuple, Gate] = {}
_gates_lock = threading.Lock()


def gate_for(url: str, concurrency: int, per_minute: int) -> Gate:
    key = (url, concurrency, per_minute)
    with _gates_lock:
        if key not in _gates:
            _gates[key] = Gate(concurrency, per_minute)
        return _gates[key]


class _TableText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            if not self.rows:
                self.rows.append([])
            self.rows[-1].append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def table_text(html: str) -> str:
    p = _TableText()
    p.feed(html)
    p.close()
    return "\n".join(" | ".join(c for c in row if c) for row in p.rows if any(row))


def markdown_text(md: str) -> str:
    """Markdown（含 HTML 表格）→ 纯文本。"""
    md = re.sub(r"<table[\s\S]*?</table>", lambda m: "\n" + table_text(m.group(0)) + "\n", md or "", flags=re.I)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)|<img[^>]*>", "", md)
    md = re.sub(r"<div[^>]*>|</div>", "\n", md, flags=re.I)
    md = re.sub(r"<[^>]+>", "", md)
    md = re.sub(r"^\s{0,3}#{1,6}\s*", "", md, flags=re.M)
    md = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), md)
    md = re.sub(r"\$\s*([^$\n]{1,40}?)\s*\$", r"\1", md)
    return "\n".join(ln.strip() for ln in md.splitlines() if ln.strip())


def _block_text(b: dict) -> str:
    content = str(b.get("block_content") or "")
    if (b.get("block_label") or "").lower() == "table" or "<table" in content.lower():
        return table_text(content) if "<t" in content.lower() else content
    return markdown_text(content)


def page_from_result(res: dict) -> dict:
    """layoutParsingResults 的一项 → {text, conf, lines, blocks, size}。"""
    pruned = res.get("prunedResult") or {}
    blocks = []
    for b in pruned.get("parsing_res_list") or []:
        text = _block_text(b)
        if text:
            blocks.append({"label": b.get("block_label"), "text": text, "bbox": b.get("block_bbox")})
    if blocks:
        text = "\n".join(b["text"] for b in blocks)
    else:
        text = markdown_text(((res.get("markdown") or {}).get("text")) or "")
    size = [pruned.get("width"), pruned.get("height")] if pruned.get("width") else None
    return {"text": text, "conf": None, "lines": None, "blocks": blocks or None, "size": size}


class OcrServiceError(RuntimeError):
    pass


class PaddleVLEngine:
    name = NAME

    def __init__(self, cfg: dict):
        self.url = str(cfg.get("url") or "").strip()
        if not self.url:
            raise RuntimeError("config/ocr.yaml 中 paddleocr_vl.url 未配置")
        self.dpi = int(cfg.get("dpi") or 150)
        self.timeout = float(cfg.get("timeout_s") or 120)
        self.retries = int(cfg.get("retries") if cfg.get("retries") is not None else 2)
        self.sec_per_page = float(cfg.get("sec_per_page") or 3.5)
        self.send_pdf = bool(cfg.get("send_pdf"))
        self.concurrency = int(cfg.get("concurrency") or 2)
        self.options = dict(cfg.get("options") or {})
        self.gate = gate_for(self.url, self.concurrency, int(cfg.get("per_minute") or 30))
        self.http = requests.Session()
        self.http.trust_env = False

    def params(self) -> dict:
        # 地址不入参数：服务换到内网地址不影响已有结果
        return {"ocr": NAME, "dpi": self.dpi, "layout": bool(self.options.get("useLayoutDetection", True))}

    def estimate_seconds(self, pages: int) -> float:
        return pages * self.sec_per_page / max(1, self.concurrency)

    def _call(self, data: bytes, file_type: int) -> list[dict]:
        body = {"file": base64.b64encode(data).decode("ascii"), "fileType": file_type, "visualize": False, **self.options}
        last = ""
        for attempt in range(self.retries + 1):
            if attempt:
                time.sleep(min(30, 2 ** attempt))
            with self.gate.slot(getattr(_local, "priority", 1)):
                try:
                    r = self.http.post(self.url, json=body, timeout=self.timeout)
                except requests.RequestException as exc:
                    last = f"{type(exc).__name__}: {exc}"
                    continue
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                continue
            if r.status_code != 200:
                raise OcrServiceError(f"HTTP {r.status_code}: {r.text[:200]}")
            try:
                d = r.json()
            except ValueError:
                raise OcrServiceError(f"返回不是 JSON：{r.text[:200]}") from None
            results = ((d.get("result") or {}).get("layoutParsingResults")) if isinstance(d, dict) else None
            if not isinstance(results, list) or not results:
                raise OcrServiceError(f"返回结构异常：{str(d)[:200]}")
            return results
        raise OcrServiceError(f"重试 {self.retries} 次仍失败：{last}")

    def _one(self, png: bytes) -> dict:
        try:
            return page_from_result(self._call(png, 1)[0])
        except OcrServiceError as exc:
            return {"failed": True, "error": str(exc)}

    def ocr_images(self, pngs: list[bytes], on_page: Callable[[int, int], None] | None = None) -> list[dict]:
        if not pngs:
            return []
        out: list[dict | None] = [None] * len(pngs)
        done = {"n": 0}
        lock = threading.Lock()
        level = getattr(_local, "priority", 1)

        def work(i: int) -> None:
            with priority(level):
                out[i] = self._one(pngs[i])
            with lock:
                done["n"] += 1
                if on_page:
                    on_page(done["n"], len(pngs))

        with ThreadPoolExecutor(max_workers=min(len(pngs), self.concurrency * 2)) as ex:
            list(ex.map(work, range(len(pngs))))
        return out  # type: ignore[return-value]

    def ocr_pdf_pages(self, pdf: bytes, indices: list[int],
                      on_page: Callable[[int, int], None] | None = None) -> list[dict]:
        """整份 PDF 模式：只把需要 OCR 的页抽成子 PDF，按批发送；返回与 indices 一一对应的页结果。"""
        import pymupdf

        src = pymupdf.open(stream=pdf, filetype="pdf")
        out: list[dict] = []
        for start in range(0, len(indices), PDF_BATCH):
            batch = indices[start:start + PDF_BATCH]
            sub = pymupdf.open()
            for i in batch:
                sub.insert_pdf(src, from_page=i, to_page=i)
            try:
                results = self._call(sub.tobytes(), 0)
                if len(results) != len(batch):
                    raise OcrServiceError(f"返回 {len(results)} 页，提交 {len(batch)} 页")
                out += [page_from_result(r) for r in results]
            except OcrServiceError as exc:
                out += [{"failed": True, "error": str(exc)} for _ in batch]
            if on_page:
                on_page(len(out), len(indices))
        return out
