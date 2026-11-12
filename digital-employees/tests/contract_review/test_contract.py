"""合同审核：本地样例端到端（问题样例 / 规范样例）+ 关键规则的边界。"""
import json

import pytest

from shared.source_adapters.local import LocalCaseClient
from contract_review import workflow as cgraph
from contract_review import samples
from tests.support.env import by_id, temp_resources, temp_store
from tests.support.fakes import FakeJudge, FakeTianyancha


@pytest.fixture()
def env(tmp_path, monkeypatch):
    cases = tmp_path / "cases"
    samples.write(cases)
    monkeypatch.setattr(cgraph, "REPORTS", tmp_path / "reports")
    return {"store": temp_store(tmp_path), "resources": temp_resources(tmp_path), "client": LocalCaseClient("contract", root=cases), "tmp": tmp_path}


def run(env, case_id, judge=None, tyc=None):
    events = []
    final = cgraph.run(case_id, env["store"], None, on_event=events.append, source="local", client=env["client"], resources=env["resources"],
                       judge=judge or FakeJudge(), tianyancha=tyc or FakeTianyancha(), lists={})
    return final, events


PROBLEM_ANSWERS = {
    "contract.R02": {"conclusion": "不一致", "summary": "合同排除了室外景观工程",
                     "differences": [{"item": "室外景观", "a_quote": "不包括室外景观工程",
                                      "b_quote": "地下车库及室外景观工程", "explain": "合同范围小于投标承诺"}]},
    "contract.R05": {"conclusion": "不一致", "summary": "付款节点不同",
                     "differences": [{"item": "付款节点", "a_quote": "主体结构封顶后支付 40%",
                                      "b_quote": "竣工验收后支付 70%", "explain": "合同增加了封顶节点"}]},
}


def test_problem_case(env):
    final, events = run(env, "DEMO-HT-001", judge=FakeJudge(PROBLEM_ANSWERS))
    r = by_id(final["results"])
    assert len(final["results"]) == 30
    expect_issue = ["R01", "R02", "R03", "R05", "R09", "R10", "R11", "R12", "R13", "R14", "R15", "R16", "R19", "R20",
                    "R21", "R23", "R24", "R25", "R27"]
    for rid in expect_issue:
        assert r[rid]["code"] == "issue", (rid, r[rid]["status"], r[rid]["message"])
    assert "1,280,000.00" in r["R01"]["message"] and "1,250,000.00" in r["R01"]["message"]
    assert "济南市仲裁委员会" in r["R14"]["message"] and "“济南仲裁委员会”" in r["R14"]["message"]
    assert r["R10"]["message"].startswith("合同约定违约金比例为 50%")
    assert r["R28"]["code"] == "review"
    for rid in ("R06", "R26", "R29", "R30"):
        assert r[rid]["code"] == "na", (rid, r[rid]["message"])
    for rid in ("R07", "R08"):
        assert r[rid]["code"] == "missing" and "招标文件" in r[rid]["message"]
    assert r["R17"]["code"] == "review" and "不合格供应商名单未提供" in json.dumps(r["R17"], ensure_ascii=False)
    # 每条问题都有证据，且证据能落到真实文件
    for rid in expect_issue:
        assert r[rid]["evidence"], rid
    assert {e["file"] for e in r["R01"]["evidence"]} == {"出版用合同文本.docx", "中标通知书.pdf"}
    rep = final["report"]
    assert rep["verdict"]["level"] == "bad"
    assert rep["summary"]["codes"]["issue"] == len(expect_issue)
    nodes = [e["node"] for e in events if e["type"] == "node.completed"]
    assert nodes == cgraph.NODES
    assert len([e for e in events if e["type"] == "rule.completed"]) == 30
    json.dumps(rep, ensure_ascii=False)  # 报告可序列化


def test_clean_case(env):
    final, _ = run(env, "DEMO-HT-002")
    r = by_id(final["results"])
    assert not [x for x in final["results"] if x["code"] in ("issue", "error")], \
        [(x["rule_id"], x["message"]) for x in final["results"] if x["code"] in ("issue", "error")]
    for rid in ("R01", "R03", "R09", "R10", "R11", "R12", "R13", "R14", "R15", "R19", "R20", "R21", "R23", "R24", "R25"):
        assert r[rid]["code"] == "pass", (rid, r[rid]["status"], r[rid]["message"])
        assert r[rid]["message"].startswith("无异常")
    assert final["report"]["verdict"]["level"] == "warn"  # R07/R08 缺招标文件、R17 名单未提供


