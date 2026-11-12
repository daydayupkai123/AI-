"""工作台任务列表、复核标注、账号登录。"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DE_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.setenv("DE_RC_MODE", "inprocess")
    monkeypatch.setenv("DE_AUTO_REVIEW", "0")
    monkeypatch.setenv("DE_USERS_FILE", str(tmp_path / "users.yaml"))
    from workbench_service import auth
    from shared.task_store import Store

    users = tmp_path / "users.yaml"
    users.write_text(
        "users:\n  admin1:\n    name: 林晓\n    role: admin\n    password: "
        + auth.hash_password("Admin@1234")
        + "\n  reviewer1:\n    name: 周静\n    role: reviewer\n    password: "
        + auth.hash_password("Review@1234")
        + "\n",
        encoding="utf-8",
    )
    auth._cache.update(mtime=None, users={})
    store = Store()
    # 真实来源样例（工作台已屏蔽 local / DEMO-*）
    tid = store.create_task("meeting", "docflow", "通设请字[2026]999号", "meeting-test", trigger_by="web")
    store.set_task_fp(tid, "fp-v1")
    store.save_report(tid, {
        "employee": "meeting", "task_id": tid, "header": {
            "request_id": "通设请字[2026]999号", "request_name": "测试请示", "subject": "测试请示",
            "facts": [["事项类型", "采购结果"], ["会议类型", "总经理办公会"], ["申请人", "综合管理部-周宁"]],
        },
        "verdict": {"level": "warn", "title": "有事项需要确认", "counts": {"issue": 0, "review": 1}},
        "summary": {"规则总数": 2, "codes": {"issue": 0, "review": 1, "pass": 1, "missing": 0, "error": 0, "na": 0, "notrun": 0}},
        "labels": {},
        "rules": [
            {"rule_id": "N01", "name": "标题与附件关联性", "code": "pass", "status": "核查通过",
             "message": "核查通过：关联明确。", "evidence": [], "items": []},
            {"rule_id": "N04", "name": "请示正文", "code": "review", "status": "人工复核",
             "message": "待人工复核：正文金额与附件不一致。", "evidence": [], "items": ["正文金额与附件不一致"]},
        ],
        "materials": [], "timings": [], "findings": [],
    })
    store.finish_task(tid, "done")
    rid = store.node_start(tid, "取单")
    store.node_end(rid, "ok", time.time() - 0.01, summary="公文系统")
    # 本地 DEMO 不应出现在工作台
    demo = store.create_task("meeting", "local", "DEMO-SH-001", "meeting-test", trigger_by="web")
    store.set_task_fp(demo, "fp-demo")
    store.finish_task(demo, "done")
    from workbench_service.server import app

    return TestClient(app), tid


def test_login_and_worklist(env):
    client, tid = env
    assert client.get("/api/meeting/worklist").status_code == 401
    bad = client.post("/api/auth/login", json={"username": "admin1", "password": "wrong"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/login", json={"username": "admin1", "password": "Admin@1234"})
    assert ok.status_code == 200 and ok.json()["name"] == "林晓"
    me = client.get("/api/auth/me").json()
    assert me["role"] == "admin" and me["auth"] is True
    wl = client.get("/api/meeting/worklist").json()
    assert wl["metrics"]["done"] >= 1 and wl["rows"][0]["id"].startswith("SH-")
    assert all(r.get("source") != "local" for r in wl["rows"])
    assert all(not str(r.get("request_id") or "").upper().startswith("DEMO-") for r in wl["rows"])
    # 找到本用例写入的真实来源任务
    row = next(r for r in wl["rows"] if r.get("task_id") == tid)
    detail = client.get(f"/api/meeting/worklist/{row['id']}").json()
    assert detail["status"] == "已完成" and detail["task_id"] == tid
    assert detail["result"]["rules"][0]["label"] == "初审通过"
    assert detail["result"]["rules"][1]["label"] == "风险提示"
    assert "正文金额与附件不一致" in detail["result"]["suggestion"]


def test_review_marks_and_permissions(env):
    client, _ = env
    client.post("/api/auth/login", json={"username": "reviewer1", "password": "Review@1234"})
    wid = client.get("/api/meeting/worklist").json()["rows"][0]["id"]
    saved = client.put(f"/api/meeting/worklist/{wid}/marks", json={
        "marks": [{"rule_id": "N04", "status": "确认问题", "note": "已核对附件，确有差异"}],
    }).json()
    rule = next(r for r in saved["result"]["rules"] if r["rule_id"] == "N04")
    assert rule["review_status"] == "确认问题" and rule["review_note"] == "已核对附件，确有差异"
    assert any(l["action"] == "保存复核" for l in saved["logs"])


def test_label_mapping():
    from workbench_service.tasks_api import LABEL, _label

    assert _label("issue") == "建议驳回"
    assert _label("review") == "风险提示"
    assert _label("pass") == "初审通过"
    assert _label(None, "命中") == "风险提示"
    assert _label("error") == "审查中止"
    assert _label("notrun") == "未执行"
    assert set(LABEL.values()) >= {"建议驳回", "风险提示", "初审通过", "无法校验", "不适用", "审查中止", "未执行"}
