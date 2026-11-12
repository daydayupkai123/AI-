"""合同审核事实抽取：表单字段（按别名）、合同正文条款、中标通知书、投标文件、招标文件。

每项事实都带出处 {"value", "file", "page", "snippet"}；抽不到就是 None，由规则判「待补充」，不猜测补全。
确定性抽取（正则 + 标准化）在这里完成；需要语义理解的比对放在规则里交给模型，并要求引用原文。
"""
from __future__ import annotations

import re

from shared.material_nodes import Material
from shared.rule_framework import common as C

from .materials import by_role, main_contract

SIDE_A = r"(甲方|发包人|发包方|委托人|委托方|采购人|采购方|买方|需方|招标人|建设单位)"
SIDE_B = r"(乙方|承包人|承包方|受托人|受托方|供应商|卖方|供方|中标人|设计人|咨询人|服务方|监理人|勘察人|代建人)"
ORG_SUFFIX = (r"(公司|集团|研究院|设计院|院|局|中心|委员会|研究所|学校|大学|学院|医院|项目部|分公司|办事处|政府|厂|站|"
              r"管理处|指挥部|部队|支队|大队|总队|事务所|办公室)")
PRICE_KW = r"(签约合同价|合同总价款|合同总价|合同价款|合同总金额|合同金额|合同价格|总价款|合同总额)"
AWARD_PRICE_KW = r"(中标价格|中标价|中标金额|中标合同价|中标总价|成交价格|成交价|成交金额|投标报价|中标报价)"
BID_PRICE_KW = r"(投标总报价|投标报价|投标总价|报价总额|总报价|报价金额|投标价)"
DURATION_KW = r"(合同工期|计划工期|总工期|工期|服务期限|服务期|履行期限|设计周期|设计工期|完成期限|交货期)"
PAY_KW = r"(付款|支付|结算|预付款|进度款|尾款|质保金|保证金)"
CAP_RE = (r"以(本)?合同(总)?(价款|金额|总价|总额|额)为限|不(应|得)?超过(本)?合同(总)?(价款|金额|总价|总额|额)|"
          r"(赔偿|违约)(总额|责任|金额|金)[^。；\n]{0,30}(上限|最高|不超过|为限)|责任限额|赔偿限额|"
          r"累计(赔偿|违约金)[^。；\n]{0,20}不(应|得)?超过")
ABOLISHED_LAWS = {"中华人民共和国合同法", "合同法", "中华人民共和国民法通则", "民法通则", "中华人民共和国民法总则",
                  "民法总则", "中华人民共和国担保法", "担保法", "中华人民共和国物权法", "物权法",
                  "中华人民共和国侵权责任法", "侵权责任法"}
CIVIL_CODE = "中华人民共和国民法典"
STANDARD_RE = re.compile(r"(GB/T|GB|JGJ/T|JGJ|DL/T|DL|NB/T|SL|CJJ/T|CJJ|HJ|AQ/T|AQ|MT/T|MT|JTG|TB|YB|SH/T|HG/T|CECS)"
                         r"\s*(\d+(?:\.\d+)?)\s*[-—–]\s*(\d{4})")


def _fact(value, mat: Material, page, text: str, start: int, end: int, **kw) -> dict:
    return C.ev(mat.name, page, C.around(text, start, end), value=value, **kw)


def fpages(mat: Material) -> list[tuple[int, str]]:
    """按页文字，已合并 PDF 硬换行（按句抽取用）。"""
    return [(no, C.flat(t)) for no, t in mat.pages]


def form_fields(form: dict, aliases: dict) -> dict:
    out = {}
    for std, names in (aliases or {}).items():
        for n in names:
            v = form.get(n)
            if v not in (None, "") and str(v).strip():
                out[std] = {"value": str(v).strip(), "label": n}
                break
    return out


def _location(mat: Material, page: int, text: str, pos: int) -> str:
    n_pages = len(mat.pages)
    if n_pages > 1:
        return "首页" if page == 1 else "签章页" if page == n_pages else "正文"
    tail = max(0, len(text) - 600)
    if pos >= tail and pos > len(text) * 0.5 and re.search(r"签字|盖章|签章|（章）|\(章\)", text[tail:]):
        return "签章页"
    return "首页" if pos < min(1200, len(text) * 0.3) else "正文"


