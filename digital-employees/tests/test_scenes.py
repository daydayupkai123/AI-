"""场景专属能力：跨单据汇总（只取每单最新且未被取代的报告）、金额解析、事项审批权限查询（金额落档）。"""
import time

from core.knowledge.base import RegulationBase
from core.knowledge.regulations import Clause, parse_range
from employees import scenes
from tests.support.env import temp_store


def _report(store, rid, rules, superseded=False):
    tid = store.create_task("contract", "contract", rid, "v1", trigger_by="auto")
    store.save_report(tid, {"header": {"subject": f"合同 {rid}"}, "rules": rules})
    store.finish_task(tid, "done")
    time.sleep(0.01)
    return tid


def test_insight_uses_latest_unsuperseded_reports(tmp_path):
    store = temp_store(tmp_path)
    old = _report(store, "100", [{"rule_id": "R17", "name": "合同主体资信", "code": "issue", "status": "发现问题",
                                  "message": "旧结论", "evidence": []}])
    new = _report(store, "100", [{"rule_id": "R17", "name": "合同主体资信", "code": "pass", "status": "核查通过"}])
    store.supersede_previous(new)
    _report(store, "200", [{"rule_id": "R17", "name": "合同主体资信", "code": "review", "status": "人工复核",
                            "message": "天眼查查询未完成", "evidence": [{"file": "合同.pdf", "page": 2, "snippet": "甲方"}]},
                           {"rule_id": "R01", "name": "合同价款与中标价一致性", "code": "issue", "status": "发现问题"}])
    d = scenes.insight(store, "credit")
    assert d["reviewed"] == 2 and d["checked"] == 2 and d["hits"] == 1
    assert [r["request_id"] for r in d["rows"]] == ["200"] and d["rows"][0]["hits"][0]["rule_id"] == "R17"
    assert old not in [r["task_id"] for r in d["rows"]]
    assert scenes.insight(store, "clauses")["rows"][0]["hits"][0]["rule_id"] == "R01"


def test_parse_amount_wan():
    assert scenes.parse_amount_wan("80") == 80
    assert scenes.parse_amount_wan("80万元") == 80
    assert scenes.parse_amount_wan("1,200,000元") == 120
    assert scenes.parse_amount_wan("1.2亿") == 12000
    assert scenes.parse_amount_wan("五万") is None


def _clause(tier, final, meetings, no=46):
    return Clause(doc_id="authority_manual", doc_name="公司权责手册", ref=f"运营管理部第{no}项", no=no, dept="运营管理部",
                  title="公司非业务合同采购结果", tier=tier, range=parse_range(tier), final=final, meetings=meetings)


def test_authority_picks_tier_by_amount():
    kb = RegulationBase([{"id": "authority_manual", "name": "公司权责手册", "state": "enabled"}], [
        _clause("≥30万元", ["总经理办公会"], ["总经理办公会"]),
        _clause("10(含)-30万元", ["总经理签批"], ["不上会（签批）"]),
        _clause("＜10万元", ["分管领导"], ["不上会（签批）"])])
    top = scenes.authority(kb, "非业务合同采购结果", 80)["results"][0]
    assert top["status"] == "matched" and top["final"] == ["总经理办公会"] and top["meetings"] == ["总经理办公会"]
    assert [t["fit"] for t in top["tiers"]] == [True, False, False]
    assert scenes.authority(kb, "非业务合同采购结果", 15)["results"][0]["final"] == ["总经理签批"]
    assert scenes.authority(kb, "非业务合同采购结果", None)["results"][0]["status"] == "need_amount"
