"""Report whether each PDF/Office file in a folder has a usable text layer."""
import sys
from pathlib import Path

import fitz

for f in sorted(Path(sys.argv[1]).iterdir()):
    if f.suffix.lower() != ".pdf":
        continue
    d = fitz.open(f)
    txt = "".join(p.get_text() for p in d).strip()
    imgs = sum(len(p.get_images()) for p in d)
    meta = d.metadata or {}
    kind = "TEXT" if len(txt) > 50 * d.page_count else "SCAN?"
    print(f"{f.name}: {kind} pages={d.page_count} chars={len(txt)} images={imgs} "
          f"producer={meta.get('producer')!r} author={meta.get('author')!r}")
    print("    " + txt.replace("\n", " ")[:160])
