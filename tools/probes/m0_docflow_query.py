"""摸底：公文系统门户「公司数据查询 → 内部请示查询」（只读）。

在调试 Chrome 新标签页打开门户空间页，点击「内部请示查询」，记录打开的页面与页面发出的请求（JSON 落盘），
拦截一切形似提交 / 保存 / 审批的非 GET 请求。产物 .runtime/probe/docflow_query/。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from playwright.sync_api import sync_playwright  # noqa: E402

from shared.portal_snapshot import WRITE, WRITE_BODY  # noqa: E402

SPACE = "https://oa-xc.gt.cn/seeyon/portal/spaceController.do?method=showThemSpace&spaceId=5055268928752140374"
OUT = ROOT / ".runtime" / "probe" / "docflow_query"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    recs, blocked = [], []

    def guard(route):
        rq = route.request
        if rq.method != "GET" and (WRITE.search(rq.url) or WRITE_BODY.search(rq.post_data or "")):
            blocked.append(f"{rq.method} {rq.url[:160]}")
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
        (OUT / f"{i:04d}.{'json' if 'json' in ctype else 'html' if 'html' in ctype else 'txt'}").write_bytes(body[:3_000_000])
        recs.append({"i": i, "method": resp.request.method, "status": resp.status, "url": resp.url,
                     "post": resp.request.post_data or "", "bytes": len(body)})

    with sync_playwright() as p:
        ctx = p.chromium.connect_over_cdp("http://127.0.0.1:9222").contexts[0]
        ctx.route("**/*", guard)
        ctx.on("response", on_resp)
        page = ctx.new_page()
        from urllib.parse import quote

        sso = "https://oa-xc.gt.cn/seeyon/tyssj.do?method=access&targetUrl=" + quote(SPACE.split("oa-xc.gt.cn", 1)[1], safe="")
        page.goto(sso, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(12000)
        page.screenshot(path=str(OUT / "space.png"))
        print("空间页：", page.url[:160], "frames", len(page.frames))
        for f in page.frames:  # 先切到「公司数据查询」页签
            tab = f.get_by_text("公司数据查询", exact=True)
            if tab.count():
                tab.first.click()
                page.wait_for_timeout(3000)
                break
        else:
            (OUT / "space_text.txt").write_text(page.evaluate("() => document.body.innerText"), encoding="utf-8")
        target = None
        for f in page.frames:
            loc = f.get_by_text("内部请示查询", exact=True)
            if loc.count():
                target = (f, loc.first)
                break
        if not target:
            print("未找到「内部请示查询」入口；frames:", [f.url[:100] for f in page.frames])
            page.close()
            return 1
        f, el = target
        info = el.evaluate("""e => { const a = e.closest('a,[onclick],li,div'); return {
            tag: a && a.tagName, href: a && a.getAttribute('href'), onclick: a && (a.getAttribute('onclick') || '').slice(0, 500),
            html: a && a.outerHTML.slice(0, 800)}; }""")
        print("入口：", json.dumps(info, ensure_ascii=False))
        before = len(ctx.pages)
        el.click()
        page.wait_for_timeout(8000)
        pages = ctx.pages[before:] or [page]
        result = {"entry": info, "pages": []}
        for pg in pages:
            try:
                pg.wait_for_load_state("networkidle", timeout=20000)
            except Exception:  # noqa: BLE001
                pass
            frames = []
            for fr in pg.frames:
                try:
                    text = fr.evaluate("() => document.body ? document.body.innerText : ''")
                except Exception as exc:  # noqa: BLE001
                    text = f"(读取失败 {exc})"
                frames.append({"url": fr.url, "text": text[:6000]})
            pg.screenshot(path=str(OUT / f"page_{len(result['pages'])}.png"), full_page=True)
            result["pages"].append({"url": pg.url, "frames": frames})
        for pg in set(pages) | {page}:
            if pg is not page or pages == [page]:
                pass
        (OUT / "result.json").write_text(json.dumps({**result, "records": recs, "blocked": blocked}, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
        for pg in pages:
            if pg != page:
                pg.close()
        page.close()
    print("打开的页面：", [x["url"][:150] for x in result["pages"]])
    print("拦截写请求：", blocked)
    for r in recs:
        if re.search(r"query|Query|cap4|form|list|data", r["url"]):
            print(f"  {r['i']:4d} {r['method']} {r['status']} {r['bytes']:>8d} {r['url'][:170]}")
    return 0


def open_row(row_id: str) -> int:
    """在查询结果页调用页面自身的行点击函数 clk({id}) 打开一条请示详情，记录打开的地址与请求。"""
    out = OUT / f"detail_{row_id}"
    out.mkdir(parents=True, exist_ok=True)
    qurl = next(r["url"] for r in json.loads((OUT / "result.json").read_text(encoding="utf-8"))["records"]
                if "queryResult.do" in r["url"])
    recs, blocked = [], []

    def guard(route):
        rq = route.request
        if rq.method != "GET" and (WRITE.search(rq.url) or WRITE_BODY.search(rq.post_data or "")):
            blocked.append(f"{rq.method} {rq.url[:160]} {(rq.post_data or '')[:200]}")
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
        (out / f"{i:04d}.{'json' if 'json' in ctype else 'html' if 'html' in ctype else 'txt'}").write_bytes(body[:3_000_000])
        recs.append({"i": i, "method": resp.request.method, "status": resp.status, "url": resp.url,
                     "post": resp.request.post_data or "", "bytes": len(body)})

    from urllib.parse import quote
    with sync_playwright() as p:
        ctx = p.chromium.connect_over_cdp("http://127.0.0.1:9222").contexts[0]
        ctx.route("**/*", guard)
        ctx.on("response", on_resp)
        page = ctx.new_page()
        page.goto("https://oa-xc.gt.cn/seeyon/tyssj.do?method=access&targetUrl=" + quote(qurl.split("oa-xc.gt.cn", 1)[1], safe=""),
                  wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(10000)
        fr = next((f for f in page.frames if f.evaluate("() => typeof clk === 'function'")), None)
        if not fr:
            print("查询页未加载出 clk；frames:", [f.url[:100] for f in page.frames])
            page.close()
            return 1
        n0 = len(recs)
        before = len(ctx.pages)
        fr.evaluate("id => clk({id: id}, 0, 0)", row_id)
        page.wait_for_timeout(12000)
        opened = ctx.pages[before:]
        result = {"query": qurl, "row": row_id, "pages": []}
        for pg in opened:
            try:
                pg.wait_for_load_state("networkidle", timeout=20000)
            except Exception:  # noqa: BLE001
                pass
            frames = []
            for f in pg.frames:
                try:
                    text = f.evaluate("() => document.body ? document.body.innerText : ''")
                except Exception as exc:  # noqa: BLE001
                    text = f"(读取失败 {exc})"
                frames.append({"url": f.url, "text": text[:8000]})
            pg.screenshot(path=str(out / f"page_{len(result['pages'])}.png"), full_page=True)
            result["pages"].append({"url": pg.url, "frames": frames})
        (out / "result.json").write_text(json.dumps({**result, "records": recs[n0:], "blocked": blocked},
                                                    ensure_ascii=False, indent=1), encoding="utf-8")
        for pg in opened:
            pg.close()
        page.close()
    print("打开的页面：", [x["url"][:200] for x in result["pages"]])
    print("拦截写请求：", blocked)
    for r in recs[n0:]:
        print(f"  {r['i']:4d} {r['method']} {r['status']} {r['bytes']:>8d} {r['url'][:200]}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--open":
        raise SystemExit(open_row(sys.argv[2]))
    raise SystemExit(main())
