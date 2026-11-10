"""三会请示要素抽取：OA 表单字段、审批/上会依据的结构化拆解、请示正文与各附件的关键事实。

每项事实带出处；抽不到为 None，由审查节点判「待补充」或「人工复核」。
"""
from __future__ import annotations

import re

from core.knowledge.base import RegulationBase
from core.knowledge.regulations import parse_range
from core.materials import Material
from core.rules import common as C

from .materials import attachments, request_body

STAGES = [
    ("采购结果", r"采购结果|成交结果|中标结果|定标|成交供应商|评审结果"),
    ("采购过程", r"采购方式|采购方案|采购文件|招标方案|采购公告|邀请招标|竞争性谈判方案"),
    ("立项", r"立项|可行性研究|可研|项目建议"),
    ("制度制定修订", r"制度|管理办法|实施细则|规定的|修订|制定"),
    ("人员事项", r"任免|聘任|任职|干部|人员调整|职级"),
    ("合同签订", r"合同签订|签约|协议签订|签署"),
]
SUBJECT_RE = (r"(总经理办公会议?|总办会|董事会|党委会议?|党委常委会|董事长专题会|专题会|总经理|董事长)"
              r"\s*(审批|审议|决定|决策|研究|审定)")
RESULT_AMOUNT_KW = r"(成交金额|成交价格|成交价|中标金额|中标价格|中标价|采购结果金额|采购金额|合同金额|合同价款|签约金额)"
BUDGET_KW = r"(预算金额|采购预算|项目预算|总预算|预算价|预算(为|是|约|共计|总额|控制在|[:：])|控制价|最高限价|投资估算|估算金额)"
TOTAL_KW = r"(费用合计|金额合计|合计金额|费用总计|总金额|总费用|总价|合计|总计)"
SUPPLIER_RE = re.compile(r"(成交供应商|中标人|中标单位|成交单位|成交人|第一(中标|成交)候选人|推荐[^。\n]{0,8}第一名)"
                         r"[为是:：\s]*([^\n，,。；;：:]{4,40}?(公司|研究院|设计院|中心))")
PLACEHOLDER_RE = re.compile(r"[XＸxх×＊*]{2,}|【\s*】|（\s{1,}）|\(\s{1,}\)|＿{2,}|_{3,}|\?{2,}")


def norm_meeting(text: str, aliases: dict) -> str | None:
    t = re.sub(r"\s", "", text or "").replace("（", "(").replace("）", ")")
    if not t:
        return None
    for std, names in (aliases or {}).items():
        for n in names:
            if n.replace("（", "(").replace("）", ")") in t:
                return std
    return None


def stage_of(text: str) -> str | None:
    for name, pat in STAGES:
        if re.search(pat, text or ""):
            return name
    return None


def title_core(title: str) -> str:
    """标题中的项目/事项名称：去掉「关于…的请示」与阶段词。"""
    t = re.sub(r"^关于|的?请示$|的?报告$", "", re.sub(r"\s", "", title or ""))
    t = re.sub(r"(采购结果|采购方案|采购方式|立项|成交结果|中标结果|事项|有关|相关|的)$", "", t)
    t = re.sub(r"(采购结果|采购方案|采购方式|立项)", "", t)
    return re.sub(r"^公司", "", t)


def _fact(value, mat: Material, page, text: str, s: int, e: int, **kw) -> dict:
    return C.ev(mat.name, page, C.around(text, s, e), value=value, **kw)


_CMP_BEFORE = re.compile(r"(<|>|≤|≥|＜|＞|小于|大于|低于|高于|不足|超过|达到|不少于|至少|一般为|原则上)\s*$")
_CMP_AFTER = re.compile(r"^\s*[（(]?含[）)]?\s*(以上|以下)|^\s*(及以上|以上|以下)")


def _threshold(text: str, s: int, e: int) -> bool:
    """「单项采购金额<50万元，部门负责人审批」「≥30万元」「一般为3人以上」这类权限门槛或组建规则，不是本事项的事实。
    「预算控制在50万元以内」是本事项的预算上限，不算门槛。"""
    return bool(_CMP_BEFORE.search(text[max(0, s - 4):s]) or _CMP_AFTER.search(text[e:e + 6]))


def amount_fact(mat: Material, kw: str) -> dict | None:
    for page, text in mat.pages:
        for m in re.finditer(kw, text):
            for a in C.amounts(text[m.end():m.end() + 40]):
                s, e = m.end() + a.start, m.end() + a.end
                if not _threshold(text, s, e):
                    return _fact(a.yuan, mat, page, text, s, e, raw=a.raw)
    return None


def date_in_sentence(mat: Material, must: str, also: str) -> dict | None:
    for page, text in mat.pages:
        for m in re.finditer(r"[^。；;\n]+", text):
            sent = m.group(0)
            if re.search(must, sent) and re.search(also, sent):
                ds = C.find_dates(sent)
                if ds:
                    d, s, e = ds[0]
                    return _fact(d, mat, page, text, m.start() + s, m.start() + e)
    return None


