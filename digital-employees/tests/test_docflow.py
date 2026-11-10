"""公文系统（Seeyon）只读适配器：表单解析、单号定位、会话失效自动单点登录、附件下载签名。用合成数据，不连真实系统。"""
import json

import pytest

from core.errors import NoAccess, SessionExpired
from core.sources import docflow
from core.sources.docflow import DocflowClient, parse_form

FORM = """
<div><font>*内请号：</font></div>
<span id="field0001_span" class="browse_class" fieldVal='{name:"field0001",displayName:"内请号",inputType:"edocDocMark",value:"测试请字\\u005b2026\\u005d7号"}'>
  <span class="xdRichTextBox">测试请字[2026]7号</span></span>
<div><font>*标题：</font></div>
<span id="field0002_span" fieldVal='{name:"field0002",displayName:"标题",inputType:"textarea",value:"关于某项目采购结果的请示"}'>
  <span>关于某项目采购结果的请示</span></span>
<div><font>是否&ldquo;三重一大&rdquo;事项：</font></div>
<span id="field0003_span" fieldVal='{name:"field0003",displayName:"是否三重一大事项",inputType:"radio",value:"-2"}'>
  <label><input type="radio" value="-1" disabled="true" /><i></i>是</label>
  <label><input type="radio" value="-2" checked="true" disabled="true" /><i></i>否</label></span>
<div><font>事项类型：</font></div>
<span id="field0004_span" fieldVal='{name:"field0004",displayName:"事项类型",inputType:"select",value:""}'><span></span></span>
<div><font>分管/相关领导：</font></div>
<span id="field0006_span" fieldVal='{name:"field0006",displayName:"分管相关领导",inputType:"multimember",value:"123"}'>
  <span>张三</span></span>
<div><font>会议类型：</font></div>
<span id="field0014_span" fieldVal='{name:"field0014",value:"0",displayName:"董事会",inputType:"checkbox"}'><span class="ico16"></span></span><font>董事会</font>
<span id="field0016_span" fieldVal='{name:"field0016",value:"1",displayName:"总经理办公会",inputType:"checkbox"}'><span class="ico16"></span></span><font>总经理办公会</font>
<span id="field0018_span" fieldVal='{name:"field0018",value:"0",displayName:"不上会",inputType:"checkbox"}'><span class="ico16"></span></span><font>不上会</font>
<div><font>审批/上会依据：</font></div>
<span id="field0008_span" fieldVal='{name:"field0008",displayName:"审批上会依据",inputType:"textarea",value:"依据《权责手册》第46项"}'>
  <span>依据《权责手册》第46项</span></span>
<div><font>附件：</font></div>
<span id="field0011_span" fieldVal='{name:"field0011",displayName:"附件",inputType:"attachment",value:"-9"}'>
  <div class="comp" attsdata='[{"id":"1","type":0,"filename":"请示正文.docx","createdate":"2026-01-05 10:00:00","size":"5","fileUrl":"777","v":"sig-a"},{"id":"2","type":2,"filename":"关联协同","createdate":"2026-01-05 10:00:00","fileUrl":"888","v":"sig-b"}]'></div></span>
"""


def test_parse_form_labels_values_and_groups():
    fields, atts = parse_form(FORM)
    by = {f["label"]: f for f in fields}
    assert by["内请号"]["display"] == "测试请字[2026]7号"
    assert by["是否“三重一大”事项"]["display"] == "否"
    assert by["事项类型"]["display"] == ""
    assert by["分管/相关领导"]["display"] == "张三"
    assert by["审批/上会依据"]["display"] == "依据《权责手册》第46项"
    assert by["会议类型"]["htmltype"] == "checkboxgroup" and by["会议类型"]["display"] == "总经理办公会"
    assert by["董事会"]["display"] == "否" and by["总经理办公会"]["display"] == "是"
    assert [a["filename"] for a in atts] == ["请示正文.docx", "关联协同"] and atts[0]["_field"] == "field0011"


class Resp:
    def __init__(self, status=200, body=b"", headers=None, url=""):
        self.status_code, self.content, self.headers, self.url = status, body, headers or {}, url

    @property
    def text(self):
        return self.content.decode("utf-8", "ignore")

    def json(self):
        return json.loads(self.content)


