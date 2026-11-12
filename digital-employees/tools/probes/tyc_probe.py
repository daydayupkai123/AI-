"""天眼查只读探测：搜索公司 → 打开详情 → 记录页面可见模块与背后的 JSON 接口。

  python tools/probes/tyc_probe.py "<公司名>"
"""
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

name = sys.argv[1]
out = Path(__file__).resolve().parents[2] / ".runtime" / "tyc" / re.sub(r"[\\/:*?\"<>|]", "_", name)
out.mkdir(parents=True, exist_ok=True)
records = []

with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx = b.contexts[0]
    page = next((pg for pg in ctx.pages if "tianyancha.com" in pg.url), None) or ctx.new_page()

    def on_resp(resp):
        if resp.request.resource_type not in ("xhr", "fetch"):
            return
        try:
            body = resp.body()
            data = json.loads(body)
        except Exception:  # noqa: BLE001
            return
        i = len(records) + 1
        (out / f"{i:03d}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        records.append({"i": i, "status": resp.status, "url": resp.url[:200], "bytes": len(body)})

    page.on("response", on_resp)
    t0 = time.time()
    page.goto("https://www.tianyancha.com/search?key=" + quote(name), wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    first = page.locator("a[href*='/company/']").first
    href = first.get_attribute("href") if first.count() else None
    print("search ms:", int((time.time() - t0) * 1000), "first result:", href)
    if href:
        t0 = time.time()
        page.goto(href if href.startswith("http") else "https://www.tianyancha.com" + href,
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        print("detail ms:", int((time.time() - t0) * 1000), "url:", page.url)
        text = page.evaluate("() => document.body.innerText")
        (out / "detail.txt").write_text(text, encoding="utf-8")
        for key in ("法定代表人", "注册资本", "统一社会信用代码", "股东信息", "主要人员", "对外投资", "失信被执行人",
                    "被执行人", "破产重整", "限制消费令", "实际控制人", "最终受益人", "疑似关系", "VIP", "开通会员", "登录后查看"):
            n = text.count(key)
            if n:
                print(f"   {key}: {n}")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        print("   head:", " | ".join(lines[:40])[:600])
    page.remove_listener("response", on_resp)

(out / "index.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
print("json responses:", len(records))
for r in records[:40]:
    print(f"   {r['i']:3d} {r['status']} {r['bytes']:>7d} {r['url']}")
