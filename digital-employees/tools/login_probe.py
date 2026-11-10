"""统一认证登录方式摸底：在全新的无界面浏览器（不带任何 Cookie）中打开登录页，看是否需要验证码 / 短信等二次校验。

  python tools/login_probe.py page            只看登录页：输入框、验证码图片、登录方式页签，截图，不提交
  python tools/login_probe.py try             用 DE_SERVICE_USER / DE_SERVICE_PASSWORD 提交一次，记录登录后出现的校验

账号密码只从环境变量读取；产物（截图、页面要素、登录相关请求，密码已打码）写到 .runtime/probe/login/，不入版本库。
只提交一次，避免触发账号锁定。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

LOGIN_URL = "https://login.gt.cn/idp/authcenter/ActionAuthChain?entityId=portal"
OUT = Path(__file__).resolve().parent.parent / ".runtime" / "probe" / "login"

_FORM_JS = """() => {
  const vis = el => { const b = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return b.width > 0 && b.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const inputs = [...document.querySelectorAll('input, select, textarea')].map(el => ({
    tag: el.tagName, type: el.type, name: el.name, id: el.id, placeholder: el.placeholder,
    visible: vis(el), cls: (el.className || '').toString().slice(0, 80)}));
  const imgs = [...document.querySelectorAll('img, canvas')].filter(vis).map(el => ({
    tag: el.tagName, src: (el.src || '').slice(0, 160), id: el.id, cls: (el.className || '').toString().slice(0, 80),
    w: el.getBoundingClientRect().width, h: el.getBoundingClientRect().height}));
  const clickable = [...document.querySelectorAll('a, button, li, span, div')].filter(el => vis(el)
    && el.children.length === 0 && (el.innerText || '').trim().length > 0 && (el.innerText || '').trim().length < 16)
    .map(el => el.innerText.trim());
  return {title: document.title, url: location.href, inputs, imgs, texts: [...new Set(clickable)].slice(0, 120)};
}"""

KEYWORDS = re.compile(r"(验证码|短信|动态码|滑块|拖动|captcha|verify|sms|二次|手机号|扫码|密码登录|账号登录)", re.I)


def _frames(page) -> list[dict]:
    out = []
    for f in page.frames:
        try:
            info = f.evaluate(_FORM_JS)
            info["frame"] = f.url[:160]
            out.append(info)
        except Exception:  # noqa: BLE001
            continue
    return out


def _summary(frames: list[dict]) -> dict:
    inputs = [i for fr in frames for i in fr["inputs"] if i["visible"] and i["type"] not in ("hidden",)]
    hits = sorted({t for fr in frames for t in fr["texts"] if KEYWORDS.search(t)}
                  | {i["placeholder"] for i in inputs if i["placeholder"] and KEYWORDS.search(i["placeholder"])})
    cap_imgs = [im for fr in frames for im in fr["imgs"]
                if re.search(r"(captcha|verify|code|kaptcha|valid)", im["src"] + im["id"] + im["cls"], re.I)]
    return {"visible_inputs": [{k: i[k] for k in ("type", "name", "id", "placeholder")} for i in inputs],
            "keyword_texts": hits, "captcha_images": cap_imgs}


def _open(p):
    try:
        browser = p.chromium.launch(channel="chrome", headless=True)
    except Exception:  # noqa: BLE001
        browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1366, "height": 860}, locale="zh-CN")
    return browser, ctx


def cmd_page(_args):
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser, ctx = _open(p)
        page = ctx.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        page.screenshot(path=str(OUT / "page.png"))
        frames = _frames(page)
        (OUT / "page.json").write_text(json.dumps(frames, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({"url": page.url, **_summary(frames)}, ensure_ascii=False, indent=1))
        browser.close()


def cmd_try(_args):
    user, pwd = os.environ.get("DE_SERVICE_USER", ""), os.environ.get("DE_SERVICE_PASSWORD", "")
    if not user or not pwd:
        sys.exit("请先设置环境变量 DE_SERVICE_USER / DE_SERVICE_PASSWORD")
    OUT.mkdir(parents=True, exist_ok=True)
    reqs: list[dict] = []

    def on_resp(resp):
        rq = resp.request
        if rq.resource_type not in ("xhr", "fetch", "document") or "login.gt.cn" not in resp.url:
            return
        body = ""
        try:
            body = resp.text()[:600]
        except Exception:  # noqa: BLE001
            pass
        post = (rq.post_data or "").replace(pwd, "***")[:400]
        reqs.append({"method": rq.method, "status": resp.status, "url": resp.url[:200], "post": post,
                     "body": body.replace(pwd, "***")})

    with sync_playwright() as p:
        browser, ctx = _open(p)
        page = ctx.new_page()
        page.on("response", on_resp)
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        user_box = page.locator("input[type=text]:visible, input[type=tel]:visible, input:not([type]):visible").first
        pwd_box = page.locator("input[type=password]:visible").first
        user_box.fill(user)
        pwd_box.fill(pwd)
        page.screenshot(path=str(OUT / "try_before.png"))
        pwd_box.press("Enter")
        t0 = time.time()
        while time.time() - t0 < 20:
            page.wait_for_timeout(1000)
            if "login.gt.cn" not in page.url:
                break
        page.wait_for_timeout(3000)
        page.screenshot(path=str(OUT / "try_after.png"))
        frames = _frames(page)
        cookies = sorted({c["domain"] for c in ctx.cookies()})
        result = {"final_url": page.url[:200], "left_login_page": "login.gt.cn" not in page.url,
                  "cookie_domains": cookies, **_summary(frames)}
        (OUT / "try.json").write_text(json.dumps({"result": result, "requests": reqs}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=1))
        for r in reqs[-8:]:
            print(f"  {r['method']} {r['status']} {r['url'][:120]}\n     body: {r['body'][:240]}")
        browser.close()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("page")
    sub.add_parser("try")
    args = ap.parse_args()
    {"page": cmd_page, "try": cmd_try}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
