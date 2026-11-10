"""界面自测：审查一笔单据后，用大模型闲聊与追问报告，截图。"""
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / ".runtime" / "ui"
OUT.mkdir(parents=True, exist_ok=True)


def wait_answer(page, timeout=180):
    t0 = time.time()
    n = page.locator(".llm-foot").count()
    while time.time() - t0 < timeout:
        page.wait_for_timeout(1000)
        feet = page.locator(".llm-foot")
        if feet.count() and feet.last.inner_text().strip():
            return time.time() - t0
        if page.locator(".m.bot .err").count():
            return -1
    return None


with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    page = b.contexts[0].new_page()
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto("http://127.0.0.1:8090/", wait_until="networkidle")
    page.click(".pcard.blue")
    page.wait_for_selector(".hero")
    page.wait_for_timeout(1500)
    page.click(".sq[data-q^='chat:']")
    print("intro answered in", wait_answer(page))
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / "07_chat_intro.png"))
    page.fill("#chat-input", "1674771")
    page.press("#chat-input", "Enter")
    for _ in range(60):
        page.wait_for_timeout(1000)
        if "完成" in page.locator(".think .tt").last.inner_text():
            break
    page.wait_for_timeout(800)
    page.fill("#chat-input", "P10 为什么判定为拿不准？我该怎么核实？")
    page.press("#chat-input", "Enter")
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT / "08_chat_thinking.png"))
    print("followup answered in", wait_answer(page))
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / "09_chat_followup.png"))
    page.close()
    print("saved ->", OUT)
