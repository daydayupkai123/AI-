"""公文适配器实测：python tools/m0_docflow_fetch.py "通设请字[2025]85号" [--download]（只读）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.session import CdpSessionProvider  # noqa: E402
from core.sources.docflow import DocflowClient  # noqa: E402


def main(rid: str, download: bool) -> None:
    c = DocflowClient(CdpSessionProvider().session())
    req = c.fetch(rid)
    print(f"{req.workflow_name}｜{req.request_name}｜节点 {req.node_name}｜{req.raw_params}｜{req.extra}")
    for f in req.fields:
        print(f"  {f['field']:22s} {f['label']:16s} {f['htmltype']:15s} {str(f['display'])[:90]}")
    for a in req.attachments:
        print("  附件", a.field_label, a.filename, a.upload_time, a.version_id)
        if download:
            data = c.download(a)
            print("     下载", len(data), "字节", data[:4])


if __name__ == "__main__":
    main(sys.argv[1], "--download" in sys.argv)
