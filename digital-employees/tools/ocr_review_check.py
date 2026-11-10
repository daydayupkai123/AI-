"""换 OCR 引擎后的审查结论对比：用指定 OCR 配置离线重跑采购历史单据，逐条对比规则结论。

用法：
  python tools/ocr_review_check.py --config config/ocr.local.yaml 1674771 1672706

原件从正式资料中心只读；新引擎的解析结果与临时库放在 .runtime/m0/ocr_review_<配置名>/（重复运行命中缓存），
不写入正式资料中心与工作台。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("requests", nargs="+")
    args = ap.parse_args()
    os.environ["DE_OCR_CONFIG"] = str(Path(args.config).resolve())

    from core.config import RC_DB_PATH, STORE
    from core.parsing import ocr
    from core.resource.client import LocalResourceClient
    from core.resource.service import ResourceService
    from core.resource.store import ResourceStore
    from employees.procurement import graph as pgraph
    from tests.support.replay import NoSessions, ReplayClient, comparable, latest_report, rebuild_request, replay_store

    work = ROOT / ".runtime" / "m0" / f"ocr_review_{Path(args.config).stem}"
    work.mkdir(parents=True, exist_ok=True)
    db = work / "resource.sqlite3"
    if not db.exists():
        shutil.copy2(RC_DB_PATH, db)

    from core.resource.store import content_sig

    class IsolatedStore(ResourceStore):
        """原件优先读隔离目录、没有再读正式目录（内容寻址，只读）；新写入的原件（压缩包解出的文件）与解析结果都写隔离目录。"""

        def blob_path(self, sig: str) -> Path:
            local = self.root / "blobs" / sig[:2] / sig
            return local if local.exists() else STORE / "blobs" / sig[:2] / sig

        def put_blob(self, data: bytes, kind: str = "", ext: str = "") -> str:
            sig = content_sig(data)
            local = self.root / "blobs" / sig[:2] / sig
            if not local.exists():
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(data)
            self._exec("INSERT OR IGNORE INTO file_blob VALUES (?,?,?,?,?,?)",
                       (sig, len(data), kind, ext, str(local.relative_to(self.root)), time.time()))
            return sig

    rs = IsolatedStore(db_path=db, root=work / "store", legacy_db=None)
    rc = LocalResourceClient(ResourceService(rs, NoSessions()))
    pgraph.REPORTS = work / "reports"
    eng = ocr.engine()
    print(f"引擎：{eng.name} {json.dumps(eng.params(), ensure_ascii=False)}")
    summary = []
    for rid in args.requests:
        history = latest_report(rid)
        if not history:
            print(f"== {rid}：本地没有历史报告，跳过")
            continue
        req = rebuild_request(rid, history, db)
        events: list[dict] = []
        (work / rid).mkdir(exist_ok=True)
        t0 = time.time()
        final = pgraph.run(rid, replay_store(work / rid), NoSessions(), on_event=events.append,
                           client=ReplayClient(req), resources=rc)
        dt = time.time() - t0
        parsed = [e for e in events if e["type"] == "file.parsed"]
        ocr_pages = sum(e.get("ocr_pages") or 0 for e in parsed if e.get("cache") != "hit")
        old = {r[0]: r for r in comparable(history["rules"])}
        new = {r[0]: r for r in comparable(final["results"])}
        diff = [k for k in old if old[k] != new.get(k)]
        print(f"== {rid}：{len(parsed)} 份文件，新识别 OCR {ocr_pages} 页，{dt:.0f}s；"
              f"规则 {len(old)} 条，结论不同 {len(diff)} 条；摘要{'一致' if final['report']['summary'] == history['summary'] else '不同'}")
        for k in diff:
            o, n = old[k], new.get(k) or ("", "", "", "（缺失）")
            print(f"   {k} 历史 {o[1]}/{o[2]}：{o[3][:90]}")
            print(f"   {' ' * len(k)} 新   {n[1]}/{n[2]}：{n[3][:90]}")
        summary.append({"request_id": rid, "rules": len(old), "diff": diff, "ocr_pages": ocr_pages, "seconds": round(dt),
                        "old": {k: old[k] for k in diff}, "new": {k: new.get(k) for k in diff}})
    (work / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("明细：", work / "result.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
