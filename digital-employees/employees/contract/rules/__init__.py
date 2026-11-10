"""合同审核 30 条规则（需求：需求场景/合同审核数字员工.docx 第 5 章）。

分三个文件按实现方式组织：
  clauses.py   合同正文条款核验（确定性为主；R18、R26 关键词定位后由模型确认）
  compare.py   多份材料比对（合同 vs 中标通知书 / 投标文件 / 招标文件 / 联合体协议 / 技术协议 / 审批表单）
  external.py  依赖外部数据或台账（天眼查、不合格供应商名单、主合同台账、人员数据、标准清单）

facts 由 extract.extract() 生成，并由流程图补充 _judge（模型判定器）、external、ledgers、lists。
"""
from __future__ import annotations

from core.rules.engine import Rule

from . import clauses as cl
from . import compare as cp
from . import external as ex

VERSION = "contract-2026.11.09-r1"
EMPLOYEE = "contract"

DET, SEM, EXT = "确定性", "语义", "外部数据"

RULES = [
    Rule("R01", "合同价款与中标价一致性", DET, cp.r01),
    Rule("R02", "工程范围/服务范围一致性", SEM, cp.r02, llm=True),
    Rule("R03", "工期/服务期限一致性", DET, cp.r03),
    Rule("R04", "履约人员名单一致性", SEM, cp.r04, llm=True),
    Rule("R05", "付款节点及比例一致性", SEM, cp.r05, llm=True),
    Rule("R06", "联合体分工协议条款校验", SEM, cp.r06, llm=True),
    Rule("R07", "违约责任条款识别", SEM, cp.r07, llm=True),
    Rule("R08", "其他实质性条款变更", SEM, cp.r08, llm=True),
    Rule("R09", "违约责任限额", DET, cl.r09),
    Rule("R10", "违约金比例合理性", DET, cl.r10),
    Rule("R11", "合同价款大小写一致性", DET, cl.r11),
    Rule("R12", "价税分离", DET, cl.r12),
    Rule("R13", "价格表述规范性", DET, cl.r13),
    Rule("R14", "仲裁机构名称规范性", DET, cl.r14),
    Rule("R15", "合同相对方名称一致性", DET, cl.r15),
    Rule("R16", "分公司、项目部授权", EXT, ex.r16),
    Rule("R17", "合同主体资信", EXT, ex.r17),
    Rule("R18", "主合同核减时分包合同联动", SEM, cl.r18, llm=True),
    Rule("R19", "合同名称表单完整性", DET, cl.r19),
    Rule("R20", "项目阶段及付款节点明细", DET, cp.r20),
    Rule("R21", "合同重复签订", EXT, ex.r21),
    Rule("R22", "会签部门正确性", EXT, ex.r22),
    Rule("R23", "法律引用准确性", DET, cl.r23),
    Rule("R24", "中标合同签订时限", DET, cp.r24),
    Rule("R25", "签订日期/工期/有效期合规性", DET, cl.r25),
    Rule("R26", "框架/战略协议排他性", SEM, cl.r26, llm=True),
    Rule("R27", "监理/项目管理价款变更条款", DET, cl.r27),
    Rule("R28", "履约人员情况表报送提示", DET, cl.r28),
    Rule("R29", "技术协议标准规范有效性", EXT, ex.r29),
    Rule("R30", "技术参数一致性", SEM, cp.r30, llm=True),
]


def catalog() -> list[dict]:
    return [{"rule_id": r.id, "name": r.name, "category": r.category, "llm": r.llm} for r in RULES]