def _base(state=2):
    return json.dumps({"code": "0", "data": {
        "summaryInfo": {"id": "S1", "subject": "内部请示：测试请字[2026]7号关于某项目采购结果的请示",
                        "startMemberName": "某人", "createDate": "2026-01-05 10:01", "affair": {"state": state}},
        "form": {"rightId": "R1", "formAppId": "F1", "formRecordId": "REC"},
        "basicInfo": {"template": {"id": "T1", "subject": "内部请示"}},
        "attachmentInfo": {"attachments": [
            {"id": "1", "type": "0", "fileName": "请示正文.docx", "createDate": "2026-01-06 09:00", "size": "5",
             "fileUrl": "777", "v": "sig-a2"},
            {"id": "3", "type": "0", "fileName": "评审报告.pdf", "createDate": "2026-01-06 09:00", "size": "4",
             "fileUrl": "999", "v": "sig-c"}]}}}).encode()


class FakeSession:
    """模拟门户 + Seeyon：oa_ok=False 时 OA 接口先跳登录页，经 tyssj 单点登录后恢复。"""

    def __init__(self, oa_ok=True, rows=None, portal_login=True, qrows=None, html_once=False):
        self.oa_ok, self.portal_login, self.html_once = oa_ok, portal_login, html_once
        self.rows = rows if rows is not None else [
            {"affairId": "4123236229515985600", "objectId": "S1", "subject": "内部请示：测试请字[2026]7号关于某项目采购结果的请示",
             "nodePolicyName": "拟文"}]
        self.qrows = qrows or []
        self.calls = []

    def post(self, url, data=None, headers=None, timeout=None, allow_redirects=True):
        if "getQueryResult" in url:
            args = json.loads(data["arguments"])
            info = json.loads(args[1]["queryInfo"])
            self.calls.append(("QUERY", url, info["userCondition"]))
            if not self.oa_ok:
                return Resp(body=b'"__LOGOUT"')
            cond = {c["fieldName"].split(".")[-1]: c["fieldValue"] for c in info["userCondition"] if c["fieldName"]}
            rows = [r for r in self.qrows if cond.get("field0001", "") in r["field0001"]
                    and cond.get("field0002", "") in r["field0002"]]
            p = args[0]
            return Resp(body=json.dumps({"total": len(rows),
                                         "data": rows[(p["page"] - 1) * p["size"]:p["page"] * p["size"]]}).encode())
        body = json.loads(data)
        self.calls.append(("POST", url, body["type"]))
        assert body["type"] in docflow.LIST_TYPES, "不得查询待办列表"
        rows = self.rows if body["type"] == "doneSent" else []
        return Resp(body=json.dumps({"respCode": "00000", "result": {"data": {body["type"]: {"data": rows}}}}).encode())

    def get(self, url, params=None, timeout=None, allow_redirects=True):
        self.calls.append(("GET", url, params))
        if "tyssj.do" in url:
            if not self.portal_login:
                return Resp(url="https://login.gt.cn/cas/login")
            self.oa_ok = True
            return Resp(url="https://oa-xc.gt.cn/seeyon/main.do")
        if not self.oa_ok:
            return Resp(302, headers={"location": "https://oa-xc.gt.cn/seeyon/main.do?method=login"})
        if "deal-base-info" in url:
            if params.get("openFrom") == "formQuery":
                d = json.loads(_base())
                d["data"]["summaryInfo"]["affair"]["affairId"] = "SENDER-AFF"
                return Resp(body=json.dumps(d).encode())
            return Resp(body=_base())
        if "content.do" in url:
            return Resp(body=FORM.encode())
        if "fileDownload.do" in url and (params or {}).get("method") == "download":
            return Resp(302, headers={"location": f"/seeyon/fileDownload.do?method=doDownload&fileId={params['fileId']}"})
        if "doDownload" in url and self.html_once:
            self.html_once = False
            return Resp(body=b'<section data-role="page"></section>', headers={"content-type": "text/html"})
        if "doDownload" in url:
            return Resp(body=b"12345" if "777" in url else b"1234", headers={"content-type": "application/octet-stream"})
        raise AssertionError(url)


