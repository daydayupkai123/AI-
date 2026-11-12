"""底座单元测试：通用判断、金额档位、制度库、天眼查解析、模型判定器、本地事项。"""
import json
from datetime import date
from pathlib import Path

import pytest

from shared.regulation_kb.base import RegulationBase, get_base
from shared.regulation_kb.regulations import describe_range, in_range, meeting_of, parse_range
from shared.rule_framework import common as C
from shared.rule_framework import status as st
from shared.rule_framework.engine import Rule, issue, ok, run_rules

FIX = Path(__file__).parents[1] / "fixtures"


# ---------------------------------------------------------------- 金额、日期、期限、连号

@pytest.mark.parametrize("text,yuan", [
    ("壹佰贰拾叁万肆仟伍佰陆拾柒元捌角玖分", 1234567.89), ("人民币叁佰伍拾万元整", 3500000.0), ("壹亿贰仟万元整", 120000000.0),
    ("拾万元整", 100000.0), ("壹佰零伍元", 105.0), ("玖仟玖佰玖拾玖元玖角", 9999.9)])
def test_cn_amount(text, yuan):
    assert C.cn_amount(text) == yuan


def test_amounts_require_unit():
    found = C.amounts("合同编号 2026001，金额 1,280,000.00 元，约 128 万元，￥500")
    assert [a.yuan for a in found] == [1280000.0, 1280000.0, 500.0]
    assert found[2].symbol is True


def test_duration_and_dates():
    d = C.duration_after("服务期限：工期为120日历天", r"服务期限")
    assert (d.value, d.unit, d.days, d.approx) == (120, "日历天", 120, False)
    m = C.duration_after("服务期为十二个月", r"服务期")
    assert m.days == 360 and m.approx
    # 相对时间不是工期（1671817 实单：投标文件「收到进场通知书后3天内进场」、合同「桩基施工全部完工后 180 天」）
    assert C.duration_after("其中详勘工期：中标人应在收到进场通知书后3天内进场", r"工期") is None
    assert C.duration_after("勘测服务工期为从签订合同日至EPC 项目桩基施工全部完工后 180 天", r"工期") is None
    assert C.cn_amounts("人民币283,018.87 元（大写：贰拾捌\n万叁仟零壹拾捌元捌角柒分）")[0][0] == 283018.87
    assert C.parse_date("2026.9.1") == date(2026, 9, 1)
    assert C.parse_date("2026年13月1日") is None


def test_consecutive_groups():
    assert C.consecutive_groups(["0001", "0002", "0004", "0002", "12", "13"]) == [["12", "13"], ["0001", "0002"]]
    assert C.consecutive_groups(["0009", "0010"]) == [["0009", "0010"]]
    assert C.consecutive_groups(["1", "3"]) == []


# ---------------------------------------------------------------- 状态与引擎

def test_status_labels():
    assert st.label("procurement", st.ISSUE) == "命中" and st.code_of("procurement", "未能识别") == st.MISSING
    assert st.label("reimburse", st.ISSUE) == "存在风险" and st.label("contract", st.NA) == "不适用"


def test_engine_keeps_order_and_isolates_failures():
    def boom(f):
        raise ValueError("x")

    rules = [Rule("A", "a", "c", lambda f: ok("无异常")), Rule("B", "b", "c", boom),
             Rule("C", "c", "c", lambda f: issue("问题", [{"file": "x", "value": date(2026, 1, 1)}]))]
    out = run_rules("contract", "v", rules, {})
    assert [r["rule_id"] for r in out] == ["A", "B", "C"]
    assert out[1]["code"] == "error" and "规则执行异常" in out[1]["message"]
    assert out[2]["evidence"][0]["value"] == "2026-01-01"  # 可序列化
    json.dumps(out, ensure_ascii=False)


# ---------------------------------------------------------------- 金额档位

@pytest.mark.parametrize("text,lo,hi", [
    ("≥30万元", (300000, True), None), ("＜10万元", None, (100000, False)), ("10(含)-30万元", (100000, True), (300000, False)),
    ("500万元（含）-1000万元", (5e6, True), (1e7, False)), ("20万元以下", None, (200000, False)),
    ("100万元＜单笔金额≤300万", (1e6, False), (3e6, True)), ("500万元≤涉案金额＜1000万元", (5e6, True), (1e7, False)),
    ("≥1000万元1", (1e7, True), None), ("金额＞100万元", (1e6, False), None)])
