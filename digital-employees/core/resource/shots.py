"""证据截图：把引用原文所在页渲染成 PNG，并高亮引用位置。

- 文字层 PDF：按引用原文搜索字符位置（逐步缩短检索片段，容忍换行与标点差异），精确高亮
- 扫描页：在解析结果的 OCR 行（RapidOCR）/ 版面块（PaddleOCR-VL）中找包含引用片段的位置并高亮
- 图片：同扫描页
- Word / Excel：无页面图（method=none），档案中展示原文片段
"""
from __future__ import annotations

import re

from ..parsing import formats

RENDER_DPI = 110


def _norm(s: str) -> str:
    return re.sub(r"[\s\u3000，,。.；;：:“”\"'‘’（）()、]", "", s or "")


def _needles(quote: str) -> list[str]:
    """检索片段：先按原文（空白合并为单个空格），再去掉空白（PDF 换行把句子拆开时），逐步缩短；
    最后按标点切出的较长分句（引用跨行或开头带页眉时，句中片段仍能定位）。"""
    spaced = re.sub(r"\s+", " ", quote or "").strip()
    tight = re.sub(r"\s+", "", quote or "")
    out = []
    for q in (spaced, tight):
        for n in (q[:40], q[:24], q[:14]):
            n = n.strip()
            if len(n) >= 6 and n not in out:
                out.append(n)
    parts = sorted({p for p in re.split(r"[，,。；;：:、（）()\s]+", quote or "") if len(p) >= 6}, key=len, reverse=True)
    for p in parts[:4]:
        if p not in out:
            out.append(p[:24])
    for n in (tight[:8],):
        if len(n) >= 4 and n not in out:
            out.append(n)
    return out


def _ocr_hits(page: dict, quote: str) -> list[list[float]]:
    """OCR 行 / 版面块中包含引用片段的框（像素坐标，OCR 渲染 dpi 下）。"""
    q = _norm(quote)
    if len(q) < 4:
        return []
    boxes = []
    for ln in page.get("lines") or []:
        t = _norm(ln.get("text"))
        if len(t) >= 4 and (t in q or q[:12] in t or (len(t) >= 6 and t[:12] in q)):
            xs, ys = [p[0] for p in ln["box"]], [p[1] for p in ln["box"]]
            boxes.append([min(xs), min(ys), max(xs), max(ys)])
    if not boxes:
        for b in page.get("blocks") or []:
            t = _norm(b.get("text"))
            if b.get("bbox") and (q[:12] in t or (len(t) >= 6 and t in q)):
                boxes.append([float(x) for x in b["bbox"][:4]])
    return boxes[:8]


def render(data: bytes, filename: str, doc: dict | None, page_no: int | None, quote: str,
           ocr_dpi: int = 150) -> dict:
    """返回 {method: text|ocr|none, page_no, rects, png: bytes|None}。"""
    import pymupdf

    kind = formats.detect(data, filename)
    if kind not in ("pdf", "image"):
        return {"method": "none", "page_no": page_no, "rects": [], "png": None}
    pdf = pymupdf.open(stream=data, filetype="pdf" if kind == "pdf" else None) if kind == "pdf" \
        else pymupdf.open(stream=data, filetype=_img_type(data))
    pages_meta = {p.get("no"): p for p in (doc or {}).get("pages", [])}
    order = [page_no] if page_no else list(range(1, pdf.page_count + 1))
    for no in order:
        if not no or no > pdf.page_count:
            continue
        page = pdf[no - 1]
        meta = pages_meta.get(no) or {}
        rects, method = [], "text"
        if kind == "pdf" and not str(meta.get("method", "text")).startswith("ocr"):
            for n in _needles(quote):
                rects = [list(r) for r in page.search_for(n)]
                if rects:
                    break
        if not rects:
            px = _ocr_hits(meta, quote)
            if px:
                method = "ocr"
                if kind == "pdf":
                    scale = 72.0 / (meta.get("dpi") or ocr_dpi)
                else:
                    w = (meta.get("ocr_size") or [None])[0] or pymupdf.Pixmap(data).width
                    scale = page.rect.width / w
                rects = [[x0 * scale, y0 * scale, x1 * scale, y1 * scale] for x0, y0, x1, y1 in px]
        if not rects:
            continue
        for r in rects:
            annot = page.add_rect_annot(pymupdf.Rect(*r) + (-2, -2, 2, 2))
            annot.set_colors(stroke=(0.9, 0.1, 0.1), fill=(1, 0.85, 0.2))
            annot.set_opacity(0.35)
            annot.update()
        png = page.get_pixmap(dpi=RENDER_DPI).tobytes("png")
        return {"method": method, "page_no": no, "rects": rects, "png": png}
    # 定位不到：给出所在页（或首页）原图，不高亮
    no = page_no if page_no and page_no <= pdf.page_count else 1
    return {"method": "page", "page_no": no, "rects": [], "png": pdf[no - 1].get_pixmap(dpi=RENDER_DPI).tobytes("png")}


