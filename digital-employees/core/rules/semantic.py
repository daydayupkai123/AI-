"""语义比对与语义确认：模型只做判断，结论必须带双方原文引用；引用回到材料里校验，定位不到的差异一律不采信。

judge(purpose, system, user) -> dict 由 core.llm.judge.Judge 提供（测试可替换）。
"""
from __future__ import annotations

import json
import re

from . import common as C
from .engine import Outcome, issue, ok, review

COMPARE_SYSTEM = (
    "你是通用技术集团工程设计有限公司的审核助理，负责对比两份材料中关于「{focus}」的约定是否实质一致。\n"
    "要求：\n"
    "1. 只依据给出的原文判断，不得推测或补充原文没有的内容；\n"
    "2. 表述方式不同但含义相同视为一致；数量、金额、比例、期限、范围、责任主体、条件的增减变化视为不一致；\n"
    "3. 每条差异必须分别逐字摘录两份材料中的对应原文（各不超过 60 字），且两段原文必须是在描述同一事项"
    "（例如都是工作内容、都是付款节点）；一方原文与该事项无关的，不得列为差异；无法摘录的不要列出；\n"
    "4. 任一份材料没有涉及该内容时，结论为「无法判断」，并在 summary 说明缺少哪一方；\n"
    "5. 只比较「{focus}」本身：材料中出现的其他条款（如价款、工期、付款、违约责任、人员等，除非它们就是本次比较的内容）"
    "即使不同也不要列出、不要影响结论，它们由其他规则单独核验。\n"
    '输出格式：{{"conclusion": "一致|不一致|无法判断", "summary": "一句话结论", '
    '"differences": [{{"item": "差异项", "a_quote": "材料A原文", "b_quote": "材料B原文", "explain": "差异说明"}}]}}'
)

VERIFY_SYSTEM = (
    "你是审核复核员，本次只核查「{focus}」。下面每一组是分别摘自两份材料的两段原文，请逐组判断三点同时成立才为 true："
    "（1）两段原文在描述同一具体事项；（2）该事项属于「{focus}」，不是价款、付款、工期、违约等其他方面（除非它们正是本次核查内容）；"
    "（3）双方对该事项作出了实质不同的约定（数量、比例、期限、范围、深度、责任、条件不同）。"
    "讲的是不同事项、不属于本次核查内容、或只是一方更具体一方更笼统、含义相同只是表述不同，都判为 false。\n"
    '输出格式：{"results": [{"no": 组号, "valid": true|false, "reason": "一句话"}]}'
)

CONFIRM_SYSTEM = (
    "你是通用技术集团工程设计有限公司的审核助理。下面是按关键词从材料中截取的片段，请判断是否确实构成「{question}」。\n"
    "要求：只依据片段原文判断；构成时必须逐字摘录触发判断的原文（不超过 80 字）。\n"
    '输出格式：{{"answer": "是|否|无法判断", "quote": "触发原文（answer 为是时必填）", "reason": "一句话理由"}}'
)


def _note(judge, title: str, body: dict) -> None:
    """原文引用校验过程入档（judge 提供 note 时）。"""
    fn = getattr(judge, "note", None)
    if callable(fn):
        fn(title, body)


def _norm(s: str) -> str:
    return re.sub(r"[\s\u3000，,。.；;：:“”\"'‘’（）()、]", "", s or "")


def quote_exact(quote: str, text: str) -> bool:
    """引用逐字出自原文（只忽略空白与标点差异）：问题本身取决于原文字句时（如语句残缺）用它，不容忍模型多写或改写。"""
    q, t = _norm(quote), _norm(text)
    return len(q) >= 4 and q in t


def quote_found(quote: str, text: str) -> bool:
    """引用是否出自原文：完整包含，或按 10 字切块有 60% 以上能在原文中找到（容忍 OCR 与标点差异）。"""
    q, t = _norm(quote), _norm(text)
    if len(q) < 4 or not t:
        return False
    if q in t:
        return True
    chunks = [q[i:i + 10] for i in range(0, max(1, len(q) - 9), 5)]
    return sum(1 for c in chunks if c in t) >= max(1, int(len(chunks) * 0.6 + 0.5))


def verify(judge, purpose: str, a: dict, b: dict, diffs: list[dict], focus: str = "") -> tuple[list[dict], list[str]]:
    """第二道复核：逐组确认差异属于本次核查内容、两段原文讲的是同一事项且约定不同；返回 (通过的差异, 剔除理由)。"""
    if not diffs:
        return [], []
    user = "\n\n".join(f"【第{i + 1}组】{d.get('item') or ''}\n{a['label']}：{d['a_quote']}\n{b['label']}：{d['b_quote']}"
                       for i, d in enumerate(diffs))
    res = judge(f"{purpose}.verify", VERIFY_SYSTEM.replace("{focus}", focus or "所列事项"), user)
    verdict = {}
    for x in res.get("results") or []:
        if isinstance(x, dict):
            try:
                verdict[int(x.get("no"))] = (bool(x.get("valid")), str(x.get("reason") or ""))
            except (TypeError, ValueError):
                continue
    kept, dropped = [], []
    for i, d in enumerate(diffs, start=1):
        ok_, why = verdict.get(i, (False, "复核未给出结论"))
        (kept if ok_ else dropped).append(d if ok_ else f"{d.get('item') or '差异'}：{why}")
    return kept, dropped


