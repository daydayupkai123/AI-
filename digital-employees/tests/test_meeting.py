"""三会审查：本地样例端到端（问题 / 规范）、金额边界、严格模式中止、条款定位失败。

制度库使用真实的四份制度 PDF（config/regulations.yaml），首次解析后缓存在 .runtime/knowledge。
"""
import json

import pytest

from core.knowledge.base import get_base
from core.sources.local import LocalCaseClient
from employees.meeting import graph as mgraph
from employees.meeting import samples
from employees.meeting.checks.basis import resolve
from tests.support.env import by_id, temp_resources, temp_store
from tests.support.fakes import FakeJudge


@pytest.fixture(scope="module")
def kb():
    base = get_base()
    if not base.lookup("authority_manual", "运营管理部", 46):
        pytest.skip("制度文件不可用")
    return base


@pytest.fixture()
def env(tmp_path, monkeypatch, kb):
    cases = tmp_path / "cases"
    samples.write(cases)
    monkeypatch.setattr(mgraph, "REPORTS", tmp_path / "reports")
    return {"store": temp_store(tmp_path), "resources": temp_resources(tmp_path), "client": LocalCaseClient("meeting", root=cases), "kb": kb}


def run(env, case_id, judge=None):
    events = []
    final = mgraph.run(case_id, env["store"], None, on_event=events.append, source="local", client=env["client"], resources=env["resources"],
                       judge=judge or FakeJudge(), kb=env["kb"])
    return final, events


CONFLICT = {"meeting.N01:园区安防改造项目报价单.docx": {
    "relation": "冲突", "quote": "济南高新区某园区安防改造项目报价单", "reason": "项目对象为园区安防改造，与标题不符"}}


def test_problem_case(env):
    final, events = run(env, "DEMO-SH-001", FakeJudge(CONFLICT))
    r = by_id(final["results"])
    assert [x["rule_id"] for x in final["results"]] == ["N01", "N02", "N03", "N04", "N05"]
    assert all(r[k]["code"] == "issue" for k in r), {k: (v["code"], v["message"]) for k, v in r.items()}
    assert "园区安防改造项目报价单" in " ".join(r["N01"]["items"])
    n03 = " ".join(r["N03"]["items"])
    assert "10(含)-30万元" in n03 and "总经理签批" in n03 and "总经理办公会" in n03
    assert "≥30万元" in n03  # 依据写的档位与金额不符
    assert any(e.get("ref") == "运营管理部第46项" and e.get("page") == 20 for e in r["N03"]["evidence"])
    assert "不上会（签批）" in " ".join(r["N02"]["items"])
    assert any("XX" in i for i in r["N04"]["items"])
    n05 = " ".join(r["N05"]["items"])
    assert "公告日期（2026-10-10）" in n05 and "2026-10-12" in n05
    assert "评审小组人数（3 人）" in n05 and "5 人" in n05
    assert final["report"]["verdict"]["level"] == "bad"
    # 节点卡片：一条综合意见 + 编号问题，事件里带上 items
    cards = [e for e in events if e["type"] == "rule.completed"]
    assert len(cards) == 5 and all("items" in c for c in cards)
    json.dumps(final["report"], ensure_ascii=False)


def test_clean_case(env):
    final, _ = run(env, "DEMO-SH-002")
    r = by_id(final["results"])
    assert all(v["code"] == "pass" for v in r.values()), {k: (v["code"], v["message"], v["items"]) for k, v in r.items()}
    assert "由总经理办公会审批" in r["N03"]["message"] and "45.80" in r["N03"]["message"].replace("458,000.00", "45.80")
    assert final["report"]["verdict"]["level"] == "good"


def test_strict_mode_aborts_without_report(env):
    from employees.meeting.graph import StrictAbort

    with pytest.raises(StrictAbort):
        run(env, "DEMO-SH-002", FakeJudge(fail={"*"}))
    tasks = env["store"].list_tasks("meeting", 1)
    assert tasks[0]["status"] == "failed"
    assert tasks[0]["error"].startswith("StrictAbort") and "模型不可用" in tasks[0]["error"]
    assert env["store"].get_report(tasks[0]["task_id"]) is None


def _facts(amount_yuan, basis="公司《权责手册（2026年修订版）》运营管理部第46项", stage="采购结果"):
    from employees.meeting.extract import basis_parts

    return {"basis": basis, "basis_parts": basis_parts(basis), "title_core": "某采购项目", "stage": stage,
            "case_amount": None if amount_yuan is None else {"value": amount_yuan, "file": "正文", "snippet": ""}}