def parties(mat: Material) -> dict:
    out = {"甲方": [], "乙方": []}
    for side, pat in (("甲方", SIDE_A), ("乙方", SIDE_B)):
        rx = re.compile(pat + r"\s*(?:[（(][^）)\n]{1,8}[）)])?\s*[:：]\s*([^\n:：，,；;。（(]{2,60}" + ORG_SUFFIX
                        + r")(?=$|[\s，,；;。（(]|地址|法定代表人|统一社会|住所)", re.M)
        for page, text in mat.pages:  # 保留原始换行：名称以行尾为界，且要据此判断首页/签章页
            for m in rx.finditer(text):
                name = re.sub(r"\s+", "", re.sub(r"[（(](盖章|签章|公章|章)[）)]$", "", m.group(2)))
                out[side].append({"name": name, "role_word": m.group(1), "where": _location(mat, page, text, m.start()),
                                  **_fact(name, mat, page, text, m.start(), m.end())})
    return out


def _is_us(name: str, ours: list[str]) -> bool:
    n = C.norm_name(name)
    return any(C.norm_name(o) in n or n in C.norm_name(o) for o in ours if o)


def counterparty(ps: dict, ours: list[str]) -> dict:
    a_us = any(_is_us(p["name"], ours) for p in ps["甲方"])
    b_us = any(_is_us(p["name"], ours) for p in ps["乙方"])
    side = "乙方" if a_us and not b_us else "甲方"
    occ = [p for p in ps[side] if not _is_us(p["name"], ours)]
    names = [p["name"] for p in occ]
    front = next((p["name"] for p in occ if p["where"] == "首页"), None)
    main = front or (max(names, key=names.count) if names else None)
    return {"side": side, "our_side": "甲方" if side == "乙方" else "乙方", "name": main, "occurrences": occ,
            "identified_us": a_us or b_us}


def first(mats: list[Material], finder) -> dict | None:
    """在材料各页中找第一个命中：finder(text) -> (value, start, end, extra) | None。"""
    for mat in mats:
        for page, text in fpages(mat):
            hit = finder(text)
            if hit:
                value, s, e, extra = hit
                return _fact(value, mat, page, text, s, e, **extra)
    return None


def _amount_finder(kw: str, window: int = 60):
    def f(text):
        a = C.amount_after(text, kw, window)
        return (a.yuan, a.start, a.end, {"raw": a.raw}) if a else None
    return f


def _duration_finder(kw: str):
    def f(text):
        d = C.duration_after(text, kw, 40)
        return (d.days, d.start, d.end, {"raw": d.raw, "unit": d.unit, "approx": d.approx}) if d else None
    return f


def _date_finder(kw: str, window: int = 40):
    def f(text):
        hit = C.date_after(text, kw, window)
        return (hit[0], hit[1], hit[2], {}) if hit else None
    return f


def _regex_finder(pattern: str, group: int = 1):
    def f(text):
        m = re.search(pattern, text)
        return (re.sub(r"\s", "", m.group(group)), m.start(), m.end(), {}) if m else None
    return f


def _tax_rate_finder(text: str):
    m = re.search(r"税率\s*[为是:：]?\s*[【\[（(]?\s*(\d+(?:\.\d+)?)\s*[】\]）)]?\s*[%％]", text)
    return (m.group(1) + "%", m.start(), m.end(), {}) if m else None


_CN_DIGIT = {"一": "1", "二": "2", "三": "3", "四": "4"}


def dispute_choice(text: str) -> str | None:
    """争议解决方式：「最终解决方式为下列第（N）种」按所选项判断为「诉讼」或「仲裁」；未出现选项写法时返回 None。"""
    for m in re.finditer(r"第\s*[（(]?\s*([1-4一二三四])\s*[）)]?\s*种", text):
        if not re.search(r"争议|纠纷", text[max(0, m.start() - 60):m.start()]):
            continue
        n = _CN_DIGIT.get(m.group(1), m.group(1))
        opt = re.search(r"[（(]\s*" + n + r"\s*[）)]([^（(]{0,80})", text[m.end():m.end() + 400])
        if not opt:
            continue
        body = opt.group(1)
        if re.search(r"法院|诉讼", body):
            return "诉讼"
        if "仲裁" in body:
            return "仲裁"
    return None


def last_date(mats: list[Material]) -> dict | None:
    for mat in mats:
        for page, text in reversed(fpages(mat)):
            ds = C.find_dates(text)
            if ds:
                d, s, e = ds[-1]
                return _fact(d, mat, page, text, s, e, approx=True)
    return None