def compare(judge, purpose: str, focus: str, a: dict, b: dict, issue_msg: str, pass_msg: str,
            guidance: str = "") -> Outcome:
    """a / b：{"label": 材料名, "file": 文件名, "text": 截取的相关条款}；guidance 为本规则的判定口径补充。"""
    system = COMPARE_SYSTEM.format(focus=focus) + (f"\n6. 本项判定口径：{guidance}" if guidance else "")
    user = (f"【材料A：{a['label']}（{a.get('file', '')}）】\n{a['text'][:3500]}\n\n"
            f"【材料B：{b['label']}（{b.get('file', '')}）】\n{b['text'][:3500]}")
    res = judge(purpose, system, user)
    concl = str(res.get("conclusion") or "").strip()
    summary = str(res.get("summary") or "").strip()
    diffs, dropped, dropped_items = [], 0, []
    for d in res.get("differences") or []:
        if not isinstance(d, dict):
            continue
        aq, bq = str(d.get("a_quote") or ""), str(d.get("b_quote") or "")
        if quote_found(aq, a["text"]) and quote_found(bq, b["text"]):
            diffs.append(d)
        else:
            dropped += 1
            dropped_items.append({"item": d.get("item"), "a_quote": aq, "b_quote": bq,
                                  "a_found": quote_found(aq, a["text"]), "b_found": quote_found(bq, b["text"])})
    _note(judge, f"{purpose} 原文引用校验", {"conclusion": concl, "accepted": len(diffs), "dropped": dropped_items})
    base_ev = [C.ev(a.get("file", ""), None, a["text"][:160], label=a["label"]),
               C.ev(b.get("file", ""), None, b["text"][:160], label=b["label"])]
    named = lambda s: str(s or "").replace("材料A", a["label"]).replace("材料B", b["label"])  # noqa: E731
    summary = named(summary)
    rejected: list[str] = []
    if concl == "不一致" and diffs:
        diffs, rejected = verify(judge, purpose, a, b, diffs, focus)
        _note(judge, f"{purpose} 差异复核", {"kept": [d.get("item") for d in diffs], "rejected": rejected})
        if not diffs:
            return review("模型初判存在差异，但复核认为所列原文并非针对同一事项的不同约定，请人工确认："
                          + "；".join(rejected[:3]), base_ev, rejected, llm=True)
        if rejected:  # 初判摘要可能提到已被剔除的差异，按保留下来的差异重写
            summary = "差异：" + "、".join(str(d.get("item") or "差异") for d in diffs)
    if concl == "不一致" and diffs:
        items = [f"{d.get('item') or '差异'}：{a['label']}「{d['a_quote']}」，{b['label']}「{d['b_quote']}」"
                 + (f"（{named(d['explain'])}）" if d.get("explain") else "") for d in diffs]
        ev = []
        for d in diffs[:6]:
            ev.append(C.ev(a.get("file", ""), None, d["a_quote"], label=f"{a['label']} · {d.get('item') or ''}"))
            ev.append(C.ev(b.get("file", ""), None, d["b_quote"], label=f"{b['label']} · {d.get('item') or ''}"))
        return issue(issue_msg + (f"（{summary}）" if summary else ""), ev, items, llm=True)
    if concl == "不一致":
        return review(f"模型判断存在差异，但给出的原文无法在材料中定位（{dropped} 条），请人工核对。"
                      + (f"模型说明：{summary}" if summary else ""), base_ev, llm=True)
    if concl == "一致":
        return ok(pass_msg + (f"（{summary}）" if summary else ""), base_ev, llm=True)
    return review("模型无法据现有条款作出判断，请人工核对。" + (f"说明：{summary}" if summary else ""), base_ev, llm=True)


def confirm(judge, purpose: str, question: str, hits: list[dict]) -> tuple[str, str, dict | None]:
    """关键词命中片段 → 模型确认。返回 (answer: 是/否/无法判断, reason, 已校验的证据或 None)。"""
    snippets = "\n".join(f"[{i + 1}]（{h.get('file')}{' 第' + str(h['page']) + '页' if h.get('page') else ''}）"
                         f"{h.get('context') or h.get('snippet')}" for i, h in enumerate(hits[:6]))
    res = judge(purpose, CONFIRM_SYSTEM.format(question=question), snippets)
    ans = str(res.get("answer") or "").strip()
    quote = str(res.get("quote") or "")
    reason = str(res.get("reason") or "").strip()
    if ans == "是":
        src = next((h for h in hits if quote_found(quote, h.get("context") or h.get("snippet") or "")), None)
        _note(judge, f"{purpose} 原文引用校验", {"answer": ans, "quote": quote, "located": bool(src)})
        if not src:
            return "无法判断", f"模型判断为是，但引用原文无法定位：{quote[:60]}", None
        return "是", reason, C.ev(src.get("file", ""), src.get("page"), quote, label="触发原文")
    return (ans if ans in ("否", "无法判断") else "无法判断"), reason, None


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
