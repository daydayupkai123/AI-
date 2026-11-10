"""工作台 UI 实测（合同 / 三会 / 报销 / 采购入口）：附着调试 Chrome，新开标签页逐个发起本地样例审查并截图。

  python tools/ui_review_check.py [--out .runtime/ui/review] [--only contract,meeting,reimburse]

只访问本机工作台 http://127.0.0.1:8090，不访问任何客户系统。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8090/"
CASES = {"contract": ["DEMO-HT-001"], "meeting": ["DEMO-SH-001", "DEMO-SH-002"], "reimburse": ["DEMO-BX-001"]}


def wait_done(page, timeout_s: int) -> str:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        state = page.evaluate("""() => {
          const t = document.querySelectorAll('.think');
          const last = t[t.length - 1];
          if (!last) return 'none';
          if (last.querySelector('.okc')) return 'done';
          if (last.querySelector('.think-head .bad')) return 'failed';
          return 'running';
        }""")
        if state in ("done", "failed"):
            return state
        time.sleep(1)
    return "timeout"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".runtime" / "ui" / "review"))
    ap.add_argument("--only", default="contract,meeting,reimburse")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    with sync_playwright() as p:
        ctx = p.chromium.connect_over_cdp("http://127.0.0.1:9222").contexts[0]
        page = ctx.new_page()
        page.set_viewport_size({"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until="networkidle")
        page.screenshot(path=str(out / "00_welcome.png"))
        result["cards"] = page.evaluate("() => [...document.querySelectorAll('.pcard')].map(c => c.innerText.split('\\n')[0] + '|' + c.querySelector('.go').innerText)")
        for emp in args.only.split(","):
            for rid in CASES[emp]:
                page.click(f".conv[data-emp='{emp}']")
                page.wait_for_selector(".hero")
                page.screenshot(path=str(out / f"{emp}_0_hero.png"))
                page.fill("#chat-input", rid)
                page.press("#chat-input", "Enter")
                t0 = time.time()
                status = wait_done(page, args.timeout)
                time.sleep(1.2)
                info = page.evaluate("""() => {
                  const res = [...document.querySelectorAll('.result')].pop();
                  const v = res && res.querySelector('.vcard');
                  return {
                    verdict: v ? v.querySelector('.vt').innerText : null,
                    nums: v ? [...v.querySelectorAll('.num')].map(n => n.innerText.replace('\\n', ' ')) : [],
                    findings: res ? res.querySelectorAll('.fd').length : 0,
                    opinions: document.querySelectorAll('.live .op').length,
                    rows: res ? res.querySelectorAll('.rules-table tbody tr:not(.grp)').length : 0,
                    error: res && res.querySelector('.ecard') ? res.querySelector('.ecard').innerText.slice(0, 300) : null,
                    steps: [...document.querySelectorAll('.think')].pop()?.querySelectorAll('.stp.ok').length,
                  };
                }""")
                info.update(status=status, seconds=round(time.time() - t0, 1))
                result[f"{emp}:{rid}"] = info
                page.evaluate("() => { const t = [...document.querySelectorAll('.think')].pop(); t && t.classList.remove('closed'); }")
                page.screenshot(path=str(out / f"{emp}_{rid}_1_view.png"))
                for sel, tag in (("[...document.querySelectorAll('.think')].pop()", "5_progress"),
                                 ("[...document.querySelectorAll('.live')].pop()", "6_opinions"),
                                 ("[...document.querySelectorAll('.result')].pop()", "7_report")):
                    if page.evaluate(f"() => {{ const el = {sel}; if (!el) return false; el.scrollIntoView({{block: 'start'}}); return true; }}"):
                        time.sleep(0.3)
                        page.screenshot(path=str(out / f"{emp}_{rid}_{tag}.png"))
                page.screenshot(path=str(out / f"{emp}_{rid}_2_full.png"), full_page=True)
                el = page.query_selector("#messages")
                if el:
                    el.screenshot(path=str(out / f"{emp}_{rid}_3_messages.png"))
                page.evaluate("() => { const m = document.querySelector('#messages'); m.scrollTop = m.scrollHeight; }")
                time.sleep(0.4)
                page.screenshot(path=str(out / f"{emp}_{rid}_4_bottom.png"))
        page.click("#btn-newchat")
        page.click(".chat-dock [data-act='rules']")
        time.sleep(1.5)
        page.screenshot(path=str(out / "rules_last.png"))
        page.click(".chat-actions [data-act='history']")
        time.sleep(1.2)
        page.screenshot(path=str(out / "history_last.png"))
        result["history_items"] = page.evaluate("() => document.querySelectorAll('#history-pop .hist[data-task]').length")
        result["page_errors"] = errors
        page.close()
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