def percentages(text: str) -> list[float]:
    vals = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*[%％]", text or ""):
        vals.append(float(m.group(1)))
    for m in re.finditer(r"百分之([零〇一二两三四五六七八九十百]+)", text or ""):
        v = C.num_word(m.group(1))
        if v is not None:
            vals.append(v)
    return vals


NOT_PAY_RATIO = r"违约|罚款|赔偿|税率|税额|滞纳|取费|费率|系数|下浮|折扣|利率|收费基价"


def _is_pay_sentence(s: str) -> bool:
    if not re.search(PAY_KW, s) or re.search(NOT_PAY_RATIO, s):
        return False
    # 只讲履约保函/保证金额度、没有支付动作的句子（如「递交合同价 5% 的履约保函」）不是付款节点
    return not (re.search(r"保函|(履约|投标)(保证金|担保)", s) and not re.search(r"支付|付款|预付|付至", s))


PAY_VERB = r"支付|付款|付至|预付|拨付|进度款|尾款|结算款|首付|质保金"


def _pay_percentages(sent: str) -> list[float]:
    """句内百分比，剔除描述保函/保证金额度的那几个：PDF 无标点换行常把下一条（如「递交合同价 5% 的履约保函」）并进同一句，
    判据是百分比与其前面最近的支付动作之间出现了履约/投标保函、保证金、担保或「递交」；质量保证金是付款节点，保留。"""
    out = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*[%％]|百分之([零〇一二两三四五六七八九十百]+)", sent):
        window = sent[max(0, m.start() - 40):m.start()]
        verbs = list(re.finditer(PAY_VERB, window))
        tail = window[verbs[-1].end():] if verbs else window
        if re.search(r"保函|(履约|投标)(保证金|担保)|递交", tail):
            continue
        v = float(m.group(1)) if m.group(1) else C.num_word(m.group(2))
        if v is not None:
            out.append(v)
    return out


def payment_percentages(mats: list[Material]) -> dict | None:
    """付款条款中的比例：只取含付款关键词、且不涉及违约/赔偿/税率/取费费率的句子，避免把这些比例当付款比例。
    cumulative 表示合同按「支付至 X%」累计口径约定（各节点比例之和不应为 100%）。"""
    for mat in mats:
        sents = [s for s in re.split(r"[。；;\n]", C.flat(mat.text)) if _is_pay_sentence(s)]
        pcts = [p for s in sents for p in _pay_percentages(s) if 0 < p <= 100]
        if 100 in pcts and abs(sum(pcts) - 200) < 0.01:
            pcts.remove(100)  # 付款里程碑表的「合计 100%」行
        if pcts:
            hit = [s.strip() for s in sents if percentages(s)]
            cumulative = any(re.search(r"(支付|付款|付)至|累计(支付|付款|付)?(至|达到?)", s) for s in hit)
            return {"value": pcts, "file": mat.name, "snippet": "；".join(hit)[:300], "cumulative": cumulative}
    return None


def penalties(mat: Material) -> list[dict]:
    out = []
    for page, text in fpages(mat):
        for m in re.finditer(r"[^。；;\n]*违约金[^。；;\n]*", text):
            sent = m.group(0)
            daily = bool(re.search(r"每日|每天|每延误一天|每逾期一天|按日|日万分之|日千分之|每逾期1日|每延误1日", sent))
            cap = bool(re.search(r"累计|最高|上限|不(应|得)?超过|总额", sent))
            of_total = bool(re.search(r"合同(总)?(价|价款|金额|总价|额)|总价|签约合同价", sent))
            ratios = [p / 100 for p in percentages(sent)]
            for w, base in (("千分之", 1000), ("万分之", 10000)):
                for mm in re.finditer(w + r"([零〇一二两三四五六七八九十]+|\d+(?:\.\d+)?)", sent):
                    v = C.num_word(mm.group(1))
                    if v is not None:
                        ratios.append(v / base)
            if ratios:
                out.append({**_fact(max(ratios), mat, page, text, m.start(), m.end()), "ratios": ratios,
                            "daily": daily, "cap": cap, "of_total": of_total})
    return out


def laws(mat: Material) -> list[dict]:
    out = []
    for page, text in fpages(mat):
        for m in re.finditer(r"《([^《》\n]{2,40})》", text):
            name = re.sub(r"\s", "", m.group(1))
            if not re.search(r"(法|法典|条例)$", name):
                continue
            wrong = None
            core = name.removeprefix("中华人民共和国")
            if name in ABOLISHED_LAWS:
                wrong = "已于 2021 年 1 月 1 日废止"
            elif core != "民法典" and core.startswith("民法") and C.ratio(core, "民法典") >= 0.6:
                wrong = "名称有误"
            out.append({**_fact(name, mat, page, text, m.start(), m.end()), "wrong": wrong})
    return out


