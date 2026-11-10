"""界面自测：门户未登录时发起审查，截取错误提示卡片。"""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / ".runtime" / "ui"
with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    page = b.contexts[0].new_page()
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto("http://127.0.0.1:8090/", wait_until="networkidle")
    page.reload(wait_until="networkidle")
    page.click(".pcard.blue")
    page.wait_for_selector(".hero")
    page.fill("#chat-input", "1674771")
    page.press("#chat-input", "Enter")
    page.wait_for_selector(".ecard", timeout=90000)
    page.wait_for_timeout(800)
    page.locator(".edet summary").last.click()
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / "10_error_card.png"))
    print("title:", page.locator(".think .tt").last.inner_text())
    page.close()
