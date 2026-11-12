"""按真实文件头识别格式并提取文本、文档属性；扫描页交给 OCR。"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from ..env_config import PDF_TEXT_MIN_CHARS
from . import ocr

ARCHIVE_MAX_FILES = 500
ARCHIVE_MAX_BYTES = 500 * 1024 * 1024


def detect(data: bytes, filename: str = "") -> str:
    head = data[:8]
    ext = Path(filename).suffix.lower().lstrip(".")
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return "unknown"
        if "word/document.xml" in names:
            return "docx"
        if "xl/workbook.xml" in names:
            return "xlsx"
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return {"xls": "xls", "ppt": "ppt"}.get(ext, "doc")
    if head.startswith(b"Rar!"):
        return "rar"
    if head.startswith(b"7z\xbc\xaf"):
        return "7z"
    if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8") or head[:2] == b"BM" \
            or head[:4] in (b"II*\x00", b"MM\x00*") or head[:3] == b"GIF":
        return "image"
    return "unknown"


def _page(no: int, method: str, text: str, conf: float | None = None, lines=None) -> dict:
    p = {"no": no, "method": method, "text": text or ""}
    if conf is not None:
        p["conf"] = conf
    if lines is not None:
        p["lines"] = lines
    return p


def _ocr_page(no: int, res: dict) -> dict:
    if res.get("failed"):
        return _page(no, "ocr-failed", "", None, None) | {"error": res.get("error")}
    p = _page(no, "ocr", res["text"], res.get("conf"), res.get("lines"))
    if res.get("blocks"):
        p["blocks"] = res["blocks"]
    if res.get("size"):
        p["ocr_size"] = res["size"]
    return p


def pdf_ocr_pages(data: bytes) -> tuple[int, int]:
    """（总页数, 需要 OCR 的页数）：只读文字层，不渲染。"""
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    need = sum(1 for page in doc if len(page.get_text().strip()) < PDF_TEXT_MIN_CHARS)
    return doc.page_count, need


def parse_pdf(data: bytes, on_page=None) -> tuple[dict, list[dict], list[str]]:
    import pymupdf

    eng = ocr.engine()
    doc = pymupdf.open(stream=data, filetype="pdf")
    meta = {k: v for k, v in (doc.metadata or {}).items() if v}
    meta["page_count"] = doc.page_count
    whole_pdf = bool(getattr(eng, "send_pdf", False))
    pages, need_ocr, pngs = [], [], []
    for i, page in enumerate(doc):
        text = page.get_text().strip()
        if len(text) >= PDF_TEXT_MIN_CHARS:
            pages.append(_page(i + 1, "text", text))
        else:
            pages.append(None)
            need_ocr.append(i)
            if not whole_pdf:
                pngs.append(page.get_pixmap(dpi=eng.dpi).tobytes("png"))
    results = eng.ocr_pdf_pages(data, need_ocr, on_page) if whole_pdf and need_ocr else eng.ocr_images(pngs, on_page)
    for idx, res in zip(need_ocr, results):
        pages[idx] = _ocr_page(idx + 1, res)
    return meta, pages, []


def parse_docx(data: bytes, on_page=None) -> tuple[dict, list[dict], list[str]]:
    import docx

    d = docx.Document(io.BytesIO(data))
    cp = d.core_properties
    meta = {"author": cp.author, "last_modified_by": cp.last_modified_by,
            "created": cp.created.isoformat() if cp.created else None,
            "modified": cp.modified.isoformat() if cp.modified else None, "title": cp.title}
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for t in d.tables:
        for row in t.rows:
            cells, seen = [], set()
            for c in row.cells:
                txt = c.text.strip().replace("\n", " ")
                if txt and id(c._tc) not in seen:
                    seen.add(id(c._tc))
                    cells.append(txt)
            if cells:
                parts.append(" | ".join(cells))
    return meta, [_page(1, "text", "\n".join(parts))], []


def parse_xlsx(data: bytes, on_page=None) -> tuple[dict, list[dict], list[str]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    p = wb.properties
    meta = {"author": p.creator, "last_modified_by": p.lastModifiedBy,
            "created": p.created.isoformat() if p.created else None}
    pages = []
    for i, ws in enumerate(wb.worksheets):
        rows = [" | ".join(str(v) for v in row if v not in (None, "")) for row in ws.iter_rows(values_only=True)]
        pages.append(_page(i + 1, "text", f"[{ws.title}]\n" + "\n".join(r for r in rows if r)))
    return meta, pages, []


def _doc_pieces(ole) -> str:
    """Word 97–2003（.doc，含 WPS 另存）正文：按 FIB → Clx → 分段表（piece table）读取文档正文，
    不含文档属性、已删除的快速保存残留与嵌入对象。格式见 [MS-DOC] 2.5 / 2.9.38。"""
    import struct

    wd = ole.openstream("WordDocument").read()
    if struct.unpack_from("<H", wd, 0)[0] != 0xA5EC:
        raise ValueError("不是 Word 二进制文档")
    table = ole.openstream("1Table" if struct.unpack_from("<H", wd, 0x0A)[0] & 0x0200 else "0Table").read()
    csw = struct.unpack_from("<H", wd, 32)[0]
    pos = 34 + csw * 2
    cslw = struct.unpack_from("<H", wd, pos)[0]
    pos += 2 + cslw * 4 + 2                       # fibRgLw 之后是 cbRgFcLcb，再之后是 fibRgFcLcb
    fc_clx, lcb_clx = struct.unpack_from("<II", wd, pos + 33 * 8)  # fcClx 为 FibRgFcLcb97 第 34 对
    clx, i = table[fc_clx:fc_clx + lcb_clx], 0
    while i < len(clx) and clx[i] == 0x01:        # 跳过 Prc
        i += 3 + struct.unpack_from("<h", clx, i + 1)[0]
    if i >= len(clx) or clx[i] != 0x02:
        raise ValueError("分段表缺失")
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + lcb]
    n = (lcb - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
    out = []
    for k in range(n):
        fc = struct.unpack_from("<I", plc, (n + 1) * 4 + k * 8 + 2)[0]
        cnt = cps[k + 1] - cps[k]
        if fc & 0x40000000:
            start = (fc & 0x3FFFFFFF) // 2
            out.append(wd[start:start + cnt].decode("cp1252", "ignore"))
        else:
            out.append(wd[fc:fc + cnt * 2].decode("utf-16le", "ignore"))
    text = "".join(out)
    text = re.sub(r"\x13[^\x13\x14\x15]*\x14([^\x15]*)\x15", r"\1", text)  # 域：保留显示结果
    text = re.sub(r"\x13[^\x15]*\x15", "", text)
    # 表格：单元格以 \x07 结束，行末再跟一个行结束标记 \x07
    text = text.replace("\x07\x07", "\n").replace("\x07", "\t").translate({0x0d: "\n", 0x0b: "\n", 0x0c: "\n"})
    text = re.sub(r"[\x00-\x08\x0e-\x1f]", "", text)
    return "\n".join(ln.rstrip() for ln in text.split("\n")).strip()


def parse_ole(data: bytes, on_page=None) -> tuple[dict, list[dict], list[str]]:
    import olefile

    meta, warnings = {}, []
    ole = None
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
        m = ole.get_metadata()
        dec = lambda b: (b.decode("gbk", "ignore") if isinstance(b, bytes) else b or "").split("\x00")[0]  # noqa: E731
        meta = {"author": dec(m.author), "last_modified_by": dec(m.last_saved_by),
                "created": m.create_time.isoformat() if m.create_time else None,
                "modified": m.last_saved_time.isoformat() if m.last_saved_time else None, "title": dec(m.title)}
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"文档属性读取失败：{exc}")
    if ole is not None and ole.exists("WordDocument"):
        try:
            text = _doc_pieces(ole)
            if text:
                return meta, [_page(1, "text", text)], warnings
        except Exception as exc:  # noqa: BLE001
            meta["approx_reason"] = f"{type(exc).__name__}: {exc}"[:200]
    meta.setdefault("approx_reason", "非 Word 正文（表格 / 演示文稿）")
    warnings.append("旧版 Office 文件：正文为近似提取，建议人工核对")
    raw = data.decode("utf-16le", "ignore")
    runs = re.findall(r"[\u4e00-\u9fff0-9A-Za-z，。、：；（）()\.,:;%\-/ ]{4,}", raw)
    text = "\n".join(r.strip() for r in runs if re.search(r"[\u4e00-\u9fff]", r))
    return meta, [_page(1, "text-approx", text)], warnings


def parse_image(data: bytes, on_page=None) -> tuple[dict, list[dict], list[str]]:
    res = ocr.engine().ocr_images([data], on_page)[0]
    return {}, [_ocr_page(1, res)], []


def _fix_name(name: str) -> str:
    for enc in ("cp437", "latin-1"):
        try:
            return name.encode(enc).decode("gbk")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return name


def extract_archive(data: bytes, kind: str) -> list[tuple[str, bytes]]:
    """返回 [(相对路径, 字节)]；zip 用标准库，rar/7z 用 bsdtar。限制文件数与总大小。"""
    out: list[tuple[str, bytes]] = []
    total = 0
    if kind == "zip":
        zf = zipfile.ZipFile(io.BytesIO(data))
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename if info.flag_bits & 0x800 else _fix_name(info.filename)
            total += info.file_size
            if len(out) >= ARCHIVE_MAX_FILES or total > ARCHIVE_MAX_BYTES:
                break
            out.append((name, zf.read(info)))
        return out
    tar = shutil.which("bsdtar") or shutil.which("tar")
    if not tar:
        raise RuntimeError("缺少 bsdtar，无法解压 rar/7z")
    with tempfile.TemporaryDirectory(prefix="de_arc_") as tmp:
        src = Path(tmp) / f"a.{kind}"
        src.write_bytes(data)
        dst = Path(tmp) / "x"
        dst.mkdir()
        proc = subprocess.run([tar, "-xf", str(src), "-C", str(dst)], capture_output=True, timeout=300)
        if proc.returncode != 0 and not any(dst.rglob("*")):
            raise RuntimeError(f"解压失败：{proc.stderr.decode('utf-8', 'ignore')[:200]}")
        for dp, _, files in os.walk(dst):
            for f in files:
                p = Path(dp) / f
                total += p.stat().st_size
                if len(out) >= ARCHIVE_MAX_FILES or total > ARCHIVE_MAX_BYTES:
                    return out
                rel = _fix_name(str(p.relative_to(dst))).replace("\\", "/")
                out.append((rel, p.read_bytes()))
    return out


PARSERS = {"pdf": parse_pdf, "docx": parse_docx, "xlsx": parse_xlsx, "doc": parse_ole, "xls": parse_ole,
           "ppt": parse_ole, "image": parse_image}
