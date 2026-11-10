"""从表单与各类材料中抽取规则所需事实（一期为确定性抽取；语义抽取后续接大模型）。

每个事实都带出处：{"value": ..., "file": 文件名, "page": 页码, "snippet": 原文片段}。
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .materials import Material

DATE_RE = r"(20\d{2})\s*[年\-./]\s*(\d{1,2})\s*[月\-./]\s*(\d{1,2})\s*日?"
TIME_RE = DATE_RE + r"\s*(\d{1,2})\s*[时:：]\s*(\d{1,2})\s*分?"


def _date(m) -> date | None:
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _dt(m) -> datetime | None:
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
    except ValueError:
        return None


def _pages(mat: Material):
    for p in mat.doc.get("pages", []):
        yield p.get("no", 1), p.get("text", "")


def _find(mats: list[Material], pattern: str, conv, flags=0):
    for mat in mats:
        for no, text in _pages(mat):
            for m in re.finditer(pattern, text, flags):
                v = conv(m)
                if v is not None:
                    s = max(0, m.start() - 30)
                    return {"value": v, "file": mat.filename, "page": no,
                            "snippet": text[s:m.end() + 30].replace("\n", " ")}
    return None


def _money_wan(text: str) -> float | None:
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*(万元|元)", text)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return v if m.group(2) == "万元" else round(v / 10000, 6)


def _norm_phone(s: str) -> str:
    return re.sub(r"\D", "", s)


def presence(mats: list[Material], items: dict[str, str]) -> dict[str, dict | None]:
    out = {}
    for name, pat in items.items():
        out[name] = _find(mats, pat, lambda m: True)
    return out


ANNOUNCEMENT_ITEMS = {
    "采购人名称": r"采购人(名称)?\s*[:：]",
    "采购人地址": r"(采购人)?地址\s*[:：]|邮寄地址",
    "采购文件获取方式": r"采购文件的?获取|获取方式",
    "项目名称": r"项目名称",
    "项目地点": r"项目地点|服务地点|实施地点|建设地点|\n地点",
    "采购内容": r"采购内容|采购范围",
    "采购方式": r"采购方式",
    "供应商资格": r"资格要求|资格条件|供应商资格",
}

PROCUREMENT_DOC_ITEMS = {
    "技术要求（质量标准）": r"技术要求|质量标准|质量要求|采购需求|服务要求",
    "报名（报价、投标）截止时间": r"截止时间",
    "项目地点": r"项目地点|服务地点|实施地点|开启地点|\n地点",
    "工期": r"工期|服务期|服务期限|完成时间",
    "合同格式": r"合同条款|合同格式|合同文本",
    "开标日期": r"开标|开启时间",
    "评分标准": r"评分标准|评分办法|评审办法|综合评分",
    "报价单模板": r"报价单|报价表|报价一览表|响应报价函|报价函",
    "报价单递交方式": r"递交方式|递交地点|邮寄地址",
    "采购人联系方式": r"联系方式|联系电话|联系人",
}

METHOD_WORDS = r"公开招标|邀请招标|招标|询比|询价|竞争性谈判|谈判|竞价|直接采购|单一来源"


def extract(form: dict, mats: list[Material], suppliers: list[str]) -> dict:
    by = lambda role: [m for m in mats if m.role == role]  # noqa: E731
    ann, pdoc, review = by("announcement"), by("procurement_doc"), by("review_report")
    facts: dict = {"form": form, "suppliers": suppliers}

    facts["ann_publish_date"] = _find(ann, r"发布日期\s*[:：]\s*" + DATE_RE, lambda m: _date_shift(m, 0)) \
        or _find(ann, DATE_RE, _date)
    facts["ann_method"] = _find(ann, r"采购方式\s*[:：]\s*(" + METHOD_WORDS + ")", lambda m: m.group(1))
    facts["deadline"] = _find(ann + pdoc + review, r"截[止至]时间[为是：:\s]*" + TIME_RE, lambda m: _dt_shift(m, 0))
    facts["max_price_wan"] = _find(ann + pdoc, r"(最高限价|限价)[\s\S]{0,400}?([\d,]+(?:\.\d+)?)\s*(万元|元)",
                                   lambda m: _to_wan(m.group(2), m.group(3)))
    facts["ann_items"] = presence(ann, ANNOUNCEMENT_ITEMS) if ann else None
    facts["pdoc_items"] = presence(pdoc, PROCUREMENT_DOC_ITEMS) if pdoc else None

    pub = None
    for m in pdoc:
        mm = re.search(r"(20\d{2})[.\-年](\d{1,2})[.\-月](\d{1,2})日?\s*[（(]发[)）]", m.filename)
        if mm:
            pub = {"value": _date(mm), "file": m.filename, "page": None, "snippet": m.filename}
            break
    facts["pdoc_publish_date"] = pub or _find(ann + pdoc, r"发售时间\s*[:：]\s*" + DATE_RE, lambda m: _date_shift(m, 0))

    facts["review_date"] = _find(review, r"评审(会议)?[^\n。]{0,20}?" + DATE_RE, lambda m: _date_any(m)) \
        or _find(review, r"日期\s*[:：]\s*" + DATE_RE, lambda m: _date_shift(m, 0))
    facts["review_method"] = _find(review, "(" + METHOD_WORDS + ")", lambda m: m.group(1))
    facts["quotes"] = review_quotes(review, suppliers)
    facts["supplier_values"] = supplier_values(mats, suppliers, ann + pdoc)
    facts["office_meta"] = {s: [{"file": m.filename, **{k: m.doc.get("meta", {}).get(k)
                                                     for k in ("author", "last_modified_by", "created")}}
                                for m in mats if m.supplier == s and m.doc.get("kind") in ("docx", "xlsx", "doc", "xls")]
                            for s in suppliers}
    return facts


def _date_shift(m, offset: int):
    try:
        return date(int(m.group(1 + offset)), int(m.group(2 + offset)), int(m.group(3 + offset)))
    except (ValueError, IndexError):
        return None


def _date_any(m):
    g = [x for x in m.groups() if x and x.isdigit()]
    try:
        return date(int(g[0]), int(g[1]), int(g[2]))
    except (ValueError, IndexError):
        return None


def _dt_shift(m, offset: int):
    try:
        return datetime(*(int(m.group(i + offset)) for i in range(1, 6)))
    except (ValueError, IndexError):
        return None


def _to_wan(num: str, unit: str) -> float | None:
    try:
        v = float(num.replace(",", ""))
    except ValueError:
        return None
    return v if unit == "万元" else round(v / 10000, 6)


def review_quotes(review: list[Material], suppliers: list[str]) -> dict:
    """在评审报告中为每家供应商找含税报价：名称所在行及其后两行内第一个带两位小数的金额（≥1000）。

    只认「一行一家」的排名表：含两家及以上供应商名称的行（列式表头、版面解析合并成段的表格）不作为锚点，
    向下找金额时遇到其他供应商名称即停止；多家的金额取自同一行视为错位（报价相同但分属不同行的不算），
    该页对这几家作废、继续找其他页。
    """
    keys = {s: s[:6] for s in suppliers}
    banned: dict[str, set] = {s: set() for s in suppliers}

    def find(s: str) -> dict | None:
        others = [k for o, k in keys.items() if o != s]
        for mat in review:
            for no, text in _pages(mat):
                if (mat.filename, no) in banned[s] or not re.search(r"含税|报价|评审意见|预成交", text):
                    continue
                lines = text.splitlines()
                for i, ln in enumerate(lines):
                    if keys[s] not in ln or any(k in ln for k in others):
                        continue
                    for j in range(i, min(i + 3, len(lines))):
                        if j > i and any(k in lines[j] for k in keys.values()):
                            break
                        nums = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.\d{2}", lines[j])]
                        nums = [n for n in nums if n >= 1000]
                        if nums:
                            return {"value": nums[0], "file": mat.filename, "page": no,
                                    "snippet": " / ".join(lines[i:j + 1])[:120], "_line": j}
        return None

    out: dict = {}
    pending = list(suppliers)
    for _ in range(len(suppliers) + 1):
        for s in pending:
            hit = find(s)
            if hit:
                out[s] = hit
        clash: dict[tuple, list] = {}
        for s, v in out.items():
            clash.setdefault((v["file"], v["page"], v["_line"]), []).append(s)
        pending = [s for group in clash.values() if len(group) > 1 for s in group]
        if not pending:
            break
        for s in pending:
            banned[s].add((out[s]["file"], out[s]["page"]))
            del out[s]
    for v in out.values():
        v.pop("_line", None)
    return out


PHONE = r"(?<!\d)(1[3-9]\d{9})(?!\d)"
EMAIL = r"[\w.\-]+@[\w\-]+(?:\.[\w\-]+)+"
ACCOUNT = r"(?:账号|帐号|账户|银行账号)[^\d\n]{0,8}(\d[\d\s]{10,28}\d)"
ADDRESS = r"(?:公司地址|注册地址|地址|住所)\s*[:：]?\s*([^\n|]{6,60})"


def supplier_values(mats: list[Material], suppliers: list[str], common_src: list[Material]) -> dict:
    """每家供应商自身材料中的电话/邮箱/账号/地址；剔除公告、采购文件中出现的公共值（代理机构、采购人信息）。"""
    common = set()
    for mat in common_src:
        for _, text in _pages(mat):
            common |= {_norm_phone(x) for x in re.findall(PHONE, text)}
            common |= {x.lower() for x in re.findall(EMAIL, text)}
            common |= {re.sub(r"\s", "", x) for x in re.findall(ACCOUNT, text)}
            common |= {_norm_addr(x) for x in re.findall(ADDRESS, text)}
    out = {}
    for s in suppliers:
        vals: dict[str, dict] = {"电话": {}, "邮箱": {}, "银行账号": {}, "地址": {}}
        for mat in mats:
            if mat.supplier != s:
                continue
            for no, text in _pages(mat):
                for kind, pat, norm in (("电话", PHONE, _norm_phone), ("邮箱", EMAIL, str.lower),
                                        ("银行账号", ACCOUNT, lambda x: re.sub(r"\s", "", x)),
                                        ("地址", ADDRESS, _norm_addr)):
                    for raw in re.findall(pat, text):
                        v = norm(raw)
                        if v and v not in common and v not in vals[kind]:
                            vals[kind][v] = {"file": mat.filename, "page": no}
        out[s] = vals
    return out


def _norm_addr(s: str) -> str:
    s = re.sub(r"[\s，,。；;（）()]", "", s)
    return s[:24] if len(s) >= 8 else ""
