"""客户 OCR 连通与效果探测：python tools/ocr_probe.py [图片或PDF ...] [--url 地址]

不改配置、不入库：按 config/ocr.yaml 的 paddleocr_vl 参数（可用 --url 覆盖地址）直接调用，打印耗时与归一后的文字。
默认用客户测试图片 AI数字员工/ocr/ocr接口能力测试/ocr图片 下的前 3 张。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.parsing import ocr  # noqa: E402
from core.parsing.ocr_remote import PaddleVLEngine  # noqa: E402

SAMPLES = ROOT.parent / "ocr" / "ocr接口能力测试" / "ocr图片"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--url")
    args = ap.parse_args()
    cfg = dict((ocr.config().get("paddleocr_vl") or {}))
    if args.url:
        cfg["url"] = args.url
    eng = PaddleVLEngine(cfg)
    files = [Path(f) for f in args.files] or sorted(SAMPLES.glob("*.png"))[:3]
    print("接口：", eng.url)
    for f in files:
        data = f.read_bytes()
        t0 = time.time()
        if f.suffix.lower() == ".pdf":
            import pymupdf

            n = pymupdf.open(stream=data, filetype="pdf").page_count
            res = eng.ocr_pdf_pages(data, list(range(n))) if eng.send_pdf else eng.ocr_images(
                [p.get_pixmap(dpi=eng.dpi).tobytes("png") for p in pymupdf.open(stream=data, filetype="pdf")])
        else:
            res = eng.ocr_images([data])
        ok = [r for r in res if not r.get("failed")]
        print(f"== {f.name}：{len(ok)}/{len(res)} 页成功，{time.time() - t0:.1f}s")
        for r in res:
            print("   ", ("失败：" + r["error"]) if r.get("failed") else r["text"][:300].replace("\n", " ⏎ "))


if __name__ == "__main__":
    main()
