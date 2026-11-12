"""通用判断工具：金额（含中文大写）、日期、期限、连号、名称相似度、原文片段。

所有抽取函数都返回原文位置，便于把证据定位回文件。
"""
from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass
from datetime import date

# ---------------------------------------------------------------- 原文片段

def around(text: str, start: int, end: int, pad: int = 40) -> str:
    s = max(0, start - pad)
    return re.sub(r"\s+", " ", text[s:end + pad]).strip()


def ev(file: str = "", page=None, snippet: str = "", **kw) -> dict:
    out = {"file": file, "page": page, "snippet": snippet}
    out.update({k: v for k, v in kw.items() if v is not None})
    return {k: v for k, v in out.items() if v not in (None, "")}


# ---------------------------------------------------------------- 金额

NUM = r"\d{1,3}(?:[,，]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_AMOUNT = re.compile(rf"(?P<cur>[￥¥]|人民币|RMB)?\s*(?P<num>{NUM})\s*(?P<unit>亿元|万元|元|亿|万)?")
_UNIT = {"元": 1, "万元": 1e4, "万": 1e4, "亿元": 1e8, "亿": 1e8}


@dataclass
class Amount:
    yuan: float
    raw: str
    start: int
    end: int
    unit: str
    symbol: bool


def to_number(s: str) -> float | None:
    try:
        return float(str(s).replace(",", "").replace("，", "").strip())
    except (TypeError, ValueError):
        return None


def amounts(text: str, require_unit: bool = True) -> list[Amount]:
    """文本中的金额；默认只认带货币单位或货币符号的数字（避免把编号、日期当金额）。"""
    out = []
    for m in _AMOUNT.finditer(text or ""):
        unit, cur = m.group("unit") or "", m.group("cur") or ""
        if require_unit and not unit and not cur:
            continue
        v = to_number(m.group("num"))
        if v is None:
            continue
        out.append(Amount(round(v * _UNIT.get(unit or "元", 1), 2), m.group(0).strip(), m.start(), m.end(),
                          unit or "元", bool(cur and cur != "人民币")))
    return out


def amount_after(text: str, keywords: str, window: int = 80) -> Amount | None:
    """关键词之后 window 字内的第一个金额，如「合同价款」「中标价」「投标报价」。"""
    for m in re.finditer(keywords, text or ""):
        seg = text[m.end():m.end() + window]
        for a in amounts(seg):
            return Amount(a.yuan, a.raw, m.end() + a.start, m.end() + a.end, a.unit, a.symbol)
    return None


_CN_DIGIT = {"零": 0, "〇": 0, "壹": 1, "一": 1, "贰": 2, "二": 2, "两": 2, "叁": 3, "参": 3, "三": 3,
             "肆": 4, "四": 4, "伍": 5, "五": 5, "陆": 6, "六": 6, "柒": 7, "七": 7, "捌": 8, "八": 8,
             "玖": 9, "九": 9}
_CN_UNIT = {"拾": 10, "十": 10, "佰": 100, "百": 100, "仟": 1000, "千": 1000}
_CN_CH = "零壹贰叁肆伍陆柒捌玖拾佰仟万亿圆元角分整正"
CN_UPPER_RE = re.compile(rf"[{_CN_CH}](?:\s*[{_CN_CH}])+")  # 允许 PDF 换行/空格把大写金额拆开


def _cn_int(s: str) -> int:
    total, section, number = 0, 0, 0
    for ch in s:
        if ch in _CN_DIGIT:
            number = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            section += (number or 1) * _CN_UNIT[ch]
            number = 0
        elif ch == "万":
            total += (section + number) * 10 ** 4
            section = number = 0
        elif ch == "亿":
            total = (total + section + number) * 10 ** 8
            section = number = 0
    return total + section + number


