"""工作台接口冒烟：在独立进程 + 临时运行目录中启动服务，覆盖员工列表、样例、规则、参数校验、一次完整审查与历史。"""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent / "support" / "api_smoke.py"


def test_api_smoke(tmp_path):
    env = {**os.environ, "DE_RUNTIME": str(tmp_path / "runtime"), "PYTHONIOENCODING": "utf-8", "DE_RC_MODE": "inprocess",
           "DE_AUTO_REVIEW": "0", "DE_COLLECT_CONFIG": str(SCRIPT.parent / "collect_local.yaml")}
    proc = subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, encoding="utf-8",
                          timeout=240)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert set(out["employees"]) == {"procurement", "contract", "meeting", "reimburse"}
    assert all(out["employees"][k]["status"] == "online" for k in ("procurement", "contract", "meeting"))
    assert out["employees"]["reimburse"]["status"] == "beta"  # 通财云外网不可达，只能审查本地事项
    assert out["employees"]["meeting"]["nodes"][-2] == "审查"
    assert out["contract_samples"] == ["DEMO-HT-001", "DEMO-HT-002"]
    assert out["meeting_samples"] == ["DEMO-SH-001", "DEMO-SH-002"]
    assert out["reimburse_samples"] == ["DEMO-BX-001", "DEMO-BX-002", "DEMO-BX-003"]
    assert out["contract_rules"]["n"] == 30 and out["meeting_rules"]["n"] == 5 and out["reimburse_rules"]["n"] == 43
    assert out["reimburse_rules"]["states"] == ["已上线", "待业务口径", "部分上线"]
    assert out["procurement_rules"] == 18
    assert out["unknown_employee"] == 404
    assert out["bad_local_id"] == 400 and out["bad_live_id"] == 400 and out["bad_source"] == 400
    assert out["run_type"] == "run.completed" and out["run_title"] == "AI 初审通过"
    assert out["run_nodes"] == ["取单", "下载附件", "解析材料", "归集材料", "抽取要素", "规则校验", "生成报告"]
    assert out["history"][0] in ("DEMO-BX-002", "1000001431-CLBX2609-000579") and "DEMO-BX-002" in out["history"]
    assert out["report_kind"] == "review"
    assert out["live_not_ready"] == "通财云取数尚未打通"
    assert out["index"] is True
    assert out["chat_guide"] is True and out["chat_hello_with_report"] == "guide"
    assert out["queue"] == {"rows": 0, "auto": False, "error": None}  # 冒烟采集配置未给合同开自动审查
    assert out["collect_status"] is True
    assert out["archive"] == "done"
    assert out["collect_run"] == {"listed": 5, "queued": 5, "error": None}
    # DEMO-BX-002 已在前面人工审查过、材料指纹一致 → 不再列为待审
    assert out["tasks_stats"] == {"total": 3, "ready": 3, "todo": 2, "reviewed": 1}
    assert ["batch", True] in out["tasks_actions"] and ["collect", True] in out["tasks_actions"]
    assert out["tasks_todo"] == ["DEMO-BX-001", "DEMO-BX-003"]
    assert out["batch"]["total"] == 2 and out["batch"]["finished"]
    assert [i[:2] for i in out["batch"]["items"]] == [["DEMO-BX-001", "done"], ["DEMO-BX-003", "done"]]
    assert all(i[2] for i in out["batch"]["items"])
    assert out["tasks_after"] == {"todo": 0, "batch_enabled": False}
    assert out["batch_again"] == 400
    assert out["batch_triggers"] == ["batch", "web"]
    assert out["meeting_tasks"] == {"total": 2, "todo": ["DEMO-SH-001", "DEMO-SH-002"]}
    assert out["procurement_tasks_rows"] == 0
    assert [g[:2] for g in out["task_groups"]] == [
        ["scene:list", "scene"], ["scene:standards", "scene"], ["scene:invoice", "scene"],
        ["batch", "do"], ["run", "do"], ["collect", "do"], ["queue", "view"], ["flow", "view"],
        ["history", "view"], ["samples", "view"], ["rules", "view"]]
    assert all(g[2] for g in out["task_groups"])  # 每个任务都有标题与「点击后做什么」的说明
    assert out["scene_list"] == {"total": 3, "todo": 0, "reviewed": 3, "next": "；点开查看每笔结论与档案"}
    # 四个场景各有专属卡片
    assert out["scene_ids"] == {"procurement": ["scene:list", "scene:collusion"],
                                "contract": ["scene:list", "scene:credit", "scene:clauses"],
                                "meeting": ["scene:authority", "scene:regs"],
                                "reimburse": ["scene:list", "scene:standards", "scene:invoice"]}
    # 样例 DEMO-BX-001 含连号、上年度发票等票据风险；DEMO-BX-002 为规范样例
    assert out["insight_invoice"]["reviewed"] == 3 and "DEMO-BX-001" in out["insight_invoice"]["rows"]
    assert "DEMO-BX-002" not in out["insight_invoice"]["rows"] and "TRV-04" in out["insight_invoice"]["rules"]
    assert out["insight_wrong_emp"] == 404
    assert out["authority"] == {"status": 200, "has_results": True, "amount": 5.0}
    assert out["authority_bad_amount"] == 400
    # 流程与规则
    assert out["flows_index"] == ["contract", "meeting", "procurement", "reimburse"]
    assert out["flow_shape"] == {"nodes": 7, "rules": 43, "plan": 5, "exec": 43}
    assert out["draft_bad"] == [400, 400, 400]  # 停用不写原因 / 参数越界 / 规则不存在
    assert out["draft_changes"] == 4  # MTG-03 启用 + 原因；ENT-09 参数 + 核实建议
    assert out["publish_no_note"] == 400
    assert out["published"]["n"] == 1 and out["published"]["eff"] and out["published"]["outdated"] == 3
    assert out["rerun"] == {"n": 3, "versions_new": True, "mtg03": ["notrun", True]}
    assert out["outdated_after"] == []
    assert out["versions"] == [1] and out["export_has"]
    assert out["rollback_changes"] > 0 and out["import_changes"] == 0
    # 原文对照
    assert out["compare"]["files"] and out["compare"]["items"] and out["compare"]["all_have_loc"]
    assert out["page_png"] in (200, None)
    assert out["center"] == {"error": None, "snapshots": 5, "blobs": True, "parse": True, "archives": True,
                             "triggers": ["batch", "web"]}
    assert out["center_rows"] == ["DEMO-BX-001", "DEMO-BX-002", "DEMO-BX-003"]
    # DEMO-BX-003：首次批量审查 + 规则发布后按新版批量重审
    assert out["center_detail"] == {"files": 2, "archives": 2, "tasks": ["batch", "batch"], "fp": True, "parsed": True}
    assert out["center_missing"] == 404
