"""旧版 Word（.doc）正文按分段表精确提取：用按 [MS-DOC] 手工构造的流字节，不含任何真实文档。"""
import struct

from shared.parsing import formats
from shared.parsing.pipeline import Parser


class FakeOle:
    def __init__(self, streams):
        self.streams = streams

    def exists(self, name):
        return name in self.streams

    def openstream(self, name):
        import io

        return io.BytesIO(self.streams[name])


def _doc(pieces: list[tuple[str, bool]], which_table: int = 0) -> FakeOle:
    wd = bytearray(2048)
    struct.pack_into("<H", wd, 0, 0xA5EC)
    struct.pack_into("<H", wd, 0x0A, 0x0200 if which_table else 0)
    struct.pack_into("<H", wd, 32, 14)                     # csw
    pos = 34 + 14 * 2
    struct.pack_into("<H", wd, pos, 22)                    # cslw
    pos += 2 + 22 * 4
    struct.pack_into("<H", wd, pos, 93)                    # cbRgFcLcb
    fclcb = pos + 2
    at, cps, pcds = 1024, [0], []
    for text, compressed in pieces:
        if compressed:
            raw = text.encode("cp1252")
            wd[at:at + len(raw)] = raw
            pcds.append((at * 2) | 0x40000000)
        else:
            raw = text.encode("utf-16le")
            wd[at:at + len(raw)] = raw
            pcds.append(at)
        at += len(raw) + 16
        cps.append(cps[-1] + len(text))
    plc = struct.pack(f"<{len(cps)}I", *cps) + b"".join(struct.pack("<HIH", 0, fc, 0) for fc in pcds)
    prc = b"\x01" + struct.pack("<h", 2) + b"\x00\x00"
    clx = prc + b"\x02" + struct.pack("<I", len(plc)) + plc
    table = b"\x00" * 64 + clx
    struct.pack_into("<II", wd, fclcb + 33 * 8, 64, len(clx))
    return FakeOle({"WordDocument": bytes(wd), "1Table" if which_table else "0Table": table})


def test_pieces_text_tables_fields_and_compressed():
    ole = _doc([("关于某项目采购结果的请示\r公司领导：\r序号\x07名称\x07\x071\x07甲公司\x07\x07", False),
                ("详见\x13 HYPERLINK \"http://x\" \x14链接\x15。\r", False), ("Total 12.5\r", True)], which_table=1)
    text = formats._doc_pieces(ole)
    assert text.splitlines()[:2] == ["关于某项目采购结果的请示", "公司领导："]
    assert "序号\t名称\n1\t甲公司" in text
    assert "详见链接。" in text and "HYPERLINK" not in text
    assert text.endswith("Total 12.5")


def test_bad_header_falls_back_to_approx(monkeypatch):
    import olefile

    ole = _doc([("正文内容足够长的一段文字", False)])
    ole.streams["WordDocument"] = b"\x00" * 64
    monkeypatch.setattr(olefile, "OleFileIO", lambda f: type("O", (), {
        "get_metadata": lambda s: (_ for _ in ()).throw(ValueError("no meta")),
        "exists": ole.exists, "openstream": ole.openstream})())
    meta, pages, warns = formats.parse_ole("正文内容足够长的一段文字".encode("utf-16le"))
    assert pages[0]["method"] == "text-approx" and meta["approx_reason"].startswith("ValueError")
    assert any("近似提取" in w for w in warns)


def test_old_approx_doc_cache_is_reparsed(monkeypatch):
    p = Parser.__new__(Parser)
    docs = {"old": {"kind": "doc", "meta": {}, "pages": [{"method": "text-approx"}]},
            "fallback": {"kind": "doc", "meta": {"approx_reason": "x"}, "pages": [{"method": "text-approx"}]},
            "new": {"kind": "doc", "meta": {}, "pages": [{"method": "text"}]}}
    monkeypatch.setattr(Parser, "_load", lambda self, sig: docs[sig])
    assert p.cached("old") is None
    assert p.cached("fallback") is docs["fallback"] and p.cached("new") is docs["new"]
