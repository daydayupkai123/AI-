"""采购回归：用本地已缓存的历史单据离线重跑整条流程，规则结果必须与历史报告逐条一致。

依赖历史数据（原件 + 解析缓存 + 报告）：当前 .runtime，或清理前的备份（见 tests/support/replay.baseline）；都没有时跳过。
"""
import pytest

from procurement_review import workflow as pgraph
from tests.support.replay import (NoSessions, ReplayClient, baseline, comparable, latest_report, rebuild_request,
                                  replay_resources, replay_store)

CASES = ["1674771", "1672706"]


@pytest.mark.parametrize("request_id", CASES)
def test_replay_matches_history(request_id, tmp_path, monkeypatch):
    base = baseline(request_id)
    if not base:
        pytest.skip(f"本地没有 {request_id} 的历史报告")
    db, rc, root = base
    history = latest_report(request_id, db)
    resources, rc_db = replay_resources(tmp_path, rc, root, db)
    req = rebuild_request(request_id, history, rc_db)
    store = replay_store(tmp_path, db)
    monkeypatch.setattr(pgraph, "REPORTS", tmp_path / "reports")
    events = []
    final = pgraph.run(request_id, store, NoSessions(), on_event=events.append, client=ReplayClient(req),
                       resources=resources)

    assert comparable(final["results"]) == comparable(history["rules"])
    assert final["report"]["summary"] == history["summary"]
    assert final["suppliers"] == history["header"]["suppliers"]
    nodes = [e["node"] for e in events if e["type"] == "node.completed"]
    assert nodes == ["取单", "下载附件", "解析材料", "归集材料", "抽取事实", "规则校验", "生成报告"]
    assert all(e.get("cache") == "hit" for e in events if e["type"] == "file.parsed")
    assert store.get_task(final["report"]["task_id"])["status"] == "done"