def test_fetch_maps_fields_and_attachments():
    c = DocflowClient(FakeSession())
    req = c.fetch("测试请字[2026]7号")
    assert req.workflow_name == "内部请示" and req.node_name == "拟文"
    assert req.raw_params["affairId"] == "4123236229515985600" and req.extra["mark"] == "测试请字[2026]7号"
    form = {f["label"]: f["display"] for f in req.fields}
    assert form["会议类型"] == "总经理办公会" and form["审批/上会依据"].startswith("依据")
    names = [a.filename for a in req.attachments]
    assert names == ["请示正文.docx", "评审报告.pdf"]  # 表单附件与 deal-base-info 附件按 fileUrl 去重
    assert req.extra["linked_docs"] == ["关联协同"]
    a = req.attachments[0]
    assert a.field_label == "附件" and a.image_file_id == "777"
    assert a.version_id == "2026-01-05 10:00:00"  # 版本标识不用会话相关的下载签名
    assert c.download(a) == b"12345"


def test_session_expiry_triggers_sso_once():
    s = FakeSession(oa_ok=False)
    req = DocflowClient(s).fetch("4123236229515985600")
    assert req.request_name.startswith("内部请示")
    assert sum(1 for m, u, _ in s.calls if "tyssj.do" in u) == 1
    assert not any(m == "POST" for m, *_ in s.calls)  # affairId 直接使用，不查列表


def test_portal_logged_out_raises_session_expired():
    with pytest.raises(SessionExpired):
        DocflowClient(FakeSession(oa_ok=False, portal_login=False)).fetch("4123236229515985600")


def test_locate_not_found_and_ambiguous():
    with pytest.raises(NoAccess, match="未找到"):
        DocflowClient(FakeSession(rows=[])).fetch("测试请字[2026]8号")
    rows = [{"affairId": "1", "objectId": "A", "subject": "内部请示：测试请字[2026]7号甲"},
            {"affairId": "2", "objectId": "B", "subject": "内部请示：测试请字[2026]7号乙"}]
    with pytest.raises(NoAccess, match="匹配到 2 份公文") as ei:
        DocflowClient(FakeSession(rows=rows)).fetch("测试请字[2026]7号")
    assert ei.value.title == "单号不唯一"


def test_mark_pattern_and_bracket_normalisation():
    import re

    for ok in ("通设请字[2026]76号", "通设请字〔2026〕76号", "通设请字【2026】 76 号", "4123236229515985642",
               "-470969041925223572"):
        assert re.fullmatch(docflow.ID_PATTERN, ok), ok
    for bad in ("关于某事项的请示", "76号", "DEMO-SH-001", "12345"):
        assert not re.fullmatch(docflow.ID_PATTERN, bad), bad
    assert docflow.norm_mark("通设请字〔2026〕 76号") == "通设请字[2026]76号"
    req = DocflowClient(FakeSession()).fetch("测试请字〔2026〕7号")
    assert req.raw_params["affairId"] == "4123236229515985600"


def test_download_size_mismatch_rejected():
    c = DocflowClient(FakeSession())
    req = c.fetch("4123236229515985600")
    bad = req.attachments[1]
    bad.loadlink = bad.loadlink.rsplit("|", 1)[0] + "|99"
    with pytest.raises(docflow.Unexpected, match="大小不符"):
        c.download(bad)


def _qrow(mark, state="已结束", subject="关于某项目采购结果的请示", sid="S1"):
    return {"id": "REC", "field0001": mark, "field0002": subject, "field0012": "某人", "field0009": "运营管理部",
            "field0013": "2026-01-05 10:00", "field0003": "否", "field0004": "", "finishedflag": state,
            "field0007": "未勾选", "summaryId": sid}


