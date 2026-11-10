"""天眼查登录（在调试 Chrome 中进行，验证码由人工在窗口中接力完成）。

  python tools/tyc_login.py check    # 是否已登录
  python tools/tyc_login.py login    # 用 TYC_USER / TYC_PASS 环境变量做密码登录

账号只从环境变量读取，不写入任何文件。
"""
from __future__ import annotations

import os
import sys
import time

from playwright.sync_api import sync_playwright

HOME = "https://www.tianyancha.com/"
LOGIN = "https://www.tianyancha.com/login"


def tyc_page(ctx):
    for pg in ctx.pages:
        if "tianyancha.com" in pg.url:
            return pg
    return ctx.new_page()


def state(page) -> dict:
    return page.evaluate("""() => {
      const btn = document.querySelector('.tyc-nav-user-btn');
      const t = btn ? btn.innerText.trim() : '';
      return {url: location.href, navUser: t, loggedIn: !!t && !/登录/.test(t)};
    }""")


def visible_text(page, limit=400):
    return page.evaluate("(n) => document.body.innerText.replace(/\\s+/g, ' ').slice(0, n)", limit)


def switch_to_password(page):
    if page.locator(".title-password").count() == 0 or not page.locator(".title-password").first.is_visible():
        card = page.locator(".login-main").first.bounding_box()
        page.mouse.click(card["x"] + card["width"] - 25, card["y"] + 22)
        page.wait_for_timeout(1200)
    page.locator(".title-password").first.click()
    page.wait_for_timeout(800)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = tyc_page(browser.contexts[0])
        page.set_viewport_size({"width": 1440, "height": 900})
        page.bring_to_front()
        if cmd == "check":
            page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            print(state(page))
            return
        user, pwd = os.environ.get("TYC_USER", ""), os.environ.get("TYC_PASS", "")
        if not user or not pwd:
            raise SystemExit("缺少 TYC_USER / TYC_PASS 环境变量")
        page.goto(LOGIN, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        switch_to_password(page)
        inputs = page.locator(".login-main input:visible")
        print("visible inputs:", [(inputs.nth(i).get_attribute("type"), inputs.nth(i).get_attribute("placeholder"))
                                  for i in range(inputs.count())])
        page.locator(".login-main input[placeholder*='手机'], .login-main input[placeholder*='账号']").locator("visible=true").first.fill(user)
        page.locator(".login-main input[type=password]").locator("visible=true").first.fill(pwd)
        icon = page.locator(".login-main .login-bottom i.tic").first
        if "weigouxuan" in (icon.get_attribute("class") or ""):
            icon.click()
            page.wait_for_timeout(400)
        print("agree icon:", icon.get_attribute("class"))
        buttons = page.locator(".login-main button:visible, .login-main [class*=btn]:visible")
        labels = [buttons.nth(i).inner_text().strip() for i in range(buttons.count())]
        print("buttons:", labels)
        target = next((i for i, t in enumerate(labels) if t.replace(" ", "") in ("登录", "登录/注册")), None)
        if target is None:
            raise SystemExit("未找到登录按钮")
        buttons.nth(target).click()
        print("已点击登录。如出现滑块或短信验证，请在调试 Chrome 窗口里完成（最多等 120 秒）。", flush=True)
        deadline = time.time() + 120
        last = ""
        while time.time() < deadline:
            page.wait_for_timeout(3000)
            try:
                st = state(page)
            except Exception:  # noqa: BLE001
                continue
            if st["loggedIn"]:
                print("登录成功:", st, flush=True)
                return
            txt = visible_text(page, 200)
            if txt != last:
                last = txt
                hint = [w for w in ("验证", "滑块", "拖动", "密码错误", "不正确", "频繁", "锁定", "异常") if w in txt]
                if hint:
                    print("页面提示:", hint, flush=True)
        print("未在时限内确认登录:", state(page))


if __name__ == "__main__":
    main()
