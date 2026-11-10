"""列出门户「我的发起 / 已办 / 已阅」中的公文（只读）：python tools/m0_docflow_list.py 内部请示"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.session import CdpSessionProvider  # noqa: E402
from core.sources.docflow import LIST_TYPES, DocflowClient  # noqa: E402

if __name__ == "__main__":
    c = DocflowClient(CdpSessionProvider().session())
    kw = sys.argv[1] if len(sys.argv) > 1 else ""
    for typ in LIST_TYPES:
        for r in c._list(typ, kw, 100):
            print(typ, r.get("affairId"), r.get("templateName") or "", "|", r.get("subject"))