_ARB_VERBS = re.compile(r"^(提交|交由|提请|申请|向|由|至|到|在|交|报)+")


def arbitration(mat: Material) -> list[dict]:
    """仲裁机构名称：向前取紧邻的地名（去掉「提交」「向」等动词），地名与「仲裁委员会」之间有「市」即不规范。"""
    out = []
    for page, text in fpages(mat):
        for m in re.finditer(r"(市)?仲裁委员会", text):
            head = re.search(r"[\u4e00-\u9fa5]{1,8}$", text[max(0, m.start() - 8):m.start()])
            place = _ARB_VERBS.sub("", head.group(0)) if head else ""
            place = place[-4:] if len(place) > 4 else place
            if len(place) < 2:
                continue
            name = place + m.group(0)
            out.append({"bad": bool(m.group(1)), "place": place,
                        **_fact(name, mat, page, text, m.start() - len(place), m.end())})
    return out


def standards(mats: list[Material]) -> list[dict]:
    out, seen = [], set()
    for mat in mats:
        for page, text in fpages(mat):
            for m in STANDARD_RE.finditer(text):
                code = f"{m.group(1)} {m.group(2)}-{m.group(3)}"
                if code in seen:
                    continue
                seen.add(code)
                out.append(_fact(code, mat, page, text, m.start(), m.end()))
    return out


def validity(mat: Material) -> tuple[dict | None, dict | None]:
    rx = re.compile(r"有效期[^。\n]{0,20}?自?\s*" + C.DATE_RE + r"\s*(?:起)?\s*[至到—\-~]{1,3}\s*" + C.DATE_RE)
    for page, text in fpages(mat):
        m = rx.search(text)
        if m:
            d1, d2 = C.parse_date("-".join(m.groups()[0:3])), C.parse_date("-".join(m.groups()[3:6]))
            return _fact(d1, mat, page, text, m.start(), m.end()), _fact(d2, mat, page, text, m.start(), m.end())
        hit = C.date_after(text, r"有效期(至|到|截止)", 20)
        if hit:
            return None, _fact(hit[0], mat, page, text, hit[1], hit[2])
    return None, None


def keyword_hits(mat: Material | None, pattern: str, pad: int = 120, limit: int = 6) -> list[dict]:
    if not mat:
        return []
    out = []
    for page, text in fpages(mat):
        for m in re.finditer(pattern, text):
            out.append(_fact(m.group(0), mat, page, text, m.start(), m.end()) | {"context": C.around(text, m.start(), m.end(), pad)})
            if len(out) >= limit:
                return out
    return out


