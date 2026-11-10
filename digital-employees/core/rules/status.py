"""统一规则状态：内部只用一套代码，各数字员工按各自需求文档的文案显示。

  issue    发现问题（采购：命中）
  pass     核查通过 / 无异常（采购：未命中）
  missing  待补充：依赖的材料或字段缺失，无法完成核验（采购：未能识别）
  review   人工复核：证据冲突、外部数据不可用或规则存在歧义
  na       不适用：规则适用条件不满足（不计为通过）
  notrun   未执行：规则尚未接入或按业务口径暂缓
  error    审查中止：解析、模型调用或执行失败，未形成有效结论

只有 pass 表示「有足够证据支持未发现异常」；其余状态都不能视为通过。
"""
from __future__ import annotations

ISSUE, PASS, MISSING, REVIEW, NA, NOTRUN, ERROR = "issue", "pass", "missing", "review", "na", "notrun", "error"
CODES = [ISSUE, REVIEW, MISSING, ERROR, PASS, NA, NOTRUN]

_REVIEW_LABELS = {ISSUE: "发现问题", PASS: "核查通过", MISSING: "待补充", REVIEW: "人工复核", NA: "不适用",
                  NOTRUN: "未执行", ERROR: "审查中止"}

LABELS: dict[str, dict[str, str]] = {
    "procurement": {ISSUE: "命中", PASS: "未命中", MISSING: "未能识别", NOTRUN: "未执行"},
    "contract": dict(_REVIEW_LABELS),
    "meeting": dict(_REVIEW_LABELS),
    "reimburse": {**_REVIEW_LABELS, ISSUE: "存在风险", PASS: "通过"},
}


def label(employee: str, code: str) -> str:
    return LABELS.get(employee, _REVIEW_LABELS).get(code) or _REVIEW_LABELS[code]


def code_of(employee: str, text: str) -> str | None:
    for code, name in LABELS.get(employee, _REVIEW_LABELS).items():
        if name == text:
            return code
    return None


def is_attention(code: str) -> bool:
    """需要审核人看的状态：问题、复核、待补充、中止。"""
    return code in (ISSUE, REVIEW, MISSING, ERROR)
