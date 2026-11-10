"""合同审核的材料类型：按文件名与所在表单字段判断；文件名只是线索，抽取时仍以内容为准。"""
from __future__ import annotations

import re

from core.materials import Material

ROLE_LABELS = {
    "contract_text": "合同正文",
    "contract_appendix": "合同附件",
    "award_notice": "中标通知书",
    "bid": "投标文件",
    "tender_doc": "招标文件",
    "consortium": "联合体协议",
    "tech_agreement": "技术协议/清单",
    "authorization": "授权文件",
    "reduction_note": "核减情况说明",
    "legal_opinion": "法律意见书",
    "other": "其他",
}

_RULES = [
    ("award_notice", r"中标通知|成交通知|中标证明|中选通知"),
    ("consortium", r"联合体|分工协议|标前协议|合作协议书"),
    ("tech_agreement", r"技术协议|技术规格|技术要求|供货清单|合同清单|设备清单|技术附件"),
    ("authorization", r"授权委托|授权书|授权文件|法人授权|总公司授权"),
    ("reduction_note", r"核减"),
    ("legal_opinion", r"法律意见"),
    ("tender_doc", r"招标文件|采购文件|谈判文件|磋商文件|询价文件"),
    ("bid", r"投标文件|响应文件|投标书|报价文件|应答文件|报价"),
    ("contract_text", r"合同|协议"),
]


def classify(filename: str, field_label: str = "") -> str:
    """字段名优先（wf=99：出版用合同文本PDF / 中标扫描件 / 其它附件 / 合同扫描件；
    wf=98 经台账带入：投标报价台账·附件 / ·中标证明附件 / ·上传最终版投标文件），文件名其次。"""
    name = filename.rsplit("/", 1)[-1]
    label = field_label or ""
    if re.search(r"中标证明|中标扫描|中标通知", label):
        return "award_notice"
    if re.search(r"最终版投标文件", label):
        return "bid"
    if re.search(r"出版用合同|合同文本|合同正文", label):
        if re.search(r"附件", name):
            return "contract_appendix"
        if not any(re.search(p, name) for _, p in _RULES[:-1]):
            return "contract_text"
    for role, pat in _RULES:
        if re.search(pat, name):
            return role
    if re.search(r"投标报价台账", label):
        return "tender_doc" if re.search(r"\.(zip|rar|7z)$", name, re.I) else "other"
    return "other"


def by_role(mats: list[Material], *roles: str) -> list[Material]:
    return [m for m in mats if m.role in roles and not m.is_archive]


def main_contract(mats: list[Material]) -> Material | None:
    """合同正文：优先「出版用合同文本」字段；其次文件名含「合同文本/正文」；多份时取文字最多的一份。
    「合同扫描件」是签章后的扫描件，只在没有文字版时兜底。"""
    cands = [m for m in by_role(mats, "contract_text") if m.readable]
    if not cands:
        return None
    for pick in (lambda m: re.search(r"出版", m.field_label),
                 lambda m: re.search(r"合同文本|合同正文", m.name) and not re.search(r"扫描", m.field_label),
                 lambda m: not re.search(r"扫描", m.field_label + m.name)):
        pool = [m for m in cands if pick(m)]
        if pool:
            return max(pool, key=lambda m: len(m.text))
    return max(cands, key=lambda m: len(m.text))
