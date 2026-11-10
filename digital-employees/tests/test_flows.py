"""流程定义与流水线一致；规则配置：草稿 / 发布 / 版本、参数叠加到 YAML、停用 / 名称 / 核实建议在执行时生效。"""
import pytest

from core import ruleconfig, settings
from core.rules.engine import Rule, ok, run_rules
from employees import registry
from employees.flows import FLOWS, deps_of, params_of


@pytest.fixture()
def cfgdb(tmp_path, monkeypatch):
    monkeypatch.setattr(ruleconfig, "DB_PATH", tmp_path / "rule_config.sqlite3")
    ruleconfig.reset_cache()
    yield
    ruleconfig.reset_cache()


def test_flow_definitions_match_pipelines():
    for e in registry.EMPLOYEES:
        f = FLOWS[e.id]
        assert [n["name"] for n in f["nodes"]] == list(e.graph.NODES), e.id
        names = {n["name"] for n in f["nodes"]}
        assert f["exec"] in names
        for c in e.catalog():
            deps = deps_of(e.id, c)
            assert deps, (e.id, c["rule_id"])
            assert all(d in names or d.startswith("（") for d in deps), (e.id, c["rule_id"], deps)
        ids = {c["rule_id"] for c in e.catalog()}
        assert set(f.get("params") or {}) <= ids and set(f.get("deps") or {}) <= ids
        for step in f["plan"]:
            assert all(n in names for n in step["nodes"]), (e.id, step)


def test_param_paths_exist_in_yaml():
    for emp, f in FLOWS.items():
        raw = settings.load(f["config"], raw=True)
        for rid, specs in (f.get("params") or {}).items():
            for s in specs:
                assert ruleconfig.get_path(raw, s["path"]) is not None, (emp, rid, s["path"])
        for s in f.get("flow_params") or []:
            assert ruleconfig.get_path(raw, s["path"]) is not None, (emp, s["path"])


def test_draft_publish_overlay_and_versions(cfgdb):
    assert settings.load("contract.yaml")["penalty_limit_ratio"] == 0.30
    assert ruleconfig.effective_version("contract", "contract-v1") == "contract-v1"
    ruleconfig.save_draft("contract", {"rules": {"R10": {"params": {"penalty_limit_ratio": 0.2}}}}, "张三", "调低上限")
    assert settings.load("contract.yaml")["penalty_limit_ratio"] == 0.30  # 草稿不生效
    assert ruleconfig.has_draft("contract")
    n = ruleconfig.publish("contract", "张三", "违约金上限调整为 20%")
    assert n == 1 and not ruleconfig.has_draft("contract")
    assert settings.load("contract.yaml")["penalty_limit_ratio"] == 0.2
    assert settings.load("contract.yaml", raw=True)["penalty_limit_ratio"] == 0.30
    assert ruleconfig.effective_version("contract", "contract-v1") == "contract-v1+c1"
    with pytest.raises(ValueError):
        ruleconfig.publish("contract", "张三", "没有改动")
    ruleconfig.rollback_to("contract", 0, "张三")
    assert ruleconfig.publish("contract", "张三", "恢复默认") == 2
    assert settings.load("contract.yaml")["penalty_limit_ratio"] == 0.30
    assert ruleconfig.effective_version("contract", "contract-v1") == "contract-v1"  # 恢复默认后不再带配置序号
    vs = ruleconfig.versions("contract")
    assert [v["n"] for v in vs] == [2, 1] and vs[1]["changes"] == 1
    actions = [x["action"] for x in ruleconfig.log("contract")]
    assert actions.count("publish") == 2 and "edit" in actions


def test_disable_name_and_suggest_apply_at_run(cfgdb):
    rules = [Rule("R09", "违约责任限额", "确定性", lambda f: ok("核查通过")),
             Rule("R11", "合同价款大小写一致性", "确定性", lambda f: ok("核查通过"))]
    ruleconfig.save_draft("contract", {"rules": {"R09": {"enabled": False, "reason": "业务口径待确认"},
                                                 "R11": {"name": "大小写金额一致", "suggest": "请核对合同首页金额"}}})
    ruleconfig.publish("contract", "李四", "测试")
    out = {r["rule_id"]: r for r in run_rules("contract", "v", rules, {})}
    assert out["R09"]["code"] == "notrun" and "业务口径待确认" in out["R09"]["message"]
    assert out["R11"]["name"] == "大小写金额一致" and out["R11"]["suggest"] == "请核对合同首页金额"


def test_procurement_param_and_tier(cfgdb):
    from datetime import date, datetime

    from employees.procurement import rules as pr

    facts = {"pdoc_publish_date": {"value": date(2026, 11, 1)}, "deadline": {"value": datetime(2026, 11, 4, 9, 0)}}
    assert pr.p08(facts)["status"] == pr.PASS  # 4 个自然日 ≥ 3
    ruleconfig.save_draft("procurement", {"rules": {"P08": {"params": {"p08_min_days": 5}, "tier": "拿不准"}}})
    ruleconfig.publish("procurement", "王五", "P08 改为 5 日")
    assert pr.p08(facts)["status"] == pr.HIT
    r = ruleconfig.apply_result("procurement", pr.p08(facts))
    assert r["tier"] == "拿不准"


def test_reimburse_enable_switch_synced_to_yaml(cfgdb):
    ruleconfig.save_draft("reimburse", {"rules": {"TRV-06": {"enabled": False, "reason": "待业务口径"}}})
    ruleconfig.publish("reimburse", "财务", "停用")
    assert settings.load("reimburse.yaml")["rules"]["TRV-06"]["enabled"] is False
    assert params_of("reimburse", "ENT-03")