@pytest.mark.parametrize("amount,meeting", [(300000, "总经理办公会"), (299999.99, "不上会（签批）"),
                                            (100000, "不上会（签批）"), (99999, "不上会（签批）")])
def test_amount_boundaries(kb, amount, meeting):
    res = resolve(_facts(amount), kb)
    assert res["status"] == "matched"
    assert res["matched"].meetings == [meeting]


def test_missing_amount_is_not_guessed(kb):
    res = resolve(_facts(None), kb)
    assert res["status"] == "no_amount"


def test_unknown_clause_goes_to_review(kb):
    res = resolve(_facts(500000, basis="公司《权责手册（2026年修订版）》运营管理部第999项"), kb)
    assert res["status"] == "not_found" and res["candidates"]


def test_quoted_item_located_by_name(kb):
    basis = "根据公司《权责手册》“预算外办公设备及软件采购事项立项，20万元以下，由总经理签批”的规定，现提交审批。"
    res = resolve(_facts(59380, basis=basis, stage="立项"), kb)
    assert res["quoted_item"] == "预算外办公设备及软件采购事项立项"
    assert res["ref"]["by_name"] and res["ref"]["dept"] == "综合管理部"
    assert res["status"] == "matched" and res["matched"].tier.startswith("20万元以下")


def test_quoted_item_missing_from_current_manual(kb):
    from employees.meeting.checks import basis as B

    basis = "根据公司《权责手册》“信息化数字化项目建设/信息化数字化设备购置（含软件），5万元（含）-10万元，由总经理审批”的规定。"
    f = _facts(59380, basis=basis, stage="采购过程")
    res = resolve(f, kb)
    assert res["status"] == "no_item" and res["quoted_item"].startswith("信息化数字化项目建设")
    f["resolution"] = res
    out = B.check(f)
    assert out.code == "review" and "未找到" in out.message and "旧版" in out.message
    # 候选优先金额落在档位内的条款
    first = res["candidates"][0]
    assert first.range is None or first.range.get("lo", 0) <= 59380


def test_cited_number_conflicts_with_quoted_item(kb):
    from employees.meeting.checks import basis as B

    basis = "根据公司《权责手册》中综合管理部第153条“公司工会年度经费预算审批及使用，1-5万工会委员会审批”，现提请公司领导审批。"
    f = _facts(45000, basis=basis, stage=None)
    f["meeting"] = "不上会（签批）"
    res = resolve(f, kb)
    assert res["status"] == "matched" and res["matched"].no == 157
    assert res["number_mismatch"]["cited"] == "综合管理部第153项"
    f["resolution"] = res
    out = B.check(f)
    assert out.code == "issue" and len(out.items) == 1
    assert "条款号引用有误" in out.items[0] and "综合管理部第157项" in out.items[0]


def test_total_amount_preferred_over_loose_budget_mention():
    from core.materials import Material
    from employees.meeting.extract import doc_facts

    text = ("关于签订电子签名证书更新协议的请示\n证书更新费用54380元，平台费5000元（共计3万元，受预算限制，本次支付5000元），"
            "费用合计59380元。")
    m = Material(sig="s", filename="请示.docx", doc={"status": "ok", "pages": [{"no": 1, "text": text}]})
    bf = doc_facts(m)
    assert bf["budget"] is None
    assert bf["total"]["value"] == 59380


def test_threshold_amounts_and_pre_result_docs_not_taken_as_result():
    from core.materials import Material
    from employees.meeting.extract import doc_facts

    note = "注：2.单项采购金额<50万元，部门负责人审批；单项采购金额≥50万元，运营管理部审核。"
    need = Material(sig="a", filename="1.采购需求审批表.pdf", role="procurement_doc",
                    doc={"status": "ok", "pages": [{"no": 1, "text": "项目预算：50万元\n采购金额：50万元\n" + note}]})
    assert doc_facts(need)["result_amount"] is None and doc_facts(need)["budget"]["value"] == 500000
    form = Material(sig="b", filename="2.采购结果审批表.pdf", role="result",
                    doc={"status": "ok", "pages": [{"no": 1, "text": note + "\n成交金额：45万元"}]})
    assert doc_facts(form)["result_amount"]["value"] == 450000
    only_note = Material(sig="c", filename="x.pdf", role="other", doc={"status": "ok", "pages": [{"no": 1, "text": note}]})
    assert doc_facts(only_note)["result_amount"] is None


