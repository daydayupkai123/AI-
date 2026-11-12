"""检查借用的会话能否访问合同系统接口（只读）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from shared.session import CdpSessionProvider  # noqa: E402

s = CdpSessionProvider().session()
print("cookies:", sorted({c.domain for c in s.cookies}))
r = s.post("https://contract.gt.cn/api/workflow/reqform/loadForm", data={"requestid": "1674771", "ismonitor": "1"},
           timeout=30, allow_redirects=False)
print("loadForm:", r.status_code, r.headers.get("content-type"), r.headers.get("location"))
print("body head:", r.text[:300].replace("\n", " "))
