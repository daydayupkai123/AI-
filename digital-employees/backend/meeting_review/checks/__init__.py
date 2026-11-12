"""三会审查 5 个审查节点（需求：需求场景/三会智能审查数字员工.docx 第七章 7.1）。

每个节点输出一条综合意见；同一节点内的多个问题按（1）（2）（3）列在 items 中，节点序号固定为 01–05。
  title.py         01 标题与附件关联性
  meeting_type.py  02 会议类型
  basis.py         03 审批/上会依据（含条款定位 resolve，供 02 共用）
  body.py          04 请示正文
  attachments.py   05 附件材料
"""
from __future__ import annotations

from shared.rule_framework.engine import Rule

from . import attachments, basis, body, meeting_type, title

VERSION = "meeting-2026.11.10-r3"
EMPLOYEE = "meeting"

RULES = [
    Rule("N01", "标题与附件关联性", "审查节点", title.check, llm=True),
    Rule("N02", "会议类型", "审查节点", meeting_type.check),
    Rule("N03", "审批/上会依据", "审查节点", basis.check, llm=True),
    Rule("N04", "请示正文", "审查节点", body.check, llm=True),
    Rule("N05", "附件材料", "审查节点", attachments.check),
]


def catalog() -> list[dict]:
    return [{"rule_id": r.id, "name": r.name, "category": r.category, "llm": r.llm} for r in RULES]
