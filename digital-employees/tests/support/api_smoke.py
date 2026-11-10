"""工作台接口冒烟（在独立进程中运行，DE_RUNTIME 指向临时目录，不污染正式存储）。输出 JSON 结果。"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.sources.local import CASES  # noqa: E402
from employees.contract import samples as cs  # noqa: E402
from employees.meeting import samples as ms  # noqa: E402
from employees.reimburse import samples as rs  # noqa: E402

for w in (cs.write, ms.write, rs.write):
    w(CASES)

from fastapi.testclient import TestClient  # noqa: E402

from core.api.server import app  # noqa: E402

out = {}
with TestClient(app) as c:
    emps = c.get("/api/employees").json()
    out["employees"] = {e["id"]: {"status": e["status"], "nodes": e["nodes"], "kind": e["kind"]} for e in emps}
    for eid in ("contract", "meeting", "reimburse"):
        out[f"{eid}_samples"] = [r["request_id"] for r in c.get(f"/api/{eid}/samples").json()["rows"]]
        rules = c.get(f"/api/{eid}/rules").json()
        out[f"{eid}_rules"] = {"n": len(rules["rules"]), "states": sorted({r["state"] for r in rules["rules"]})}
    out["procurement_rules"] = len(c.get("/api/procurement/rules").json()["rules"])
    out["unknown_employee"] = c.get("/api/nobody/rules").status_code
    out["bad_local_id"] = c.post("/api/runs", json={"employee": "reimburse", "request_id": "DEMO-XX-999", "source": "local"}).status_code
    out["bad_live_id"] = c.post("/api/runs", json={"employee": "reimburse", "request_id": "abc"}).status_code
    out["bad_source"] = c.post("/api/runs", json={"employee": "meeting", "request_id": "DEMO-SH-001", "source": "contract"}).status_code
    r = c.post("/api/runs", json={"employee": "reimburse", "request_id": "DEMO-BX-002", "source": "local"}).json()
    events, t0 = [], time.time()
    while time.time() - t0 < 60:
        with c.stream("GET", f"/api/runs/{r['task_id']}/events") as s:
            for line in s.iter_lines():
                if line.startswith("data:") and line[5:].strip() != "{}":
                    events.append(json.loads(line[5:]))
        if any(e.get("type") in ("run.completed", "run.failed") for e in events):
            break
    done = next(e for e in events if e.get("type") in ("run.completed", "run.failed"))
    out["run_type"] = done["type"]
    out["run_title"] = (done.get("report") or {}).get("verdict", {}).get("title") or done.get("error")
    out["run_nodes"] = [e["node"] for e in events if e.get("type") == "node.completed"]
    out["history"] = [x["request_id"] for x in c.get("/api/runs?employee=reimburse").json()]
    out["report_kind"] = c.get(f"/api/runs/{r['task_id']}").json()["kind"]
    live = c.post("/api/runs", json={"employee": "reimburse", "request_id": "1000001431-CLBX2609-000579"}).json()
    time.sleep(1.5)
    evs = []
    with c.stream("GET", f"/api/runs/{live['task_id']}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data:") and line[5:].strip() != "{}":
                evs.append(json.loads(line[5:]))
    failed = next((e for e in evs if e.get("type") == "run.failed"), {})
    out["live_not_ready"] = failed.get("error")
    page = c.get("/")
    out["index"] = page.status_code == 200 and "AI 数字员工工作台" in page.text

    def chat(msg, task_id=None):
        evs = []
        with c.stream("POST", "/api/chat", json={"employee": "contract", "message": msg, "task_id": task_id}) as s:
            for line in s.iter_lines():
                if line.startswith("data:"):
                    evs.append(json.loads(line[5:]))
        return evs

    g = chat("今天天气怎么样")
    out["chat_guide"] = g[0]["type"] == "guide" and "不闲聊" in g[0]["text"]
    out["chat_hello_with_report"] = chat("你好", r["task_id"])[0]["type"]  # 报告存在时闲聊也只给引导
    q = c.get("/api/contract/queue").json()
    out["queue"] = {"rows": len(q["rows"]), "auto": q["auto_review"], "error": q["error"]}
    st = c.get("/api/collect/status")
    out["collect_status"] = st.status_code == 200 and "sources" in st.json()
    out["archive"] = c.get(f"/api/runs/{r['task_id']}/archive").json().get("status")

    # 采集本地事项 → 任务清单（开场可点击的流程与待审单据）→ 批量审查 → 批次进度
    out["collect_run"] = {k: v for k, v in c.post("/api/collect/run?source=local").json().items()
                          if k in ("listed", "queued", "error")}
    t0 = time.time()
    while time.time() - t0 < 60:
        tasks = c.get("/api/reimburse/tasks").json()
        if tasks["stats"]["ready"] == 3:
            break
        time.sleep(0.5)
    out["tasks_stats"] = {k: tasks["stats"][k] for k in ("total", "ready", "todo", "reviewed")}
    out["tasks_actions"] = [(a["id"], a["enabled"]) for a in tasks["actions"]]
    out["tasks_todo"] = sorted(x["request_id"] for x in tasks["todo"])
    b = c.post("/api/reimburse/batch", json={}).json()
    t0 = time.time()
    while not b["finished"] and time.time() - t0 < 120:
        time.sleep(0.5)
        b = c.get(f"/api/batches/{b['batch_id']}").json()
    out["batch"] = {"total": b["total"], "finished": b["finished"],
                    "items": sorted((i["request_id"], i["status"], (i["verdict"] or {}).get("title")) for i in b["items"])}
    after = c.get("/api/reimburse/tasks").json()
    out["tasks_after"] = {"todo": after["stats"]["todo"],
                          "batch_enabled": next(a for a in after["actions"] if a["id"] == "batch")["enabled"]}
    out["batch_again"] = c.post("/api/reimburse/batch", json={}).status_code
    out["batch_triggers"] = sorted({x["trigger_by"] for x in c.get("/api/runs?employee=reimburse").json()})
    m = c.get("/api/meeting/tasks").json()
    out["meeting_tasks"] = {"total": m["stats"]["total"], "todo": sorted(x["request_id"] for x in m["todo"])}
    out["procurement_tasks_rows"] = c.get("/api/procurement/tasks").json()["stats"]["total"]
    out["task_groups"] = [(a["id"], a["group"], bool(a["title"]) and bool(a["desc"])) for a in after["actions"]]
    out["scene_list"] = next(a for a in after["actions"] if a["id"] == "scene:list")["counts"]
    out["scene_ids"] = {e: [a["id"] for a in c.get(f"/api/{e}/tasks").json()["actions"] if a["group"] == "scene"]
                        for e in ("procurement", "contract", "meeting", "reimburse")}
    inv = c.get("/api/reimburse/insights/invoice").json()
    out["insight_invoice"] = {"reviewed": inv["reviewed"], "rows": sorted(r["request_id"] for r in inv["rows"]),
                              "rules": sorted(b["rule_id"] for b in inv["by_rule"])}
    out["insight_wrong_emp"] = c.get("/api/reimburse/insights/collusion").status_code
    au = c.post("/api/meeting/authority", json={"matter": "对外捐赠", "amount": "5"})
    out["authority"] = {"status": au.status_code, "has_results": "results" in au.json(),
                        "amount": au.json().get("amount_wan")}
    out["authority_bad_amount"] = c.post("/api/meeting/authority", json={"matter": "对外捐赠", "amount": "五万"}).status_code

    # 流程与规则：流程线 → 草稿校验 → 发布 → 版本号 → 按新版规则批量重审 → 停用规则在新报告中记「未执行」 → 导出 / 导入 / 回退
    out["flows_index"] = sorted(x["id"] for x in c.get("/api/flows").json())
    fr = c.get("/api/flows/reimburse").json()
    out["flow_shape"] = {"nodes": len(fr["nodes"]), "rules": len(fr["rules"]), "plan": len(fr["plan"]),
                         "exec": len(next(n for n in fr["nodes"] if n["name"] == "规则校验")["exec_rules"])}
    out["draft_bad"] = [
        c.put("/api/flows/reimburse/draft", json={"rules": {"MTG-03": {"enabled": False}}}).status_code,
        c.put("/api/flows/reimburse/draft", json={"rules": {"ENT-09": {"params": {"prior_year_cutoff_month": 13}}}}).status_code,
        c.put("/api/flows/reimburse/draft", json={"rules": {"XXX-01": {"name": "x"}}}).status_code]
    d = c.put("/api/flows/reimburse/draft", json={"author": "测试", "rules": {
        "MTG-03": {"enabled": False, "reason": "冒烟测试停用"},
        "ENT-09": {"params": {"prior_year_cutoff_month": 3}, "suggest": "请更换为本年度发票"}}}).json()
    out["draft_changes"] = len(d["draft_changes"])
    out["publish_no_note"] = c.post("/api/flows/reimburse/publish", json={"author": "测试", "note": ""}).status_code
    pub = c.post("/api/flows/reimburse/publish", json={"author": "测试", "note": "冒烟"}).json()
    out["published"] = {"n": pub["n"], "eff": pub["effective_version"].endswith("+c1"), "outdated": pub["outdated"]}
    ids = [r["request_id"] for r in c.get("/api/flows/reimburse/outdated").json()["rows"] if r["runnable"]]
    b = c.post("/api/reimburse/batch", json={"request_ids": ids}).json()
    t0 = time.time()
    while not b["finished"] and time.time() - t0 < 120:
        time.sleep(0.5)
        b = c.get(f"/api/batches/{b['batch_id']}").json()
    reps = {i["request_id"]: c.get(f"/api/runs/{i['task_id']}").json() for i in b["items"]}
    mtg = (next(r for r in reps["DEMO-BX-003"]["rules"] if r["rule_id"] == "MTG-03")) if "DEMO-BX-003" in reps else {}
    out["rerun"] = {"n": len(reps), "versions_new": all(r["rules_version"].endswith("+c1") for r in reps.values()),
                    "mtg03": [mtg.get("code"), "冒烟测试停用" in (mtg.get("message") or "")]}
    out["outdated_after"] = c.get("/api/flows/reimburse/outdated").json()["rows"]
    out["versions"] = [v["n"] for v in c.get("/api/flows/reimburse/versions").json()["versions"]]
    exp = c.get("/api/flows/reimburse/export").text
    out["export_has"] = "MTG-03" in exp and "冒烟测试停用" in exp
    c.post("/api/flows/reimburse/rollback/0", json={"author": "测试"})
    out["rollback_changes"] = len(c.get("/api/flows/reimburse").json()["draft_changes"])
    out["import_changes"] = len(c.post("/api/flows/reimburse/import", json={"yaml_text": exp, "author": "测试"}).json()["draft_changes"])
    c.post("/api/flows/reimburse/discard", json={})

    # 原文对照：问题项 ↔ 源文件位置
    tid1 = next(i["task_id"] for i in b["items"] if i["request_id"] == "DEMO-BX-001")
    cm = c.get(f"/api/runs/{tid1}/compare").json()
    out["compare"] = {"files": len(cm["files"]) > 0, "items": len(cm["items"]) > 0,
                      "all_have_loc": all("loc" in e for it in cm["items"] for e in it["evidence"]), "located": cm["located"]}
    pdf = next((f for f in cm["files"] if f["kind"] == "pdf"), None)
    out["page_png"] = c.get(f"/api/files/{pdf['sig']}/pages/1.png").status_code if pdf else None

    # 资料中心全流程演示接口
    ov = c.get("/api/center/overview").json()
    st = ov["stats"]
    out["center"] = {"error": ov["error"], "snapshots": sum(st["snapshots"].values()), "blobs": st["blobs"]["n"] > 0,
                     "parse": st["parse"]["n"] > 0, "archives": sum(st["archives"].values()) >= 3,
                     "triggers": sorted(ov["tasks"]["by_trigger"])}
    reqs = c.get("/api/center/requests?employee=reimburse").json()["rows"]
    out["center_rows"] = sorted(r["request_id"] for r in reqs)
    d = c.get("/api/center/requests/local/DEMO-BX-003").json()
    out["center_detail"] = {"files": len(d["snapshot"]["files"]), "archives": len(d["snapshot"]["archives"]),
                            "tasks": [t["trigger_by"] for t in d["tasks"]], "fp": bool(d["snapshot"]["material_fp"]),
                            "parsed": all((f["parsed"] or {}).get("status") == "ok" for f in d["snapshot"]["files"])}
    out["center_missing"] = c.get("/api/center/requests/local/DEMO-XX-404").status_code
print(json.dumps(out, ensure_ascii=False))
