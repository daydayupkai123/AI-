"""财务报销初审：样例端到端 + 43 条规则逐条单测（构造单据与附件，不经文件解析）。"""
import json

import pytest

from core import settings
from core.materials import Material
from core.rules.engine import run_rule
from core.sources.local import LocalCaseClient
from employees.reimburse import graph as rgraph
from employees.reimburse import rules as R
from employees.reimburse import samples
from employees.reimburse.extract import groups_of
from employees.reimburse.model import Claim
from tests.support.env import by_id, temp_resources, temp_store

CFG = settings.load("reimburse.yaml")


# ---------------------------------------------------------------- 端到端

@pytest.fixture()
def env(tmp_path, monkeypatch):
    cases = tmp_path / "cases"
    samples.write(cases)
    monkeypatch.setattr(rgraph, "REPORTS", tmp_path / "reports")
    return {"store": temp_store(tmp_path), "resources": temp_resources(tmp_path), "client": LocalCaseClient("reimburse", root=cases)}


def run(env, case_id):
    events = []
    final = rgraph.run(case_id, env["store"], None, on_event=events.append, source="local", client=env["client"], resources=env["resources"])
    return final, events


def test_travel_with_entertain(env):
    final, events = run(env, "DEMO-BX-001")
    r = by_id(final["results"])
    assert {x["group"] for x in final["results"]} == {"差旅费", "业务招待费"}
    assert len(final["results"]) == 20
    issue = ["TRV-01", "TRV-02", "TRV-04", "TRV-07", "TRV-08", "ENT-02", "ENT-03", "ENT-06", "ENT-07", "ENT-09",
             "ENT-10", "ENT-11", "ENT-12"]
    for rid in issue:
        assert r[rid]["code"] == "issue", (rid, r[rid]["message"], r[rid]["items"])
        assert r[rid]["evidence"], rid
    assert r["TRV-03"]["code"] == "pass" and r["TRV-05"]["code"] == "pass"
    assert r["TRV-06"]["code"] == "notrun" and "待确认 01" in r["TRV-06"]["message"]
    assert r["ENT-08"]["code"] == "pass"  # 招待费发票只有一张，火车票连号不算招待费连号
    for rid in ("ENT-01", "ENT-04", "ENT-05"):
        assert r[rid]["code"] == "na"
    assert "咨询公司" in r["ENT-12"]["message"]
    assert "中国石油" in " ".join(r["ENT-06"]["items"])
    rep = final["report"]
    assert rep["verdict"]["title"] == f"AI 初审存在风险提示 {len(issue)} 项"
    assert [e["node"] for e in events if e["type"] == "node.completed"] == rgraph.NODES
    json.dumps(rep, ensure_ascii=False)


def test_office_clean(env):
    final, _ = run(env, "DEMO-BX-002")
    r = by_id(final["results"])
    assert [x["rule_id"] for x in final["results"]] == ["OFF-01", "OFF-02", "OFF-03", "OFF-04", "OFF-05"]
    assert all(r[k]["code"] == "pass" for k in ("OFF-01", "OFF-02", "OFF-03", "OFF-05")), r
    assert r["OFF-04"]["code"] == "missing" and "负面清单" in r["OFF-04"]["message"]
    assert final["report"]["verdict"]["title"] == "AI 初审通过"


def test_meeting_fee(env):
    final, _ = run(env, "DEMO-BX-003")
    r = by_id(final["results"])
    assert r["MTG-01"]["code"] == "pass" and r["MTG-02"]["code"] == "pass"
    assert r["MTG-03"]["code"] == "issue" and "王五" in " ".join(r["MTG-03"]["items"])


# ---------------------------------------------------------------- 规则单测

def mat(name, role, text="", kind="docx", ocr=False):
    pages = [{"no": 1, "method": "ocr" if ocr else "text", "text": text}]
    return Material(sig="0" * 64, filename=name, role=role, doc={"status": "ok", "kind": kind, "pages": pages})


def facts(claim: dict, docs=(), seals=None, cfg=None):
    return {"claim": Claim.of(claim), "materials": list(docs), "seals": seals or {}, "cfg": cfg or CFG, "has_claim": True}


RULES = {r.id: r for r in R.RULES}


def code(rid, f):
    return run_rule("reimburse", R.VERSION, RULES[rid], f)


def inv(no, **kw):
    return {"number": no, "kind": kw.pop("kind", "数电发票普通发票"), **kw}


