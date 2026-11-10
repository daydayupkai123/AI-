import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolated_rule_config(tmp_path_factory, monkeypatch):
    """测试一律使用空的规则配置库：正式环境在「流程与规则」页发布的配置不影响回放与单测结论。"""
    from core import ruleconfig

    monkeypatch.setattr(ruleconfig, "DB_PATH", tmp_path_factory.mktemp("rulecfg") / "rule_config.sqlite3")
    ruleconfig.reset_cache()
    yield
    ruleconfig.reset_cache()
