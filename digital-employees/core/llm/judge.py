"""结构化判定：让模型只输出 JSON，并按「模型 + 提示词版本 + 输入内容」缓存结果。

- 输出无法解析时追加一次纠正提示重试，仍失败抛 LLMBadOutput；连接失败抛 LLMUnavailable。
- 调用方据此把规则记为「审查中止」，不会把模型失败当成通过。
- 缓存记录带完整性签名，被改动的缓存不会被采用。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Callable

from ..config import hmac_key
from ..errors import DEError
from ..signing import canonical
from . import client as llm


class LLMError(DEError):
    title = "大模型调用失败"
    hint = "请确认 config/llm.yaml 中配置的模型服务已启动（本机 Ollama 需打开客户端），然后点「重新审查」。"


class LLMUnavailable(LLMError):
    title = "无法连接大模型"


class LLMBadOutput(LLMError):
    title = "大模型返回内容无法解析"
    hint = "可以点「重新审查」再试；反复出现时请在 config/llm.yaml 中换用更强的模型。"


JSON_RULE = "只输出一个 JSON 对象，不要输出 JSON 以外的任何文字、解释或 Markdown 代码块标记。"


def parse_json(text: str) -> dict:
    text = re.sub(r"<think>[\s\S]*?</think>", "", text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("没有找到 JSON 对象")
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("JSON 顶层不是对象")
    return obj


def _sign(key: str, body: str) -> str:
    return hmac.new(hmac_key(), f"{key}|{hashlib.sha256(body.encode('utf-8')).hexdigest()}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


class Judge:
    """可注入的判定器：graph 里统一通过 judge(purpose, system, user) 调用，测试可替换为假实现。"""

    def __init__(self, store=None, task_id: str | None = None, role: str = "judge", prompt_ver: str = "1",
                 complete: Callable[..., str] | None = None, trace: Callable[[str, str, object], None] | None = None):
        """trace(kind, title, body)：执行档案记录（完整提示词、原始输出、解析结果、是否命中缓存、耗时）。"""
        self.store = store
        self.task_id = task_id
        self.role = role
        self.prompt_ver = prompt_ver
        self._complete = complete or llm.complete
        self._trace = trace

    def note(self, title: str, body) -> None:
        """规则侧的模型结果核验过程（原文引用采纳 / 丢弃）入档。"""
        if self._trace:
            self._trace("check", title, body)

    def _record(self, purpose: str, p: dict, messages: list[dict], **kw) -> None:
        if self._trace:
            self._trace("llm", purpose, {"purpose": purpose, "provider": p["name"], "model": p.get("model"),
                                         "prompt_ver": self.prompt_ver, "messages": messages, **kw})

    def __call__(self, purpose: str, system: str, user: str) -> dict:
        p = llm.provider(self.role)
        messages = [{"role": "system", "content": f"{system}\n\n{JSON_RULE}"}, {"role": "user", "content": user}]
        key = hashlib.sha256(canonical([p["name"], p.get("model"), self.prompt_ver, purpose, messages])).hexdigest()
        t0 = time.time()
        if self.store is not None:
            row = self.store.get_llm_cache(key)
            if row and hmac.compare_digest(_sign(key, row["body"]), row["integrity"]):
                self.store.log_llm(self.task_id, self.role, purpose, p["name"], p.get("model"), True, True, 0)
                obj = json.loads(row["body"])
                self._record(purpose, p, messages, cached=True, ok=True, output=obj, ms=0)
                return obj
        last_err, raw = "", []
        for attempt in range(2):
            try:
                text = self._complete(messages, self.role)
            except Exception as exc:  # noqa: BLE001
                ms = int((time.time() - t0) * 1000)
                if self.store is not None:
                    self.store.log_llm(self.task_id, self.role, purpose, p["name"], p.get("model"), False, False, ms,
                                       f"{type(exc).__name__}: {exc}")
                self._record(purpose, p, messages, cached=False, ok=False, raw=raw, ms=ms,
                             error=f"{type(exc).__name__}: {exc}")
                raise LLMUnavailable(f"{p['name']}（{p.get('model')}）：{type(exc).__name__}: {exc}") from exc
            raw.append(text)
            try:
                obj = parse_json(text)
                break
            except (ValueError, json.JSONDecodeError) as exc:
                last_err = f"{exc}；模型原文前 200 字：{text[:200]}"
                messages = messages + [{"role": "assistant", "content": text[:2000]},
                                       {"role": "user", "content": "上面的输出不是合法 JSON。" + JSON_RULE}]
        else:
            ms = int((time.time() - t0) * 1000)
            if self.store is not None:
                self.store.log_llm(self.task_id, self.role, purpose, p["name"], p.get("model"), False, False, ms,
                                   last_err)
            self._record(purpose, p, messages, cached=False, ok=False, raw=raw, ms=ms, error=last_err)
            raise LLMBadOutput(f"{purpose}：{last_err}")
        ms = int((time.time() - t0) * 1000)
        if self.store is not None:
            body = json.dumps(obj, ensure_ascii=False)
            self.store.put_llm_cache(key, p["name"], p.get("model") or "", self.prompt_ver, body, _sign(key, body))
            self.store.log_llm(self.task_id, self.role, purpose, p["name"], p.get("model"), False, True, ms)
        self._record(purpose, p, messages, cached=False, ok=True, raw=raw, output=obj, ms=ms)
        return obj