def cn_amount(s: str) -> float | None:
    """中文大写金额 → 元，如「壹佰贰拾叁万肆仟伍佰陆拾柒元捌角玖分」→ 1234567.89。"""
    s = re.sub(r"[\s人民币大写：:（）()]", "", s or "")
    if not s or not re.search(r"[壹贰叁肆伍陆柒捌玖拾佰仟]", s):
        return None
    m = re.match(r"^([^元圆]*)[元圆]?(.*)$", s)
    integer, rest = m.group(1), m.group(2)
    value = float(_cn_int(integer)) if integer else 0.0
    jiao = re.search(r"([零壹贰叁肆伍陆柒捌玖一二三四五六七八九])角", rest)
    fen = re.search(r"([零壹贰叁肆伍陆柒捌玖一二三四五六七八九])分", rest)
    if jiao:
        value += _CN_DIGIT[jiao.group(1)] * 0.1
    if fen:
        value += _CN_DIGIT[fen.group(1)] * 0.01
    return round(value, 2)


def cn_amounts(text: str) -> list[tuple[float, str, int, int]]:
    out = []
    for m in CN_UPPER_RE.finditer(text or ""):
        raw = re.sub(r"\s", "", m.group(0))
        v = cn_amount(raw)
        if v is not None and v > 0:
            out.append((v, raw, m.start(), m.end()))
    return out


def flat(text: str) -> str:
    """去掉 PDF 硬换行（中文按句抽取前使用）：行尾不是句末标点时与下一行直接相连。"""
    return re.sub(r"(?<![。；;：:！？!?])[ \t]*\n[ \t]*", "", text or "")


def fmt_yuan(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f} 元"


def fmt_wan(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v / 1e4:,.2f} 万元"


# ---------------------------------------------------------------- 日期与期限

DATE_RE = r"(20\d{2})\s*[年\-./]\s*(\d{1,2})\s*[月\-./]\s*(\d{1,2})\s*日?"
_DATE = re.compile(DATE_RE)


