"""门户导航摸底：在调试 Chrome 新标签页中按菜单文字逐级点击（只点导航，不点任何单据或按钮），记录各步 URL、
页面可见文字与背后的 JSON 接口。

  python tools/portal_nav_probe.py <name> <菜单1> [<菜单2> ...] [--start https://i.gt.cn/main/] [--wait 6]

纪律：只读。拦截非 GET 且路径形似提交/保存/审批的请求。产物写到 .runtime/probe/<name>/（不入库）。
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

OUT = Path(__file__).resolve().parent.parent / ".runtime" / "probe"
WRITE = re.compile(r"(submit|save|delete|remove|agree|disagree|reject|takeback|withdraw|doback|stepback|finish|"
                   r"repeal|cancel)", re.I)  # 门户接口一律 POST，接口名含 OPERATION/APPROVE/lockWhiteList 的为只读，不拦


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("menus", nargs="+")
    ap.add_argument("--start", default="https://i.gt.cn/main/")
    ap.add_argument("--wait", type=int, default=6)
    args = ap.parse_args()
    out = OUT / args.name
    out.mkdir(parents=True, exist_ok=True)
    records, steps = [], []

    def guard(route):
        req = route.request
        if req.method != "GET" and WRITE.search(urlparse(req.url).path):
            print("  [已拦截写操作]", req.method, req.url[:140])
            return route.abort()
        return route.continue_()

    def on_resp(resp):
        if resp.request.resource_type not in ("xhr", "fetch"):
            return
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            return
        i = len(records) + 1
        (out / f"{i:04d}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        records.append({"i": i, "method": resp.request.method, "url": resp.url, "post": (resp.request.post_data or "")[:1500],
                        "page": resp.frame.page.url if resp.frame else ""})

    with sync_playwright() as p:
        ctx = p.chromium.connect_over_cdp("http://127.0.0.1:9222").contexts[0]
        ctx.route("**/*", guard)
        ctx.on("response", on_resp)
        page = ctx.new_page()
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(args.start, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(args.wait * 1000)
        cur = page
        for k, menu in enumerate(args.menus, 1):
            pages_before = set(ctx.pages)
            loc = None
            for fr in cur.frames:  # 门户子页面常嵌在 iframe 中
                for exact in (True, False):
                    cand = fr.get_by_text(menu, exact=exact)
                    try:
                        if cand.count():
                            loc = cand
                            break
                    except Exception:  # noqa: BLE001
                        continue
                if loc is not None:
                    break
            if loc is None:
                print(f"第 {k} 步未找到菜单「{menu}」；frames：{[f.url[:80] for f in cur.frames]}")
                break
            loc.first.click()
            cur.wait_for_timeout(args.wait * 1000)
            new = [pg for pg in ctx.pages if pg not in pages_before]
            if new:
                cur = new[-1]
                cur.wait_for_load_state("domcontentloaded")
                cur.wait_for_timeout(args.wait * 1000)
            cur.screenshot(path=str(out / f"step{k}.png"))
            text = cur.evaluate("() => document.body.innerText")[:3000]
            frames = [f.url for f in cur.frames if f.url and f.url != "about:blank"]
            steps.append({"step": k, "menu": menu, "url": cur.url, "frames": frames, "text": text})
            print(f"第 {k} 步「{menu}」→ {cur.url}")
            for fu in frames[1:6]:
                print("     frame:", fu[:150])
        for pg in ctx.pages:
            if pg is not page and pg.url.startswith("http") and pg not in (ctx.pages[0], ctx.pages[1]) and pg != cur:
                pass
        (out / "steps.json").write_text(json.dumps(steps, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "index.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
        hosts = sorted({urlparse(r["url"]).netloc for r in records})
        print(f"JSON 接口 {len(records)} 个；域名：{', '.join(hosts)}；保存到 {out}")
        for r in records[-40:]:
            print(f"   {r['i']:4d} {r['method']:4s} {r['url'][:150]}")


if __name__ == "__main__":
    sys.exit(main())
