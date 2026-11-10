"""合同审核数字员工的对话提示词（受限对话：只做任务入口与报告追问）。"""
from __future__ import annotations

from core import chat

from . import rules as rules_mod

INPUT_HINT = "发送主合同审批流程的单号（纯数字，如 1609472），或在「样例单据」里选择本地样例"


def system_prompt(emp: dict, report: dict | None, question: str = "") -> str:
    return chat.system_prompt(
        emp, report,
        scope="读取合同管理系统中「主合同审批」流程的表单、合同正文、中标通知书、投标文件等附件，",
        input_hint=f"用户想审核合同时，请他{INPUT_HINT}；",
        rules=rules_mod.catalog(), question=question, rules_title="合同审核 30 条规则（按实现方式分为确定性、语义、外部数据三类）")
