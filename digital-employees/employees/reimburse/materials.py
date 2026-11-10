"""报销附件类型识别（文件名 + 内容开头）、发票文字识别兜底、签字与盖章的可判定性。

签字、盖章只在能判定时给结论：文字版材料按「签字栏是否留空」判断；扫描件/图片的签字一律转人工核对；
盖章按页面红色印章像素比例初判，Word 文档无法判断盖章。
"""
from __future__ import annotations

import re

from core.materials import Material
from core.rules import common as C

from .model import Invoice

ROLE_LABELS = {
    "invoice": "发票", "itinerary": "出差行程单", "entertain_list": "业务招待清单", "official_letter": "公务公函",
    "gift_detail": "纪念品购物明细", "purchase_list": "采购/办公费清单", "repair_list": "车辆维修清单",
    "repair_order": "维修/保养送修单", "rental_approval": "租车审批表/内请报告", "rental_contract": "租车合同/协议",
    "ride_detail": "第三方出行明细", "meeting_notice": "会议通知", "doc_flow": "公文流转单", "internal_request": "内请报告",
    "courier_split": "快递费结算分摊表", "waybill": "运单明细", "house_lease": "租房协议", "car_application": "租车申请",
    "asset_inbound": "资产入库单", "asset_request": "固定资产购买申请单", "purchase_contract": "采购合同",
    "meeting_material": "上会资料", "meeting_resolution": "上会决议", "other": "其他",
}

_RULES = [
    ("courier_split", r"快递费?结算分摊|分摊表"),
    ("waybill", r"运单|快递明细|邮寄明细"),
    ("ride_detail", r"行程单.*(滴滴|首汽|曹操|T3|高德|美团|神州)|(滴滴|首汽|曹操|T3|高德|美团|神州).*(行程|明细)|出行明细|用车明细"),
    ("itinerary", r"出差行程|行程单|行程确认"),
    ("entertain_list", r"招待清单|代预算审批|业务招待审批"),
    ("official_letter", r"公函"),
    ("gift_detail", r"纪念品|购物明细"),
    ("repair_order", r"送修单|保养单|维修申请"),
    ("repair_list", r"维修清单|维修明细|修理清单|结算清单"),
    ("rental_contract", r"租车(合同|协议)|车辆租赁(合同|协议)"),
    ("rental_approval", r"租车审批|租赁审批|临时租赁"),
    ("car_application", r"租车申请"),
    ("house_lease", r"租房协议|房屋租赁(合同|协议)"),
    ("meeting_notice", r"会议(的)?通知"),
    ("doc_flow", r"公文流转"),
    ("meeting_resolution", r"上会决议|会议决议|会议纪要"),
    ("meeting_material", r"上会资料|上会材料"),
    ("internal_request", r"内请|请示"),
    ("asset_inbound", r"入库单"),
    ("asset_request", r"购买申请|购置申请"),
    ("purchase_contract", r"采购合同|购销合同|买卖合同"),
    ("purchase_list", r"清单|明细|销货"),
    ("invoice", r"发票|电子客票|票据"),
]


def classify(filename: str, field_label: str = "") -> str:
    name = filename.rsplit("/", 1)[-1]
    for role, pat in _RULES:
        if re.search(pat, name):
            return role
    if re.search(r"发票", field_label or ""):
        return "invoice"
    return "other"


def refine(m: Material) -> None:
    """文件名不足以判断时，按内容开头再识别一次（只改 other）。"""
    if m.role != "other" or not m.readable:
        return
    head = m.text[:300]
    if re.search(r"发票号码|开票日期|价税合计", head):
        m.role = "invoice"
        return
    for role, pat in _RULES:
        if role != "invoice" and re.search(pat, head):
            m.role = role
            return


def find(mats: list[Material], *roles: str) -> list[Material]:
    return [m for m in mats if m.role in roles and not m.is_archive]


def invoice_from_text(m: Material) -> Invoice | None:
    """数电发票 PDF 为文字版时识别号码、日期、金额、商品名称、备注（单据未提供发票结构化数据时兜底）。"""
    t = m.text
    no = re.search(r"发票号码[:：]?\s*(\d{8,20})", t)
    if not no:
        return None
    d = C.date_after(t, r"开票日期", 20)
    total = re.search(r"价税合计[^\d¥￥]{0,20}[¥￥]?\s*([\d,]+\.\d{2})", t) or re.search(r"[（(]小写[)）]\s*[¥￥]?\s*([\d,]+\.\d{2})", t)
    kind = "数电票铁路电子客票" if "铁路电子客票" in t else "数电发票普通发票" if re.search(r"电子发票[（(]普通发票[)）]|普通发票", t) \
        else "增值税专用发票" if "专用发票" in t else "定额发票" if "定额" in t else ""
    items = re.findall(r"\*[\u4e00-\u9fa5A-Za-z]+\*[^\s\d]{1,30}", t)
    remark = re.search(r"备\s*注[:：]?\s*([^\n]{0,120})", t)
    return Invoice(number=no.group(1), kind=kind, date=d[0] if d else None,
                   amount=C.to_number(total.group(1)) if total else None, items=items,
                   remark=remark.group(1).strip() if remark else "", file=m.name, source="text")


SIGN_LABELS = r"(经办人|部门负责人|负责人|审核人|审批人|验收人|保管人|使用人|领用人|签字|签名)"


def signature_state(m: Material) -> tuple[str, list[str]]:
    """('ok'|'missing'|'unknown', 缺签栏位)。扫描件/图片的手写签字无法可靠识别 → unknown。"""
    pages = m.doc.get("pages") or []
    if any(p.get("method") == "ocr" for p in pages) or m.doc.get("kind") == "image":
        return "unknown", []
    empty = []
    for mm in re.finditer(SIGN_LABELS + r"\s*[:：]\s*([^\n]{0,8})", m.text):
        val = re.sub(r"[\s_＿（）()年月日\d/.-]", "", mm.group(2))
        if not re.match(r"[\u4e00-\u9fa5]{2,4}", val):
            empty.append(mm.group(1))
    if not re.search(SIGN_LABELS, m.text):
        return "unknown", []
    return ("missing", empty) if empty else ("ok", [])


def red_seal_ratio(data: bytes, kind: str) -> float | None:
    """首页红色像素占比（印章初判）；无法渲染的格式返回 None。"""
    try:
        import pymupdf

        if kind == "pdf":
            doc = pymupdf.open(stream=data, filetype="pdf")
            pix = doc[0].get_pixmap(dpi=40)
        elif kind == "image":
            pix = pymupdf.Pixmap(data)
            if pix.alpha or pix.n > 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        else:
            return None
    except Exception:  # noqa: BLE001
        return None
    s, n, red = pix.samples, pix.n, 0
    total = pix.width * pix.height
    for i in range(0, len(s) - n + 1, n):
        r, g, b = s[i], s[i + 1], s[i + 2]
        if r > 150 and g < 100 and b < 100 and r - g > 80:
            red += 1
    return red / total if total else None
