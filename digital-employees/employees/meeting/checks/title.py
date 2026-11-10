"""01 标题与附件关联性：附件内容包含标题所述项目名称 → 关联明确；其余交模型判断（相关 / 冲突 / 无法确认）。

相似度只用于发现可能相关的材料，不单独作为通过依据（需求 6.1）。
"""
from __future__ import annotations

from core.rules import common as C
from core.rules.engine import issue, missing, ok, review
from core.rules.semantic import quote_found

from .. import prompts


def _contains_core(core: str, text: str) -> bool:
    c, t = C.norm_name(core), C.norm_name(text)
    if len(c) < 4:
        return False
    if c in t:
        return True
    size = min(10, max(6, len(c) // 2))
    return any(c[i:i + size] in t for i in range(0, len(c) - size + 1))


def check(f):
    title, core = f.get("title"), f.get("title_core")
    atts = f.get("attachments") or []
    if not title:
        return missing("OA 表单未填写标题。")
    if not atts and not f.get("body"):
        return missing("未读取到请示正文或任何附件，无法核验标题与附件的关联性。")
    judge = f["_judge"]
    clear, unsure, conflict, ev = [], [], [], []
    docs = ([f["body"]] if f.get("body") else []) + atts
    for m in docs:
        if not m.readable:
            unsure.append(f"{m.name}：文件无法读取或未识别出文字")
            continue
        head = m.text[:2000]
        if _contains_core(core, m.name + "\n" + head):
            clear.append(m.name)
            continue
        res = judge(f"meeting.N01:{m.name}", prompts.ASSOC, f"【请示标题】{title}\n\n【附件：{m.name}】\n{head[:1800]}")
        rel, quote, reason = str(res.get("relation") or ""), str(res.get("quote") or ""), str(res.get("reason") or "")
        if rel in ("相关", "冲突") and not quote_found(quote, head):
            unsure.append(f"{m.name}：模型判断为{rel}，但引用原文无法在附件中定位")
            continue
        if rel == "相关":
            clear.append(m.name)
            ev.append(C.ev(m.name, None, quote, label="关联依据"))
        elif rel == "冲突":
            conflict.append(f"{m.name}：{reason or '项目对象或阶段与标题不一致'}")
            ev.append(C.ev(m.name, None, quote, label="冲突原文"))
        else:
            unsure.append(f"{m.name}：{reason or '内容不足以确认关联'}")
    summary = f"关联明确 {len(clear)} 份" + (f"，无法确认 {len(unsure)} 份" if unsure else "") + \
              (f"，存在冲突 {len(conflict)} 份" if conflict else "")
    items = conflict + unsure
    ev = [C.ev("OA 表单", None, f"标题：{title}", label="标题")] + ev
    if conflict:
        return issue(f"发现问题：{summary}。附件中有与标题项目对象或阶段不一致的材料。", ev, items, llm=True)
    if unsure:
        return review(f"待人工复核：{summary}。", ev, items, llm=True)
    return ok(f"核查通过：{summary}（{'、'.join(clear)}）。", ev, llm=True)