def extract(form: dict, mats: list[Material], cfg: dict) -> dict:
    contract = main_contract(mats)
    awards = by_role(mats, "award_notice")
    bids = by_role(mats, "bid")
    tenders = by_role(mats, "tender_doc")
    ff = form_fields(form, cfg.get("form_fields") or {})
    facts: dict = {"form": ff, "form_raw": form, "contract": contract, "cfg": cfg,
                   "awards": awards, "bids": bids, "tenders": tenders,
                   "appendix_docs": [m for m in by_role(mats, "contract_appendix") if m.readable],
                   "consortium_docs": by_role(mats, "consortium"), "tech_docs": by_role(mats, "tech_agreement"),
                   "auth_docs": by_role(mats, "authorization"), "materials": mats}
    if contract is None:
        return facts
    text = C.flat(contract.text)
    ps = parties(contract)
    facts["parties"] = ps
    facts["counterparty"] = counterparty(ps, cfg.get("our_names") or [])
    facts["price"] = first([contract], _amount_finder(PRICE_KW))
    facts["price_upper"] = []
    for v, raw, s, e in C.cn_amounts(text):
        # 惯常写法「人民币 X 元（大写：…）」：优先取紧挨在大写之前 40 字内的小写金额，其次取之后的
        before = [a for a in C.amounts(text[max(0, s - 40):s])]
        after = [a for a in C.amounts(text[e:e + 40])]
        best = before[-1] if before else (after[0] if after else None)
        facts["price_upper"].append({**_fact(v, contract, None, text, s, e), "raw": raw,
                                     "lower": best.yuan if best else None, "lower_raw": best.raw if best else None})
    facts["tax"] = {"不含税金额": first([contract], _amount_finder(r"不含(增值)?税(金额|价款|价|合同价|总价)?", 40)),
                    "税率": first([contract], _tax_rate_finder),
                    "税额": first([contract], _amount_finder(r"(税额|税金|增值税额)", 40))}
    facts["currency_mix"] = [_fact(m.group(0), contract, page, t, m.start(), m.end())
                             for page, t in fpages(contract)
                             for m in re.finditer(r"[￥¥]\s*[\d,，]+(?:\.\d+)?\s*(?:万)?元", t)]
    facts["arbitration"] = arbitration(contract)
    facts["has_arbitration"] = "仲裁" in text
    facts["dispute_choice"] = dispute_choice(text)
    facts["laws"] = laws(contract)
    facts["sign_date"] = first([contract], _date_finder(r"(签订日期|签署日期|签订时间|签约日期|签订于|本合同于)\s*[:：]?", 30))
    if ff.get("合同签订日期") and C.parse_date(ff["合同签订日期"]["value"]):
        facts["sign_date_form"] = {"value": C.parse_date(ff["合同签订日期"]["value"]), "file": "审批表单",
                                   "snippet": f"{ff['合同签订日期']['label']}：{ff['合同签订日期']['value']}"}
    facts["duration"] = first([contract], _duration_finder(DURATION_KW))
    facts["duration_hits"] = keyword_hits(contract, DURATION_KW + r"[^。；\n]{0,60}", limit=2)
    facts["bid_duration_hits"] = [h for b in bids for h in keyword_hits(b, DURATION_KW + r"[^。；\n]{0,60}", limit=2)][:2]
    facts["start_date"] = first([contract], _date_finder(r"(计划开工日期|开工日期|开始日期|起始日期|服务期自|开始时间)"))
    facts["end_date"] = first([contract], _date_finder(r"(计划竣工日期|竣工日期|完工日期|结束日期|服务期至|完成日期)"))
    facts["valid_from"], facts["valid_to"] = validity(contract)
    facts["penalties"] = penalties(contract)
    facts["liability_text"] = C.keyword_windows(text, SIDE_B + r"[^。\n]{0,12}(违约|赔偿)", pad=400, limit=3000)
    facts["liability_hits"] = keyword_hits(contract, SIDE_B + r"[^。；\n]{0,12}(违约|赔偿)[^。；\n]*")
    facts["cap_hits"] = keyword_hits(contract, CAP_RE)
    facts["liability_formula"] = [
        dict(h, value=re.split(r"\s*\d+(?:\.\d+)+\.?\s*(?=[\u4e00-\u9fa5])", h["value"])[0])
        for h in keyword_hits(contract, r"赔偿(金|金额|额)\s*[=＝][^。；\n]{4,80}", limit=2)]
    facts["reduction_hits"] = keyword_hits(contract, r"核减|减少[^。；\n]{0,8}(合同|价款|金额|合同额)")
    facts["exclusive_hits"] = keyword_hits(contract, r"唯一(合作|供应|服务)?|排他|独家|仅能|只能与|不得与(任何)?(第三方|其他)")
    facts["price_change_hits"] = keyword_hits(contract, r"附加工作|额外(工作|服务)|酬金|价款(的)?调整|合同价款(的)?(调整|变更)|费用调整|变更(费用|价款)")
    facts["payment_contract"] = payment_percentages([contract]) or payment_percentages(facts["appendix_docs"])
    facts["standards"] = standards([contract] + facts["appendix_docs"] + facts["tech_docs"])
    facts["award_price"] = first(awards, _amount_finder(AWARD_PRICE_KW))
    facts["award_duration"] = first(awards, _duration_finder(DURATION_KW))
    facts["award_date"] = first(awards, _date_finder(r"(发出日期|签发日期|发文日期|通知日期)")) or last_date(awards)
    facts["bid_price"] = first(bids, _amount_finder(BID_PRICE_KW))
    facts["bid_duration"] = first(bids, _duration_finder(DURATION_KW))
    facts["payment_bid"] = payment_percentages(bids)
    pay_form = ff.get("付款节点明细")
    facts["payment_form"] = ({"value": [p for p in percentages(pay_form["value"]) if 0 < p <= 100],
                              "file": "审批表单", "snippet": pay_form["value"][:200]} if pay_form else None)
    return facts