def reviewers(mat: Material) -> dict | None:
    rx = re.compile(r"(评审(小组|委员会|专家组)|谈判小组|评标委员会|专家)[^。；\n]{0,10}?由?\s*"
                    r"(\d+|[一二三四五六七八九十]+)\s*(名|人|位)")
    rx2 = re.compile(r"(\d+|[一二三四五六七八九十]+)\s*(名|人|位)\s*(评审专家|专家|评委)")
    for page, text in mat.pages:
        for m in [*rx.finditer(text), *rx2.finditer(text)]:
            g = 3 if m.re is rx else 1
            v = C.num_word(m.group(g))
            if v and not _threshold(text, m.start(g), m.end()):
                return _fact(int(v), mat, page, text, m.start(), m.end())
    return None


def supplier(mat: Material) -> dict | None:
    for page, text in mat.pages:
        m = SUPPLIER_RE.search(text)
        if m:
            return _fact(re.sub(r"\s", "", m.group(3)), mat, page, text, m.start(), m.end())
    return None


def doc_facts(mat: Material) -> dict:
    head = mat.text[:1500]
    name = None
    for pat in (r"项目名称\s*[:：]\s*([^\n，,。；;]{4,60})", r"关于(.{4,60}?)的(请示|通知|报告|公告|函)", r"^(.{6,60}?)(采购公告|评审报告|成交通知书?|报价单|报价表)"):
        m = re.search(pat, head, re.M)
        if m:
            name = re.sub(r"\s", "", m.group(1))
            break
    # 采购需求 / 采购文件形成于结果之前，其中的「采购金额」是预算口径，不作为成交金额比对
    pre_result = mat.role == "procurement_doc"
    return {"project": name, "result_amount": None if pre_result else amount_fact(mat, RESULT_AMOUNT_KW),
            "budget": amount_fact(mat, BUDGET_KW), "total": amount_fact(mat, TOTAL_KW),
            "announce_date": _first_date_fact(mat, r"(发布日期|公告日期|发布时间)")
            or date_in_sentence(mat, r"公告", r"发布|发出|刊登|公示"),
            "review_date": date_in_sentence(mat, r"评审|评标|谈判", r"召开|进行|组织|开展|会议|时间|日期"),
            "reviewers": None if pre_result else reviewers(mat), "supplier": supplier(mat), "stage": stage_of(head)}


def _first_date_fact(mat: Material, kw: str) -> dict | None:
    for page, text in mat.pages:
        hit = C.date_after(text, kw, 30)
        if hit:
            return _fact(hit[0], mat, page, text, hit[1], hit[2])
    return None


def basis_parts(basis: str) -> dict:
    refs = RegulationBase.refs_in(basis)
    subj = re.search(SUBJECT_RE, re.sub(r"\s", "", basis or ""))
    return {"refs": refs, "range": parse_range(basis or ""), "subject": subj.group(1) if subj else None,
            "action": subj.group(2) if subj else None}


def extract(form: dict, mats: list[Material], cfg: dict) -> dict:
    ff = {}
    for std, names in (cfg.get("form_fields") or {}).items():
        for n in names:
            v = form.get(n)
            if v not in (None, "") and str(v).strip():
                ff[std] = {"value": str(v).strip(), "label": n}
                break
    body = request_body(mats)
    atts = attachments(mats, body)
    title = (ff.get("标题") or {}).get("value") or ""
    facts: dict = {"form": ff, "form_raw": form, "body": body, "attachments": atts, "materials": mats,
                   "title": title, "title_core": title_core(title),
                   "meeting": norm_meeting((ff.get("会议类型") or {}).get("value"), cfg.get("meeting_aliases")),
                   "basis": (ff.get("审批依据") or {}).get("value") or "",
                   "att_facts": {m.name: doc_facts(m) for m in atts if m.readable}}
    facts["basis_parts"] = basis_parts(facts["basis"])
    if body:
        text = body.text
        facts["body_facts"] = doc_facts(body)
        facts["body_title"] = (re.search(r"关于.{2,60}?的请示", text[:400]) or [None])[0]
        facts["stage"] = stage_of(title) or stage_of(facts["body_title"] or "") or stage_of(text[:1500])
        req = re.search(r"(提请|报请|提交|请|拟提交)(公司)?\s*(总经理办公会议?|总办会|董事会|党委会议?|党委常委会|董事长专题会|专题会)"
                        r"\s*(审议|研究|审批|决定|决策|审定)?", text)
        facts["body_meeting"] = ({**_fact(req.group(0), body, None, text, req.start(), req.end()),
                                  "value": norm_meeting(req.group(3), cfg.get("meeting_aliases")), "raw": req.group(0)}
                                 if req else None)
        facts["body_refs"] = RegulationBase.refs_in(text)
        facts["placeholders"] = [_fact(m.group(0), body, None, text, m.start(), m.end())
                                 for m in PLACEHOLDER_RE.finditer(text)][:6]
        facts["amount_mentions"] = [_fact(a.yuan, body, None, text, a.start, a.end, raw=a.raw) for a in C.amounts(text)]
    else:
        facts["stage"] = stage_of(title)
    bf = facts.get("body_facts") or {}
    if facts["stage"] in ("立项", "采购过程"):
        facts["case_amount"] = bf.get("budget") or bf.get("total") or bf.get("result_amount")
    else:
        facts["case_amount"] = bf.get("result_amount") or bf.get("total") or bf.get("budget")
    return facts
