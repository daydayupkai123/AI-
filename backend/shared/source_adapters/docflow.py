"""公文系统（致远 Seeyon，oa-xc.gt.cn）「内部请示」只读取数适配器。接口说明见摸底文档《M0-公文系统取数摸底》。

取数链路（均为查询类请求）：
  1. 门户 i.gt.cn 工作台列表 API_CODE_FINDPERSONALWORKS（app=4 公文），按内请号/标题定位 affairId；
  2. /seeyon/rest/govdoc/summary/v1/deal-base-info：标题、模板、附件清单（含下载签名 v）；
  3. /seeyon/content/content.do：表单 HTML，逐个解析 fieldVal 字段（单选取选中项，复选框按前置标签分组合成）；
  4. /seeyon/fileDownload.do?method=download：附件下载（必须带 v 与 createDate，302 到 doDownload 后返回文件）。
OA 会话失效时经 /seeyon/tyssj.do 用门户统一认证换取新会话（纯 HTTP，无需浏览器）。

门户「我的发起 / 已办 / 已阅」里找不到的内请号，再到 OA「公司数据查询 → 内部请示查询」（表单查询
formQueryResultManager.getQueryResult）定位，按查询入口的只读视图 openFrom=formQuery 打开；
只打开流程已结束的请示（未结束的可能是他人待办）。
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import quote

import requests

from ..errors import DEError, NoAccess, SessionExpired, UpstreamUnavailable, UpstreamUnexpected
from .contract import Attachment, RequestData

SOURCE = "docflow"
HOST = "oa-xc.gt.cn"
OA = "https://oa-xc.gt.cn"
PORTAL_LIST = "https://i.gt.cn/http/pcPortal/API_CODE_FINDPERSONALWORKS"
SYSTEM = "公文系统"
# 只在「我的发起 / 已办 / 已阅」中定位：打开他人待办会改变其阅读状态
LIST_TYPES = ("doneSent", "donePending", "doneRead")
AFFAIR_RE = re.compile(r"-?\d{15,20}")
# 「公司数据查询 → 内部请示查询」：表单查询的编号与结果列（formmain_25329 为内部请示表单主表）
QUERY = {"queryId": "-4037857976162825094", "formId": "-5612251084050314838", "table": "formmain_25329",
         "operationId": "-6155648955446964314.-3563027052804682398"}
QUERY_COLS = {"field0001": "mark", "field0002": "subject", "field0012": "applicant", "field0009": "department",
              "field0013": "created", "field0003": "major", "field0004": "matter_type", "finishedflag": "flow_state",
              "field0007": "meeting_type"}
QUERY_NAMES = "内请号,标题,申请人,申请部门,申请时间,是否三重一大事项,事项类型,流程状态,会议类型"
QUERY_PAGE = (f"/seeyon/form/queryResult.do?method=queryExc&showTopLabel=true&fromPortal=section&type=query"
              f"&queryId={QUERY['queryId']}")
FINISHED = "已结束"
# OA 同一账号只允许一处在线：别处单点登录后，本会话的接口返回 401「您的帐号在另一地点登录，您被迫下线」，
# 附件下载返回一个网页；附件下载签名 v 与会话绑定，重新登录后须重新取单换签名
KICKED = re.compile(r"被迫下线|在另一地点登录")
MARK_RE = r"[\u4e00-\u9fa5]{1,10}字\s*[\[〔【（(]\s*\d{4}\s*[\]〕】）)]\s*\d{1,5}\s*号"
ID_PATTERN = rf"{MARK_RE}|-?\d{{15,20}}"


def norm_mark(s: str) -> str:
    """内请号统一为门户标题中的写法：通设请字[2026]76号（全角括号、空白归一）。"""
    s = re.sub(r"\s+", "", s or "")
    return re.sub(r"[〔【（(]", "[", re.sub(r"[〕】）)]", "]", s))


def canonical_id(rid: str) -> str:
    """任务单号：内请号按标准写法保存，affairId 与其他输入原样保留。"""
    rid = (rid or "").strip()
    return norm_mark(rid) if re.fullmatch(MARK_RE, rid) else rid


class SourceNotReady(DEError):
    title = "该系统取数尚未打通"
    hint = "需要在调试 Chrome 中登录门户后完成接口摸底（tools/probes/portal_probe.py）。在此之前可在「样例单据」中选择本地事项审查。"


class Unavailable(UpstreamUnavailable):
    title = "公文系统暂时无法访问"
    hint = "可能是网络或公文系统本身的问题，请确认能在浏览器中从门户正常打开公文后，再点「重新审查」。"


class Unexpected(UpstreamUnexpected):
    title = "公文系统返回了无法识别的内容"
    hint = "通常是登录状态异常或系统维护导致。请在调试 Chrome 中刷新门户确认已登录，再点「重新审查」。"


def _unescape_js(s: str) -> str:
    s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
    return s.replace('\\"', '"').replace("\\\\", "\\")


def _field_meta(raw: str) -> dict:
    out = {}
    for k in ("name", "displayName", "inputType", "value"):
        m = re.search(r"\b" + k + r':"((?:[^"\\]|\\.)*)"', raw)
        out[k] = _unescape_js(m.group(1)) if m else ""
    return out


def _clean_label(text: str) -> str:
    return re.sub(r"\s+", "", text).lstrip("*＊").rstrip("：:")


class _FormParser(HTMLParser):
    """解析 content.do 中的表单：每个 <span fieldVal=...> 是一个字段，字段前最近的「xxx：」文字是其可见标签。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fields: list[dict] = []
        self.atts: list[dict] = []
        self.label = ""
        self.group = ""
        self.cur: dict | None = None
        self.depth = 0
        self.pending: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.cur is None:
            if tag == "span" and a.get("fieldval"):
                meta = _field_meta(a["fieldval"])
                label = _clean_label(self.label) if self.label else ""
                if meta["inputType"] == "checkbox":
                    self.group = label or self.group
                    label = ""
                else:
                    self.group = ""
                self.cur = {"meta": meta, "label": label, "text": [], "options": [], "group": self.group}
                self.label = ""
                self.depth = 1
            return
        if tag == "span":
            self.depth += 1
        elif tag == "input" and a.get("type") in ("radio", "checkbox"):
            self.pending = {"value": a.get("value", ""), "checked": "checked" in a, "text": ""}
            self.cur["options"].append(self.pending)
        elif tag == "option":
            self.pending = {"value": a.get("value", ""), "checked": "selected" in a, "text": ""}
            self.cur["options"].append(self.pending)
        if a.get("attsdata"):
            try:
                for d in json.loads(a["attsdata"]):
                    self.atts.append(dict(d, _field=self.cur["meta"]["name"]))
            except ValueError:
                raise Unexpected(f"表单附件数据无法解析：{a['attsdata'][:120]}") from None

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag == "span" and self.cur is not None:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.cur is None or tag != "span":
            return
        self.depth -= 1
        if self.depth == 0:
            self._finish()

    def handle_data(self, data):
        t = data.strip()
        if not t:
            return
        if self.cur is None:
            if t.endswith(("：", ":")) and len(t) <= 40:
                self.label = t
            return
        if self.pending is not None and not self.pending["text"]:
            self.pending["text"] = t
            self.pending = None
            return
        self.cur["text"].append(t)

    def _finish(self):
        c, self.cur, self.pending = self.cur, None, None
        meta = c["meta"]
        typ, value = meta["inputType"], meta["value"]
        if typ in ("radio", "select") and c["options"]:
            display = "、".join(o["text"] for o in c["options"] if o["checked"] or (value and o["value"] == value))
        elif typ == "checkbox":
            display = "是" if value == "1" else "否"
        elif typ == "attachment":
            display = ""
        else:
            display = "".join(c["text"]).strip() or (value if typ in ("text", "textarea", "edocDocMark") else "")
        self.fields.append({"field": meta["name"], "label": c["label"] or meta["displayName"],
                            "name": meta["displayName"], "htmltype": typ, "value": value, "display": display,
                            "group": c["group"] if typ == "checkbox" else ""})


