"""工作台界面截图（开发期验收用）：本机无界面 Chrome 按指定尺寸打开工作台，执行一段页面脚本后截图。

  python tools/checks/ui_shot.py <输出.png> "<页面脚本，async 函数体>" [--w 1440 --h 900 --full]

页面脚本示例：document.querySelector("#rail .rail-item[title='流程与规则']").click(); await sleep(2000);
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from playwright.sync_api import sync_playwright  # noqa: E402

from shared.portal_snapshot import _launch  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("script", nargs="?", default="")
    ap.add_argument("--w", type=int, default=1440)
    ap.add_argument("--h", type=int, default=900)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--url", default="http://127.0.0.1:8090/")
    a = ap.parse_args()
    if a.script.startswith("@"):  # 脚本写在文件里（避免命令行引号转义）
        a.script = Path(a.script[1:]).read_text(encoding="utf-8")
    with sync_playwright() as p:
        b = _launch(p)
        page = b.new_page(viewport={"width": a.w, "height": a.h})
        page.goto(a.url, wait_until="networkidle")
        page.wait_for_timeout(1200)
        if a.script:
            page.evaluate(f"async () => {{ const sleep = (ms) => new Promise(r => setTimeout(r, ms)); {a.script} }}")
        page.wait_for_timeout(600)
        page.screenshot(path=a.out, full_page=a.full)
        b.close()
    print(a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
