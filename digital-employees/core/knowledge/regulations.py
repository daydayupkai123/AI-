"""制度 PDF → 条款（Clause）。

权责手册：每页一张大表，列数随页变化（20–23 列），按每页表头动态对列；
  单元格中 ①②③ 为流转顺序、● 为备案、红色为审批/决策（最终审批主体），按坐标把红色字符对到列上；
  合并单元格（无 bbox）表示沿用上一行：分类/具体描述/制度依据/责任部门/备注始终沿用，档位只在同一事项内沿用。
重大经营管理事项清单：√ 为决策主体，▲ 前置研究，↑ 研究拟订。
党委决定的重大事项清单：决策主体为党委会。
董事会授权决策方案：授权董事长事项 → 董事长专题会；授权总经理事项 → 总经理办公会（方案第五条第一款）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PARSER_VER = "1"
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


@dataclass
class Clause:
    doc_id: str
    doc_name: str
    ref: str
    no: int | None
    title: str
    dept: str = ""
    category: str = ""
    sub: str = ""
    tier: str = ""
    variant: str = ""
    range: dict | None = None
    steps: list = field(default_factory=list)
    final: list = field(default_factory=list)
    meetings: list = field(default_factory=list)
    basis: str = ""
    owner: str = ""
    note: str = ""
    major: str = ""
    page: int | None = None

    @property
    def text(self) -> str:
        return " ".join(x for x in (self.category, self.title, self.sub, self.tier, self.note) if x)

    def describe(self) -> str:
        parts = [f"《{self.doc_name}》{self.ref}「{self.title}{('·' + self.sub) if self.sub else ''}」"]
        if self.tier:
            parts.append(f"档位：{self.tier}")
        if self.final:
            parts.append(f"审批/决策主体：{'、'.join(self.final)}")
        return "；".join(parts)


def clean(s) -> str:
    s = re.sub(r"\s+", "", str(s or ""))
    return s.replace("（", "(").replace("）", ")")


# ---------------------------------------------------------------- 金额档位

_NUMU = r"(\d+(?:\.\d+)?)\s*(亿元|万元|元|亿|万)?"
_UNIT = {"亿元": 1e8, "亿": 1e8, "万元": 1e4, "万": 1e4, "元": 1}


def _yuan(num: str, unit: str | None, fallback: str | None) -> float:
    return float(num) * _UNIT.get(unit or fallback or "", 0)


def parse_range(text: str) -> dict | None:
    """金额条件 → {lo, lo_incl, hi, hi_incl}（元）；没有金额或无法判断方向返回 None。

    支持：≥30万元、＜10万元、10(含)-30万元、500万元(含)-1000万元、20万元以下、
          100万元＜单笔金额≤300万、500万元≤涉案金额＜1000万元、金额＞100万元。
    """
    s = clean(text).replace("＜", "<").replace("＞", ">").replace("≦", "≤").replace("≧", "≥")
    s = s.replace("<=", "≤").replace(">=", "≥")
    s = re.sub(r"(万元|元|万)\d$", r"\1", s)  # 去掉上标备注号「≥100万元1」
    if not re.search(r"\d\s*(亿元|万元|元|亿|万)", s):
        return None
    r: dict = {}
    m = re.search(_NUMU + r"(\(含\))?[-—~～至]" + _NUMU + r"(\(含\))?", s)
    if m:
        unit = m.group(5) or m.group(2)
        lo, hi = _yuan(m.group(1), m.group(2), unit), _yuan(m.group(4), m.group(5), unit)
        if lo and hi:
            return {"lo": lo, "lo_incl": bool(m.group(3)) or not m.group(6), "hi": hi, "hi_incl": bool(m.group(6))}
    m = re.search(_NUMU + r"(≤|<)[^\d≤<]{0,8}(≤|<)" + _NUMU, s)
    if m:
        unit = m.group(6) or m.group(2)
        return {"lo": _yuan(m.group(1), m.group(2), unit), "lo_incl": m.group(3) == "≤",
                "hi": _yuan(m.group(5), m.group(6), unit), "hi_incl": m.group(4) == "≤"}
    for m in re.finditer(r"(≥|>|大于等于|不低于|大于|超过)" + _NUMU, s):
        r.update(lo=_yuan(m.group(2), m.group(3), "万元"), lo_incl=m.group(1) in ("≥", "大于等于", "不低于"))
    for m in re.finditer(r"(≤|<|小于等于|不超过|小于|低于|不足)" + _NUMU, s):
        r.update(hi=_yuan(m.group(2), m.group(3), "万元"), hi_incl=m.group(1) in ("≤", "小于等于", "不超过"))
    m = re.search(_NUMU + r"(\(含\))?以上", s)
    if m and m.group(2) and "lo" not in r:
        r.update(lo=_yuan(m.group(1), m.group(2), None), lo_incl=True)
    m = re.search(_NUMU + r"(\(含\))?以下(\(含\))?", s)
    if m and m.group(2) and "hi" not in r:
        r.update(hi=_yuan(m.group(1), m.group(2), None), hi_incl=bool(m.group(3) or m.group(4)))
    return r or None


def in_range(rng: dict | None, yuan: float) -> bool | None:
    if not rng:
        return None
    if "lo" in rng and (yuan < rng["lo"] or (yuan == rng["lo"] and not rng.get("lo_incl", True))):
        return False
    if "hi" in rng and (yuan > rng["hi"] or (yuan == rng["hi"] and not rng.get("hi_incl", False))):
        return False
    return True


def describe_range(rng: dict | None) -> str:
    if not rng:
        return ""
    w = lambda v: f"{v / 1e4:g}万元"  # noqa: E731
    parts = []
    if "lo" in rng:
        parts.append(f"{'≥' if rng.get('lo_incl', True) else '>'}{w(rng['lo'])}")
    if "hi" in rng:
        parts.append(f"{'≤' if rng.get('hi_incl') else '<'}{w(rng['hi'])}")
    return " 且 ".join(parts)


# ---------------------------------------------------------------- 审批主体 → 会议类型

def meeting_of(subject: str) -> str:
    s = clean(subject)
    if "办公会" in s:
        return "总经理办公会"
    if "董事长" in s and "专题会" in s:
        return "董事长专题会"
    if s.startswith("党委会") or s == "党委会":
        return "党委会"
    if s == "董事会":
        return "董事会"
    if s == "纪委会":
        return "纪委会"
    if s == "专题会":
        return "专题会"
    return "不上会（签批）"


def _is_red(color: int) -> bool:
    return ((color >> 16) & 255) >= 200 and ((color >> 8) & 255) <= 90 and (color & 255) <= 90


def _red_points(page) -> list[tuple[float, float]]:
    pts = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                if sp["text"].strip() and _is_red(sp["color"]):
                    x0, y0, x1, y1 = sp["bbox"]
                    pts.append(((x0 + x1) / 2, (y0 + y1) / 2))
    return pts


def _inside(pt, bbox) -> bool:
    return bbox is not None and bbox[0] <= pt[0] <= bbox[2] and bbox[1] <= pt[1] <= bbox[3]


def _page_chars(page) -> list[tuple[float, float, str, float]]:
    """页面全部字符 (cx, cy, 字符, 字高)；表格抽取的单元格文字标点错位，按坐标重排可还原阅读顺序。"""
    out = []
    for b in page.get_text("rawdict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                for ch in sp["chars"]:
                    x0, y0, x1, y1 = ch["bbox"]
                    out.append(((x0 + x1) / 2, (y0 + y1) / 2, ch["c"], y1 - y0))
    return out


def _cell_text(chars, bbox, fallback: str = "") -> str:
    if bbox is None:
        return clean(fallback)
    inside = sorted(((cy, cx, c, h) for cx, cy, c, h in chars
                     if bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]), key=lambda x: (x[0], x[1]))
    if not inside:
        return clean(fallback)
    lines, cur, base = [], [], None
    for cy, cx, c, h in inside:
        if base is not None and abs(cy - base) > max(3.0, h * 0.6):
            lines.append(cur)
            cur, base = [], None
        cur.append((cx, c))
        base = cy if base is None else base
    lines.append(cur)
    return clean("".join("".join(c for _, c in sorted(ln)) for ln in lines))


def _marks(text: str) -> list[int]:
    return [CIRCLED.index(ch) + 1 for ch in text if ch in CIRCLED]


# ---------------------------------------------------------------- 权责手册

_DESC_COLS = ("分类", "具体描述")
_INHERIT_ALWAYS = ("分类", "具体描述", "参考制度依据", "责任部门", "备注", "是否三重一大事项")


def _header_names(row0: list, row1: list) -> list[str]:
    names, top = [], ""
    for c in range(len(row0)):
        t0, t1 = clean(row0[c]), clean(row1[c]) if c < len(row1) else ""
        if t0:
            top = t0
        if top == "职权事项":
            if t1:
                names.append(t1)
            else:
                names.append("续")
        elif top in ("总经理", "董事长"):
            names.append(top + (t1 or ""))
        else:
            names.append(top if t0 else (top + (t1 or "")) if t1 else top + "续")
    # 具体描述之后的续列：最后一个为「档位」，之前的为「子项」
    cont = [i for i, n in enumerate(names) if n == "续"]
    for k, i in enumerate(cont):
        names[i] = "档位" if k == len(cont) - 1 else "子项"
    return names


def parse_authority_manual(data: bytes, doc_id: str, doc_name: str) -> tuple[list[Clause], list[str]]:
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    clauses, warns = [], []
    prev: dict = {}
    pending: list[dict] = []  # 序号写在合并单元格最后一行时，前面无序号的行先挂起，归入随后出现的序号
    dept = ""

    def emit(cur: dict, page_no: int) -> None:
        tier, sub = cur["档位"], cur["子项"]
        if not tier and sub and parse_range(sub):
            tier, sub = sub, ""
        steps = cur["_steps"]
        final = [s["subject"] for s in steps if s["red"]]
        variant = "经营单位发起" if any(s["subject"] == "经营单位" and "①" in s["mark"] for s in steps) else ""
        clauses.append(Clause(
            doc_id=doc_id, doc_name=doc_name, ref=f"{dept}第{cur['序号']}项", no=int(cur["序号"]),
            title=cur["具体描述"], dept=dept, category=cur["分类"], sub=sub, tier=tier, variant=variant,
            range=parse_range(tier) or parse_range(sub) or parse_range(cur["具体描述"]), steps=steps, final=final,
            meetings=sorted({meeting_of(x) for x in final}), basis=cur["参考制度依据"], owner=cur["责任部门"],
            note=cur["备注"], major=cur["是否三重一大事项"], page=page_no))

    for pi, page in enumerate(doc):
        m = re.search(r"权责手册（(.+?)）", page.get_text())
        if not m:
            continue
        if m.group(1) != dept:
            dept, prev, pending = m.group(1), {}, []
        tabs = page.find_tables().tables
        if not tabs:
            warns.append(f"第{pi + 1}页未识别出表格")
            continue
        t = max(tabs, key=lambda x: x.row_count * x.col_count)
        rows = t.extract()
        if len(rows) < 3:
            continue
        names = _header_names(rows[0], rows[1])
        try:
            first = names.index("是否三重一大事项")
            last = names.index("参考制度依据")
        except ValueError:
            warns.append(f"第{pi + 1}页表头无法识别：{names}")
            continue
        subjects = range(first + 1, last)
        reds = _red_points(page)
        chars = _page_chars(page)
        idx = {n: i for i, n in reversed(list(enumerate(names)))}
        for ri in range(2, len(rows)):
            row, bboxes = rows[ri], t.rows[ri].cells
            merged = {i: bboxes[i] is None for i in range(len(names))}
            raw = {i: clean(row[i]) for i in range(len(names))}
            if not any(raw.values()):
                continue
            no_i = idx.get("序号")
            no_txt = raw[no_i] if no_i is not None else ""
            new_item = no_i is not None and not merged[no_i] and bool(re.fullmatch(r"\d+", no_txt or ""))
            orphan = no_i is not None and not merged[no_i] and not no_txt
            cur: dict = {}
            for name in ("分类", "序号", "具体描述", "子项", "档位", "是否三重一大事项", "参考制度依据", "责任部门", "备注"):
                i = idx.get(name)
                if i is None:
                    cur[name] = ""
                    continue
                v = raw[i] if name in ("序号", "是否三重一大事项") else _cell_text(chars, bboxes[i], raw[i])
                if merged[i] and not v:
                    base = pending[-1] if pending else prev
                    if name in _INHERIT_ALWAYS or (not new_item and name in ("序号", "子项", "档位")):
                        v = base.get(name, "")
                cur[name] = v
            steps = []
            for i in subjects:
                txt = raw[i]
                if not txt or merged[i]:
                    continue
                red = any(_inside(p, bboxes[i]) for p in reds)
                steps.append({"subject": names[i], "mark": txt, "order": (_marks(txt) or [None])[0], "red": red})
            cur["_steps"] = steps
            if orphan or (pending and merged.get(no_i, False)):
                pending.append(cur)
                continue
            if new_item and pending:
                parts: list[str] = []
                for p in pending:
                    d = p["具体描述"]
                    if d and d not in parts and d not in cur["具体描述"]:
                        parts.append(d)
                title = "".join(parts) + cur["具体描述"]
                for p in pending:
                    emit({**p, "序号": cur["序号"], "分类": cur["分类"] or p["分类"], "具体描述": title}, pi + 1)
                cur["具体描述"] = title
                pending = []
            if not cur["序号"] or not re.fullmatch(r"\d+", cur["序号"]):
                warns.append(f"第{pi + 1}页第{ri + 1}行缺少序号，已跳过：{list(raw.values())[:4]}")
                continue
            emit(cur, pi + 1)
            prev = cur
        if pending:
            warns.append(f"第{pi + 1}页末尾有 {len(pending)} 行无法归属序号，已跳过")
            pending = []
    return clauses, warns


# ---------------------------------------------------------------- 重大经营管理事项清单

def _list_header(rows: list[list]) -> tuple[int, list[str]]:
    """找到含「事项名称」的表头行，与下一行（主体名称）合并成列名。"""
    for hi, row in enumerate(rows[:4]):
        if any("事项名称" in clean(c) for c in row):
            nxt = rows[hi + 1] if hi + 1 < len(rows) else [None] * len(row)
            names, top = [], ""
            for c in range(len(row)):
                t0, t1 = clean(row[c]), clean(nxt[c]) if c < len(nxt) else ""
                if t0:
                    top = t0
                names.append(t1 or (top if t0 else top + "续"))
            body = hi + 2 if any(clean(x) for x in nxt) and not re.fullmatch(r"\d+", clean(nxt[1] or "")) else hi + 1
            return body, names
    return -1, []


def parse_major_items(data: bytes, doc_id: str, doc_name: str) -> tuple[list[Clause], list[str]]:
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    clauses, warns, category = [], [], ""
    for pi, page in enumerate(doc):
        chars = _page_chars(page)
        for t in page.find_tables().tables:
            rows = t.extract()
            body, names = _list_header(rows)
            if body < 0:
                continue
            idx = {n: i for i, n in reversed(list(enumerate(names)))}
            subj = [i for i, n in enumerate(names) if any(k in n for k in ("办公会", "党委会", "董事会", "专题会"))]
            for ri in range(body, len(rows)):
                row, bboxes = rows[ri], t.rows[ri].cells
                cells = {n: _cell_text(chars, bboxes[i], row[i]) for n, i in idx.items()}
                if cells.get("分类"):
                    category = cells["分类"]
                no = cells.get("项号") or cells.get("序号") or ""
                if not re.fullmatch(r"\d+", no):
                    continue
                steps, final = [], []
                for i in subj:
                    txt = clean(row[i])
                    if txt:
                        steps.append({"subject": names[i], "mark": txt, "order": (_marks(txt) or [None])[0],
                                      "red": "√" in txt})
                        if "√" in txt:
                            final.append(names[i])
                title = cells.get("事项名称", "")
                clauses.append(Clause(doc_id=doc_id, doc_name=doc_name, ref=f"第{no}项", no=int(no), title=title,
                                      category=category, range=parse_range(title), steps=steps, final=final,
                                      meetings=sorted({meeting_of(x) for x in final}), owner=cells.get("责任部门", ""),
                                      note=cells.get("备注", ""), page=pi + 1))
    if not clauses:
        warns.append("未解析出任何事项")
    return clauses, warns


def parse_party_items(data: bytes, doc_id: str, doc_name: str) -> tuple[list[Clause], list[str]]:
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    clauses, warns, category = [], [], ""
    for pi, page in enumerate(doc):
        chars = _page_chars(page)
        for t in page.find_tables().tables:
            rows = t.extract()
            for ri, row in enumerate(rows):
                cells = [_cell_text(chars, t.rows[ri].cells[i], c) for i, c in enumerate(row)]
                if len(cells) < 3:
                    continue
                if cells[0] and not cells[0].startswith(("事项类型", "分类")):
                    category = cells[0]
                if not re.fullmatch(r"\d+", cells[1] or ""):
                    continue
                clauses.append(Clause(doc_id=doc_id, doc_name=doc_name, ref=f"第{cells[1]}项", no=int(cells[1]),
                                      title=cells[2], category=category, final=["党委会"], meetings=["党委会"],
                                      owner=cells[3] if len(cells) > 3 else "", range=parse_range(cells[2]),
                                      page=pi + 1))
    if not clauses:
        warns.append("未解析出任何事项")
    return clauses, warns


def parse_board_authorization(data: bytes, doc_id: str, doc_name: str) -> tuple[list[Clause], list[str]]:
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = [(i + 1, p.get_text()) for i, p in enumerate(doc)]
    text = "\n".join(re.sub(r"—\s*\d+\s*—", "", t) for _, t in pages)
    m = re.search(r"三、授权内容([\s\S]*?)四、", text)
    if not m:
        return [], ["未找到「三、授权内容」"]
    clauses = []
    for sec in re.finditer(r"（([一二三四五])）授权[^\n]*?(董事长|总经理)[^\n]*\n([\s\S]*?)(?=（[一二三四五]）授权|\Z)",
                           m.group(1)):
        who = sec.group(2)
        meeting = "董事长专题会" if who == "董事长" else "总经理办公会"
        for item in re.finditer(r"(?m)^\s*(\d+)\.([\s\S]*?)(?=^\s*\d+\.|\Z)", sec.group(3)):
            title = re.sub(r"\s+", "", item.group(2))
            page = next((no for no, t in pages if title[:8] in re.sub(r"\s+", "", t)), None)
            clauses.append(Clause(doc_id=doc_id, doc_name=doc_name, ref=f"三（{sec.group(1)}）第{item.group(1)}项",
                                  no=int(item.group(1)), title=title, category=f"授权{who}决策事项",
                                  final=[meeting], meetings=[meeting], range=parse_range(title), page=page,
                                  note=f"董事会授权{who}决策；按方案第五条第一款应召开{'专题会' if who == '董事长' else '总经理办公会'}集体研究"))
    return clauses, [] if clauses else ["未解析出任何授权事项"]


PARSERS = {"authority_manual": parse_authority_manual, "major_items": parse_major_items,
           "party_items": parse_party_items, "board_authorization": parse_board_authorization}
