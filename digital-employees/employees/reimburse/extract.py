"""报销要素：单据结构化数据（Claim）+ 附件归类 + 发票（结构化优先，缺失时从发票文件文字识别）+ 适用的单据类别。"""
from __future__ import annotations

import re

from core.materials import Material

from .materials import find, invoice_from_text, red_seal_ratio, refine
from .model import Claim

GROUPS = [
    ("差旅费", "TRV", r"差旅"),
    ("业务招待费", "ENT", r"招待"),
    ("办公费", "OFF", r"办公"),
    ("车辆使用费", "VEH", r"车辆使用|车辆费"),
    ("交通费", "TRA", r"交通费|市内交通"),
    ("会议费", "MTG", r"会议费"),
    ("培训费", "TRN", r"培训"),
    ("通用报销单", "GEN", r"通用费用|通用报销"),
    ("资产采购", "AST", r"资产采购|资产购置"),
]


def groups_of(claim: Claim) -> list[str]:
    """报销单里出现哪类费用就执行哪一类规则；一张单同时含差旅与招待时两类都执行。"""
    text = claim.doc_type + " " + " ".join(claim.expense_types())
    found = [code for _, code, pat in GROUPS if re.search(pat, text)]
    if "TRV" in found and claim.entertain and "ENT" not in found and (claim.entertain.get("guests") or 0) > 0:
        found.append("ENT")
    return found


def extract(claim_dict: dict, mats: list[Material], read_blob) -> dict:
    claim = Claim.of(claim_dict or {})
    for m in mats:
        refine(m)
    if not claim.invoices:
        for m in find(mats, "invoice"):
            inv = invoice_from_text(m)
            if inv:
                claim.invoices.append(inv)
    seals = {}
    for m in find(mats, "repair_list", "courier_split", "asset_inbound"):
        kind = m.doc.get("kind")
        seals[m.name] = red_seal_ratio(read_blob(m.sig), kind) if kind in ("pdf", "image") else None
    return {"claim": claim, "materials": mats, "groups": groups_of(claim), "seals": seals,
            "has_claim": bool(claim_dict)}
