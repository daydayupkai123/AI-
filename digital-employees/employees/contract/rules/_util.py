"""合同规则共用的小工具：证据转换、条款截取、表单取值、适用条件。"""
from __future__ import annotations

import functools
import re

from core.rules import common as C
from core.rules.engine import missing

SCOPE_KW = r"(工作范围|服务范围|服务内容|工程范围|承包范围|设计范围|项目范围|工作内容|委托内容|合同范围)"
PERSON_KW = r"(项目负责人|项目经理|总监|设计总负责人|技术负责人|专业负责人|主要人员|人员名单|履约人员|拟派|人员配置)"
PAY_KW = r"(付款|支付|结算|预付款|进度款|尾款|质保金)"
PENALTY_KW = r"(违约责任|违约金|赔偿|违约)"
SUBST_KW = r"(履行地点|服务地点|交付地点|实施地点|履行方式|服务方式|质量要求|质量标准|服务标准|验收标准|质量目标)"
CONSORTIUM_KW = r"(联合体|牵头人|牵头方|成员方|成员单位|分工|职责划分|工作划分)"
TECH_KW = r"(技术参数|技术要求|技术指标|规格|型号|供货范围|接口|性能|参数)"
BRANCH_RE = r"分公司|项目部|分院|办事处|分部|分厂"
YES = ("是", "有", "Y", "y", "yes", "√", "含", "包含")


def fev(fact: dict | None, label: str = "") -> dict:
    """事实 → 证据（去掉内部字段）。"""
    if not fact:
        return {}
    e = {k: v for k, v in fact.items() if k in ("file", "page", "snippet", "value", "raw")}
    if label:
        e["label"] = label
    return e


SECTIONS = {
    PAY_KW: r"合同价格及支付|合同价款及支付|合同价款与支付|价款及支付|付款方式|支付方式|付款里程碑",
    PENALTY_KW: r"违约责任",
    SCOPE_KW: r"工作范围|服务范围|勘测范围|勘察范围|设计范围|工程范围|服务内容|工作内容|委托内容",
    PERSON_KW: r"乙方的人员|项目人员|人员配置|主要负责人员",
}


def window(mats, pattern: str, limit: int = 3500) -> dict | None:
    """多份材料中截取相关条款，合并为一段供比对：优先取编号章节（如「13. 违约责任」整章），
    取不到再按关键词密度截取窗口。"""
    parts, files = [], []
    mats = list(mats or [])
    share = max(1200, limit // max(1, min(len(mats), 3)))  # 正文与附件按份分配篇幅，避免附件分不到
    for m in mats:
        room = min(share, limit - sum(len(p) for p in parts))
        if room <= 0:
            break
        text = C.flat(m.text)
        sec_title = SECTIONS.get(pattern)
        w = C.section_text(text, sec_title, max_len=room) if sec_title else ""
        if len(w) < 200:
            w = C.keyword_windows(text, pattern, pad=300, limit=room)
        if w:
            parts.append(w)
            files.append(m.name)
    if not parts:
        return None
    return {"text": "\n……\n".join(parts)[:limit], "file": "、".join(files)}


def form(f: dict, key: str) -> str:
    v = (f.get("form") or {}).get(key)
    return v["value"] if v else ""


def form_ev(f: dict, key: str) -> dict:
    v = (f.get("form") or {}).get(key)
    return C.ev("审批表单", None, f"{v['label']}：{v['value']}") if v else {}


def biz_text(f: dict) -> str:
    return " ".join(x for x in (form(f, "业务类型"), form(f, "业务类型二级"), form(f, "合同设计阶段"),
                                form(f, "合同签订类型"), form(f, "合同名称")) if x)


def no_award(f: dict) -> bool:
    """表单「有无中标通知书」为无，且材料中也没有中标通知书。"""
    return form(f, "有无中标通知书").strip() == "无" and not f.get("awards")


def non_bid(f: dict) -> bool:
    """表单「投标方式」为非投标，且台账与附件中都没有投标文件。"""
    return "非投标" in form(f, "投标方式") and not f.get("bids")


def contract_docs(f: dict) -> list:
    return [f["contract"]] + list(f.get("appendix_docs") or [])


def is_yes(v: str) -> bool:
    return bool(v) and (v.strip() in YES or v.strip().startswith(YES))


def money(v: float | None) -> str:
    return C.fmt_yuan(v)


def pcts(values) -> str:
    return "、".join(f"{v:g}%" for v in values) or "—"


def needs_contract(fn):
    @functools.wraps(fn)
    def run(f):
        if not f.get("contract"):
            return missing("未找到可读取的合同正文（出版用合同文本），无法核验。")
        return fn(f)
    return run


def judge_of(f: dict):
    j = f.get("_judge")
    if j is None:
        raise RuntimeError("未配置模型判定器")
    return j


def has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text or ""))
