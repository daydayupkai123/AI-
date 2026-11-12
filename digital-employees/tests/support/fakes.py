"""测试替身：模型判定器、天眼查。"""
from __future__ import annotations

from shared.external_lookup import ExternalUnavailable


class FakeJudge:
    """按 purpose 返回预设结果；未预设的比对返回「一致」、确认返回「否」。记录每次调用。"""

    def __init__(self, answers: dict | None = None, fail: set[str] | None = None):
        self.answers = answers or {}
        self.fail = fail or set()
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, purpose: str, system: str, user: str) -> dict:
        self.calls.append((purpose, system, user))
        if purpose in self.fail or "*" in self.fail:
            from shared.llm.judge import LLMUnavailable
            raise LLMUnavailable(f"测试模拟：{purpose} 模型不可用")
        ans = self.answers.get(purpose)
        if callable(ans):
            return ans(system, user)
        if ans is not None:
            return ans
        if purpose.endswith(".verify"):
            import re
            return {"results": [{"no": int(n), "valid": True} for n in re.findall(r"【第(\d+)组】", user)]}
        if "输出格式：{\"answer\"" in system:
            return {"answer": "否", "reason": "测试默认"}
        return {"conclusion": "一致", "summary": "测试默认一致", "differences": []}


class FakeTianyancha:
    def __init__(self, profiles: dict | None = None, error: str | None = None):
        self.profiles = profiles or {}
        self.error = error
        self.queries: list[str] = []

    def profile(self, name: str) -> dict:
        self.queries.append(name)
        if self.error:
            raise ExternalUnavailable(self.error)
        if name in self.profiles:
            return self.profiles[name]
        return {"name": name, "reg_status": "存续", "legal_person": "张三", "reg_capital": "1000万人民币",
                "reg_capital_yuan": 1e7, "risks": {"失信被执行人": 0, "被执行人": 0, "破产案件": 0}, "url": ""}
