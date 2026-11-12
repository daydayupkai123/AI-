"""生成本地样例用的文档（docx / 文字版 pdf / 图片），只用于合成数据，不含任何真实单据内容。"""
from __future__ import annotations

import json
from pathlib import Path


def docx(path: Path, paragraphs: list[str], tables: list[list[list[str]]] | None = None,
         author: str = "样例") -> None:
    import docx as _docx

    d = _docx.Document()
    d.core_properties.author = author
    for p in paragraphs:
        d.add_paragraph(p)
    for t in tables or []:
        tb = d.add_table(rows=len(t), cols=len(t[0]))
        for i, row in enumerate(t):
            for j, cell in enumerate(row):
                tb.cell(i, j).text = cell
    path.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(path))


def pdf(path: Path, pages: list[list[str]]) -> None:
    import pymupdf

    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page(width=595, height=842)
        y = 60
        for ln in lines:
            page.insert_text((50, y), ln, fontname="china-s", fontsize=11)
            y += 20
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def case(root: Path, employee: str, case_id: str, body: dict, files: dict[str, callable]) -> Path:
    """files：{相对路径: 生成函数(path)}；case.json 的 attachments 引用这些文件。"""
    d = root / employee / case_id
    d.mkdir(parents=True, exist_ok=True)
    for rel, make in files.items():
        make(d / rel)
    (d / "case.json").write_text(json.dumps({"request_id": case_id, **body}, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    return d