def parse_form(html: str) -> tuple[list[dict], list[dict]]:
    """返回 (字段列表, 表单附件元数据)。复选框按其前置标签合成一个分组字段（如「会议类型」= 勾选项名称）。"""
    p = _FormParser()
    p.feed(html)
    p.close()
    fields = list(p.fields)
    groups: dict[str, list[dict]] = {}
    for f in p.fields:
        if f["htmltype"] == "checkbox" and f["group"]:
            groups.setdefault(f["group"], []).append(f)
    for g, items in groups.items():
        fields.append({"field": "group:" + g, "label": g, "name": g, "htmltype": "checkboxgroup",
                       "value": ",".join(f["field"] for f in items if f["value"] == "1"),
                       "display": "、".join(f["label"] for f in items if f["value"] == "1"), "group": ""})
    return fields, p.atts


class DocflowClient:
    def __init__(self, session: requests.Session):
        self.s = session
        self._origin: dict[str, str] = {}  # 附件 fileUrl → 所属单号（重新登录后换下载签名用）

    # ---------- 门户列表：单号 → affairId ----------
    def _list(self, typ: str, subject: str, page_size: int = 50) -> list[dict]:
        body = {"type": typ, "memberId": "", "isLeader": False, "subject": subject, "templeteId": "", "mark": "",
                "summaryState": "", "sender": "", "department": "", "app": "4", "preApprover": "", "pageNo": 1,
                "pageSize": page_size, "sequence": 0, "timeType": None, "platform": "PC"}
        try:
            r = self.s.post(PORTAL_LIST, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=30,
                            headers={"Content-Type": "application/json;charset=UTF-8", "Origin": "https://i.gt.cn",
                                     "Referer": "https://i.gt.cn/"})
        except requests.RequestException as exc:
            raise Unavailable(f"门户工作台列表：{type(exc).__name__}: {exc}") from exc
        try:
            d = r.json()
        except ValueError:
            if "login.gt.cn" in r.text[:2000] or r.status_code in (401, 403):
                raise SessionExpired("门户工作台列表要求重新登录") from None
            raise Unexpected(f"门户工作台列表返回 {r.status_code}：{r.text[:200]}") from None
        desc = str(d.get("respDesc") or "")
        if str(d.get("respCode")) != "00000":
            if "登录" in desc or "token" in desc.lower():
                raise SessionExpired(f"门户工作台列表：{desc}")
            raise Unexpected(f"门户工作台列表返回 {d.get('respCode')}：{desc}")
        res = d.get("result")
        if not isinstance(res, dict):
            raise Unexpected(f"门户工作台列表类型 {typ} 返回 {str(res)[:80]}")
        return ((res.get("data") or {}).get(typ) or {}).get("data") or []

    def locate(self, request_id: str) -> dict:
        """内请号/标题关键字 → 列表行（含 affairId）；纯数字视为 affairId 直接使用。"""
        rid = request_id.strip()
        if AFFAIR_RE.fullmatch(rid):
            return {"affairId": rid}
        rid = canonical_id(rid)
        by_summary: dict[str, dict] = {}
        for typ in LIST_TYPES:
            for row in self._list(typ, rid):
                if rid in norm_mark(row.get("subject") or "") or rid == norm_mark(row.get("mark") or ""):
                    by_summary.setdefault(str(row.get("objectId") or row["affairId"]), dict(row, _list=typ))
        if not by_summary:
            return self._locate_query(rid)
        if len(by_summary) > 1:
            names = "；".join(f"{r.get('subject')}（affairId {r['affairId']}）" for r in list(by_summary.values())[:5])
            raise NoAccess(f"「{rid}」匹配到 {len(by_summary)} 份公文：{names}。请输入完整内请号或 affairId。",
                           title="单号不唯一")
        return next(iter(by_summary.values()))

    # ---------- 公司数据查询 → 内部请示查询 ----------
    def query(self, *, mark: str = "", keyword: str = "", page: int = 1, size: int = 50) -> tuple[list[dict], int]:
        """表单查询（只读）：按内请号 / 标题关键字（包含）过滤，按申请时间倒序。返回 (行, 总数)。"""
        t = QUERY["table"]
        cond = [(f"{t}.field0001", "内请号", mark), (f"{t}.field0002", "标题", keyword)]
        user = [{"leftChar": "", "fieldName": f, "fieldName_txt": n, "operation": "include", "fieldValue": v,
                 "rightChar": "", "rowOperation": "and"} for f, n, v in cond if v]
        fields = ",".join(f"{t}.{k}" if k.startswith("field") else k for k in QUERY_COLS)
        info = {"userCondition": user or [{"leftChar": "", "fieldName": "", "fieldName_txt": "", "operation": None,
                                           "fieldValue": "", "rightChar": "", "rowOperation": "and"}],
                "userFastCon": [],
                "stateCon": {"finishedflag0": "0", "finishedflag1": "1", "finishedflag3": "3", "state0": None,
                             "state1": "1", "state2": "2", "state3": "3", "ratifyflag0": "0", "ratifyflag1": "1",
                             "ratifyflag2": "2"},
                "show": {"showFields": fields, "showFieldNames": QUERY_NAMES, "currentShowFields": fields,
                         "currentShowFieldNames": QUERY_NAMES, "oldOrderByNameList": f"{t}.field0013",
                         "oldOrderByShowList": "申请时间↓", "orderByNameList": f"{t}.field0013",
                         "orderByShowList": "申请时间↓"},
                "baseInfo": {"formId": QUERY["formId"], "type": "query", "queryId": QUERY["queryId"],
                             "queryModuleType": "2"}}
        args = [{"page": page, "size": size}, {"queryInfo": json.dumps(info, ensure_ascii=False)}]
        d = self._oa_post("/seeyon/ajax.do?method=ajaxAction&managerName=formQueryResultManager&nn=getQueryResult",
                          {"managerMethod": "getQueryResult", "arguments": json.dumps(args, ensure_ascii=False)},
                          sso_target=QUERY_PAGE)
        if not isinstance(d, dict) or not isinstance(d.get("data"), list):
            raise Unexpected(f"内部请示查询返回 {str(d)[:200]}")
        rows = [{QUERY_COLS.get(k, k): v for k, v in r.items()} for r in d["data"]]
        return rows, int(d.get("total") or 0)

    def _locate_query(self, rid: str) -> dict:
        from .contract import pending_detail_allowed

        by_mark = re.fullmatch(MARK_RE, rid) is not None
        rows, _ = self.query(mark=rid, size=20) if by_mark else self.query(keyword=rid, size=20)
        hit = [r for r in rows if (norm_mark(r.get("mark") or "") == rid if by_mark else rid in (r.get("subject") or ""))]
        if not hit:
            raise NoAccess(f"在门户「我的发起 / 已办 / 已阅」公文和「公司数据查询 → 内部请示查询」中都未找到「{rid}」。"
                           f"请确认内请号，或直接输入 affairId（公文详情地址中的 affairId 参数）。", title="未找到该内部请示")
        if len(hit) > 1:
            names = "；".join(f"{r.get('mark')} {r.get('subject')}" for r in hit[:5])
            raise NoAccess(f"「{rid}」匹配到 {len(hit)} 份内部请示：{names}。请输入完整内请号。", title="单号不唯一")
        row = hit[0]
        if row.get("flow_state") != FINISHED and not pending_detail_allowed():
            raise NoAccess(f"{row.get('mark')}「{row.get('subject')}」流程状态为「{row.get('flow_state')}」，可能是他人的待办；"
                           f"按约定只打开流程已结束的请示。", title="流程未结束的请示暂不打开")
        if not row.get("summaryId"):
            raise Unexpected(f"内部请示查询结果缺少 summaryId（{row.get('mark')}）")
        return dict(row, _list="formQuery")

    def _oa_post(self, url: str, data: dict, *, sso_target: str, timeout: int = 60):
        """POST OA 查询类 ajax（返回 JSON）；会话失效时自动单点登录后重试一次。"""
        for attempt in (0, 1):
            try:
                r = self.s.post(OA + url, data=data, timeout=timeout, allow_redirects=False,
                                headers={"X-Requested-With": "XMLHttpRequest", "Referer": OA + sso_target})
            except requests.RequestException as exc:
                raise Unavailable(f"{url.split('&nn=')[-1]}：{type(exc).__name__}: {exc}") from exc
            if r.status_code >= 500:
                raise Unavailable(f"{url.split('&nn=')[-1]} 返回 {r.status_code}")
            if r.status_code == 200:
                try:
                    d = r.json()
                    if d != "__LOGOUT":
                        return d
                except ValueError:
                    if "main.do?method=login" not in r.text[:3000] and "login.gt.cn" not in r.text[:3000]:
                        raise Unexpected(f"{url.split('&nn=')[-1]} 返回 {r.text[:200]}") from None
            if attempt == 1:
                raise SessionExpired(f"{SYSTEM}会话无效（{url.split('&nn=')[-1]} 返回 {r.status_code}）")
            self._sso(sso_target)
        raise AssertionError("unreachable")

    # ---------- OA 会话 ----------
    def _sso(self, target: str) -> None:
        url = f"{OA}/seeyon/tyssj.do?method=access&targetUrl={quote(target, safe='')}"
        try:
            r = self.s.get(url, timeout=60, allow_redirects=True)
        except requests.RequestException as exc:
            raise Unavailable(f"单点登录：{type(exc).__name__}: {exc}") from exc
        if "login.gt.cn" in r.url or ("method=login" in r.url and "ticket=" not in r.url):
            raise SessionExpired(f"{SYSTEM}单点登录停在登录页（门户未登录）：{r.url[:120]}")

    def _oa_get(self, path: str, params: dict, *, want_json: bool, sso_target: str, timeout: int = 60,
                follow: str = "", ok_status: tuple = ()):
        """GET OA 接口；会话失效（跳登录页）时自动单点登录后重试一次。follow 非空时允许 302 跳到包含该片段的地址；
        ok_status 中的状态码原样返回给调用方处理。"""
        for attempt in (0, 1):
            try:
                r = self.s.get(OA + path, params=params, timeout=timeout, allow_redirects=False)
            except requests.RequestException as exc:
                raise Unavailable(f"{path}：{type(exc).__name__}: {exc}") from exc
            if r.status_code >= 500:
                raise Unavailable(f"{path} 返回 {r.status_code}")
            loc = r.headers.get("location") or ""
            if (r.status_code in (301, 302, 303) and follow and follow in loc) or r.status_code in ok_status:
                return r
            expired = r.status_code in (301, 302, 303, 401)
            if not expired:
                if not want_json:
                    if r.status_code != 200:
                        raise Unexpected(f"{path} 返回 {r.status_code}")
                    if "main.do?method=login" not in r.text[:3000] and not KICKED.search(r.text[:5000]):
                        return r
                    expired = True
                else:
                    try:
                        return r.json()
                    except ValueError:
                        if "main.do?method=login" not in r.text[:3000] and "login.gt.cn" not in r.text[:3000]:
                            raise Unexpected(f"{path} 返回 {r.status_code}：{r.text[:200]}") from None
                        expired = True
            if attempt == 1:
                raise SessionExpired(f"{SYSTEM}会话无效（{path} 返回 {r.status_code} {loc[:80]} {r.text[:80]}）")
            # 也可能是同一账号在别处（其他进程 / 浏览器）登录了 OA，本会话被挤下线：重新单点登录即可
            self._sso(sso_target)
        raise AssertionError("unreachable")

    # ---------- 取单 ----------
    def fetch(self, request_id: str) -> RequestData:
        row = self.locate(request_id)
        open_from = "formQuery" if row.get("_list") == "formQuery" else "listDone"
        if open_from == "formQuery":
            q = {"summaryId": str(row["summaryId"]), "openFrom": open_from, "operationId": QUERY["operationId"],
                 "formId": QUERY["formId"]}
            target = "/seeyon/govdoc/govdoc.do?method=summary&" + "&".join(f"{k}={v}" for k, v in q.items())
        else:
            q = {"isFromHome": "true", "openFrom": open_from, "affairId": str(row["affairId"])}
            target = f"/seeyon/govdoc/govdoc.do?method=summary&isFromHome=true&openFrom=listDone&affairId={row['affairId']}"
        base = self._oa_get("/seeyon/rest/govdoc/summary/v1/deal-base-info",
                            {"method": "summary", **q, "option.n_a_s": "1"}, want_json=True, sso_target=target)
        if str(base.get("code")) != "0" or not isinstance(base.get("data"), dict):
            raise NoAccess(f"{SYSTEM}未返回公文 {request_id} 的详情：{str(base.get('message'))[:200]}",
                           title="当前账号无权查看该公文")
        data = base["data"]
        summ, form = data.get("summaryInfo") or {}, data.get("form") or {}
        tpl = (data.get("basicInfo") or {}).get("template") or {}
        aff = str(row.get("affairId") or (summ.get("affair") or {}).get("affairId") or "")
        if not summ.get("id") or not form.get("rightId") or not aff:
            raise Unexpected(f"详情缺少 summaryId/rightId/affairId（{request_id}）")
        state = str((summ.get("affair") or {}).get("state") or "2")
        page = self._oa_get("/seeyon/content/content.do", {
            "method": "index", "fromIframeName": "summary4Gov", "isFullPage": "true", "moduleId": summ["id"],
            "moduleType": "4", "contentType": "", "rightId": form["rightId"], "affairId": aff,
            "templateId": tpl.get("id") or "", "formAppid": form.get("formAppId") or "", "viewState": "2",
            "openFrom": open_from, "canDeleteISigntureHtml": "false", "isShowMoveMenu": "false",
            "isShowDocLockMenu": "false", "affairState": state}, want_json=False, sso_target=target)
        fields, form_atts = parse_form(page.text)
        if not fields:
            raise Unexpected(f"表单页未解析到任何字段（affairId {aff}）")
        labels = {f["field"]: f["label"] for f in fields}
        atts: list[Attachment] = []
        linked: list[str] = []
        seen: set[str] = set()

        def add(a: dict, name: str, created: str, label: str) -> None:
            if str(a.get("type")) != "0":
                linked.append(name)
                return
            url = str(a.get("fileUrl") or "")
            if not url or url in seen:
                return
            seen.add(url)
            if not a.get("v"):
                raise Unexpected(f"附件 {name} 缺少下载签名 v")
            # 下载签名 v 随会话变化，不能作为版本标识；fileUrl 每次上传唯一，配合上传时间即可判定同一文件
            atts.append(Attachment(field_key=label, field_label=label, filename=name,
                                   ext=name.rsplit(".", 1)[-1].lower() if "." in name else "", file_id=str(a.get("id")),
                                   image_file_id=url, version_id=created or url, upload_time=created, secret_level="",
                                   loadlink=f"{created[:10]}|{a['v']}|{a.get('size') or ''}"))

        for a in form_atts:
            add(a, a.get("filename") or "", a.get("createdate") or "", labels.get(a.get("_field"), "附件"))
        for a in (data.get("attachmentInfo") or {}).get("attachments") or []:
            add(a, a.get("fileName") or "", a.get("createDate") or "", "附件")
        mark = next((f["display"] for f in fields if f["htmltype"] == "edocDocMark"), "")
        for a in atts:
            self._origin[a.image_file_id] = str(request_id)
        return RequestData(
            request_id=str(request_id), workflow_id=str(tpl.get("id") or ""), workflow_name=tpl.get("subject") or "",
            request_name=summ.get("subject") or "", node_name=row.get("nodePolicyName") or "", fields=fields,
            approval_log=[], attachments=atts,
            raw_params={"affairId": aff, "summaryId": summ.get("id"), "formRecordId": form.get("formRecordId"),
                        "openFrom": open_from, **({"flow_state": row.get("flow_state")} if open_from == "formQuery" else {})},
            extra={"mark": mark, "sender": summ.get("startMemberName") or "", "created": summ.get("createDate") or "",
                   "linked_docs": [x for x in linked if x]})

    def _download_once(self, att: Attachment, timeout: int):
        created, v, _ = (att.loadlink.split("|") + ["", "", ""])[:3]
        r = self._oa_get("/seeyon/fileDownload.do", {"method": "download", "fileId": att.image_file_id,
                                                      "createDate": created, "v": v, "filename": att.filename},
                         want_json=False, sso_target="/seeyon/main.do", timeout=timeout, follow="fileDownload.do",
                         ok_status=(404,))
        if r.status_code in (301, 302, 303):
            loc = r.headers["location"]
            try:
                r = self.s.get(loc if loc.startswith("http") else OA + loc, timeout=timeout, allow_redirects=False)
            except requests.RequestException as exc:
                raise Unavailable(f"下载附件 {att.filename} 失败：{type(exc).__name__}: {exc}") from exc
        return r

    def _resign(self, att: Attachment) -> None:
        """重新单点登录，并重新取该附件所属单据，换取新会话下的下载签名。"""
        self._sso("/seeyon/main.do")
        rid = self._origin.get(att.image_file_id)
        if not rid:
            return
        fresh = next((a for a in self.fetch(rid).attachments if a.image_file_id == att.image_file_id), None)
        if fresh is None:
            raise Unexpected(f"重新登录后单据 {rid} 中已没有附件 {att.filename}")
        att.loadlink = fresh.loadlink

    def download(self, att: Attachment, timeout: int = 300) -> bytes:
        size = (att.loadlink.split("|") + ["", "", ""])[2]
        r = self._download_once(att, timeout)
        if r.status_code == 404 or r.headers.get("content-type", "").startswith("text/html"):
            # 多为本会话被别处的单点登录挤下线（下载返回网页），或签名属于已失效的会话（404）
            self._resign(att)
            r = self._download_once(att, timeout)
        if r.status_code != 200 or not r.content:
            raise Unexpected(f"下载附件 {att.filename} 返回 {r.status_code}，大小 {len(r.content)}")
        if r.headers.get("content-type", "").startswith("text/html"):
            raise Unexpected(f"下载附件 {att.filename} 返回了网页而不是文件：{r.text[:120]}")
        if size.isdigit() and int(size) != len(r.content):
            raise Unexpected(f"附件 {att.filename} 大小不符：元数据 {size} 字节，实际 {len(r.content)} 字节")
        return r.content
