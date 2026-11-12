import pytest


@pytest.fixture(autouse=True)
def _isolated_rule_config(tmp_path_factory, monkeypatch):
    """测试一律使用空的规则配置库：正式环境在「流程与规则」页发布的配置不影响回放与单测结论。"""
    from shared import rule_config

    monkeypatch.setattr(rule_config, "DB_PATH", tmp_path_factory.mktemp("rulecfg") / "rule_config.sqlite3")
    rule_config.reset_cache()
    yield
    rule_config.reset_cache()
