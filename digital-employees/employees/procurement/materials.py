"""材料归集：按文件名与所在字段判断材料类型，并把响应文件、报名资料归到具体供应商。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ROLE_LABELS = {
    "announcement": "采购公告",
    "procurement_doc": "采购文件",
    "response": "供应商响应文件",
    "review_report": "评审报告",
    "registration": "报名资料",
    "publicity": "结果公示",
    "requirement_approval": "采购需求审批表",
    "quote": "报价单",
    "direct_note": "直接采购说明",
    "other": "其他",
}

_RULES = [
    ("response", r"响应文件|投标文件|报价文件|应答文件"),
    ("review_report", r"评审|评标|谈判报告|询比报告"),
    ("publicity", r"公示|成交结果|中标结果|结果公告"),
    ("announcement", r"公告"),
    ("procurement_doc", r"采购文件|招标文件|询比文件|谈判文件|（发）|\(发\)"),
    ("registration", r"报名|登记表|营业执照"),
    ("requirement_approval", r"需求审批"),
    ("quote", r"报价单|报价表"),
    ("direct_note", r"直接采购|单一来源"),
]


@dataclass
class Material:
    sig: str
    filename: str
    role: str
    supplier: str | None = None
    parent_sig: str | None = None
    field_label: str = ""
    doc: dict = field(default_factory=dict)

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)


def classify(filename: str, field_label: str = "") -> str:
    name = filename.rsplit("/", 1)[-1]
    for role, pat in _RULES:
        if re.search(pat, name):
            return role
    if "公告文件" in field_label:
        return "publicity"
    return "other"


def supplier_from_response(filename: str) -> str | None:
    """「响应文件--某某公司」「某某-投标文件-扫描」「某某公司投标文件」三种写法。"""
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", filename.rsplit("/", 1)[-1])
    stem = re.sub(r"[（(]?(扫描件?|盖章版?|正本|副本)[)）]?", "", stem)
    m = re.search(r"(?:响应文件|投标文件|报价文件)\s*[-—_－:：]+\s*(.+)$", stem)
    if m and m.group(1).strip(" -—_"):
        return m.group(1).strip(" -—_")
    m = re.match(r"^(.+?(?:有限责任公司|有限公司|公司|研究院|研究所|学院|大学))", stem)
    if m:
        return m.group(1)
    m = re.match(r"^([^-—_－]{2,20})[-—_－]", stem)
    return m.group(1).strip() if m else None


COMPANY_RE = re.compile(r"[\u4e00-\u9fa5（）()]{2,40}?(?:有限责任公司|股份有限公司|有限公司|研究院|研究所|设计院|学院|大学)")


def expand_names(shorts: list[str], texts: list[str]) -> dict[str, str]:
    """用评审报告等材料中出现的公司全称，补全文件名里的简称（如「山东明洋」→「山东明洋…有限公司」）。"""
    full = set()
    for t in texts:
        full |= {re.sub(r"\s", "", x) for x in COMPANY_RE.findall(t or "")}
    out = {}
    for s in shorts:
        if COMPANY_RE.fullmatch(s):
            out[s] = s
            continue
        cands = sorted({f for f in full if s in f}, key=len)
        out[s] = cands[0] if cands else s
    return out


def looks_like_announcement(text: str) -> bool:
    head = (text or "")[:1500]
    return "采购公告" in head and bool(re.search(r"截止时间|获取方式|采购文件的?获取", text or "")) and "成交候选人" not in head


def match_supplier(hint: str, suppliers: list[str]) -> str | None:
    """把压缩包目录名（如「1.山东泽陆园」「2.鼎丞」）匹配到供应商全称。"""
    core = re.sub(r"^[\d\.\s、\-_]+", "", hint or "").strip()
    core = re.sub(r"(信息)?(登记表|报名|营业执照|资料).*$", "", core).strip(" -_")
    if len(core) < 2:
        return None
    hits = [s for s in suppliers if core in s]
    if len(hits) == 1:
        return hits[0]
    for size in range(min(len(core), 6), 1, -1):
        for i in range(len(core) - size + 1):
            part = core[i:i + size]
            hits = [s for s in suppliers if part in s]
            if len(hits) == 1:
                return hits[0]
    return None
