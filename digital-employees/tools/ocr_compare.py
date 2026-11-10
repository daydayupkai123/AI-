"""OCR 对比：从资料中心挑已用 RapidOCR 识别过的真实扫描件，按指定 OCR 配置在临时库中重新解析，逐页对比文字。

用法：
  python tools/ocr_compare.py --config config/ocr.local.yaml --limit 8 --max-pages 6

只读正式资料中心（读文件与已入库的识别结果），重新解析写在临时目录，不影响正式缓存。
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def pick(db: Path, limit: int, max_pages: int) -> list[dict]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = c.execute(
        "SELECT r.proc_key, r.content_sig, r.page_count, r.ocr_pages, "
        "(SELECT filename FROM file_occurrence o WHERE o.content_sig = r.content_sig LIMIT 1) "
        "FROM parse_result r WHERE r.ocr_pages > 0 AND r.ocr_pages <= ? AND r.status = 'ok' "
        "ORDER BY r.ocr_pages DESC, r.created_at DESC", (max_pages,)).fetchall()
    out, seen = [], set()
    for key, sig, pages, ocr_pages, name in rows:
        if sig in seen:
            continue
        seen.add(sig)
        base = {no: (m, t) for no, m, t in c.execute(
            "SELECT page_no, method, text FROM parse_page WHERE proc_key = ?", (key,))}
        out.append({"sig": sig, "filename": name or sig[:12], "pages": pages, "ocr_pages": ocr_pages, "base": base})
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="待测 OCR 配置（engine 与地址）")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--max-pages", type=int, default=6, help="只挑 OCR 页数不超过此值的文件")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    os.environ["DE_OCR_CONFIG"] = str(Path(args.config).resolve())

    from core.parsing import ocr
    from core.parsing.pipeline import Parser
    from core.config import RC_DB_PATH, STORE
    from core.resource.store import ResourceStore

    eng = ocr.engine()
    prod = ResourceStore(db_path=RC_DB_PATH, root=STORE, legacy_db=None)
    files = pick(RC_DB_PATH, args.limit, args.max_pages)
    tmp = Path(tempfile.mkdtemp(prefix="ocr_compare_"))
    store = ResourceStore(db_path=tmp / "rc.sqlite3", root=tmp / "store", legacy_db=None)
    parser = Parser(store, source_system="contract")
    print(f"引擎：{eng.name}  参数：{json.dumps(eng.params(), ensure_ascii=False)}  文件：{len(files)}")
    report, sims, total_s, total_pages = [], [], 0.0, 0
    for f in files:
        assert store.put_blob(prod.read_blob(f["sig"])) == f["sig"]
        t0 = time.time()
        doc = parser.parse(f["sig"], f["filename"])
        dt = time.time() - t0
        rows = []
        for p in doc.get("pages", []):
            m0, t0_text = f["base"].get(p["no"], (None, ""))
            if not str(m0 or "").startswith("ocr"):
                continue
            sim = difflib.SequenceMatcher(None, norm(t0_text), norm(p.get("text", ""))).ratio()
            rows.append({"page": p["no"], "method": p.get("method"), "similarity": round(sim, 3),
                         "chars_base": len(norm(t0_text)), "chars_new": len(norm(p.get("text", ""))),
                         "blocks_with_bbox": sum(1 for b in (p.get("blocks") or []) if b.get("bbox")),
                         "base": t0_text[:120], "new": (p.get("text") or "")[:120]})
            sims.append(sim)
        total_s += dt
        total_pages += len(rows)
        failed = [r["page"] for r in rows if r["method"] == "ocr-failed"]
        avg = sum(r["similarity"] for r in rows) / len(rows) if rows else 0
        print(f"- {f['filename'][:40]:<40} OCR {len(rows)} 页  {dt:5.1f}s  相似度 {avg:.2f}"
              f"{'  失败页 ' + str(failed) if failed else ''}")
        report.append({"filename": f["filename"], "sig": f["sig"], "status": doc.get("status"), "seconds": round(dt, 1),
                       "pages": rows})
    if sims:
        print(f"合计 {total_pages} 页，{total_s:.0f}s（{total_s / max(total_pages, 1):.1f}s/页），"
              f"平均相似度 {sum(sims) / len(sims):.2f}，≥0.8 的页 {sum(1 for s in sims if s >= 0.8)}/{len(sims)}")
    out = Path(args.out or ROOT / ".runtime" / "m0" / f"ocr_compare_{Path(args.config).stem}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"engine": eng.name, "params": eng.params(), "files": report}, ensure_ascii=False,
                              indent=2), encoding="utf-8")
    print("明细：", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
