"""M0 接口摸底：附着到已登录的调试 Chrome，只读地记录客户系统的页面与接口。

  python tools/probes/m0_probe.py status                 # 查看标签页与登录状态
  python tools/probes/m0_probe.py capture <name> <url>   # 打开页面，记录其背后的 /api 响应
  python tools/probes/m0_probe.py table <dataKey> [--pages N]   # 按 dataKey 翻页取列表数据

纪律：只读。拦截一切形似提交/保存/退回/删除的请求；不点击任何按钮。
产物写到 .runtime/m0/<name>/，含会话相关内容，不入版本库。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".runtime" / "m0"

WRITE_PATTERN = re.compile(
    r"(submit|save|operation|reject|forward|delete|remove|approve|takeback|withdraw|"
    r"doback|remark/|signature|lock)",
    re.IGNORECASE,
)


def _guard(route):
    req = route.request
    if req.method != "GET" and WRITE_PATTERN.search(urlparse(req.url).path):
        print(f"  [BLOCKED] {req.method} {req.url[:160]}", flush=True)
        route.abort()
        return
    route.continue_()


def _attach(p):
    browser = p.chromium.connect_over_cdp(CDP)
    if not browser.contexts:
        raise SystemExit("调试 Chrome 没有可用的上下文")
    return browser, browser.contexts[0]


def cmd_status(_args):
    with sync_playwright() as p:
        browser, ctx = _attach(p)
        for i, page in enumerate(ctx.pages):
            title = ""
            try:
                title = page.title()
            except Exception:  # noqa: BLE001
                pass
            print(f"tab[{i}] {title!r} {page.url[:150]}")
        hosts = sorted({c["domain"] for c in ctx.cookies()})
        print("cookie domains:", ", ".join(hosts) or "(none)")
        logged_in = any(not urlparse(pg.url).netloc.startswith("login.") and "gt.cn" in pg.url for pg in ctx.pages)
        print("login_state:", "LIKELY_LOGGED_IN" if logged_in else "NOT_LOGGED_IN_OR_ON_LOGIN_PAGE")


def cmd_capture(args):
    out = OUT / args.name
    out.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as p:
        browser, ctx = _attach(p)
        page = ctx.new_page()
        page.route("**/*", _guard)

        def on_response(resp):
            url = resp.url
            if "/api/" not in url:
                return
            try:
                ctype = resp.headers.get("content-type", "")
                body = resp.body()
            except Exception:  # noqa: BLE001
                return
            idx = len(records) + 1
            fname = f"{idx:03d}.json"
            entry = {"idx": idx, "method": resp.request.method, "status": resp.status,
                     "url": url, "ctype": ctype, "bytes": len(body), "file": fname,
                     "post": (resp.request.post_data or "")[:2000]}
            records.append(entry)
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
                (out / fname).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception:  # noqa: BLE001
                (out / fname.replace(".json", ".txt")).write_bytes(body[:200000])
                entry["file"] = fname.replace(".json", ".txt")

        page.on("response", on_response)
        print(f"open {args.url}", flush=True)
        page.goto(args.url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(args.wait * 1000)
        final = page.url
        try:
            page.screenshot(path=str(out / "page.png"), full_page=False)
        except Exception:  # noqa: BLE001
            pass
        (out / "index.json").write_text(json.dumps({"final_url": final, "records": records},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
        page.close()
    print("final_url:", final)
    for r in records:
        print(f"  {r['idx']:3d} {r['method']:4s} {r['status']} {r['bytes']:>8d}  {r['url'][:150]}")
    print(f"saved -> {out}")


def cmd_table(args):
    out = OUT / (args.name or "table")
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser, ctx = _attach(p)
        req = ctx.request
        base = args.base.rstrip("/")
        cnt = req.post(f"{base}/api/ec/dev/table/counts", form={"dataKey": args.data_key}).json()
        print("counts:", cnt)
        rows = []
        for cur in range(1, args.pages + 1):
            r = req.post(f"{base}/api/ec/dev/table/datas",
                         form={"dataKey": args.data_key, "current": str(cur), "pageSize": str(args.page_size),
                               "sortParams": "[]"}).json()
            datas = r.get("datas") or []
            if cur == 1:
                (out / "columns.json").write_text(json.dumps(r.get("columns"), ensure_ascii=False, indent=1),
                                                  encoding="utf-8")
            rows.extend(datas)
            print(f"page {cur}: {len(datas)} rows")
            if len(datas) < args.page_size:
                break
        (out / "rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"saved {len(rows)} rows -> {out}")


def cmd_files(args):
    """Download every attachment listed in a captured loadForm (GET only) and hash it."""
    import hashlib

    src = OUT / args.name
    idx = json.loads((src / "index.json").read_text(encoding="utf-8"))
    rec = next(r for r in idx["records"] if "/reqform/loadForm" in r["url"])
    form = json.loads((src / rec["file"]).read_text(encoding="utf-8"))
    fmap = ((form.get("tableInfo") or {}).get("main") or {}).get("fieldinfomap") or {}
    maindata = form.get("maindata") or {}
    out = src / "files"
    out.mkdir(exist_ok=True)
    manifest = []
    with sync_playwright() as p:
        browser, ctx = _attach(p)
        for fid, f in fmap.items():
            if str(f.get("htmltype")) != "6":
                continue
            files = ((maindata.get(f"field{fid}") or {}).get("specialobj") or {}).get("filedatas") or []
            for fd in files:
                url = "https://contract.gt.cn" + fd["loadlink"]
                t0 = time.time()
                resp = ctx.request.get(url, timeout=120000)
                body = resp.body()
                sha = hashlib.sha256(body).hexdigest()
                name = fd.get("filename") or f"{fd.get('fileid')}.bin"
                (out / name).write_bytes(body)
                item = {"field": f"field{fid}", "label": f.get("fieldlabel"), "filename": name,
                        "status": resp.status, "ctype": resp.headers.get("content-type"),
                        "bytes": len(body), "sha256": sha, "ms": int((time.time() - t0) * 1000),
                        "head": body[:8].hex()}
                manifest.append(item)
                print(f"  {resp.status} {len(body):>9d}B {item['ms']:>5d}ms {sha[:16]}  {name}  ({item['ctype']})")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved {len(manifest)} files -> {out}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    c = sub.add_parser("capture")
    c.add_argument("name")
    c.add_argument("url")
    c.add_argument("--wait", type=int, default=15)
    t = sub.add_parser("table")
    t.add_argument("data_key")
    t.add_argument("--name")
    t.add_argument("--base", default="https://contract.gt.cn")
    t.add_argument("--pages", type=int, default=1)
    t.add_argument("--page-size", type=int, default=50)
    fl = sub.add_parser("files")
    fl.add_argument("name")
    args = ap.parse_args()
    {"status": cmd_status, "capture": cmd_capture, "table": cmd_table, "files": cmd_files}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
