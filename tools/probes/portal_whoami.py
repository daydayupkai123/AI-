"""查看调试 Chrome 中门户当前登录的账号（只读 sessionStorage）：python tools/probes/portal_whoami.py"""
import json

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    ctx = p.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=8000).contexts[0]
    pg = next((x for x in ctx.pages if "i.gt.cn" in x.url), ctx.pages[0])
    u = json.loads(pg.evaluate("() => sessionStorage.getItem('userInfo') || '{}'") or "{}")
    keep = {k: v for k, v in u.items() if isinstance(v, (str, int)) and any(
        t in k.lower() for t in ("name", "code", "account", "dept", "company", "login"))}
    print(json.dumps(keep, ensure_ascii=False, indent=1)[:1500])
