"""门户子系统接口摸底（公文系统、通财云等）：附着已登录的调试 Chrome，记录人工浏览时页面背后的 JSON 接口。

  python tools/probes/portal_probe.py watch <name> [--seconds 300] [--url <起始地址>]

用法：运行后在调试 Chrome 中手动操作（如 门户 → 工作 → 公文 → 已办 → 打开一条「内部请示」；
门户 → 应用 → 通财云 → 已办任务 → 打开一张报销单），脚本在旁记录所有 XHR/fetch 的 JSON 响应。

纪律：只读。拦截一切非 GET 且路径形似提交/保存/审批/退回/删除的请求；脚本本身不点击任何按钮。
产物写到 .runtime/probe/<name>/（含会话相关内容与客户数据，不入版本库）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"
OUT = Path(__file__).resolve().parents[2] / ".runtime" / "probe"
WRITE_PATTERN = re.compile(r"(submit|save|operation|reject|forward|delete|remove|approve|agree|takeback|withdraw|"
                           r"doback|sign|audit|pass|return|cancel|lock|update)", re.IGNORECASE)


def _guard(route):
    req = route.request
    if req.method != "GET" and WRITE_PATTERN.search(urlparse(req.url).path):
        print(f"  [已拦截写操作] {req.method} {req.url[:160]}", flush=True)
        route.abort()
        return
    route.continue_()


def cmd_watch(args):
    out = OUT / args.name
    out.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []

    def on_response(resp):
        if resp.request.resource_type not in ("xhr", "fetch"):
            return
        try:
            body = resp.body()
            data = json.loads(body.decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            return
        idx = len(records) + 1
        fname = f"{idx:04d}.json"
        (out / fname).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        rec = {"idx": idx, "at": time.strftime("%H:%M:%S"), "method": resp.request.method, "status": resp.status,
               "url": resp.url, "post": (resp.request.post_data or "")[:2000], "bytes": len(body), "file": fname,
               "page": resp.frame.page.url[:200] if resp.frame else ""}
        records.append(rec)
        print(f"  {idx:4d} {rec['method']:4s} {rec['status']} {len(body):>8d}  {resp.url[:140]}", flush=True)

    with sync_playwright() as p:
        ctx = p.chromium.connect_over_cdp(CDP).contexts[0]
        ctx.route("**/*", _guard)
        ctx.on("response", on_response)  # 上下文级事件已覆盖现有与新开的标签页
        if args.url:
            ctx.new_page().goto(args.url, wait_until="domcontentloaded", timeout=90000)
        print(f"开始记录 {args.seconds} 秒，请在调试 Chrome 中操作……", flush=True)
        t_end = time.time() + args.seconds
        while time.time() < t_end:
            time.sleep(1)
            (out / "index.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
        tabs = [{"title": pg.title(), "url": pg.url} for pg in ctx.pages]
    (out / "index.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "tabs.json").write_text(json.dumps(tabs, ensure_ascii=False, indent=1), encoding="utf-8")
    hosts = sorted({urlparse(r["url"]).netloc for r in records})
    print(f"共记录 {len(records)} 个 JSON 响应；涉及域名：{', '.join(hosts)}；保存到 {out}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch")
    w.add_argument("name")
    w.add_argument("--seconds", type=int, default=300)
    w.add_argument("--url", default="")
    args = ap.parse_args()
    {"watch": cmd_watch}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
