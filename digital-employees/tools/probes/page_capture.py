"""只读打开一个页面并完整记录：各 frame 的 URL 与可见文字、附件链接、页面背后的 XHR/fetch（JSON 与 HTML 片段）。

  python tools/probes/page_capture.py <name> <url> [--wait 10]

只用于已办 / 已发事项（不改变任何人的待办）。拦截非 GET 且形似提交、保存、审批的请求。产物 .runtime/probe/<name>/。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[2] / ".runtime" / "probe"
WRITE = re.compile(r"(submit|save|delete|remove|agree|disagree|takeback|withdraw|doback|stepback|finish|send|"
                   r"repeal|cancel|lock|update|audit|approve|reject|unaudit)", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("url")
    ap.add_argument("--wait", type=int, default=10)
    args = ap.parse_args()
    out = OUT / args.name
    out.mkdir(parents=True, exist_ok=True)
    recs = []

    def guard(route):
        req = route.request
        target = urlparse(req.url).path + "?" + (urlparse(req.url).query or "")
        # 金蝶云苍穹的按钮动作写在请求体里（如 bar_submit / audit），请求体也要检查
        if req.method != "GET" and (WRITE.search(target) or WRITE.search(req.post_data or "")):
            print("  [已拦截写操作]", req.method, req.url[:160], (req.post_data or "")[:160])
            return route.abort()
        return route.continue_()

    def on_resp(resp):
        if resp.request.resource_type not in ("xhr", "fetch", "document"):
            return
        try:
            body = resp.body()
        except Exception:  # noqa: BLE001
            return
        i = len(recs) + 1
        ctype = resp.headers.get("content-type", "")
        ext = "json" if "json" in ctype else "html" if "html" in ctype else "txt"
        (out / f"{i:04d}.{ext}").write_bytes(body[:3_000_000])
        recs.append({"i": i, "type": resp.request.resource_type, "method": resp.request.method, "status": resp.status,
                     "url": resp.url, "ctype": ctype, "bytes": len(body), "post": (resp.request.post_data or "")[:1500]})

    with sync_playwright() as p:
        ctx = p.chromium.connect_over_cdp("http://127.0.0.1:9222").contexts[0]
        page = ctx.new_page()
        page.set_viewport_size({"width": 1440, "height": 900})
        page.route("**/*", guard)
        page.on("response", on_resp)
        page.goto(args.url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(args.wait * 1000)
        page.screenshot(path=str(out / "page.png"), full_page=True)
        frames = []
        for f in page.frames:
            try:
                text = f.evaluate("() => document.body ? document.body.innerText : ''")
                links = f.evaluate("""() => [...document.querySelectorAll('a,[onclick]')].map(a => ({
                    text: (a.innerText || '').trim().slice(0, 80), href: a.getAttribute('href') || '',
                    onclick: (a.getAttribute('onclick') || '').slice(0, 300)})).filter(x => x.text || x.onclick)""")
            except Exception as exc:  # noqa: BLE001
                text, links = f"(读取失败 {exc})", []
            frames.append({"url": f.url, "name": f.name, "text": text[:20000], "links": links[:300]})
        final = page.url
        page.close()
    (out / "frames.json").write_text(json.dumps(frames, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "index.json").write_text(json.dumps({"final_url": final, "records": recs}, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    print("final:", final)
    for f in frames:
        print(f"== frame {f['name'] or '-'} {f['url'][:140]}  文字 {len(f['text'])}  链接 {len(f['links'])}")
    print(f"响应 {len(recs)} 个：")
    for r in recs:
        print(f"   {r['i']:4d} {r['type'][:5]:5s} {r['method']:4s} {r['status']} {r['bytes']:>8d} {r['url'][:150]}")


if __name__ == "__main__":
    sys.exit(main())
