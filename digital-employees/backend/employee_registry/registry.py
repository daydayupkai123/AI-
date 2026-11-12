"""数字员工注册表：工作台与 API 按员工 id 查找流程、规则清单、对话提示词与来源。

新增数字员工只需在这里登记，不改 server.py / app.js。
status：online 已接通客户系统（可审查真实单据、参与采集与自动审查）；beta 规则已就绪，客户系统取数待打通，可审查本地事项。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import ModuleType
from typing import Callable

from shared.source_adapters import docflow
from contract_review import chat_prompts as contract_chat
from contract_review import workflow as contract_graph
from contract_review import rules as contract_rules
from meeting_review import chat_prompts as meeting_chat
from meeting_review import checks as meeting_checks
from meeting_review import workflow as meeting_graph
from procurement_review import chat_prompts as procurement_chat
from procurement_review import workflow as procurement_graph
from procurement_review import rules as procurement_rules
from reimburse_review import chat_prompts as reimburse_chat
from reimburse_review import workflow as reimburse_graph
from reimburse_review import rules as reimburse_rules


@dataclass
class Employee:
    id: str
    persona: str
    name: str
    status: str
    desc: str
    dept: str
    intro: str
    skills: list[str]
    graph: ModuleType
    chat: ModuleType
    catalog: Callable[[], list[dict]]
    rules_version: str
    sources: tuple[str, ...]
    live_source: str
    live_ready: bool
    id_pattern: str
    id_hint: str
    layout: str = "rules"            # rules：按状态分组；nodes：按审查节点固定顺序（三会）；groups：按单据类别（报销）
    examples: list[str] = field(default_factory=list)
    live_note: str = ""

    def public(self) -> dict:
        return {"id": self.id, "persona": self.persona, "name": self.name, "status": self.status, "desc": self.desc,
                "dept": self.dept, "intro": self.intro, "skills": self.skills, "nodes": self.graph.NODES,
                "node_hints": getattr(self.graph, "NODE_HINTS", {}), "sources": list(self.sources),
                "live_source": self.live_source, "live_ready": self.live_ready, "id_hint": self.id_hint,
                "id_pattern": self.id_pattern,
                "layout": self.layout, "examples": self.examples, "live_note": self.live_note,
                "kind": "procurement" if self.id == "procurement" else "review", "rules_total": len(self.catalog())}

    def valid_live_id(self, rid: str) -> bool:
        return bool(re.fullmatch(self.id_pattern, rid))


def _procurement_catalog() -> list[dict]:
    return [{"rule_id": rid, "name": name, "category": tier} for rid, name, tier in procurement_rules.META]


EMPLOYEES: list[Employee] = [
    Employee("procurement", "林悦", "采购审批数字员工", "online", "采购结果审批 · 18 条规则 · 供应商横向比对", "运营管理部审核岗",
             "我会读取采购结果审批单据的表单、审批日志和全部附件，按 18 条规则逐条核验，"
             "并把多家供应商的材料放在一起横向比对，帮你找出不合规与串标线索。",
             ["扫描件 OCR", "压缩包解析", "供应商横向比对", "报价规律识别", "证据可追溯"],
             procurement_graph, procurement_chat, _procurement_catalog, procurement_rules.RULES_VERSION,
             ("contract",), "contract", True, r"\d{5,}", "采购结果审批流程单号（纯数字，如 1674771）"),
    Employee("contract", "陈睿", "合同审核数字员工", "online", "主合同审批 · 30 条规则 · 要点比对与风险识别", "合同审核岗",
             "对照中标通知书、投标文件、招标文件与合同正文，自动比对价款、范围、工期、付款与违约条款，"
             "核查主体资信、授权、法律引用与日期合规，每条结论附原文依据。",
             ["条款比对", "大小写金额", "主体资信", "法律引用", "日期合规"],
             contract_graph, contract_chat, contract_rules.catalog, contract_rules.VERSION,
             contract_graph.SOURCES, "contract", True, r"\d{5,}", "主合同审批流程单号（纯数字）",
             examples=["DEMO-HT-001", "DEMO-HT-002"],
             live_note="合同管理系统已打通（主合同审批流程、投标报价台账、主合同台账），规则在真实单据上持续校准中。"),
    Employee("meeting", "苏婉", "三会审查数字员工", "online", "三会请示 · 5 个审查节点 · 四份制度依据", "三会审核岗",
             "依据权责手册、重大经营管理事项清单、党委决定的重大事项清单与董事会授权决策方案，核验请示的会议类型、"
             "审批依据、金额档位与审批主体，并交叉核对正文与附件。",
             ["制度检索", "金额档位", "审批主体", "正文与附件交叉核验"],
             meeting_graph, meeting_chat, meeting_checks.catalog, meeting_checks.VERSION,
             meeting_graph.SOURCES, "docflow", True, docflow.ID_PATTERN, "内请号（如 通设请字[2026]76号）或 affairId",
             layout="nodes", examples=["DEMO-SH-001", "DEMO-SH-002"],
             live_note="公文系统已打通：输入内请号即可审查；只在门户「我的发起 / 已办 / 已阅」中定位请示，不打开他人待办。"),
    Employee("reimburse", "周航", "财务报销初审数字员工", "beta", "八类单据 · 43 条规则 · 票据风险识别", "会计审核岗",
             "按差旅、招待、办公、车辆、交通、会议、培训、通用、资产九类单据的 43 条规则，核对附件、数据、标准与票据风险，"
             "生成初审提示单。",
             ["发票要素", "标准测算", "连号识别", "附件完整性"],
             reimburse_graph, reimburse_chat, reimburse_rules.catalog, reimburse_rules.VERSION,
             reimburse_graph.SOURCES, "fincloud", False, r"\d{10}-[A-Z]{2,6}\d{4}-\d{6}",
             "通财云单据编码（如 1000001431-CLBX2609-000579）", layout="groups",
             examples=["DEMO-BX-001", "DEMO-BX-002", "DEMO-BX-003"],
             live_note="通财云（金蝶云苍穹）不支持外网直接访问，需在本机连接 VPN 后打通取数；当前可审查本地事项。"),
]

BY_ID = {e.id: e for e in EMPLOYEES}


def get(employee_id: str) -> Employee | None:
    return BY_ID.get(employee_id)
