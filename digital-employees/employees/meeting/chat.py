"""三会审查数字员工的对话提示词（受限对话：只做任务入口与报告追问）。"""
from __future__ import annotations

from core import chat

from . import checks

INPUT_HINT = "发送内部请示的内请号（如 通设请字[2026]76号），或在「样例单据」里选择本地样例"


def system_prompt(emp: dict, report: dict | None, question: str = "") -> str:
    return chat.system_prompt(
        emp, report,
        scope="读取公文系统中「内部请示」的 OA 表单（标题、会议类型、审批/上会依据）、请示正文与附件，"
              "依据权责手册、重大经营管理事项清单、党委决定的重大事项清单、董事会授权决策方案四份制度，",
        input_hint=f"用户想审查请示时，请他{INPUT_HINT}；",
        rules=checks.catalog(), question=question, rules_title="三会审查 5 个审查节点（每个节点输出一条综合意见，多个问题按（1）（2）（3）列示）")