TRIP = {"start": "2026-09-01", "end": "2026-09-03", "days": 3, "subsidy_days": 2}
ENT_OK = {"type": "商务招待", "units": ["某设计院有限公司"], "guests": 4, "accompany": 4, "date": "2026-09-02", "total": 1500}


CASES = [
    # 差旅
    ("TRV-01", {"travel": TRIP}, [mat("出差行程单.docx", "itinerary", "出差日期 2026年9月1日 至 2026年9月3日")], "pass"),
    ("TRV-01", {"travel": TRIP}, [mat("出差行程单.docx", "itinerary", "2026年9月2日 至 2026年9月3日")], "issue"),
    ("TRV-01", {"travel": TRIP}, [], "missing"),
    ("TRV-02", {"travel": TRIP, "invoices": [inv("1", kind="数电票铁路电子客票", travel_date="2026-09-02")]}, [], "pass"),
    ("TRV-02", {"travel": TRIP, "invoices": [inv("1", kind="数电票铁路电子客票", travel_date="2026-09-08")]}, [], "issue"),
    ("TRV-02", {"travel": TRIP, "invoices": [inv("1", kind="数电票铁路电子客票", travel_date="2026-09-08", remark="退票")]}, [], "pass"),
    ("TRV-02", {"travel": TRIP, "invoices": [inv("1")]}, [], "na"),
    ("TRV-03", {"travel": TRIP, "invoices": [inv("1", items=["*运输服务*客运服务费"], remark="出行日期：2026年9月9日")]}, [], "issue"),
    ("TRV-03", {"travel": TRIP, "invoices": [inv("1", items=["*运输服务*客运服务费"], remark="出行日期：2026年9月2日")]}, [], "pass"),
    ("TRV-03", {"travel": TRIP, "invoices": [inv("1", items=["*住宿服务*住宿费"], remark="入住2026年9月9日")]}, [], "na"),
    ("TRV-04", {"invoices": [inv("10000001"), inv("10000002")]}, [], "issue"),
    ("TRV-04", {"invoices": [inv("10000001"), inv("10000005")]}, [], "pass"),
    ("TRV-04", {}, [], "missing"),
    ("TRV-05", {"invoices": [inv("1", amount=86.5, items=["*运输服务*客运服务费"], remark="出行人：李明 出行日期：2026年9月2日")]},
     [mat("滴滴行程单.pdf", "ride_detail", "合计 86.50 元")], "pass"),
    ("TRV-05", {"invoices": [inv("1", amount=86.5, items=["*运输服务*客运服务费"], remark="出行日期：2026年9月2日")]}, [], "issue"),
    ("TRV-06", {"travel": {**TRIP, "reason": "院车出差", "subsidy_amount": 150}}, [], "notrun"),
    ("TRV-07", {"expenses": [{"type": "业务招待费"}], "entertain": {**ENT_OK, "accompany": 5}}, [], "issue"),
    ("TRV-07", {"expenses": [{"type": "业务招待费"}], "entertain": ENT_OK}, [], "pass"),
    ("TRV-07", {"expenses": [{"type": "差旅费"}]}, [], "na"),
    ("TRV-08", {"expenses": [{"type": "业务招待费"}], "travel": {**TRIP, "subsidy_days": 3}}, [], "issue"),
    ("TRV-08", {"expenses": [{"type": "业务招待费"}], "travel": TRIP}, [], "pass"),
    # 业务招待
    ("ENT-01", {"entertain": {**ENT_OK, "type": "其他公务招待"}}, [], "issue"),
    ("ENT-01", {"entertain": {**ENT_OK, "type": "其他公务招待"}}, [mat("派出单位公函.pdf", "official_letter", "公函")], "pass"),
    ("ENT-01", {"entertain": {**ENT_OK, "type": "其他公务招待"}, "remark": "特殊情况，公函事后补"}, [], "pass"),
    ("ENT-01", {"entertain": ENT_OK}, [], "na"),
    ("ENT-02", {"entertain": {**ENT_OK, "guests": 8, "accompany": 4}}, [], "pass"),     # >5 人，1/2 → 4
    ("ENT-02", {"entertain": {**ENT_OK, "guests": 8, "accompany": 5}}, [], "issue"),
    ("ENT-02", {"entertain": {**ENT_OK, "type": "其他公务招待", "guests": 10, "accompany": 3}}, [], "pass"),
    ("ENT-02", {"entertain": {**ENT_OK, "type": "其他公务招待", "guests": 11, "accompany": 4}}, [], "pass"),  # 11/3 向上取整 4
    ("ENT-02", {"entertain": {**ENT_OK, "type": "其他公务招待", "guests": 11, "accompany": 5}}, [], "issue"),
    ("ENT-03", {"grade": "专业通道8级", "entertain": {**ENT_OK, "total": 1600}}, [], "pass"),      # 400/人
    ("ENT-03", {"grade": "专业通道8级", "entertain": {**ENT_OK, "total": 1800}}, [], "review"),    # 450：一般档超，高档不超
    ("ENT-03", {"grade": "专业通道12级", "entertain": {**ENT_OK, "total": 1800}}, [], "pass"),
    ("ENT-03", {"grade": "专业通道8级", "entertain": {**ENT_OK, "total": 2400}}, [], "issue"),     # 600 两档都超
    ("ENT-04", {"entertain": {**ENT_OK, "type": "其他公务招待", "gift": True}}, [], "issue"),
    ("ENT-04", {"entertain": {**ENT_OK, "type": "其他公务招待"}}, [], "pass"),
    ("ENT-05", {"entertain": {**ENT_OK, "gift": True, "gift_per_person": 280, "gift_times": 1}},
     [mat("纪念品购物明细.pdf", "gift_detail", "明细")], "pass"),
    ("ENT-05", {"entertain": {**ENT_OK, "gift": True, "gift_per_person": 350, "gift_times": 2}}, [], "issue"),
    ("ENT-05", {"entertain": ENT_OK}, [], "na"),
    ("ENT-06", {"entertain": {**ENT_OK, "units": ["国家电网有限公司"]}}, [], "issue"),
    ("ENT-06", {"entertain": {**ENT_OK, "type": "其他公务招待", "units": ["国家电网有限公司"]}}, [], "pass"),
    ("ENT-06", {"entertain": {**ENT_OK, "units": ["中国某某集团有限公司"]}}, [], "review"),
    ("ENT-06", {"entertain": ENT_OK}, [], "pass"),
    ("ENT-07", {"entertain": ENT_OK}, [mat("招待清单.docx", "entertain_list", "实际参加人数：4人 陪同人数：4人 实际费用总额：1500.00元")], "pass"),
    ("ENT-07", {"entertain": ENT_OK}, [mat("招待清单.docx", "entertain_list", "实际参加人数：6人 陪同人数：4人 实际费用总额：1500.00元")], "issue"),
    ("ENT-07", {"entertain": ENT_OK}, [], "missing"),
    ("ENT-08", {"doc_type": "业务招待费报销单", "invoices": [inv("20000001"), inv("20000002")]}, [], "issue"),
    ("ENT-09", {"doc_type": "业务招待费报销单", "submit_date": "2026-03-01", "invoices": [inv("1", date="2025-12-30")]}, [], "issue"),
    ("ENT-09", {"doc_type": "业务招待费报销单", "submit_date": "2026-01-20", "invoices": [inv("1", date="2025-12-30")]}, [], "pass"),
    ("ENT-10", {"doc_type": "业务招待费报销单", "entertain": ENT_OK, "invoices": [inv("1", date="2026-09-03")]}, [], "pass"),
    ("ENT-10", {"doc_type": "业务招待费报销单", "entertain": ENT_OK, "invoices": [inv("1", date="2026-09-05")]}, [], "issue"),
    ("ENT-11", {"doc_type": "差旅报销单", "travel": {**TRIP, "subsidy_days": 3}}, [], "issue"),
    ("ENT-11", {"doc_type": "业务招待费报销单"}, [], "na"),
    ("ENT-12", {"reason": "招待上级公司检查组"}, [], "issue"),
    ("ENT-12", {"reason": "招待业主单位"}, [], "pass"),
    # 办公费
    ("OFF-01", {"invoices": [inv("1", items=["*办公用品*办公用品"])]}, [], "issue"),
    ("OFF-01", {"invoices": [inv("1", items=["*纸制品*复印纸 A4"])]}, [], "pass"),
    ("OFF-01", {"invoices": [inv("1", kind="定额发票")]}, [], "issue"),
    ("OFF-02", {"invoices": [inv("1", amount=100, detail_total=90)]}, [], "issue"),
    ("OFF-02", {"invoices": [inv("1", amount=100, detail_total=100)]}, [], "pass"),
    ("OFF-02", {"amount": 120, "invoices": [inv("1", kind="定额发票", amount=100)]},
     [mat("清单.docx", "purchase_list", "合计：120.00元")], "issue"),
    ("OFF-03", {"flags": {"consecutive": "是"}}, [], "issue"),
    ("OFF-03", {"invoices": [inv("30000001"), inv("30000003")]}, [], "pass"),
    ("OFF-04", {"invoices": [inv("1", items=["*食品*月饼"])]}, [], "missing"),
    ("OFF-05", {"invoices": [inv("1", items=["*预付卡*储值卡充值"])]}, [], "issue"),
    ("OFF-05", {"invoices": [inv("1", items=["*纸制品*复印纸"])]}, [], "pass"),
    # 车辆使用费
    ("VEH-01", {"vehicle": {"item": "燃油费"}, "invoices": [inv("1", items=["*汽油*92号汽油"])]}, [], "pass"),
    ("VEH-01", {"vehicle": {"item": "燃油费"}, "invoices": [inv("1", items=["*停车服务*停车费"])]}, [], "issue"),
    ("VEH-02", {"vehicle": {"item": "保养费", "plate": "鲁A12345"}}, [mat("维修清单.pdf", "repair_list", "清单")], "issue"),
    ("VEH-02", {"vehicle": {"item": "保养费", "plate": "鲁A12345"}},
     [mat("维修清单.pdf", "repair_list", "清单"), mat("送修单.pdf", "repair_order", "送修")], "pass"),
    ("VEH-02", {"vehicle": {"item": "车辆租赁费", "plate": "其他"}}, [], "issue"),
    ("VEH-02", {"vehicle": {"item": "燃油费", "plate": "鲁A12345"}}, [], "na"),
    ("VEH-03", {"amount": 900, "vehicle": {"item": "车辆修理费"}}, [mat("送修单.pdf", "repair_order", "费用预算：800.00元")], "issue"),
    ("VEH-03", {"amount": 700, "vehicle": {"item": "车辆修理费"}}, [mat("送修单.pdf", "repair_order", "费用预算：800.00元")], "pass"),
    # 交通费
    ("TRA-01", {"invoices": [inv("1", amount=35.2, seller="滴滴出行科技有限公司")]}, [mat("出行明细.pdf", "ride_detail", "合计 35.20")], "pass"),
    ("TRA-01", {"invoices": [inv("1", amount=35.2, seller="滴滴出行科技有限公司")]}, [], "issue"),
    ("TRA-01", {"invoices": [inv("1", amount=35.2, seller="某出租汽车公司")]}, [], "na"),
    ("TRA-02", {"invoices": [inv("40000009"), inv("40000010")]}, [], "issue"),
    # 会议费
    ("MTG-01", {}, [mat("其他.docx", "other", "无关内容")], "issue"),
    ("MTG-01", {}, [mat("扫描件.pdf", "other", "", kind="pdf")], "review"),
    ("MTG-02", {}, [mat("内请报告.docx", "internal_request", "关于召开会议的请示，组织相关人员参会")], "issue"),
    ("MTG-02", {}, [mat("内请报告.docx", "internal_request", "参会人员：张三、李四")], "pass"),
    ("MTG-03", {"expenses": [{"person": "张三"}, {"person": "李四"}]}, [mat("公文流转单.docx", "doc_flow", "通用设计公文流转 参会人员：张三、李四")], "pass"),
    # 培训费
    ("TRN-01", {"expenses": [{"name": "生产生活费服务*培训费"}], "invoices": [inv("1", items=["*生产生活费服务*培训费"])]}, [], "pass"),
    ("TRN-01", {"expenses": [{"name": "培训费"}], "invoices": [inv("1", items=["*生产生活费服务*培训费"])]}, [], "issue"),
    # 通用报销单
    ("GEN-01", {"doc_type": "通用费用报销单（对公）", "dept": "综合管理部", "expenses": [{"item": "邮递费"}]}, [], "issue"),
    ("GEN-01", {"doc_type": "通用费用报销单（对公）", "dept": "综合管理部", "expenses": [{"item": "邮递费"}]},
     [mat("快递费结算分摊表.docx", "courier_split", "经办人：孙丽\n部门负责人：王强")], "pass"),
    ("GEN-01", {"doc_type": "通用费用报销单（对公）", "dept": "综合管理部", "expenses": [{"item": "邮递费"}]},
     [mat("快递费结算分摊表.docx", "courier_split", "经办人：孙丽\n部门负责人：\n")], "issue"),
    ("GEN-01", {"doc_type": "通用费用报销单（对公）", "dept": "综合管理部", "expenses": [{"item": "邮递费"}]},
     [mat("快递费结算分摊表.pdf", "courier_split", "经办人 部门负责人", kind="pdf", ocr=True)], "review"),
    ("GEN-02", {"doc_type": "通用费用报销单（对私）", "dept": "运营管理部", "expenses": [{"item": "邮递费", "amount": 56}]},
     [mat("运单明细.pdf", "waybill", "合计：56.00元")], "pass"),
    ("GEN-02", {"doc_type": "通用费用报销单（对私）", "dept": "运营管理部", "expenses": [{"item": "邮递费", "amount": 56}]},
     [mat("运单明细.pdf", "waybill", "合计：60.00元")], "issue"),
    ("GEN-03", {"expenses": [{"item": "房屋及建筑物租赁费"}]}, [mat("租房协议.pdf", "house_lease", "协议")], "issue"),
    ("GEN-03", {"expenses": [{"item": "房屋及建筑物租赁费"}]},
     [mat("租房协议.pdf", "house_lease", "协议"), mat("内请报告.docx", "internal_request", "请示")], "pass"),
    ("GEN-04", {"expenses": [{"item": "车辆租赁费"}]}, [], "issue"),
    ("GEN-04", {"expenses": [{"item": "车辆租赁费"}]}, [mat("租车申请.docx", "car_application", "申请")], "review"),
    ("GEN-05", {"expenses": [{"item": "修理费"}]}, [], "issue"),
    ("GEN-05", {"expenses": [{"item": "修理费"}]}, [mat("维修清单.docx", "repair_list", "合计 100.00元")], "review"),
    ("GEN-06", {"amount": 100, "expenses": [{"item": "修理费", "amount": 100}]}, [mat("维修清单.docx", "repair_list", "合计：100.00元")], "pass"),
    ("GEN-06", {"amount": 100, "expenses": [{"item": "修理费", "amount": 100}]}, [mat("维修清单.docx", "repair_list", "合计：120.00元")], "issue"),
    # 资产采购
    ("AST-01", {"assets": [{"name": "笔记本电脑", "amount": 8999}], "invoices": [inv("1", amount=8999, items=["*计算机*笔记本电脑"])]}, [], "pass"),
    ("AST-01", {"assets": [{"name": "笔记本电脑", "amount": 8999}], "invoices": [inv("1", amount=7999, items=["*计算机*笔记本电脑"])]}, [], "issue"),
    ("AST-02", {"asset_tier": "必备"}, [mat("资产入库单.docx", "asset_inbound", "入库"), mat("固定资产购买申请单.docx", "asset_request", "申请")], "pass"),
    ("AST-02", {"asset_tier": "专项"}, [mat("资产入库单.docx", "asset_inbound", "入库")], "issue"),
    ("AST-02", {"asset_tier": ""}, [], "missing"),
    ("AST-03", {}, [mat("资产入库单.docx", "asset_inbound", "验收人：张三\n保管人：李四")], "pass"),
    ("AST-03", {}, [mat("资产入库单.docx", "asset_inbound", "验收人：张三\n保管人：")], "issue"),
]


