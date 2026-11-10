"""规则执行引擎：每条规则独立执行、互不阻断，结果按规则编号固定顺序输出。

规则函数签名：fn(facts) -> Outcome。抛异常不会静默跳过：模型失败记「审查中止」并写明原因，
其他异常记「审查中止 · 规则执行异常」。
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

from ..errors import DEError
from . import status as st


@dataclass
class Outcome:
    code: str
    message: str
    evidence: list = field(default_factory=list)
    items: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


def ok(message: str, evidence=None, **extra) -> Outcome:
    return Outcome(st.PASS, message, evidence or [], [], extra)


def issue(message: str, evidence=None, items=None, **extra) -> Outcome:
    return Outcome(st.ISSUE, message, evidence or [], list(items or []), extra)


def missing(message: str, evidence=None, **extra) -> Outcome:
    return Outcome(st.MISSING, message, evidence or [], [], extra)


def review(message: str, evidence=None, items=None, **extra) -> Outcome:
    return Outcome(st.REVIEW, message, evidence or [], list(items or []), extra)


def na(message: str, **extra) -> Outcome:
    return Outcome(st.NA, message, [], [], extra)


def notrun(message: str, **extra) -> Outcome:
    return Outcome(st.NOTRUN, message, [], [], extra)


def aborted(message: str, evidence=None, **extra) -> Outcome:
    return Outcome(st.ERROR, message, evidence or [], [], extra)


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    category: str
    fn: Callable[[dict], Outcome]
    group: str = ""
    llm: bool = False


def jsonable(v):
    """证据里的日期、集合等转成可序列化的值（入库与推送都用 JSON）。"""
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items() if not str(k).startswith("_")}
    if isinstance(v, (list, tuple, set)):
        return [jsonable(x) for x in v]
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def _result(employee: str, version: str, rule: Rule, out: Outcome, ms: int) -> dict:
    return {"rule_id": rule.id, "rule_ver": version, "name": rule.name, "category": rule.category,
            "group": rule.group, "tier": rule.category, "code": out.code, "status": st.label(employee, out.code),
            "message": out.message, "evidence": jsonable(out.evidence), "items": [str(x) for x in out.items],
            "ms": ms, **jsonable(out.extra)}


def run_rule(employee: str, version: str, rule: Rule, facts: dict) -> dict:
    from .. import ruleconfig

    t0 = time.time()
    off = ruleconfig.disabled_reason(employee, rule.id)
    if off:
        return ruleconfig.apply_result(employee, _result(employee, version, rule, notrun(f"未执行：{off}"), 0))
    try:
        out = rule.fn(facts)
        if not isinstance(out, Outcome):
            raise TypeError(f"规则 {rule.id} 未返回 Outcome")
    except DEError as exc:
        out = aborted(f"{exc.title}：{exc.detail or exc}。本条规则未形成结论。")
    except Exception as exc:  # noqa: BLE001
        out = aborted(f"规则执行异常：{type(exc).__name__}: {exc}。本条规则未形成结论。")
    return ruleconfig.apply_result(employee, _result(employee, version, rule, out, int((time.time() - t0) * 1000)))


def run_rules(employee: str, version: str, rules: list[Rule], facts: dict,
              on_result: Callable[[dict], None] | None = None, workers: int = 4) -> list[dict]:
    """并发执行，on_result 按完成先后回调（用于实时推送）；返回值按 rules 的顺序排列。"""
    lock = threading.Lock()
    out: dict[str, dict] = {}

    def done(r: dict) -> None:
        with lock:
            out[r["rule_id"]] = r
            if on_result:
                on_result(r)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(run_rule, employee, version, rule, facts) for rule in rules]
        for f in as_completed(futs):
            done(f.result())
    return [out[r.id] for r in rules]


def summarize(employee: str, results: list[dict]) -> dict:
    counts = {code: 0 for code in st.CODES}
    for r in results:
        counts[r["code"]] = counts.get(r["code"], 0) + 1
    return {"规则总数": len(results), "codes": counts,
            **{st.label(employee, code): n for code, n in counts.items()}}