def parse_date(s) -> date | None:
    if isinstance(s, date):
        return s
    m = _DATE.search(str(s or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def find_dates(text: str) -> list[tuple[date, int, int]]:
    out = []
    for m in _DATE.finditer(text or ""):
        try:
            out.append((date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.start(), m.end()))
        except ValueError:
            continue
    return out


def date_after(text: str, keywords: str, window: int = 40) -> tuple[date, int, int] | None:
    for m in re.finditer(keywords, text or ""):
        for d, s, e in find_dates(text[m.end():m.end() + window]):
            return d, m.end() + s, m.end() + e
    return None


_CN_NUM_WORD = re.compile(r"[零〇一二两三四五六七八九十百千]+")


def num_word(s: str) -> float | None:
    """阿拉伯数字或中文小写数字（「十二」「三百」）→ 数值。"""
    v = to_number(s)
    if v is not None:
        return v
    if _CN_NUM_WORD.fullmatch(s or ""):
        return float(_cn_int(s))
    return None


_num_word = num_word


DURATION_RE = re.compile(r"(\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千]+)\s*(个?日历天|个?工作日|天|日|个月|个?月|年)")


@dataclass
class Duration:
    value: float
    unit: str
    days: float
    raw: str
    start: int
    end: int
    approx: bool


def duration_after(text: str, keywords: str, window: int = 40) -> Duration | None:
    """关键词后直接给出的期限：「工期：120日历天」「服务期限为12个月」「总工期 90 天」。
    月按 30 天、年按 365 天折算（approx=True）。关键词与数字之间只允许「为/是/：/共/总计/约」等连接词，
    「收到通知后3天内进场」「完工后180天」这类相对时间不算工期。"""
    for m in re.finditer(keywords, text or ""):
        seg = text[m.end():m.end() + window]
        d = DURATION_RE.search(seg)
        if not d:
            continue
        gap = re.sub(r"[\s:：（）()]", "", seg[:d.start()])
        if not re.fullmatch(r"(为|是|共|总|总计|合计|约|暂定|计划|不超过|应为|共计|工期|期限|服务期)*", gap):
            continue
        tail = seg[d.end():d.end() + 4]
        if re.match(r"\s*(内|之内|以内)?(进场|开工|提交|完成|后)", tail):
            continue
        v = _num_word(d.group(1))
        if v is None:
            continue
        unit = d.group(2).lstrip("个")
        factor, approx = (30, True) if unit in ("月",) else (365, True) if unit == "年" else (1, False)
        if unit == "工作日":
            approx = True
        return Duration(v, unit, v * factor, d.group(0), m.end() + d.start(), m.end() + d.end(), approx)
    return None


def ceil_div(a: float, b: float) -> int:
    return int(math.ceil(a / b))


# ---------------------------------------------------------------- 连号

def consecutive_groups(numbers: list[str]) -> list[list[str]]:
    """号码连续（同位数、数值相差 1）的分组，长度 ≥2 才返回；重复号码只计一次。"""
    clean = sorted({re.sub(r"\D", "", str(n)) for n in numbers if n and re.sub(r"\D", "", str(n))},
                   key=lambda x: (len(x), int(x)))
    groups, cur = [], []
    for n in clean:
        if cur and len(n) == len(cur[-1]) and int(n) - int(cur[-1]) == 1:
            cur.append(n)
        else:
            if len(cur) >= 2:
                groups.append(cur)
            cur = [n]
    if len(cur) >= 2:
        groups.append(cur)
    return groups


# ---------------------------------------------------------------- 名称与相似度

def norm_name(s: str) -> str:
    s = (s or "").replace("（", "(").replace("）", ")")
    return re.sub(r"[\s\u3000·•,，。、；;：:\"“”'‘’《》【】\[\]]", "", s)


def ratio(a: str, b: str) -> float:
    a, b = norm_name(a), norm_name(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def bigrams(s: str) -> set[str]:
    s = norm_name(s)
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else ({s} if s else set())


def jaccard(a: str, b: str) -> float:
    x, y = bigrams(a), bigrams(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def contains_any(text: str, words) -> list[str]:
    return [w for w in words if w and w in (text or "")]


def section_text(text: str, title: str, max_len: int = 3500) -> str:
    """按编号章节截取：「13. 违约责任 …」截到「14. 」之前；目录里的同名条目很短，取最长的一段。"""
    best = ""
    for m in re.finditer(rf"(?<![\d.．])(\d{{1,2}})\s*[．.、]\s*(?:{title})", text or ""):
        n = int(m.group(1))
        nxt = re.search(rf"(?<![\d.．]){n + 1}\s*[．.、]\s*[\u4e00-\u9fa5]", text[m.end():])
        end = m.end() + nxt.start() if nxt else min(len(text), m.end() + max_len)
        seg = text[m.start():end]
        if len(seg) > len(best):
            best = seg
    return best[:max_len].strip()


def keyword_windows(text: str, pattern: str, pad: int = 300, limit: int = 4000) -> str:
    """按关键词截取上下文窗口，用于把相关条款送给模型（控制长度）。

    长文档（投标文件动辄上百页）里关键词首次出现的位置常是目录或无关段落，因此按窗口内关键词密度排序挑选，
    目录页（「……」或连续页码）降权；入选窗口再按原文顺序拼接。"""
    text = text or ""
    spans = []
    for m in re.finditer(pattern, text):
        s, e = max(0, m.start() - pad), min(len(text), m.end() + pad)
        if spans and s <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], e))
        else:
            spans.append((s, e))
    if not spans:
        return ""

    def score(span):
        chunk = text[span[0]:span[1]]
        hits = len(re.findall(pattern, chunk))
        toc = len(re.findall(r"\.{4,}|…{2,}|·{4,}", chunk)) + len(re.findall(r"\n\s*\d{1,3}\s*\n", chunk)) \
            + 0.3 * len(re.findall(r"\d{1,2}\s*[．.、]\s*[\u4e00-\u9fa5]{2,10}(?=\s*\d{1,2}\s*[．.、])", chunk))
        return hits / max(1, len(chunk) / 500) - toc * 0.5

    ranked = sorted(spans, key=score, reverse=True)
    chosen, total = [], 0
    for s, e in ranked:
        n = min(e - s, max(0, limit - total))
        if n <= 0:
            break
        chosen.append((s, s + n))
        total += n
    return "\n……\n".join(text[s:e].strip() for s, e in sorted(chosen) if text[s:e].strip())
