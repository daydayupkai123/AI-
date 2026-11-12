"""合同管理系统（泛微 e-cology）只读取数适配器。接口说明见摸底文档《M0-合同系统取数摸底》。"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import requests

from shared.env_config import CONTRACT_BASE
from shared.errors import NoAccess, SessionExpired, UpstreamUnavailable, UpstreamUnexpected

SOURCE = "contract"
HOST = "contract.gt.cn"


def _json(r: requests.Response) -> dict:
    """合同系统未登录时返回跳转统一认证的 HTML，或 JSON {"msg": "登录信息超时", "errorCode": "002"}，这里显式识别。"""
    where = f"{r.request.method} {r.url.split('?')[0]}"
    try:
        data = r.json()
    except ValueError:
        text = r.text[:500]
        if "login.gt.cn" in text or "authorize" in text or "/wui/index.html" in text:
            raise SessionExpired(f"合同系统要求重新认证（{where}）") from None
        raise UpstreamUnexpected(f"{where} 返回 {r.status_code}：{text[:200]}") from None
    if isinstance(data, dict) and (str(data.get("errorCode")) == "002" or "登录信息超时" in str(data.get("msg") or "")):
        raise SessionExpired(f"合同系统会话已超时（{where}：{data.get('msg')}）")
    return data


@dataclass
class Attachment:
    field_key: str
    field_label: str
    filename: str
    ext: str
    file_id: str
    image_file_id: str
    version_id: str
    upload_time: str
    secret_level: str
    loadlink: str


@dataclass
class RequestData:
    request_id: str
    workflow_id: str
    workflow_name: str
    request_name: str
    node_name: str
    fields: list[dict]
    approval_log: list[dict]
    attachments: list[Attachment]
    via_monitor: bool = False
    raw_params: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    def value(self, label: str) -> str:
        for f in self.fields:
            if f["label"] == label:
                return str(f["display"] or "").strip()
        return ""


def _strip(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


def is_pending(params: dict) -> bool:
    """loadForm 返回的当前账号待办（未处理）：isremark 0/1/5/7/8/9，或 requestType=1。"""
    return str(params.get("isremark")) in ("0", "1", "5", "7", "8", "9") or str(params.get("requestType")) == "1"


def pending_detail_allowed() -> bool:
    from storage_service import settings

    return bool(settings.collect().get("allow_pending_detail"))


class ContractClient:
    def __init__(self, session: requests.Session, base: str = CONTRACT_BASE):
        self.s = session
        self.base = base.rstrip("/")

    def _post(self, path: str, data: dict, timeout: int = 60) -> dict:
        try:
            r = self.s.post(self.base + path, data=data, timeout=timeout)
        except requests.RequestException as exc:
            raise UpstreamUnavailable(f"{type(exc).__name__}: {exc}") from exc
        if r.status_code >= 500:
            raise UpstreamUnavailable(f"POST {path} 返回 {r.status_code}")
        return _json(r)

    def load_form(self, request_id: str) -> tuple[dict, bool]:
        form = self._post("/api/workflow/reqform/loadForm", {"requestid": request_id})
        if (form.get("params") or {}).get("workflowid"):
            return form, False
        form = self._post("/api/workflow/reqform/loadForm", {"requestid": request_id, "ismonitor": "1"})
        if (form.get("params") or {}).get("workflowid"):
            return form, True
        raise NoAccess(f"loadForm 对单据 {request_id} 返回 canview=false（含监控方式），"
                       f"可能单号不存在或当前账号无权限")

    def approval_log(self, request_id: str, params: dict) -> list[dict]:
        q = {"isFromWfForm": "1", "requestid": request_id, "requestType": "0",
             "workflowid": params.get("workflowid"), "nodeid": params.get("nodeid"),
             "isprint": "0", "submit": "0", "pgnumber": "1", "orderbytype": "1"}
        for k in ("signatureAttributesStr", "signatureSecretKey", "f_weaver_belongto_userid",
                  "f_weaver_belongto_usertype", "authStr", "authSignatureStr"):
            if params.get(k) not in (None, ""):
                q[k] = params[k]
        base = self._post("/api/workflow/reqform/getRequestLogBaseInfo", q)
        for k in ("viewLogIds", "creatorNodeId", "isHideInput", "isFormSignature"):
            if base.get(k) not in (None, ""):
                q[k] = base[k]
        q["wfsignlddtcnt"] = "200"
        log = self._post("/api/workflow/reqform/getRequestLogList", q)
        return [{"date": it.get("log_operatedate"), "time": it.get("log_operatetime"),
                 "node": it.get("log_nodename"), "operator": it.get("displayname"),
                 "dept": it.get("displaydepname"), "action": it.get("operationname"),
                 "remark": _strip(it.get("log_remarkHtml"))}
                for it in (log.get("loglist") or [])]

    def fetch(self, request_id: str) -> RequestData:
        form, via_monitor = self.load_form(request_id)
        params = form.get("params") or {}
        if is_pending(params) and not pending_detail_allowed():
            raise NoAccess(f"单据 {request_id} 是当前账号的待办（loadForm：isremark={params.get('isremark')}、"
                           f"requestType={params.get('requestType')}），按约定在确认读取详情不改变待办状态之前只读，"
                           f"不读取表单详情、不下载附件。确认后在 config/collect.yaml 设 allow_pending_detail: true。",
                           title="待办单据暂不打开", hint="可审查台账、已办或监控范围内的单据。")
        fmap = ((form.get("tableInfo") or {}).get("main") or {}).get("fieldinfomap") or {}
        maindata = form.get("maindata") or {}
        fields, atts = [], []
        for fid, f in fmap.items():
            v = maindata.get(f"field{fid}") or {}
            ht = str(f.get("htmltype"))
            label = (f.get("fieldlabel") or f.get("fieldname") or "").rstrip("：:").strip()
            raw = v.get("value")
            if ht == "6":
                for fd in ((v.get("specialobj") or {}).get("filedatas")) or []:
                    atts.append(Attachment(
                        field_key=f"field{fid}", field_label=label, filename=fd.get("filename") or "",
                        ext=(fd.get("fileExtendName") or "").lower(), file_id=str(fd.get("fileid") or ""),
                        image_file_id=str(fd.get("imagefileid") or ""), version_id=str(fd.get("versionId") or ""),
                        upload_time=fd.get("uploaddate") or "", secret_level=str(fd.get("secretLevel") or ""),
                        loadlink=fd.get("loadlink") or ""))
                continue
            display = raw
            if ht == "3":
                display = "、".join(_strip(o.get("name")) for o in (v.get("specialobj") or [])) or raw
            elif ht == "5":
                for it in ((f.get("selectattr") or {}).get("selectitemlist")) or []:
                    if str(it.get("selectvalue")) == str(raw):
                        display = it.get("selectname")
                        break
            fields.append({"field": f"field{fid}", "label": label, "htmltype": ht, "value": raw, "display": display})
        return RequestData(
            request_id=str(request_id), workflow_id=str(params.get("workflowid")),
            workflow_name=params.get("workflowname") or "", request_name=params.get("requestname") or "",
            node_name=params.get("nodename") or "", fields=fields,
            approval_log=self.approval_log(request_id, params), attachments=atts, via_monitor=via_monitor,
            raw_params={k: params.get(k) for k in ("formid", "nodeid", "creater", "isbill", "isremark", "isviewonly",
                                                    "requestType")})

    def ledger(self, customid: str, page_size: int = 500, max_pages: int = 4) -> list[dict]:
        """读取 cube 台账（如 83 采购结果审批台账），返回去 HTML 后的行。"""
        ts = int(time.time() * 1000)
        r = _json(self.s.post(f"{self.base}/api/cube/search/getList?customid={customid}&guid=search&canIsQuickSearch=1"
                              f"&isNewTableSearch=1&windowWidth=1600&__random__={ts}", timeout=60))
        key = r.get("datas")
        if not key:
            raise RuntimeError(f"台账 {customid} 无法读取：{str(r)[:200]}")
        rows = []
        for cur in range(1, max_pages + 1):
            page = self._post("/api/ec/dev/table/datas", {"dataKey": key, "current": str(cur),
                                                          "pageSize": str(page_size), "sortParams": "[]"}, 120)
            datas = page.get("datas") or []
            for d in datas:
                rows.append({k: _strip(str(d.get(k + "span") or d.get(k) or "")) for k in d
                             if not k.endswith("span") and k != "randomFieldId"})
            if len(datas) < page_size:
                break
        return rows

    def list_requests(self, scope: str, workflow_ids: list | None = None, page_size: int = 50) -> list[dict]:
        """本账号的待办（doing）/ 已办（done）/ 我的请求（mine）列表，只读列表不打开单据。"""
        rows: list[dict] = []
        for wf in (workflow_ids or [None]):
            body = {"viewScope": scope}
            if wf:
                body["workflowid"] = str(wf)
            key = self._post("/api/workflow/reqlist/splitPageKey", body).get("sessionkey")
            if not key:
                raise UpstreamUnexpected(f"列表 {scope} 未返回 sessionkey")
            page = self._post("/api/ec/dev/table/datas", {"dataKey": key, "current": "1", "pageSize": str(page_size),
                                                          "sortParams": "[]"}, 120)
            for d in page.get("datas") or []:
                rows.append({"request_id": str(d.get("requestid")), "workflow_id": str(d.get("workflowid") or ""),
                             "title": _strip(str(d.get("requestnamespan") or d.get("requestname") or "")),
                             "date": d.get("createdate") or d.get("receivedate") or ""})
        return rows

    def download(self, att: Attachment, timeout: int = 300) -> bytes:
        try:
            r = self.s.get(self.base + att.loadlink, timeout=timeout)
        except requests.RequestException as exc:
            raise UpstreamUnavailable(f"下载附件 {att.filename} 失败：{type(exc).__name__}: {exc}") from exc
        if r.status_code != 200 or not r.content:
            raise UpstreamUnexpected(f"下载附件 {att.filename} 返回 {r.status_code}，大小 {len(r.content)}")
        if r.headers.get("content-type", "").startswith("text/html") and b"login.gt.cn" in r.content[:2000]:
            raise SessionExpired(f"下载附件 {att.filename} 时被要求重新认证")
        return r.content