def test_reviewer_rules_and_budget_cap():
    from employees.meeting.extract import doc_facts, reviewers

    rule = _mat("4.采购文件.docx", "6.1谈判小组 评审的评审小组负责，评审小组由采购人组建，一般为3人以上单数。")
    assert reviewers(rule) is None
    assert doc_facts(_mat("4.采购文件.docx", "评审小组由5人组成。", "procurement_doc"))["reviewers"] is None
    assert reviewers(_mat("评审报告.pdf", "评审小组由5人组成，推荐成交候选人"))["value"] == 5
    cap = _mat("请示.doc", "三、预算安排\n本项目总预算控制在50万元以内，计划分项列支。", "request_body")
    assert doc_facts(cap)["budget"]["value"] == 500000


def test_body_incomplete_sentence_needs_exact_quote():
    from employees.meeting.checks import body as B

    text = "关于某项目的请示\n公司领导：\n甲公司将服务费在本协议签订后28个工作日内支付给乙公司，乙公司开具发票。"
    f = {"body": _mat("请示.docx", text, "request_body"), "stage": "合同签订", "body_title": None, "title_core": "某项目",
         "case_amount": {"value": 1}, "placeholders": [], "body_refs": [], "basis_parts": {},
         "_judge": lambda *a: {"problems": [{"quote": "在本协议签订后28个工作日内支付给乙公司， /think", "issue": "语句残缺"}]}}
    assert B.check(f).code == "issue"  # 去掉抄进来的思考开关标记后，原文逐字可定位
    f["_judge"] = lambda *a: {"problems": [{"quote": "在本协议签订后28个工作日内支付给乙公司，并承担", "issue": "语句残缺"}]}
    out = B.check(f)
    assert out.code == "pass" and "无法在正文中定位" in out.message  # 模型多写的内容不采信


def _mat(name, text="内容", role="other"):
    from core.materials import Material

    return Material(sig=name, filename=name, role=role, doc={"status": "ok", "pages": [{"no": 1, "text": text}]})


BODY = ("关于某项目采购结果的请示\n公司领导：\n……现提请公司总经理办公会审议。\n当否，请批示。\n\n"
        "附件：1.采购需求审批表\n      2.采购结果审批表\n      3.评审报告\n      4.采购公告\n\n\n运营管理部\n2026年10月8日")


def test_body_llm_findings_outside_scope_not_adopted():
    from employees.meeting.checks import body as B

    text = "关于某项目采购结果的请示\n公司领导：\n成交金额为45万元，供应商为甲公司。依据权责手册第46项，现提请总经理办公会审议。"
    m = _mat("请示.docx", text, "request_body")
    out_of_scope = {"problems": [{"quote": "依据权责手册第46项", "issue": "关键依据不明确", "explain": "未说明条款内容"},
                                 {"quote": "成交金额为45万元", "issue": "关键对象不清", "explain": "未写采购方式"},
                                 {"quote": "不存在的原文", "issue": "语句残缺"}]}
    f = {"body": m, "stage": "采购结果", "body_title": None, "title_core": "某项目", "case_amount": {"value": 450000},
         "placeholders": [], "body_refs": [], "basis_parts": {}, "_judge": lambda *a: out_of_scope}
    out = B.check(f)
    assert out.code == "issue" and out.items[0].startswith("关键对象不清")  # 类型在范围内且原文可定位的才采信
    assert any("不属于文本完整性检查范围" in i for i in out.items) and any("无法在正文中定位" in i for i in out.items)
    f["_judge"] = lambda *a: {"problems": out_of_scope["problems"][:1]}
    assert B.check(f).code == "pass"


def test_declared_attachment_list_vs_provided():
    from employees.meeting.checks import attachments as A

    body = _mat("请示.doc", BODY, "request_body")
    items, ev = A.declared_list(body)
    assert items == ["采购需求审批表", "采购结果审批表", "评审报告", "采购公告"] and ev["label"] == "正文·附件清单"
    atts = [_mat("1.采购需求审批表.pdf"), _mat("4.采购公告.PDF"), _mat("评审报告（盖章版）.pdf")]
    out = A.check({"attachments": atts, "materials": [body, *atts], "body": body, "body_facts": {}, "att_facts": {}})
    assert out.code == "issue" and len(out.items) == 1
    assert "列明 4 份材料" in out.items[0] and "未找到 1 份：采购结果审批表" in out.items[0]
    full = atts + [_mat("2.采购结果审批表.pdf")]
    out = A.check({"attachments": full, "materials": [body, *full], "body": body, "body_facts": {}, "att_facts": {}})
    assert out.code != "issue"
    assert A.declared_list(_mat("请示.docx", "关于某事项的请示\n正文没有附件清单。", "request_body")) == ([], None)
