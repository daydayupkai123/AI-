"""三会审查本地样例（合成数据）：DEMO-SH-001 问题样例、DEMO-SH-002 规范样例。"""
from __future__ import annotations

from functools import partial
from pathlib import Path

from shared.source_adapters import samplegen as g

BASIS = "公司《权责手册（2026年修订版）》运营管理部第46项“公司非业务合同采购事项（≥30万元）”，由总经理办公会审批"


def _problem(root: Path) -> Path:
    name = "智能体开发平台及数字员工建设项目"
    body = [f"关于公司{name}采购结果的请示", "公司领导：",
            f"为推进数字化转型，运营管理部组织开展{name}采购，项目预算32.00万元。",
            "2026年10月10日在集团中心采购平台发布采购公告，共有3家供应商响应。",
            "2026年10月24日组织召开评审会，评审小组由3名专家组成，推荐济南瑞智信息科技有限公司为第一成交候选人。",
            "成交金额为28.60万元，成交供应商为济南瑞智信息科技有限公司。",
            "项目实施周期XX个月。",
            "依据公司《权责手册（2026年修订版）》运营管理部第46项，现提请总经理办公会审议。",
            "妥否，请批示。", "运营管理部", "2026年10月28日"]
    notice = [[f"{name}采购公告", "发布日期：2026年10月12日", "采购预算：32.00万元",
               "采购方式：询比采购", "采购人：通用技术集团工程设计有限公司"]]
    review = [f"{name}评审报告", "评审时间：2026年10月24日", "评审小组由5名专家组成。",
              "推荐第一成交候选人：济南瑞智信息科技有限公司，报价28.60万元。", "成交金额：28.60万元"]
    result = [["成交通知书", "济南瑞智信息科技有限公司：", f"你公司参与的{name}已确定为成交。",
               "成交金额：28.60万元", "通用技术集团工程设计有限公司", "2026年10月27日"]]
    other = ["济南高新区某园区安防改造项目报价单", "报价总额：15.20万元", "报价单位：山东安盾科技有限公司"]
    return g.case(root, "meeting", "DEMO-SH-001", {
        "workflow_name": "内部请示（本地样例）", "request_name": f"关于公司{name}采购结果的请示（问题样例）",
        "node_name": "三会审核岗", "title": f"{name}采购结果请示", "tags": ["问题样例", "采购结果", "总经理办公会"],
        "summary": "合成数据：金额落入签批档位却报总经理办公会、公告日期与评审人数与附件不一致、混入其他项目材料",
        "fields": {"标题": f"关于公司{name}采购结果的请示", "事项类型": "采购结果", "会议类型": "总经理办公会",
                   "审批/上会依据": BASIS, "发起部门": "运营管理部"},
        "attachments": [{"file": "files/请示正文.docx", "field_label": "正文"},
                        {"file": "files/采购公告.pdf", "field_label": "附件"},
                        {"file": "files/评审报告.docx", "field_label": "附件"},
                        {"file": "files/成交通知书.pdf", "field_label": "附件"},
                        {"file": "files/园区安防改造项目报价单.docx", "field_label": "附件"}],
    }, {
        "files/请示正文.docx": partial(g.docx, paragraphs=body),
        "files/采购公告.pdf": partial(g.pdf, pages=notice),
        "files/评审报告.docx": partial(g.docx, paragraphs=review),
        "files/成交通知书.pdf": partial(g.pdf, pages=result),
        "files/园区安防改造项目报价单.docx": partial(g.docx, paragraphs=other),
    })


def _clean(root: Path) -> Path:
    name = "协同办公平台升级改造项目"
    body = [f"关于公司{name}采购结果的请示", "公司领导：",
            f"为提升协同办公效率，综合管理部采用询比采购方式组织开展{name}采购，项目预算48.00万元。",
            "2026年9月5日在集团中心采购平台发布采购公告，共有4家供应商响应。",
            "2026年9月19日组织召开评审会，评审小组由5名专家组成，推荐山东华信软件有限公司为第一成交候选人。",
            "成交金额为45.80万元，成交供应商为山东华信软件有限公司，实施周期6个月。",
            "依据公司《权责手册（2026年修订版）》运营管理部第46项，现提请总经理办公会审议。",
            "妥否，请批示。", "综合管理部", "2026年9月24日"]
    notice = [[f"{name}采购公告", "发布日期：2026年9月5日", "采购预算：48.00万元", "采购方式：询比采购"]]
    review = [f"{name}评审报告", "评审时间：2026年9月19日", "评审小组由5名专家组成。",
              "推荐第一成交候选人：山东华信软件有限公司，报价45.80万元。", "成交金额：45.80万元"]
    result = [["成交通知书", "山东华信软件有限公司：", f"你公司参与的{name}已确定为成交。", "成交金额：45.80万元"]]
    return g.case(root, "meeting", "DEMO-SH-002", {
        "workflow_name": "内部请示（本地样例）", "request_name": f"关于公司{name}采购结果的请示（规范样例）",
        "node_name": "三会审核岗", "title": f"{name}采购结果请示", "tags": ["规范样例", "采购结果"],
        "summary": "合成数据：依据、金额档位、会议类型与附件事实相互一致",
        "fields": {"标题": f"关于公司{name}采购结果的请示", "事项类型": "采购结果", "会议类型": "总经理办公会",
                   "审批/上会依据": BASIS, "发起部门": "综合管理部"},
        "attachments": [{"file": "files/请示正文.docx", "field_label": "正文"},
                        {"file": "files/采购公告.pdf", "field_label": "附件"},
                        {"file": "files/评审报告.docx", "field_label": "附件"},
                        {"file": "files/成交通知书.pdf", "field_label": "附件"}],
    }, {
        "files/请示正文.docx": partial(g.docx, paragraphs=body),
        "files/采购公告.pdf": partial(g.pdf, pages=notice),
        "files/评审报告.docx": partial(g.docx, paragraphs=review),
        "files/成交通知书.pdf": partial(g.pdf, pages=result),
    })


def write(root: Path) -> list[Path]:
    return [_problem(root), _clean(root)]