def test_parse_range(text, lo, hi):
    r = parse_range(text)
    assert ((r["lo"], r["lo_incl"]) if "lo" in r else None) == lo
    assert ((r["hi"], r["hi_incl"]) if "hi" in r else None) == hi


def test_range_edges():
    r = parse_range("10(含)-30万元")
    assert in_range(r, 100000) and not in_range(r, 300000) and in_range(r, 299999.99)
    assert parse_range("纳入公司客商灰名单") is None and in_range(None, 1) is None
    assert describe_range(parse_range("≥30万元")) == "≥30万元"
    assert meeting_of("总经理(办公会)") == "总经理办公会" and meeting_of("总经理签批") == "不上会（签批）"


# ---------------------------------------------------------------- 制度库（真实 PDF）

@pytest.fixture(scope="module")
def kb() -> RegulationBase:
    base = get_base()
    if not base.clauses:
        pytest.skip("制度文件不可用")
    return base


def test_kb_documents_enabled(kb):
    docs = {d["id"]: d for d in kb.documents()}
    assert all(d["state"] == "enabled" for d in docs.values()), docs
    assert docs["authority_manual"]["clauses"] >= 400 and docs["major_items"]["clauses"] == 47
    assert docs["party_items"]["clauses"] == 63 and docs["board_authorization"]["clauses"] == 12
    assert not docs["authority_manual"]["warnings"]


def test_kb_every_manual_row_has_final_subject(kb):
    rows = kb.lookup("authority_manual")
    assert rows and all(c.final for c in rows)


def test_kb_item_46_tiers(kb):
    tiers = {(c.tier, tuple(c.final)) for c in kb.lookup("authority_manual", "运营管理部", 46)}
    assert tiers == {("≥30万元", ("总经理办公会",)), ("10(含)-30万元", ("总经理签批",)), ("＜10万元", ("相关领导",))}


def test_kb_pending_rows_join_following_number(kb):
    rows = kb.lookup("authority_manual", "科技质量部", 18)
    assert [c.tier for c in rows] == ["申报", "奖励", "维护及管理"]
    assert rows[0].title == "知识产权申报、奖励、维护及管理审批"


def test_kb_text_order_restored(kb):
    c = kb.lookup("authority_manual", "运营管理部", 44)[0]
    assert "项目管理、工程监理项目、代建管理、全咨项目" in c.title


def test_kb_board_and_major(kb):
    b = kb.lookup("board_authorization", None, 1)
    assert {c.meetings[0] for c in b} == {"董事长专题会", "总经理办公会"}
    assert len(kb.lookup("board_authorization", None, 3)) == 1  # 授权董事长只有 2 项
    m42 = kb.lookup("major_items", None, 42)[0]
    assert m42.meetings == ["总经理办公会"] and in_range(m42.range, 6e6)


def test_refs_in_basis_text():
    refs = RegulationBase.refs_in("依据公司《权责手册（2026年修订版）》运营管理部第46项，及《重大经营管理事项清单》第十二项")
    assert {(r["doc_id"], r["dept"], r["no"]) for r in refs} == {("authority_manual", "运营管理部", 46),
                                                                ("major_items", None, 12)}


def test_kb_search(kb):
    top = kb.search("公司非业务合同采购结果 智能体平台", 3)
    assert top[0][1].ref == "运营管理部第46项"


# ---------------------------------------------------------------- 天眼查解析（2026-11-06 实测样本）

def _tyc(name):
    return json.loads((FIX / "tyc" / name).read_text(encoding="utf-8"))