@pytest.mark.parametrize("rid,claim,docs,expect", CASES, ids=[f"{c[0]}-{i}" for i, c in enumerate(CASES)])
def test_rule(rid, claim, docs, expect):
    r = code(rid, facts(claim, docs))
    assert r["code"] == expect, (r["status"], r["message"], r["items"])
    if expect == "issue":
        assert r["message"] and (r["items"] or r["evidence"])


def test_every_rule_has_cases():
    covered = {c[0] for c in CASES}
    assert covered == {r.id for r in R.RULES}, sorted({r.id for r in R.RULES} - covered)
    assert len(R.RULES) == 43


def test_gen05_seal_detection():
    docs = [mat("维修清单.pdf", "repair_list", "合计 100.00元", kind="pdf")]
    assert code("GEN-05", facts({"expenses": [{"item": "修理费"}]}, docs, seals={"维修清单.pdf": 0.01}))["code"] == "pass"
    assert code("GEN-05", facts({"expenses": [{"item": "修理费"}]}, docs, seals={"维修清单.pdf": 0.0}))["code"] == "issue"


def test_groups_routing():
    assert groups_of(Claim.of({"doc_type": "差旅报销单", "expenses": [{"type": "业务招待费"}]})) == ["TRV", "ENT"]
    assert groups_of(Claim.of({"doc_type": "通用费用报销单（对公）"})) == ["GEN"]
    assert groups_of(Claim.of({"doc_type": "资产采购报销单"})) == ["AST"]
    assert groups_of(Claim.of({"doc_type": "未知单据"})) == []
