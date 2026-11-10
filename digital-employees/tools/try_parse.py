"""本地试解析：把文件放入存储并解析（走签名缓存），打印耗时与文本片段。

  python tools/try_parse.py <文件路径> [...]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.parsing.pipeline import Parser, full_text  # noqa: E402
from core.resource.store import ResourceStore  # noqa: E402

if __name__ == "__main__":
    store = ResourceStore()
    parser = Parser(store, source_system="try")
    for f in sys.argv[1:]:
        p = Path(f)
        sig = store.put_blob(p.read_bytes(), ext=p.suffix.lstrip("."))
        t0 = time.time()
        doc = parser.parse(sig, p.name)
        txt = full_text(doc)
        ocr_pages = sum(1 for pg in doc["pages"] if pg.get("method") == "ocr")
        print(f"== {p.name} kind={doc['kind']} status={doc['status']} cache={doc['_cache']} "
              f"pages={len(doc['pages'])} ocr={ocr_pages} chars={len(txt)} {time.time() - t0:.1f}s")
        if doc.get("children"):
            print("   children:", [c["name"] for c in doc["children"]])
        out = Path(".runtime/try") / (p.stem + ".txt")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(txt, encoding="utf-8")
        print("   text ->", out)
