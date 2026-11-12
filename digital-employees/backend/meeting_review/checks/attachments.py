"""05 附件材料：读取状态 + 正文与附件、附件之间关键事实交叉核验（公告日期、评审日期、评审人数、成交金额、成交供应商），
以及正文「附件：」清单列明的材料是否都在 OA 附件中（需求 4 章「附件」字段：核对附件名称、数量）。

只核对文件中确有的内容；必传规则未确认，不按事项类型判定缺少某类附件（需求 5.2）。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from shared.rule_framework import common as C
from shared.rule_framework.engine import issue, missing, ok, review

KEYS = [("announce_date", "公告日期"), ("review_date", "评审日期"), ("reviewers", "评审小组人数"),
        ("result_amount", "成交金额"), ("supplier", "成交供应商")]


def _fmt(key: str, v) -> str:
    if key == "result_amount":
        return C.fmt_wan(v)
    if key == "reviewers":
        return f"{v} 人"
    return str(v)


def _same(key: str, a, b) -> bool:
    if key == "result_amount":
        return abs(float(a) - float(b)) < 0.01
    if key == "supplier":
        x, y = C.norm_name(str(a)), C.norm_name(str(b))
        return x == y or (len(min(x, y, key=len)) >= 6 and (x in y or y in x))
    return a == b


_LIST_HEAD = re.compile(r"(?:^|\n)\s*附\s*件\s*[:：]")
_ITEM_NO = re.compile(r"(?:^|\s)(?:\d{1,2}|[一二三四五六七八九十]{1,2})\s*[.、．]\s*")
_EXT = re.compile(r"\.(pdf|docx?|xlsx?|zip|rar|7z|jpe?g|png|ofd)$", re.I)
_NAME_NOISE = re.compile(r"[\s《》“”\"'（）()\[\]【】、，,。.．:：;；_\-—]")
_SIGN_LINE = re.compile(r".{0,20}(部|院|中心|公司|办公室|委员会)|\d{4}\s*年.{0,8}日")


def declared_list(body) -> tuple[list[str], dict | None]:
    """正文末尾「附件：1.xx 2.xx」列明的材料名称及出处；没有清单时返回空。"""
    for page, text in reversed(body.pages if body else []):
        heads = list(_LIST_HEAD.finditer(text))
        if not heads:
            continue
        m = heads[-1]
        lines = []
        for ln in text[m.end():m.end() + 800].split("\n"):
            s = ln.strip()
            if lines and (not s or (not _ITEM_NO.match(" " + s) and _SIGN_LINE.fullmatch(s))):
                break  # 清单后的空行或落款（部门、日期）
            if s:
                lines.append(s)
        items = [x.strip() for x in _ITEM_NO.split(" " + " ".join(lines)) if x.strip()]
        items = [x for x in items if 2 <= len(x) <= 40]
        if items:
            return items, C.ev(body.name, page, C.around(text, m.start(), m.end() + 120), label="正文·附件清单")
    return [], None


def _norm(name: str) -> str:
    n = re.sub(r"^\s*(?:\d{1,2}|[一二三四五六七八九十]{1,2})\s*[.、．]\s*", "", name.rsplit("/", 1)[-1].strip())
    return _NAME_NOISE.sub("", _EXT.sub("", n))


def _provided(item: str, names: list[str]) -> bool:
    a = _norm(item)
    for n in names:
        b = _norm(n)
        if a and b and (a in b or b in a or SequenceMatcher(None, a, b).ratio() >= 0.75):
            return True
    return False


def check(f):
    atts = f.get("attachments") or []
    if not atts:
        return missing("待补充：除请示正文外未读取到附件材料。")
    problems, notes, ev = [], [], []
    items, list_ev = declared_list(f.get("body"))
    absent = [x for x in items if not _provided(x, [m.name for m in f.get("materials") or atts])]
    if absent:
        problems.append(f"正文附件清单列明 {len(items)} 份材料，OA 附件中未找到 {len(absent)} 份：" + "、".join(absent))
        ev.append(list_ev)
    for m in atts:
        if not m.readable:
            notes.append(f"《{m.name}》无法读取或未识别出文字，未完成内容比对")
    bf = f.get("body_facts") or {}
    af = f.get("att_facts") or {}
    compared = 0
    for key, label in KEYS:
        b = bf.get(key)
        vals = [(name, facts[key]) for name, facts in af.items() if facts.get(key)]
        for name, v in vals:
            if b:
                compared += 1
                if not _same(key, b["value"], v["value"]):
                    problems.append(f"正文所述{label}（{_fmt(key, b['value'])}）与《{name}》记载（{_fmt(key, v['value'])}）不一致")
                    ev.append(C.ev(b["file"], b.get("page"), b["snippet"], label=f"正文·{label}"))
                    ev.append(C.ev(v["file"], v.get("page"), v["snippet"], label=f"附件·{label}"))
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                (n1, v1), (n2, v2) = vals[i], vals[j]
                compared += 1
                if not _same(key, v1["value"], v2["value"]) and not b:
                    problems.append(f"《{n1}》与《{n2}》记载的{label}不一致（{_fmt(key, v1['value'])} / {_fmt(key, v2['value'])}）")
                    ev.append(C.ev(v1["file"], v1.get("page"), v1["snippet"], label=label))
                    ev.append(C.ev(v2["file"], v2.get("page"), v2["snippet"], label=label))
    readable = [m for m in atts if m.readable]
    if problems:
        return issue(f"发现问题：已比对附件 {len(readable)} 份，发现 {len(problems)} 处不一致。", ev, problems + notes)
    if notes or not compared:
        reason = notes + ([] if compared else ["正文与附件之间没有可比对的公告日期、评审信息、成交金额或供应商"])
        return review(f"待人工复核：已读取附件 {len(readable)}/{len(atts)} 份。" + "；".join(reason) + "。", ev, reason)
    return ok(f"核查通过：已比对附件 {len(readable)} 份、{compared} 组关键事实，正文与附件记载一致。", ev)