def test_tianyancha_profile_from_samples():
    from shared.external_lookup.tianyancha import assemble, capital_yuan

    detail = (FIX / "tyc" / "detail.txt").read_text(encoding="utf-8")
    cap = {k: _tyc(f"{k}.json") for k in ("base", "staff", "holders", "suspected", "controller", "beneficiary")}
    p = assemble("济南瑞亿创新信息技术有限公司", cap, detail, "https://www.tianyancha.com/company/6815676713")
    assert p.name == "济南瑞亿创新信息技术有限公司" and p.credit_code == "91370100MADB9MCT3F"
    assert p.legal_person == "刘翠萍" and p.reg_capital_yuan == 1e6
    assert {x["name"] for x in p.holders} == {"刘翠萍", "陈鼎活"}
    assert {x["name"] for x in p.staff} == {"刘翠萍", "刘静"}
    assert len(p.suspected) == 2 and "125589377@qq.com" in p.suspected[0]["detail"]
    assert p.risks["失信被执行人"] == 0 and p.risks["破产案件"] == 0 and p.self_risk == 0
    assert capital_yuan("1.2亿人民币") == 1.2e8 and capital_yuan("100万美元") is None


def test_tianyancha_risk_counts_and_unknown():
    from shared.external_lookup.tianyancha import parse_risk_text

    text = "x\n法律诉讼\n司法案件开庭公告失信被执行人3被执行人12历史被执行人9破产案件\n经营风险\n经营异常2严重违法\n经营信息\n"
    risks, _ = parse_risk_text(text)
    assert risks["失信被执行人"] == 3 and risks["被执行人"] == 12 and risks["破产案件"] == 0 and risks["经营异常"] == 2
    assert parse_risk_text("页面改版，没有导航")[0] == {}  # 读不到 → 未知，不当 0
    # 大型企业实测页面（2026-11-09）：「法律诉讼」先出现在概览计数区，再出现在维度导航
    big, self_risk = parse_risk_text((FIX / "tyc" / "detail_large.txt").read_text(encoding="utf-8"))
    assert big and big["失信被执行人"] == 0 and big["破产案件"] == 0 and self_risk == 9


def test_tianyancha_missing_base_raises():
    from shared.external_lookup import ExternalUnavailable
    from shared.external_lookup.tianyancha import assemble

    with pytest.raises(ExternalUnavailable):
        assemble("某公司", {}, "", "")


# ---------------------------------------------------------------- 模型判定器

def test_judge_parse_cache_and_tamper(tmp_path):
    from shared.llm.judge import Judge, LLMBadOutput, LLMUnavailable, parse_json
    from tests.support.env import temp_store

    assert parse_json("<think>…</think>```json\n{\"a\": 1}\n```") == {"a": 1}
    store = temp_store(tmp_path)
    calls = []

    def fake(messages, role):
        calls.append(messages)
        return '好的：{"conclusion": "一致"}'

    j = Judge(store, "t1", complete=fake)
    assert j("p", "sys", "user") == {"conclusion": "一致"}
    assert j("p", "sys", "user") == {"conclusion": "一致"} and len(calls) == 1  # 第二次命中缓存
    store._exec("UPDATE llm_cache SET body = ?", ('{"conclusion": "不一致"}',))
    assert j("p", "sys", "user") == {"conclusion": "一致"} and len(calls) == 2   # 篡改的缓存不被采用
    bad = Judge(store, "t1", complete=lambda m, r: "不是 JSON")
    with pytest.raises(LLMBadOutput):
        bad("q", "s", "u")

    def down(m, r):
        raise ConnectionError("refused")

    with pytest.raises(LLMUnavailable):
        Judge(store, "t1", complete=down)("r", "s", "u")
    assert store.llm_stats("t1")["failed"] == 2


# ---------------------------------------------------------------- 本地事项

def test_local_case_client(tmp_path):
    from shared.errors import NoAccess
    from shared.source_adapters.local import LocalCaseClient
    from contract_review import samples

    samples.write(tmp_path)
    c = LocalCaseClient("contract", root=tmp_path)
    assert [x["request_id"] for x in c.list()] == ["DEMO-HT-001", "DEMO-HT-002"]
    req = c.fetch("DEMO-HT-001")
    assert req.value("合同名称") == "天悦府二期监理合同" and len(req.attachments) == 3
    assert c.download(req.attachments[0])[:2] == b"PK"
    with pytest.raises(NoAccess):
        c.fetch("../../etc")
