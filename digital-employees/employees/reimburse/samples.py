"""财务报销初审本地样例（合成数据）：
  DEMO-BX-001 差旅含业务招待（问题样例）
  DEMO-BX-002 办公费（规范样例）
  DEMO-BX-003 会议费（费用人不在参会名单）
"""
from __future__ import annotations

from functools import partial
from pathlib import Path

from core.sources import samplegen as g


def _travel(root: Path) -> Path:
    claim = {
        "doc_type": "差旅报销单", "code": "DEMO-BX-001", "amount": 4239.5, "applicant": "李明", "dept": "运营管理部",
        "identity": "其他员工", "grade": "专业通道8级", "submit_date": "2026-09-10",
        "reason": "赴北京开展项目对接，期间招待北京某咨询公司及中国石油天然气集团有限公司来访人员",
        "expenses": [{"type": "差旅费", "item": "城市间交通费", "amount": 1192.5},
                     {"type": "业务招待费", "item": "招待费", "amount": 2400},
                     {"type": "差旅费", "item": "住宿费", "amount": 647}],
        "travel": {"start": "2026-09-01", "end": "2026-09-03", "days": 3, "subsidy_days": 3, "subsidy_amount": 300,
                   "reason": "赴北京项目对接"},
        "entertain": {"type": "商务招待", "units": ["中国石油天然气集团有限公司", "北京某咨询公司"], "guests": 4,
                      "accompany": 5, "date": "2026-09-02", "total": 2400, "gift": False},
        "invoices": [
            {"number": "26372000000012345678", "kind": "数电票铁路电子客票", "date": "2026-09-05", "amount": 553,
             "items": ["铁路电子客票"], "travel_date": "2026-09-05", "remark": "济南西-北京南"},
            {"number": "26372000000012345679", "kind": "数电票铁路电子客票", "date": "2026-09-01", "amount": 553,
             "items": ["铁路电子客票"], "travel_date": "2026-09-01", "remark": "北京南-济南西"},
            {"number": "26110000000066660001", "kind": "数电发票普通发票", "date": "2026-09-02", "amount": 86.5,
             "items": ["*运输服务*客运服务费"], "remark": "出行人：李明；出行日期：2026年9月2日", "seller": "滴滴出行科技有限公司"},
            {"number": "25110000000088880001", "kind": "数电发票普通发票", "date": "2025-12-28", "amount": 2400,
             "items": ["*餐饮服务*餐费"], "seller": "北京某餐饮有限公司"},
            {"number": "26110000000077770001", "kind": "数电发票普通发票", "date": "2026-09-03", "amount": 647,
             "items": ["*住宿服务*住宿费"], "remark": "入住2026年9月1日，离店2026年9月3日"},
        ],
    }
    return g.case(root, "reimburse", "DEMO-BX-001", {
        "workflow_name": "差旅报销单（本地样例）", "request_name": "李明-差旅报销单-北京项目对接（问题样例）",
        "node_name": "会计审核岗", "title": "差旅报销单（含业务招待）", "tags": ["问题样例", "差旅费", "业务招待费"],
        "summary": "合成数据：行程单日期、乘车日期、连号、陪餐超标、人均超标、央企商务宴请、上年度发票等",
        "fields": {"单据编码": "DEMO-BX-001", "单据类型": "差旅报销单", "报销金额": "4239.50"},
        "attachments": [{"file": "files/出差行程单.docx", "field_label": "附件"},
                        {"file": "files/滴滴出行行程单.pdf", "field_label": "附件"},
                        {"file": "files/业务招待清单.docx", "field_label": "附件"}],
        "extra": {"claim": claim},
    }, {
        "files/出差行程单.docx": partial(g.docx, paragraphs=["出差行程单", "出差人：李明", "出差地点：北京",
                                                          "出差日期：2026年9月1日 至 2026年9月4日"]),
        "files/滴滴出行行程单.pdf": partial(g.pdf, pages=[["滴滴出行-行程单", "行程人：李明", "2026年9月2日 国贸 → 北京南站",
                                                         "合计金额：86.50 元"]]),
        "files/业务招待清单.docx": partial(g.docx, paragraphs=["业务招待清单（代预算审批单）", "招待类别：商务招待",
                                                          "实际参加人数：5人", "陪同人数：5人", "实际费用总额：2400.00元",
                                                          "经办人：李明", "审批人：王强"]),
    })


