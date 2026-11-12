"""三会测试事项：取公文系统「公司数据查询 → 内部请示查询」中已结束的真实请示（只读），在其材料上注入已知问题，
生成本地事项 .runtime/cases/meeting/REAL-SH-*，每条写明注入的问题与预期命中的审查节点。

  .venv\\Scripts\\python.exe tools/samples/make_meeting_real_cases.py [底稿内请号] [混入材料的内请号]

默认底稿：通设请字[2026]342号（智能体开发平台及数字员工建设项目采购结果，总经理办公会，6 份材料）；
默认混入：通设请字[2026]307号（广联达造价软件加密锁租赁服务项目采购结果）的评审报告。
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from shared.session import provider_from_config  # noqa: E402
from shared.source_adapters.docflow import DocflowClient  # noqa: E402
from shared.source_adapters.local import CASES  # noqa: E402

BASE, DONOR = "通设请字[2026]342号", "通设请字[2026]307号"
MEETINGS = ("董事会", "党委会", "总经理办公会", "专题会", "不上会")


def _fetch(c: DocflowClient, rid: str, out: Path) -> tuple[dict, list[dict]]:
    req = c.fetch(rid)
    if req.raw_params.get("flow_state") not in (None, "已结束"):
        raise SystemExit(f"{rid} 流程未结束，不使用")
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for a in req.attachments:
        p = out / a.filename
        if not p.exists():
            p.write_bytes(c.download(a))
            time.sleep(0.5)
        files.append({"filename": a.filename, "path": p, "field_label": a.field_label})
    fields = {f["label"]: f["display"] for f in req.fields if f["htmltype"] not in ("attachment",)}
    return {"req": req, "fields": fields}, files


def _case(cid: str, base: dict, files: list[dict], *, fields: dict | None = None, drop=(), add=(), tags=(),
          summary: str, expect: dict, kw: dict | None = None) -> Path:
    """expect：{节点: 预期被指出的问题}；kw：{节点: [该节点意见中必须出现的词]}，用于验收时确认是因注入的问题而被指出。"""
    d = CASES / "meeting" / cid
    if d.exists():
        shutil.rmtree(d)
    (d / "files").mkdir(parents=True)
    atts = []
    for f in [x for x in files if not any(re.search(p, x["filename"]) for p in drop)] + list(add):
        shutil.copy2(f["path"], d / "files" / f["filename"])
        atts.append({"file": f"files/{f['filename']}", "field_label": f["field_label"]})
    req = base["req"]
    body = {"request_id": cid, "workflow_name": "内部请示（真实材料·测试改造）",
            "request_name": f"{req.request_name.split('：', 1)[-1]}（{'、'.join(tags)}）",
            "node_name": "三会审核岗", "title": base["fields"].get("标题") or req.request_name,
            "tags": ["真实材料", *tags], "summary": summary,
            "fields": {**base["fields"], **(fields or {})}, "attachments": atts,
            "extra": {"origin": {"mark": req.extra.get("mark"), "summaryId": req.raw_params.get("summaryId"),
                                 "flow_state": req.raw_params.get("flow_state")}, "expect": expect,
                      "expect_kw": kw or {}}}
    (d / "case.json").write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def _meeting(name: str) -> dict:
    return {"会议类型": name, **{m: ("是" if m == name else "否") for m in MEETINGS}}


def main(base_id: str, donor_id: str) -> int:
    c = DocflowClient(provider_from_config().session())
    raw = CASES.parent / "cases_src" / "meeting"
    base, files = _fetch(c, base_id, raw / base_id)
    _, donor_files = _fetch(c, donor_id, raw / donor_id)
    review = next((f for f in donor_files if "评审报告" in f["filename"]), None)
    mine = next((f for f in files if "评审报告" in f["filename"]), None)
    if not review or not mine:
        raise SystemExit(f"{base_id} / {donor_id} 缺少评审报告附件，无法构造「误传其他项目材料」样例")
    review = dict(review, filename=mine["filename"])  # 同名替换：模拟上传了其他项目的评审报告
    mark = base["req"].extra.get("mark") or base_id
    meeting = base["fields"].get("会议类型") or ""
    out = [
        _case("REAL-SH-A", base, files, tags=["原样对照"],
              summary=f"{mark} 原样（流程已结束的真实请示），作为其余改造样例的对照基线",
              expect={"note": "原样基线：记录审查结论，供 B–E 对比"}),
        _case("REAL-SH-B", base, files, fields=_meeting("董事会"), tags=["会议类型错误"],
              summary=f"{mark} 的会议类型由「{meeting}」改为「董事会」，与依据条款（权责手册）规定的决策机构不一致",
              expect={"N02": "会议类型与依据条款的决策机构不一致"}, kw={"N02": ["董事会"]}),
        _case("REAL-SH-C", base, files,
              fields={"审批/上会依据": re.sub(r"第\s*(\d+)\s*项", "第460项", base["fields"].get("审批/上会依据") or "")
                      or "公司《权责手册》运营管理部第460项"},
              tags=["依据条款不存在"], summary=f"{mark} 的审批/上会依据改为权责手册中不存在的「第460项」",
              expect={"N03": "依据条款在权责手册中找不到"}, kw={"N03": ["第460项"]}),
        _case("REAL-SH-D", base, files, drop=(r"评审报告", r"采购结果审批表"), tags=["附件与正文清单不符"],
              summary=f"{mark} 去掉「评审报告」「采购结果审批表」两份附件（正文附件清单仍列明这两份）",
              expect={"N05": "正文附件清单列明的评审报告、采购结果审批表在 OA 附件中找不到"},
              kw={"N05": ["未找到", "评审报告", "采购结果审批表"]}),
        _case("REAL-SH-E", base, files, drop=(r"评审报告",), add=(review,), tags=["误传其他项目材料"],
              summary=f"{mark} 的「{mine['filename']}」被替换成 {donor_id}（其他项目）的同名评审报告",
              expect={"N01": "评审报告与请示标题不是同一项目"}, kw={"N01": ["评审报告"]}),
    ]
    for d in out:
        print(d)
    return 0


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("-")]
    raise SystemExit(main(a[0] if a else BASE, a[1] if len(a) > 1 else DONOR))
