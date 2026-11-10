"""财务报销初审数字员工的对话提示词（受限对话：只做任务入口与报告追问）。"""
from __future__ import annotations

from core import chat

from . import rules as rules_mod

INPUT_HINT = ("发送通财云单据编码（如 1000001431-CLBX2609-000579），或在「样例单据」里选择本地样例"
              "（通财云需连接 VPN 后打通取数，当前可审查本地事项）")


def system_prompt(emp: dict, report: dict | None, question: str = "") -> str:
    return chat.system_prompt(
        emp, report,
        scope="读取通财云中报销单的表单、费用明细、发票与附件，按单据类别（差旅、招待、办公、车辆、交通、会议、培训、通用、资产）"
              "执行对应规则，",
        input_hint=f"用户想初审报销单时，请他{INPUT_HINT}；",
        rules=rules_mod.catalog(), question=question, rules_title="报销初审 43 条规则（按单据类别执行，类别为材料/数据/标准/风险）")
