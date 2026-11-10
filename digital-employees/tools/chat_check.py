"""命令行验证 /api/llm/status 与 /api/chat 流式对话。

  python tools/chat_check.py "你好" [task_id]
"""
import json
import sys
import time

import requests

BASE = "http://127.0.0.1:8090"
s = requests.Session()
s.trust_env = False
print("status:", s.get(BASE + "/api/llm/status", timeout=10).json())
msg = sys.argv[1] if len(sys.argv) > 1 else "你好，先介绍一下你自己吧"
task = sys.argv[2] if len(sys.argv) > 2 else None
t0 = time.time()
think, text, first = "", "", None
with s.post(BASE + "/api/chat", json={"employee": "procurement", "message": msg, "history": [], "task_id": task},
            stream=True, timeout=600) as r:
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        ev = json.loads(line[5:])
        if ev["type"] in ("think", "text") and first is None:
            first = time.time() - t0
        if ev["type"] == "think":
            think += ev["text"]
        elif ev["type"] == "text":
            text += ev["text"]
        elif ev["type"] in ("start", "done", "error"):
            print(ev)
print(f"first token {first:.1f}s, total {time.time() - t0:.1f}s, think {len(think)} chars, answer {len(text)} chars")
print("--- think (head) ---\n" + think.strip()[:300])
print("--- answer ---\n" + text.strip())
