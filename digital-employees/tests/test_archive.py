"""执行档案：脱敏、审查全过程入档（快照 / 模型调用 / 规则 / 报告 / 截图）、接口报文、截图定位、档案失败不中断审查。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from core.resource.mask import mask_obj, mask_text, mask_url


def _valid_id(prefix17: str) -> str:
    w = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    return prefix17 + "10X98765432"[sum(int(c) * x for c, x in zip(prefix17, w)) % 11]


def test_mask_rules():
    idno = _valid_id("37088319880508741")
    s = f"总监理工程师张胜，身份证号码：{idno}，电话 13812345678，开户账号：6222 0202 0001 2345 678"
    m = mask_text(s)
    assert idno not in m and idno[:3] + "*" * 11 + idno[-4:] in m
    assert "138****5678" in m and "6222020200012345678" not in m and "622************5678" in m
    # 不是身份证（校验位错）、单据编号、affairId 不误伤
    keep = "affairId 4123236229515985642，单号 1671817，编号 370883198805087410"
    assert mask_text(keep) == keep
    u = mask_url("https://x/weaver.file.FileDownload?fileid=1&authStr=abc&authSignatureStr=def&v=sig&requestid=9")
    assert "abc" not in u and "def" not in u and "v=***" in u and "requestid=9" in u and "fileid=1" in u
    assert mask_obj({"token": "t", "a": [f"手机 13900001111"]}) == {"token": "***", "a": ["手机 139****1111"]}


def _fake_complete(messages, role):
    return json.dumps({"conclusion": "一致", "summary": "测试一致", "differences": [], "answer": "否",
                       "relation": "相关", "quote": "", "problems": [], "results": [], "reason": "测试"},
                      ensure_ascii=False)


@pytest.fixture()
def meeting_env(tmp_path, monkeypatch):
    from core.llm import client as llm
    from core.sources.local import LocalCaseClient
    from employees.meeting import graph as mgraph
    from employees.meeting import samples
    from tests.support.env import temp_resources, temp_store

    cases = tmp_path / "cases"
    samples.write(cases)
    monkeypatch.setattr(mgraph, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(llm, "complete", _fake_complete)
    return mgraph, temp_store(tmp_path), temp_resources(tmp_path), LocalCaseClient("meeting", root=cases)


def test_review_run_is_fully_archived(meeting_env):
    mgraph, store, rc, client = meeting_env
    events = []
    final = mgraph.run("DEMO-SH-001", store, None, on_event=events.append, source="local", client=client,
                       resources=rc)
    tid = final["task_id"]
    arc = rc.archive(tid)
    assert arc["status"] == "done" and arc["employee"] == "meeting" and arc["request_id"] == "DEMO-SH-001"
    assert arc["material_fp"] and arc["material_fp"] == store.get_task(tid)["material_fp"]
    assert arc["versions"]["rules"] and arc["versions"]["code"] and "meeting.yaml" in arc["versions"]["config"]
    assert "accounts.yaml" not in arc["versions"]["config"]
    kinds = [i["kind"] for i in arc["items"]]
    for k in ("snapshot", "event", "llm", "rules", "report"):
        assert k in kinds, k
    snap = next(i for i in arc["items"] if i["kind"] == "snapshot")["body"]
    assert snap["fields"] and snap["attachments"] and "loadlink" not in snap["attachments"][0]
    llm_items = [i["body"] for i in arc["items"] if i["kind"] == "llm"]
    assert llm_items and all(x["messages"][0]["role"] == "system" and x["ok"] for x in llm_items)
    assert any(x.get("raw") for x in llm_items)  # 首次调用记录模型原始输出
    seq = [i["seq"] for i in arc["items"]]
    assert seq == sorted(seq) == list(range(1, len(seq) + 1))
    assert arc["verdict"] and arc["verdict"]["level"] == "bad"
    assert arc["shots"], "问题样例应生成证据截图"
    assert any(e["type"] == "archive.shots" for e in events)


def test_archive_failure_does_not_stop_review(meeting_env, monkeypatch):
    mgraph, store, rc, client = meeting_env

    def broken(*a, **k):
        raise RuntimeError("资料中心档案库不可写")

    monkeypatch.setattr(rc.service, "archive_start", broken)
    events = []
    final = mgraph.run("DEMO-SH-002", store, None, on_event=events.append, source="local", client=client,
                       resources=rc)
    assert store.get_task(final["task_id"])["status"] == "done"
    assert any(e["type"] == "node.note" and "执行档案写入失败" in e["text"] for e in events)


def test_rerun_supersedes_previous(meeting_env):
    mgraph, store, rc, client = meeting_env
    a = mgraph.run("DEMO-SH-002", store, None, source="local", client=client, resources=rc)["task_id"]
    b = mgraph.run("DEMO-SH-002", store, None, source="local", client=client, resources=rc)["task_id"]
    assert store.get_task(a)["superseded_by"] == b and store.get_task(b)["superseded_by"] is None


def test_api_hook_records_masked_traffic(tmp_path):
    from core.archive import RunArchive
    from tests.support.env import temp_resources

    idno = _valid_id("11010519491231002")

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            data = json.dumps({"name": "张三", "idcard": idno, "mobile": "13800138000"}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    rc = temp_resources(tmp_path)
    arc = RunArchive(rc, {"task_id": "t1", "employee": "contract", "source_system": "contract", "request_id": "1",
                          "trigger_by": "web", "rules_version": "1"})
    s = requests.Session()
    s.trust_env = False
    s.hooks["response"].append(arc.api_hook)
    s.post(f"http://127.0.0.1:{srv.server_address[1]}/api/workflow/reqform/loadForm?authStr=SECRET",
           data={"requestid": "1609472", "authSignatureStr": "SIG"})
    arc.finish("done")
    srv.shutdown()
    item = next(i for i in rc.archive("t1")["items"] if i["kind"] == "api")["body"]
    text = json.dumps(item, ensure_ascii=False)
    assert "SECRET" not in text and "SIG" not in text and idno not in text and "13800138000" not in text
    assert "1609472" in item["request_body"] and item["status"] == 200 and "张三" in item["response"]


def test_shot_render_text_and_ocr(tmp_path):
    import pymupdf

    from core.resource import shots

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Payment: 30% after signing the contract.")
    blank = doc.new_page()
    data = doc.tobytes()
    r = shots.render(data, "a.pdf", None, 1, "30% after signing")
    assert r["method"] == "text" and r["rects"] and r["png"].startswith(b"\x89PNG")
    parsed = {"pages": [{"no": 1, "method": "text"},
                        {"no": 2, "method": "ocr", "lines": [{"text": "违约金按合同价款的百分之二十计算", "box": [[150, 300], [600, 300], [600, 340], [150, 340]]}]}]}
    r2 = shots.render(data, "a.pdf", parsed, 2, "违约金按合同价款的百分之二十计算")
    assert r2["method"] == "ocr" and r2["page_no"] == 2
    x0, y0, x1, y1 = r2["rects"][0]
    assert abs(x0 - 150 * 72 / 150) < 0.01 and abs(y1 - 340 * 72 / 150) < 0.01
    r3 = shots.render(data, "a.pdf", parsed, None, "完全找不到的引用内容")
    assert r3["method"] == "page" and r3["rects"] == [] and r3["png"]
    assert shots.render(b"PK\x03\x04", "a.docx", None, 1, "x")["method"] == "none"