def test_llm_failure_marks_aborted_not_pass(env):
    final, _ = run(env, "DEMO-HT-001", judge=FakeJudge(fail={"*"}))
    r = by_id(final["results"])
    for rid in ("R02", "R05"):
        assert r[rid]["code"] == "error" and "模型" in r[rid]["message"], r[rid]
    assert r["R01"]["code"] == "issue"  # 确定性规则不受影响
    assert any("审查中止" in n for n in final["report"]["notes"])


def test_hallucinated_quote_is_not_accepted(env):
    fake = {"conclusion": "不一致", "summary": "x",
            "differences": [{"item": "范围", "a_quote": "合同中根本没有的一句话内容", "b_quote": "投标文件里也没有这句"}]}
    final, _ = run(env, "DEMO-HT-001", judge=FakeJudge({"contract.R02": fake}))
    r = by_id(final["results"])["R02"]
    assert r["code"] == "review" and "无法在材料中定位" in r["message"]


def test_verify_rejects_off_topic_differences(env):
    answers = {**PROBLEM_ANSWERS, "contract.R02.verify": {"results": [{"no": 1, "valid": False, "reason": "讲的不是同一事项"}]}}
    final, _ = run(env, "DEMO-HT-001", judge=FakeJudge(answers))
    r = by_id(final["results"])["R02"]
    assert r["code"] == "review" and "讲的不是同一事项" in r["message"]


def test_tianyancha_unavailable_is_aborted_with_reason(env):
    final, _ = run(env, "DEMO-HT-002", tyc=FakeTianyancha(error="天眼查要求登录"))
    r = by_id(final["results"])["R17"]
    assert r["code"] == "error" and "天眼查查询失败" in r["message"] and "处理：" in r["message"], r


def test_tianyancha_block_page_is_not_reported_as_not_found():
    import pytest

    from shared.external_lookup import TianyanchaBlocked, TianyanchaNeedsLogin
    from shared.external_lookup.tianyancha import check_text

    with pytest.raises(TianyanchaBlocked, match="识别码 406-6af3d160"):
        check_text("https://www.tianyancha.com/search?key=x",
                   "系统检测到您的操作存在异常 已暂停您的访问请求 识别码: 406-6af3d160-dead298a")
    with pytest.raises(TianyanchaNeedsLogin):
        check_text("https://www.tianyancha.com/login", "请拖动滑块完成拼图")
    check_text("https://www.tianyancha.com/company/1", "济宁华擎工程管理有限公司 开业")


def test_tianyancha_dishonest_is_issue(env):
    tyc = FakeTianyancha({"济南城市建设集团有限公司": {
        "name": "济南城市建设集团有限公司", "reg_capital": "100万人民币", "url": "",
        "risks": {"失信被执行人": 2, "被执行人": 0, "破产案件": 0}}})
    final, _ = run(env, "DEMO-HT-002", tyc=tyc)
    r = by_id(final["results"])["R17"]
    assert r["code"] == "issue" and "失信被执行人记录 2 条" in r["message"]


def test_local_case_never_queries_tianyancha(env):
    final = cgraph.run("DEMO-HT-002", env["store"], None, source="local", client=env["client"], resources=env["resources"], judge=FakeJudge(), lists={})
    r = by_id(final["results"])["R17"]
    assert "失信被执行人 0" in json.dumps(r, ensure_ascii=False)          # 用的是样例自带的离线数据
    assert final["external"]["tianyancha"]["legal_person"] == "（样例法定代表人）"


def test_wrong_workflow_rejected(env):
    from shared.errors import WrongWorkflow
    from shared.source_adapters.contract import RequestData

    req = RequestData(request_id="1", workflow_id="100", workflow_name="采购结果审批流程", request_name="x",
                      node_name="", fields=[], approval_log=[], attachments=[])
    with pytest.raises(WrongWorkflow) as ei:
        cgraph._check_workflow(req, cgraph.config())
    assert ei.value.title == "该单号不是主合同审批流程"


def test_report_persisted_and_listed(env):
    final, _ = run(env, "DEMO-HT-002")
    store = env["store"]
    tid = final["report"]["task_id"]
    assert store.get_report(tid)["rules_version"] == cgraph.rules_mod.VERSION
    rows = store.list_tasks("contract", 5)
    assert rows[0]["task_id"] == tid and rows[0]["subject"].startswith("济南城市建设集团")
    md = (env["tmp"] / "reports").glob("contract_DEMO-HT-002_*.md")
    assert any("合同审核数字员工 · 审核报告" in p.read_text(encoding="utf-8") for p in md)
