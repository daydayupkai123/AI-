"""受限对话边界实测（调用本机工作台 /api/chat）：python tools/chat_boundary_check.py <合同任务 task_id>

- 无报告 + 业务外问题 → 固定引导（不调模型）
- 有报告 + 闲聊 → 固定引导（不调模型）
- 有报告 + 与报告无关的问题 → 模型按边界只回复固定拒答
- 有报告 + 报告追问 → 模型基于报告作答
"""
from __future__ import annotations

import json
import sys

import httpx

WB = "http://127.0.0.1:8090"


def ask(msg: str, task_id: str | None) -> tuple[str, str]:
    kind, text = "", ""
    with httpx.Client(trust_env=False, timeout=600) as c:
        with c.stream("POST", f"{WB}/api/chat", json={"employee": "contract", "message": msg, "task_id": task_id}) as s:
            for line in s.iter_lines():
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:])
                if ev["type"] in ("guide", "text"):
                    kind = kind or ev["type"]
                    text += ev["text"]
                elif ev["type"] == "error":
                    return "error", ev.get("error", "")
    return kind, text.strip()


if __name__ == "__main__":
    tid = sys.argv[1]
    cases = [("无报告·业务外", "帮我写一首关于秋天的诗", None),
             ("有报告·闲聊", "你好", tid),
             ("有报告·与报告无关", "帮我写一首关于秋天的诗", tid),
             ("有报告·追问", "R07 为什么判为发现问题？依据是哪两份文件？", tid)]
    for name, msg, t in cases:
        kind, text = ask(msg, t)
        print(f"== {name}：{msg}\n   [{kind}] {text[:300]}\n")
