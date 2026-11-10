"""三会请示的材料类型。附件名称只是类型线索，最终核验以文件内容为准；必传规则未确认，不判定「缺少某类附件」。"""
from __future__ import annotations

import re

from core.materials import Material

ROLE_LABELS = {
    "request_body": "请示正文",
    "procurement_doc": "采购需求/采购文件",
    "announcement": "采购公告/邀请文件",
    "review_report": "评审报告",
    "result": "采购结果/成交文件",
    "quote": "供应商报价资料",
    "contract": "合同/协议",
    "other": "其他支持材料",
}

_RULES = [
    ("request_body", r"请示|报告正文|正文"),
    ("review_report", r"评审报告|评审意见|评标报告|谈判记录|评审记录"),
    ("result", r"成交通知|中标通知|采购结果|成交结果|结果公示|成交公告|中标公告"),
    ("announcement", r"公告|邀请函|邀请书|询价函"),
    ("quote", r"报价|响应文件|投标文件"),
    ("procurement_doc", r"采购需求|采购文件|招标文件|采购方案|需求书"),
    ("contract", r"合同|协议"),
]


def classify(filename: str, field_label: str = "") -> str:
    name = filename.rsplit("/", 1)[-1]
    if re.search(r"正文", field_label or ""):
        return "request_body"
    for role, pat in _RULES:
        if re.search(pat, name):
            return role
    return "other"


def request_body(mats: list[Material]) -> Material | None:
    cands = [m for m in mats if m.role == "request_body" and m.readable]
    if cands:
        return max(cands, key=lambda m: len(m.text))
    for m in mats:
        if m.readable and re.search(r"关于.{2,60}的请示", m.text[:300]):
            m.role = "request_body"
            return m
    return None


def attachments(mats: list[Material], body: Material | None) -> list[Material]:
    return [m for m in mats if m is not body and not m.is_archive]