def _open(data: bytes, kind: str):
    import pymupdf

    return pymupdf.open(stream=data, filetype="pdf") if kind == "pdf" else pymupdf.open(stream=data, filetype=_img_type(data))


def _para_hit(text: str, quote: str) -> int | None:
    """Word / Excel：引用所在段落序号（按换行切分；容忍空白与标点差异）。"""
    needles = [n for n in (_norm(x) for x in _needles(quote)) if len(n) >= 4]
    for i, para in enumerate((text or "").split("\n")):
        t = _norm(para)
        if t and any(n in t for n in needles):
            return i
    return None


def locate(data: bytes, filename: str, doc: dict | None, quote: str, page_no: int | None = None,
           ocr_dpi: int = 150) -> dict:
    """原文对照用：只计算引用位置，不出图。返回 {kind, method, page_no, rects（PDF 点坐标）, page_w, page_h, para}。
    method：text 文字层精确定位 / ocr OCR 行 / para 段落（Word、Excel）/ page 只知道页 / none 未定位。"""
    kind = formats.detect(data, filename)
    pages = (doc or {}).get("pages", [])
    if kind not in ("pdf", "image"):
        for p in pages if not page_no else sorted(pages, key=lambda p: p.get("no") != page_no):
            i = _para_hit(p.get("text") or "", quote)
            if i is not None:
                return {"kind": kind, "method": "para", "page_no": p.get("no"), "para": i, "rects": []}
        return {"kind": kind, "method": "none", "page_no": page_no, "rects": []}
    pdf = _open(data, kind)
    meta = {p.get("no"): p for p in pages}
    needles = [n for n in _needles(quote)]
    tn = [x for x in (_norm(n) for n in needles) if len(x) >= 6]
    # 候选页：给定页优先，其次解析文本中含检索片段的页，最后全部页
    cand = [p.get("no") for p in pages if tn and any(x in _norm(p.get("text") or "") for x in tn)]
    order = ([page_no] if page_no else []) + [n for n in cand if n != page_no]
    order += [n for n in range(1, pdf.page_count + 1) if n not in order] if not cand else []
    for no in order:
        if not no or no > pdf.page_count:
            continue
        page = pdf[no - 1]
        m = meta.get(no) or {}
        rects, method = [], "text"
        if kind == "pdf" and not str(m.get("method", "text")).startswith("ocr"):
            for n in needles:
                rects = [list(r) for r in page.search_for(n)]
                if rects:
                    break
        if not rects:
            px = _ocr_hits(m, quote)
            if px:
                method = "ocr"
                scale = 72.0 / (m.get("dpi") or ocr_dpi) if kind == "pdf" else \
                    page.rect.width / ((m.get("ocr_size") or [None])[0] or page.rect.width)
                rects = [[x0 * scale, y0 * scale, x1 * scale, y1 * scale] for x0, y0, x1, y1 in px]
        if rects:
            return {"kind": kind, "method": method, "page_no": no, "rects": [[round(v, 1) for v in r] for r in rects[:8]],
                    "page_w": round(page.rect.width, 1), "page_h": round(page.rect.height, 1)}
    no = page_no if page_no and page_no <= pdf.page_count else (cand[0] if cand else None)
    if no:
        page = pdf[no - 1]
        return {"kind": kind, "method": "page", "page_no": no, "rects": [], "page_w": round(page.rect.width, 1),
                "page_h": round(page.rect.height, 1)}
    return {"kind": kind, "method": "none", "page_no": None, "rects": [], "pages": pdf.page_count}


def page_png(data: bytes, filename: str, page_no: int, dpi: int = RENDER_DPI) -> tuple[bytes, float, float] | None:
    """按页渲染（原文对照查看器用）：返回 (PNG, 页宽 pt, 页高 pt)；页码越界返回 None。"""
    kind = formats.detect(data, filename)
    if kind not in ("pdf", "image"):
        return None
    pdf = _open(data, kind)
    if page_no < 1 or page_no > pdf.page_count:
        return None
    page = pdf[page_no - 1]
    return page.get_pixmap(dpi=dpi).tobytes("png"), page.rect.width, page.rect.height


def _img_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8"):
        return "jpeg"
    if data[:2] == b"BM":
        return "bmp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return "png"
