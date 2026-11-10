"""平台页面截图试跑：按审查时的同一规则只读打开单据详情页并截图（不写档案），产物 .runtime/probe/portal_<单号>.png。

  python tools/portal_shot.py contract 1671817
  python tools/portal_shot.py docflow "通设请字[2026]76号"

待办单据不会打开（与审查时规则一致）；被拦截的写请求会列出来。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import portal  # noqa: E402
from core.session import provider_from_config  # noqa: E402


def main() -> int:
    source, rid = sys.argv[1], sys.argv[2]
    sess = provider_from_config()
    if source == "contract":
        from core.sources.contract import ContractClient
        client = ContractClient(sess.session())
    else:
        from core.sources.docflow import DocflowClient
        client = DocflowClient(sess.session())
    req = client.fetch(rid)
    tgt = portal.target(source, req)
    print("目标：", json.dumps(tgt, ensure_ascii=False))
    if tgt.get("skip"):
        return 0
    r = portal.capture(sess.session(), tgt["url"])
    out = ROOT / ".runtime" / "probe" / f"portal_{source}_{rid.replace('[', '').replace(']', '')}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    if r.get("png"):
        from PIL import Image, ImageDraw

        im = Image.open(io.BytesIO(r["png"])).convert("RGB")
        d = ImageDraw.Draw(im)
        for x0, y0, x1, y1 in r["pii"]:
            d.rectangle([x0, y0, x1, y1], fill=(46, 50, 56))
        im.save(out)
    print(f"耗时 {r.get('ms')} ms，尺寸 {r.get('width')}x{r.get('height')}，截断 {r.get('truncated')}，"
          f"打码 {len(r['pii'])} 处，页面请求 {len(r['ops'])} 个，拦截写请求 {len(r['blocked'])} 个，错误 {r.get('error')}")
    print("最终地址：", r.get("final_url"))
    for b in r["blocked"]:
        print("  [拦截]", b["method"], b["url"][:150])
    for o in r["ops"][:40]:
        print(f"  {o['at']:6.2f}s {o['type'][:5]:5s} {o['method']:4s} {o['status']} {o['url'][:130]}")
    print("截图（已打码预览）：", out if r.get("png") else "无")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
