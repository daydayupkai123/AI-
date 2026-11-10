"""本地事项取数源：从 .runtime/cases/<员工>/<单号>/case.json 读取表单、审批日志与附件。

用途：客户系统打通前的端到端联调、测试，以及「导入事项后审查」。返回结构与合同系统适配器一致
（RequestData / Attachment），流程图无需区分来源。

case.json：
  {"request_id", "workflow_name", "request_name", "node_name", "title", "summary",
   "fields": {"标签": "值", ...}, "approval_log": [...],
   "attachments": [{"file": "files/xx.pdf", "field_label": "附件"}], "extra": {...}}
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import RUNTIME
from ..errors import NoAccess
from .contract import Attachment, RequestData

SOURCE = "local"
CASES = RUNTIME / "cases"


class LocalCaseClient:
    def __init__(self, employee: str, root: Path = CASES):
        self.dir = Path(root) / employee

    def _case_dir(self, case_id: str) -> Path:
        d = (self.dir / case_id).resolve()
        if self.dir.resolve() not in d.parents or not (d / "case.json").exists():
            raise NoAccess(f"本地事项 {case_id} 不存在（{self.dir}）", title="本地事项不存在",
                           hint="请先导入事项，或运行 tools/make_demo_cases.py 生成本地样例。")
        return d

    def list(self) -> list[dict]:
        out = []
        if not self.dir.exists():
            return out
        for p in sorted(self.dir.glob("*/case.json")):
            c = json.loads(p.read_text(encoding="utf-8"))
            out.append({"request_id": c["request_id"], "title": c.get("title") or c.get("request_name"),
                        "summary": c.get("summary", ""), "tags": c.get("tags", []), "source": SOURCE})
        return out

    def fetch(self, case_id: str) -> RequestData:
        d = self._case_dir(case_id)
        c = json.loads((d / "case.json").read_text(encoding="utf-8"))
        fields = [{"field": f"local{i}", "label": k, "htmltype": "1", "value": v, "display": v}
                  for i, (k, v) in enumerate((c.get("fields") or {}).items(), start=1)]
        atts = []
        for i, a in enumerate(c.get("attachments") or [], start=1):
            name = a.get("filename") or Path(a["file"]).name
            path = d / a["file"]
            if not path.exists():
                raise FileNotFoundError(f"本地事项 {case_id} 缺少附件文件 {a['file']}")
            st = path.stat()
            # 版本号 = 大小 + 修改时间：文件未变时资料中心直接复用，替换文件后视为新版本
            atts.append(Attachment(field_key=f"local{i}", field_label=a.get("field_label", "附件"), filename=name,
                                   ext=Path(name).suffix.lstrip(".").lower(), file_id=str(i),
                                   image_file_id=f"{case_id}/{a['file']}", version_id=f"{st.st_size}-{st.st_mtime_ns}",
                                   upload_time="", secret_level="", loadlink=str(path)))
        return RequestData(request_id=str(c["request_id"]), workflow_id=c.get("workflow_id", "local"),
                           workflow_name=c.get("workflow_name", ""), request_name=c.get("request_name", ""),
                           node_name=c.get("node_name", ""), fields=fields, approval_log=c.get("approval_log", []),
                           attachments=atts, extra=c.get("extra") or {})

    def download(self, att: Attachment) -> bytes:
        return Path(att.loadlink).read_bytes()
