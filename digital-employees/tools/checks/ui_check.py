"""工作台界面自测：在调试 Chrome 新开标签，按桌面尺寸操作并截图。

  python tools/checks/ui_check.py [单号] [--wait 秒]
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[2] / ".runtime" / "ui"
OUT.mkdir(parents=True, exist_ok=True)
rid = sys.argv[1] if len(sys.argv) > 1 else "1674771"
wait_s = int(sys.argv[sys.argv.index("--wait") + 1]) if "--wait" in sys.argv else 120

with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    page = b.contexts[0].new_page()
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto("http://127.0.0.1:8090/", wait_until="networkidle")
    page.wait_for_timeout(1000)
    page.screenshot(path=str(OUT / "01_welcome.png"))
    page.click(".pcard.blue")
    page.wait_for_selector(".hero", timeout=10000)
    page.wait_for_timeout(900)
    page.screenshot(path=str(OUT / "02_hero.png"))
    page.click(".sq[data-q='samples']")
    page.wait_for_selector(".sug", timeout=60000)
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / "03_samples.png"))
    page.fill("#chat-input", rid)
    page.press("#chat-input", "Enter")
    t0 = time.time()
    title = ""
    while time.time() - t0 < wait_s:
        page.wait_for_timeout(1000)
        title = page.locator(".think .tt").last.inner_text()
        if "完成" in title or "中止" in title:
            break
    page.wait_for_timeout(1200)
    page.locator(".m.bot").last.scroll_into_view_if_needed()
    page.evaluate("document.querySelector('#messages').scrollTop = document.querySelector('.m.bot:last-child').offsetTop - 70")
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / "04_result.png"))
    page.locator(".think-head").last.click()
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / "05_process.png"))
    page.fill("#chat-input", "有哪些规则")
    page.press("#chat-input", "Enter")
    page.wait_for_selector(".rules-table >> nth=-1", timeout=10000)
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "06_rules.png"))
    print("title:", title, f"{time.time() - t0:.1f}s")
    print("saved ->", OUT)
    page.close()
