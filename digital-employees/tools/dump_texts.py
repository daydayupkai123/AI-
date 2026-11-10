"""把某张单据已入库材料的解析全文导出为 txt（只读资料中心，不下载、不重新解析）：
python tools/dump_texts.py contract 1609472"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import RUNTIME  # noqa: E402
from core.resource.client import default_client  # noqa: E402


def main(source: str, rid: str) -> None:
    rc = default_client()
    snap = rc.request(source, rid)
    files = (snap or {}).get("files") or []
    if not files:
        print("资料中心没有该单据的文件记录")
        return
    out = RUNTIME / "probe" / f"text_{source}_{rid}"
    out.mkdir(parents=True, exist_ok=True)
    for f in {f["content_sig"]: f for f in files}.values():
        doc = rc.parsed(f["content_sig"], source)
        if not doc:
            print(f["filename"], "未解析")
            continue
        text = "\n".join(f"----- 第 {i + 1} 页 -----\n{p.get('text', '')}" for i, p in enumerate(doc.get("pages", [])))
        path = out / (Path(f["filename"]).name[:80] + ".txt")
        path.write_text(text, encoding="utf-8")
        print(path.name, len(text))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