def _office(root: Path) -> Path:
    claim = {
        "doc_type": "办公费报销单", "code": "DEMO-BX-002", "amount": 1256.0, "applicant": "赵敏", "dept": "运营管理部",
        "identity": "其他员工", "grade": "专业通道6级", "submit_date": "2026-10-15",
        "reason": "运营管理部采购打印纸、硒鼓等办公用品",
        "expenses": [{"type": "办公费", "item": "办公用品", "amount": 1256.0}],
        "flags": {"consecutive": "否", "prepaid": "否"},
        "invoices": [{"number": "26370000000011110001", "kind": "数电发票普通发票", "date": "2026-10-12", "amount": 1256.0,
                      "items": ["*纸制品*复印纸 A4 70g", "*计算机配套产品*硒鼓 HP 88A"], "detail_total": 1256.0,
                      "seller": "济南某办公用品有限公司"}],
    }
    return g.case(root, "reimburse", "DEMO-BX-002", {
        "workflow_name": "办公费报销单（本地样例）", "request_name": "赵敏-办公费报销单-打印耗材（规范样例）",
        "node_name": "会计审核岗", "title": "办公费报销单", "tags": ["规范样例", "办公费"],
        "summary": "合成数据：发票列明商品、清单与票面一致、无连号与储值",
        "fields": {"单据编码": "DEMO-BX-002", "单据类型": "办公费报销单", "报销金额": "1256.00"},
        "attachments": [{"file": "files/办公用品采购清单.docx", "field_label": "附件"}],
        "extra": {"claim": claim},
    }, {
        "files/办公用品采购清单.docx": partial(g.docx, paragraphs=["办公用品采购清单"], tables=[[
            ["商品名称", "型号", "数量", "单价", "金额"], ["复印纸", "A4 70g", "20", "28.00", "560.00"],
            ["硒鼓", "HP 88A", "4", "174.00", "696.00"], ["合计", "", "", "", "1256.00元"]]]),
    })


def _meeting(root: Path) -> Path:
    claim = {
        "doc_type": "会议费报销单", "code": "DEMO-BX-003", "amount": 3600.0, "applicant": "孙丽", "dept": "综合管理部",
        "reason": "2026年第四季度安全生产工作会议会议费",
        "expenses": [{"type": "会议费", "item": "会议费", "amount": 1800, "person": "张三"},
                     {"type": "会议费", "item": "会议费", "amount": 1800, "person": "王五"}],
        "invoices": [{"number": "26370000000022220001", "kind": "数电发票普通发票", "date": "2026-10-20", "amount": 3600,
                      "items": ["*会议服务*会议费"]}],
    }
    return g.case(root, "reimburse", "DEMO-BX-003", {
        "workflow_name": "会议费报销单（本地样例）", "request_name": "孙丽-会议费报销单-四季度安全生产会",
        "node_name": "财务待办", "title": "会议费报销单", "tags": ["问题样例", "会议费"],
        "summary": "合成数据：费用人王五不在公文流转单参会人员名单中",
        "fields": {"单据编码": "DEMO-BX-003", "单据类型": "会议费报销单", "报销金额": "3600.00"},
        "attachments": [{"file": "files/会议通知.pdf", "field_label": "附件"},
                        {"file": "files/公文流转单.docx", "field_label": "附件"}],
        "extra": {"claim": claim},
    }, {
        "files/会议通知.pdf": partial(g.pdf, pages=[["关于召开2026年第四季度安全生产工作会议的通知", "各部门：",
                                                   "定于2026年10月20日召开第四季度安全生产工作会议。", "综合管理部"]]),
        "files/公文流转单.docx": partial(g.docx, paragraphs=["通用设计公文流转单", "事由：组织召开第四季度安全生产工作会议",
                                                          "参会人员：张三、李四、赵六", "拟稿人：孙丽"]),
    })


def write(root: Path) -> list[Path]:
    return [_travel(root), _office(root), _meeting(root)]
