"""报销单统一模型：通财云适配器（或本地事项）把单据转换成 Claim，规则只依赖这个结构。

字段名与需求说明书「读取的数据」一节对应；取不到的字段保持 None / 空，由规则判「待补充」。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from shared.rule_framework.common import parse_date, to_number


def _d(v) -> date | None:
    return parse_date(v) if v else None


def _n(v) -> float | None:
    return to_number(v) if v not in (None, "") else None


@dataclass
class Invoice:
    number: str = ""
    kind: str = ""                 # 发票类型：数电票铁路电子客票 / 数电发票普通发票 / 增值税专用发票 / 定额发票 …
    date: date | None = None       # 开票日期
    amount: float | None = None    # 价税合计
    items: list = field(default_factory=list)   # 货物或应税劳务名称（商品名称）
    remark: str = ""
    travel_date: date | None = None  # 乘车/乘机日期（铁路电子客票）
    seller: str = ""
    detail_total: float | None = None  # 随票销货清单合计（如有）
    file: str = ""
    source: str = "structured"     # structured：单据结构化数据；text：从发票文件文字识别

    @classmethod
    def of(cls, d: dict) -> "Invoice":
        return cls(number=str(d.get("number") or ""), kind=d.get("kind") or "", date=_d(d.get("date")),
                   amount=_n(d.get("amount")), items=list(d.get("items") or []), remark=d.get("remark") or "",
                   travel_date=_d(d.get("travel_date")), seller=d.get("seller") or "",
                   detail_total=_n(d.get("detail_total")), file=d.get("file") or "", source=d.get("source", "structured"))

    @property
    def label(self) -> str:
        return f"发票 {self.number or '（无号码）'}"


@dataclass
class Claim:
    doc_type: str = ""             # 单据类型：差旅报销单 / 业务招待费报销单 / 办公费报销单 / 车辆使用费报销单 / 交通费报销单 /
                                   # 会议费报销单 / 培训费报销单 / 通用费用报销单（对公|对私）/ 资产采购报销单
    code: str = ""                 # 单据编码
    amount: float | None = None    # 报销金额
    reason: str = ""               # 报销事由
    applicant: str = ""
    dept: str = ""                 # 申请人主职部门
    identity: str = ""             # 审批流身份：公司领导班子成员 / 部门主要负责人 / 其他员工
    grade: str = ""                # 岗位职级（ENT-03）
    submit_date: date | None = None
    remark: str = ""
    expenses: list = field(default_factory=list)   # [{type, item, amount, person, name}]
    travel: dict = field(default_factory=dict)     # {start, end, days, subsidy_days, subsidy_amount, reason}
    entertain: dict = field(default_factory=dict)  # {type, units, guests, accompany, date, total, gift, gift_per_person, gift_times}
    vehicle: dict = field(default_factory=dict)    # {plate, item}
    assets: list = field(default_factory=list)     # [{name, amount}]
    asset_tier: str = ""           # 必备 / 专项 / 重大
    flags: dict = field(default_factory=dict)      # {consecutive: 表单「存在连号」字段, prepaid: 是否预付储值}
    invoices: list = field(default_factory=list)   # list[Invoice]

    @classmethod
    def of(cls, d: dict) -> "Claim":
        t, e = dict(d.get("travel") or {}), dict(d.get("entertain") or {})
        for k in ("start", "end"):
            t[k] = _d(t.get(k))
        for k in ("days", "subsidy_days", "subsidy_amount"):
            t[k] = _n(t.get(k))
        e["date"] = _d(e.get("date"))
        for k in ("guests", "accompany", "total", "gift_per_person", "gift_times"):
            e[k] = _n(e.get(k))
        return cls(doc_type=d.get("doc_type") or "", code=d.get("code") or "", amount=_n(d.get("amount")),
                   reason=d.get("reason") or "", applicant=d.get("applicant") or "", dept=d.get("dept") or "",
                   identity=d.get("identity") or "", grade=d.get("grade") or "", submit_date=_d(d.get("submit_date")),
                   remark=d.get("remark") or "",
                   expenses=[{**x, "amount": _n(x.get("amount"))} for x in d.get("expenses") or []],
                   travel=t, entertain=e, vehicle=dict(d.get("vehicle") or {}),
                   assets=[{**x, "amount": _n(x.get("amount"))} for x in d.get("assets") or []],
                   asset_tier=d.get("asset_tier") or "", flags=dict(d.get("flags") or {}),
                   invoices=[Invoice.of(x) for x in d.get("invoices") or []])

    def expense_types(self) -> set[str]:
        return {str(x.get("type") or "") for x in self.expenses}

    def items_of(self) -> set[str]:
        return {str(x.get("item") or "") for x in self.expenses if x.get("item")}

    def text_fields(self) -> str:
        """ENT-12 全字段检索用：事由、备注、招待对象单位、费用明细。"""
        parts = [self.reason, self.remark, " ".join(self.entertain.get("units") or []),
                 " ".join(str(x.get("item") or "") + str(x.get("name") or "") for x in self.expenses)]
        return " ".join(p for p in parts if p)
