"""原文对照定位：文字层 PDF 精确到句、跨页找到正确页、Word 正文到段落、定位不到只给页且不伪造坐标。"""
import pymupdf

from core.resource import shots


def _pdf(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for t in pages:
        p = doc.new_page()
        p.insert_font(fontname="cjk", fontbuffer=pymupdf.Font("china-s").buffer)
        p.insert_text((72, 120), t, fontname="cjk", fontsize=12)
    return doc.tobytes()


def test_pdf_text_layer_finds_page_and_rect():
    data = _pdf(["第一页：合同总价款人民币贰拾壹万元。", "第二页：每逾期一日，向甲方支付该阶段价款的0.1‰作为违约金。"])
    doc = {"pages": [{"no": 1, "text": "第一页：合同总价款人民币贰拾壹万元。", "method": "text"},
                     {"no": 2, "text": "第二页：每逾期一日，向甲方支付该阶段价款的0.1‰作为违约金。", "method": "text"}]}
    r = shots.locate(data, "合同.pdf", doc, "向甲方支付该阶段价款的0.1‰")
    assert r["method"] == "text" and r["page_no"] == 2 and r["rects"]
    x0, y0, x1, y1 = r["rects"][0]
    assert 0 < x0 < x1 <= r["page_w"] and 0 < y0 < y1 <= r["page_h"]
    png, w, h = shots.page_png(data, "合同.pdf", 2)
    assert png[:4] == b"\x89PNG" and (w, h) == (r["page_w"], r["page_h"])
    assert shots.page_png(data, "合同.pdf", 9) is None


def test_not_found_gives_page_only_without_fake_rects():
    data = _pdf(["只有这一页的内容。"])
    doc = {"pages": [{"no": 1, "text": "只有这一页的内容。", "method": "text"}]}
    r = shots.locate(data, "a.pdf", doc, "完全不存在的一段引用文字内容", page_no=1)
    assert r["method"] == "page" and r["page_no"] == 1 and r["rects"] == []
    assert shots.locate(data, "a.pdf", doc, "完全不存在的一段引用文字内容")["method"] == "none"


def test_docx_text_paragraph():
    doc = {"pages": [{"no": 1, "text": "一、项目概况\n（五）勘测工期、进度管控与计划管理\n整体服务工期 120 天"}]}
    data = b"PK\x03\x04" + b"\x00" * 50  # 非 PDF / 图片：按解析文本定位段落
    r = shots.locate(data, "投标文件.docx", doc, "勘测工期、进度管控与计划管理")
    assert r["method"] == "para" and r["page_no"] == 1 and r["para"] == 1
