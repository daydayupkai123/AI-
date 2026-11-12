"""真实环境端到端验收（当前登录账号，经工作台接口）：采购、合同、三会三个已接入场景，逐项对照需求核验。

  python tools/checks/e2e_live_check.py                     # 全部
  python tools/checks/e2e_live_check.py procurement contract

前提：资料中心（:8091）与工作台（:8090）已启动，调试 Chrome 已登录门户。全程只读客户系统。
结果逐项打印并写入 .runtime/m0/e2e_live_<时间>.json。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8090"
c = httpx.Client(base_url=BASE, trust_env=False, timeout=120)
results: list[dict] = []


def check(scene: str, name: str, ok: bool, detail: str = "") -> bool:
    results.append({"scene": scene, "check": name, "ok": bool(ok), "detail": detail})
    print(f"  {'✔' if ok else '✘'} {name}{('：' + detail) if detail else ''}")
    return ok


def run(emp: str, rid: str, source: str | None = None, timeout_s: int = 1200) -> tuple[str, list[dict]]:
    body = {"employee": emp, "request_id": rid, **({"source": source} if source else {})}
    r = c.post("/api/runs", json=body)
    r.raise_for_status()
    tid = r.json()["task_id"]
    events: list[dict] = []
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        with c.stream("GET", f"/api/runs/{tid}/events", timeout=timeout_s) as s:
            for line in s.iter_lines():
                if line.startswith("data:") and line[5:].strip() not in ("", "{}"):
                    events.append(json.loads(line[5:]))
        if any(e.get("type") in ("run.completed", "run.failed") for e in events):
            break
    return tid, events


def chat(emp: str, msg: str, task_id: str | None) -> tuple[str, str]:
    kinds, text = set(), []
    with c.stream("POST", "/api/chat", json={"employee": emp, "message": msg, "task_id": task_id}, timeout=300) as s:
        for line in s.iter_lines():
            if line.startswith("data:"):
                ev = json.loads(line[5:])
                kinds.add(ev.get("type"))
                if ev.get("type") in ("text", "guide"):  # 「think」为深度思考过程，界面单独折叠展示，不算正文
                    text.append(str(ev.get("text") or ""))
    return ("guide" if "guide" in kinds else "error" if "error" in kinds else "answer"), "".join(text)


def done(events):
    return next((e for e in events if e.get("type") == "run.completed"), None)


def failed(events):
    return next((e for e in events if e.get("type") == "run.failed"), None)


def common_checks(scene: str, emp: dict, tid: str, events: list[dict], live: bool, n_rules: int, statuses: set):
    ev = done(events)
    if not check(scene, "审查完成", ev is not None, (failed(events) or {}).get("error", "")):
        return None
    rep = ev["report"]
    nodes = [e["node"] for e in events if e.get("type") == "node.completed"]
    check(scene, "节点按流水线全部完成", nodes == emp["nodes"], " → ".join(nodes))
    rules = rep.get("rules") or []
    check(scene, f"{n_rules} 条规则 / 节点全部有结论", len(rules) == n_rules and all(
        (r.get("code") or r.get("status")) in statuses for r in rules),
        f"{len(rules)} 条；" + "、".join(f"{k} {v}" for k, v in _count(rules).items()))
    check(scene, "报告留存规则版本与生成时间", bool(rep.get("rules_version") and rep.get("generated_at")),
          f"{rep.get('rules_version')} · {rep.get('generated_at')}")
    parsed = [e for e in events if e.get("type") == "file.parsed"]
    hits = sum(1 for e in parsed if e.get("cache") == "hit")
    check(scene, "附件解析（命中资料中心缓存的直接复用）", bool(parsed) or not live, f"{len(parsed)} 份，复用 {hits} 份")
    arc = c.get(f"/api/runs/{tid}/archive").json()
    kinds = {i["kind"] for i in arc.get("items", [])}
    need = {"snapshot", "rules", "report"} | ({"api", "page"} if live else set())
    check(scene, "执行档案完整", arc.get("status") == "done" and need <= kinds,
          "、".join(sorted(kinds)) + f"；证据截图 {len(arc.get('shots') or [])} 张")
    if live:
        page = next((i["body"] for i in arc["items"] if i["kind"] == "page"), {})
        if page.get("page_id"):
            img = c.get(f"/api/archive/pages/{page['page_id']}.png?w=400")
            check(scene, "平台页面整页截图（打码版）", img.status_code == 200 and len(img.content) > 5000,
                  f"{page.get('width')}×{page.get('height')}，拦截写请求 {len(page.get('blocked') or [])} 个")
        else:
            check(scene, "平台页面截图（或写明未截原因）", bool(page.get("skip") or page.get("error")),
                  page.get("skip") or page.get("error") or "无记录")
    return rep


def _count(rules):
    out: dict[str, int] = {}
    for r in rules:
        k = r.get("status") or r.get("code")
        out[k] = out.get(k, 0) + 1
    return out


def supersede_check(scene: str, source: str, rid: str, tid: str):
    d = c.get(f"/api/center/requests/{source}/{rid}")
    if d.status_code != 200:
        return check(scene, "资料中心可追溯该单据", False, f"{d.status_code}")
    tasks = d.json()["tasks"]
    older = [t for t in tasks if t["task_id"] != tid and t["status"] == "done"]
    check(scene, "资料中心可追溯该单据（全流程抽屉数据）", tasks and tasks[0]["task_id"] == tid,
          f"附件 {len(d.json()['snapshot']['files'])} 份，审查 {len(tasks)} 次")
    if older:
        check(scene, "重新审查后旧报告标记为被取代", all(t["superseded_by"] for t in older), f"旧报告 {len(older)} 份")


def chat_checks(scene: str, emp_id: str, tid: str, question: str, expect: list[str]):
    kind, text = chat(emp_id, question, tid)
    check(scene, f"报告追问「{question}」基于报告作答", kind == "answer" and any(w in text for w in expect),
          text[:80].replace("\n", " "))
    kind, _ = chat(emp_id, "今天天气怎么样", tid)
    check(scene, "无关问题不调模型、引导回任务", kind == "guide")


def tasks_checks(scene: str, emp_id: str, scene_ids: list[str]):
    t = c.get(f"/api/{emp_id}/tasks").json()
    got = [a["id"] for a in t["actions"] if a["group"] == "scene"]
    check(scene, "开场任务清单含场景专属卡片", got == scene_ids, "、".join(a["title"] for a in t["actions"] if a["group"] == "scene"))
    return t


# ------------------------------------------------------------------ 场景
def procurement(emps):
    s = "采购"
    print(f"\n== {s}审批（林悦）")
    tasks_checks(s, "procurement", ["scene:list", "scene:collusion"])
    rid = "1674771"
    tid, events = run("procurement", rid)
    if failed(events):
        check(s, f"{rid} 可访问", False, failed(events).get("error"))
        rid = next(r["request_id"] for r in c.get("/api/procurement/queue").json()["rows"] if r["runnable"])
        tid, events = run("procurement", rid)
    rep = common_checks(s, emps["procurement"], tid, events, True, 18, {"命中", "未命中", "未能识别", "未执行"})
    if rep:
        summ = rep.get("summary") or {}
        check(s, "报告按两档汇总并单列未能识别", all(k in summ for k in ("一定不通过", "拿不准", "未能识别")),
              json.dumps(summ, ensure_ascii=False))
        p12 = next((r for r in rep["rules"] if r["rule_id"] == "P12"), {})
        check(s, "串标线索横向比对（P10–P12 有结论）", all(any(r["rule_id"] == k for r in rep["rules"]) for k in ("P10", "P11", "P12")),
              (p12.get("message") or "")[:60])
        supersede_check(s, "contract", rid, tid)
        chat_checks(s, "procurement", tid, "P12 报价有没有规律性差异？", ["P12", "报价", "等差"])
    ins = c.get("/api/procurement/insights/collusion").json()
    check(s, "串标线索汇总可用", "rows" in ins, f"{ins.get('reviewed')} 笔，命中 {ins.get('hits')} 条")


def contract(emps):
    s = "合同"
    print(f"\n== {s}审核（陈睿）")
    tasks_checks(s, "contract", ["scene:list", "scene:credit", "scene:clauses"])
    q = c.get("/api/contract/queue").json()["rows"]
    rid = next((r["request_id"] for r in q if r["request_id"] == "1671817"), None) or \
        next(r["request_id"] for r in q if r["runnable"] and r["list_name"] == "主合同台账·最近")
    tid, events = run("contract", rid)
    rep = common_checks(s, emps["contract"], tid, events, True, 30, {"pass", "issue", "review", "missing", "na"})
    if rep:
        flagged = [r for r in rep["rules"] if r.get("code") in ("issue", "review")]
        check(s, "发现问题 / 人工复核项均附证据或说明", all(r.get("evidence") or r.get("message") for r in flagged),
              f"{len(flagged)} 项")
        arc = c.get(f"/api/runs/{tid}/archive").json()
        llm = [i for i in arc["items"] if i["kind"] == "llm"]
        semantic = [r for r in rep["rules"] if r.get("category") == "语义" and r.get("code") in ("pass", "issue", "review")]
        check(s, "语义规则调用模型并入档（输入输出完整）",
              (bool(llm) and all(i["body"].get("messages") for i in llm)) if semantic else True,
              f"实际执行的语义规则 {len(semantic)} 条，模型调用 {len(llm)} 次，"
              f"命中缓存 {sum(1 for i in llm if i['body'].get('cached'))} 次")
        r17 = next((r for r in rep["rules"] if r["rule_id"] == "R17"), {})
        check(s, "主体资信外部查询有结论（天眼查，共享账号走缓存）", bool(r17.get("status")), (r17.get("message") or "")[:70])
        supersede_check(s, "contract", rid, tid)
        chat_checks(s, "contract", tid, "R17 主体资信是什么情况？", ["R17", "资信", "天眼查", "相对方"])
    for name in ("credit", "clauses"):
        ins = c.get(f"/api/contract/insights/{name}").json()
        check(s, f"{ins.get('title')}可用", "rows" in ins, f"{ins.get('reviewed')} 笔，需关注 {ins.get('hits')} 条")
    _, ev = run("contract", "1656669")
    f = failed(ev) or {}
    check(s, "当前账号待办（1656669）不打开详情、不下载附件", f.get("error") == "待办单据暂不打开", f.get("error") or "未拦截")


def meeting(emps):
    s = "三会"
    print(f"\n== {s}审查（苏婉）")
    tasks_checks(s, "meeting", ["scene:authority", "scene:regs"])
    docs = c.get("/api/knowledge").json()["documents"]
    check(s, "四份制度已启用", len([d for d in docs if d["state"] == "enabled"]) == 4,
          "、".join(f"{d['name'][:10]}…{d['clauses']}条" for d in docs))
    a = c.post("/api/meeting/authority", json={"matter": "信息化项目采购结果", "amount": "80"}).json()
    top = (a.get("results") or [{}])[0]
    check(s, "事项审批权限查询：金额落档并给出审批主体", top.get("status") == "matched" and top.get("final"),
          f"《{top.get('doc', '')[:12]}》{top.get('ref')} → {'、'.join(top.get('final') or [])}")
    _, ev = run("meeting", "通设请字[2026]371号")
    f = failed(ev) or {}
    check(s, "公文系统可达；流程未结束的请示（371 号，当前账号待办）不打开",
          f.get("error") in ("流程未结束的请示暂不打开", "未找到该内部请示", "当前账号无权查看该公文"), f.get("error") or "未拦截")
    rid = "通设请字[2026]342号"
    tid, events = run("meeting", rid)
    rep = common_checks(s, emps["meeting"], tid, events, True, 5, {"pass", "issue", "review", "missing", "na"})
    if rep:
        snap = c.get(f"/api/center/requests/docflow/{rid}").json().get("snapshot") or {}
        check(s, f"{rid}：经「公司数据查询 → 内部请示查询」只读打开已结束请示",
              len(snap.get("files") or []) >= 6, f"附件 {len(snap.get('files') or [])} 份")
        check(s, f"{rid}：5 个节点均有综合意见", [r["rule_id"] for r in rep["rules"]] == ["N01", "N02", "N03", "N04", "N05"],
              "；".join(f"{r['rule_id']} {r['code']}" for r in rep["rules"]))
        supersede_check(s, "docflow", rid, tid)
    real_cases(s, emps)
    for rid, expect in (("DEMO-SH-001", "issue"), ("DEMO-SH-002", "pass")):
        tid, events = run("meeting", rid, "local")
        rep = common_checks(s, emps["meeting"], tid, events, False, 5, {"pass", "issue", "review", "missing", "na"})
        if rep:
            ids = [r["rule_id"] for r in rep["rules"]]
            check(s, f"{rid}：5 个节点按固定顺序输出综合意见", ids == ["N01", "N02", "N03", "N04", "N05"],
                  "；".join(f"{r['rule_id']} {r['status']}" for r in rep["rules"]))
            n03 = rep["rules"][2]
            check(s, f"{rid}：审批依据引用真实制度文件与条款", "《" in (n03.get("message") or "") or n03.get("code") in ("missing", "review"),
                  (n03.get("message") or "")[:70])
            want = any(r["code"] == "issue" for r in rep["rules"]) if expect == "issue" else all(
                r["code"] == "pass" for r in rep["rules"])
            check(s, f"{rid}：结论符合样例设计（{'问题样例' if expect == 'issue' else '规范样例'}）", want,
                  (rep.get("verdict") or {}).get("title", ""))
            if rid == "DEMO-SH-001":
                chat_checks(s, "meeting", tid, "N03 审批依据有什么问题？", ["N03", "依据", "条款", "权责"])
    tid, events = run("meeting", "DEMO-SH-001", "local")
    parsed = [e for e in events if e.get("type") == "file.parsed"]
    check(s, "重新审查时材料复用缓存（T06）", parsed and all(e.get("cache") == "hit" for e in parsed),
          f"{len(parsed)} 份附件全部复用" if parsed else "无解析事件")


def real_cases(s: str, emps: dict):
    """真实材料改造事项（tools/samples/make_meeting_real_cases.py）：每条的注入问题须在预期节点被指出（issue / review）。"""
    rows = {r["request_id"]: r for r in c.get("/api/meeting/samples").json().get("rows", [])}
    ids = sorted(k for k in rows if k.startswith("REAL-SH-"))
    if not check(s, "真实材料改造事项已生成", len(ids) == 5, "、".join(ids) or "请先运行 tools/samples/make_meeting_real_cases.py"):
        return
    base = {}
    for rid in ids:
        case = json.loads((ROOT / ".runtime" / "cases" / "meeting" / rid / "case.json").read_text(encoding="utf-8"))
        expect = {k: v for k, v in (case.get("extra") or {}).get("expect", {}).items() if k.startswith("N")}
        kws = (case.get("extra") or {}).get("expect_kw") or {}
        tid, events = run("meeting", rid, "local")
        ev = done(events)
        if not check(s, f"{rid} 审查完成", ev is not None, (failed(events) or {}).get("error", "")):
            continue
        codes = {r["rule_id"]: r for r in ev["report"]["rules"]}
        line = "；".join(f"{k} {r['code']}" for k, r in codes.items())
        if not expect:
            base = {k: r["code"] for k, r in codes.items()}
            check(s, f"{rid}（{case['summary'][:24]}…）基线", True, line)
            continue
        def said(k):  # 该节点意见（综合意见 + 编号问题）
            r = codes.get(k, {})
            return (r.get("message") or "") + " " + " ".join(r.get("items") or [])

        hit = {k: codes.get(k, {}).get("code") in ("issue", "review") and all(w in said(k) for w in kws.get(k, []))
               for k in expect}
        changed = [k for k in expect if base and codes.get(k, {}).get("code") != base.get(k)]
        check(s, f"{rid}（{'、'.join(case['tags'][1:])}）在预期节点因注入的问题被指出", all(hit.values()),
              "；".join(f"{k} {codes.get(k, {}).get('code')}：" + next(
                  (x for x in (codes.get(k, {}).get("items") or []) if all(w in x for w in kws.get(k, [])[:1])),
                  codes.get(k, {}).get("message") or "")[:70] for k in expect)
              + (f"（相对基线变化：{'、'.join(changed)}）" if changed else ""))


def flows():
    """流程与规则 + 原文对照（真实单据）：发布测试配置 → 审查生效 → 对照原文 → 恢复默认并重审，结束后真实环境回到默认规则。"""
    s = "流程与规则"
    print("\n== 流程与规则 / 原文对照（合同 1671817）")
    idx = c.get("/api/flows").json()
    check(s, "四个员工都有流程定义", sorted(x["id"] for x in idx) == ["contract", "meeting", "procurement", "reimburse"],
          "；".join(f"{x['persona']} {x['nodes']} 节点 / {x['rules']} 条规则" for x in idx))
    fd = c.get("/api/flows/contract").json()
    exec_node = next(n for n in fd["nodes"] if n["name"] == fd["exec"])
    check(s, "合同流程线：规则挂在执行节点并声明依赖", len(exec_node["exec_rules"]) == 30 and all(r["deps"] for r in fd["rules"]),
          f"「{fd['exec']}」执行 {len(exec_node['exec_rules'])} 条；方案对照 {len(fd['plan'])} 步")
    base = fd["effective_version"]
    author = "端到端验收"
    c.put("/api/flows/contract/draft", json={"author": author, "rules": {
        "R07": {"suggest": "请核对合同违约责任条款与招标文件的差异，确认是否经过谈判同意"},
        "R10": {"params": {"penalty_limit_ratio": 0.25}}}}).raise_for_status()
    pub = c.post("/api/flows/contract/publish", json={"author": author, "note": "端到端验收测试配置（验收后恢复默认）"}).json()
    check(s, "发布后生效版本带配置序号", pub["effective_version"] != base and "+c" in pub["effective_version"], pub["effective_version"])
    tid, events = run("contract", "1671817")
    rep = (done(events) or {}).get("report") or {}
    r07 = next((r for r in rep.get("rules", []) if r["rule_id"] == "R07"), {})
    check(s, "新报告按新版规则生成", rep.get("rules_version") == pub["effective_version"], rep.get("rules_version", ""))
    check(s, "核实建议进入报告（R07）", r07.get("suggest", "").startswith("请核对合同违约责任"), r07.get("suggest", "")[:30])
    arc = c.get(f"/api/runs/{tid}/archive").json()
    snap = (arc.get("versions") or {}).get("rule_config") or {}
    check(s, "执行档案保存当时的规则配置快照", snap.get("n") == pub["n"] and "R10" in (snap.get("body") or {}).get("rules", {}),
          f"第 {snap.get('n')} 版")
    cm = c.get(f"/api/runs/{tid}/compare?refresh=1").json()
    exact = sum(1 for it in cm["items"] for e in it["evidence"] if (e.get("loc") or {}).get("method") in ("text", "ocr", "para"))
    check(s, "原文对照：问题项定位到源文件", cm["items"] and exact >= cm["evidence_total"] * 0.7,
          f"需关注 {len(cm['items'])} 项，证据 {cm['evidence_total']} 条，精确定位 {exact} 条")
    loc = next(e["loc"] for it in cm["items"] for e in it["evidence"] if (e.get("loc") or {}).get("method") == "text")
    img = c.get(f"/api/files/{loc['sig']}/pages/{loc['page_no']}.png")
    check(s, "原文对照：按页出图并给出高亮坐标", img.status_code == 200 and loc["rects"], f"第 {loc['page_no']} 页，{len(loc['rects'])} 处")
    c.post("/api/flows/contract/rollback/0", json={"author": author}).raise_for_status()
    back = c.post("/api/flows/contract/publish", json={"author": author, "note": "端到端验收结束，恢复代码默认"}).json()
    check(s, "恢复默认后生效版本回到代码规则版本", back["effective_version"] == base, back["effective_version"])
    od = c.get("/api/flows/contract/outdated").json()["rows"]
    check(s, "测试期间生成的报告标记为按旧版规则生成", any(r["task_id"] == tid for r in od), f"{len(od)} 份")
    tid2, ev2 = run("contract", "1671817")
    rep2 = (done(ev2) or {}).get("report") or {}
    check(s, "按默认规则重审，真实环境恢复原状", rep2.get("rules_version") == base and not any(
        r.get("suggest") for r in rep2.get("rules", [])), rep2.get("rules_version", ""))


def collection():
    s = "采集"
    print("\n== 资料中心采集与全流程")
    since = time.time() - 1
    for src in ("contract", "docflow"):
        c.post(f"/api/collect/run?source={src}")
    rounds = []
    for _ in range(90):
        time.sleep(2)
        st = c.get("/api/collect/status").json()
        rounds = [r for r in st["rounds"] if r["started_at"] >= since and r["finished_at"]]
        if {r["source"] for r in rounds} >= {"contract", "docflow"}:
            break
    for r in rounds:
        check(s, f"立即采集 · {r['source']}", not r.get("error"), f"列出 {r['listed']}，同步 {r['queued']}{('；' + r['error']) if r.get('error') else ''}")
    ov = c.get("/api/center/overview").json()
    st = ov.get("stats") or {}
    check(s, "资料中心全流程总览", not ov.get("error") and st.get("blobs", {}).get("n", 0) > 0,
          f"单据 {sum((st.get('snapshots') or {}).values())}，原件 {st['blobs']['n']}，OCR {st['parse']['ocr_pages']} 页，"
          f"档案 {sum((st.get('archives') or {}).values())}")


def main() -> int:
    want = sys.argv[1:] or ["procurement", "contract", "meeting", "flows", "collection"]
    emps = {e["id"]: e for e in c.get("/api/employees").json()}
    print("员工状态：", "，".join(f"{e['persona']} {e['status']}" for e in emps.values()))
    llm = c.get("/api/llm/status").json()
    print("对话模型：", json.dumps(llm, ensure_ascii=False)[:160])
    for name in want:
        try:
            globals()[name](emps) if name not in ("collection", "flows") else globals()[name]()
        except Exception as exc:  # noqa: BLE001
            check(name, "执行异常", False, f"{type(exc).__name__}: {exc}")
    ok = sum(1 for r in results if r["ok"])
    print(f"\n合计 {ok}/{len(results)} 项通过")
    out = ROOT / ".runtime" / "m0" / f"e2e_live_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("明细：", out)
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