def test_company_query_fallback_opens_finished_request_read_only():
    s = FakeSession(rows=[], oa_ok=False, qrows=[_qrow("测试请字[2026]70号"), _qrow("测试请字[2026]7号")])
    c = DocflowClient(s)
    req = c.fetch("测试请字〔2026〕7号")
    assert req.raw_params["openFrom"] == "formQuery" and req.raw_params["flow_state"] == "已结束"
    assert req.raw_params["affairId"] == "SENDER-AFF"  # 发起人的已发事项，不涉及任何人的待办
    base = next(p for m, u, p in s.calls if m == "GET" and "deal-base-info" in u)
    assert base["summaryId"] == "S1" and base["openFrom"] == "formQuery" and "affairId" not in base
    content = next(p for m, u, p in s.calls if m == "GET" and "content.do" in u)
    assert content["openFrom"] == "formQuery" and content["affairId"] == "SENDER-AFF"
    assert sum(1 for m, u, _ in s.calls if "tyssj.do" in u) == 1  # "__LOGOUT" 视为会话失效，单点登录后重试
    assert c.download(req.attachments[0]) == b"12345"


def test_company_query_unfinished_and_missing():
    s = FakeSession(rows=[], qrows=[_qrow("测试请字[2026]7号", state="未结束")])
    with pytest.raises(NoAccess, match="只打开流程已结束") as ei:
        DocflowClient(s).fetch("测试请字[2026]7号")
    assert ei.value.title == "流程未结束的请示暂不打开"
    assert not any("deal-base-info" in u for _, u, _ in s.calls)
    with pytest.raises(NoAccess, match="内部请示查询"):
        DocflowClient(FakeSession(rows=[], qrows=[_qrow("测试请字[2026]70号")])).fetch("测试请字[2026]7号")


def test_download_after_kicked_offline_relogins_and_resigns():
    """同一账号在别处登录后本会话被挤下线：下载返回网页 → 重新单点登录、重新取单换签名后重试。"""
    s = FakeSession(html_once=True)
    c = DocflowClient(s)
    req = c.fetch("4123236229515985600")
    a = req.attachments[0]
    assert a.loadlink.split("|")[1] == "sig-a"
    assert c.download(a) == b"12345"
    assert sum(1 for _, u, _ in s.calls if "tyssj.do" in u) == 1
    assert sum(1 for _, u, _ in s.calls if "deal-base-info" in u) == 2  # 重新取单
    assert a.loadlink.split("|")[1] == "sig-a"


def test_kicked_json_relogins():
    class Kick(FakeSession):
        kicked = True

        def get(self, url, params=None, timeout=None, allow_redirects=True):
            if "deal-base-info" in url and self.kicked:
                self.calls.append(("GET", url, params))
                self.kicked = False
                return Resp(401, body="您的帐号在另一地点登录，您被迫下线".encode())
            return super().get(url, params, timeout, allow_redirects)

    s = Kick()
    DocflowClient(s).fetch("4123236229515985600")
    assert sum(1 for _, u, _ in s.calls if "tyssj.do" in u) == 1


def test_query_lister_keeps_finished_only():
    from core.resource import listers

    rows = [_qrow("测试请字[2026]9号", subject="关于甲项目采购结果的请示"),
            _qrow("测试请字[2026]8号", state="未结束", subject="关于乙项目采购结果的请示"),
            _qrow("测试请字[2026]7号", state="终止", subject="关于丙项目采购结果的请示"),
            _qrow("测试请字[2026]6号", subject="关于提请审议人事议题的请示"),
            _qrow("测试请字〔2026〕5号", subject="关于丁项目采购结果的请示")]
    c = DocflowClient(FakeSession(qrows=rows))
    out = listers.LISTERS["docflow"](c, {"kind": "query", "title_keyword": "采购结果|人事", "title_exclude": "人事议题", "max": 10})
    assert [r["request_id"] for r in out] == ["测试请字[2026]9号", "测试请字[2026]5号"]


def test_portal_target_for_query_view():
    from core import portal
    from core.sources.contract import RequestData

    def req(rp):
        return RequestData(request_id="x", workflow_id="", workflow_name="", request_name="", node_name="", fields=[],
                           approval_log=[], attachments=[], raw_params=rp)

    t = portal.target("docflow", req({"openFrom": "formQuery", "flow_state": "已结束", "summaryId": "S1", "affairId": "A"}))
    assert "summaryId%3DS1" in t["url"] and "openFrom%3DformQuery" in t["url"] and "affairId" not in t["url"]
    assert "skip" in portal.target("docflow", req({"openFrom": "formQuery", "flow_state": "未结束", "summaryId": "S1"}))
    assert portal.WRITE.search("https://oa-xc.gt.cn/seeyon/rest/track/log?t=1")
