"""M0：不渲染页面，直接回放接口取一笔流程的表单、审批日志与附件（只读）。

  python tools/probes/m0_fetch.py <requestid> [<requestid> ...]

会话来自已登录的调试 Chrome（CDP），只在内存中转给 requests 使用，不落盘。
产物：.runtime/m0/fetch_<requestid>/{form.json, log.json, summary.json, files/*}
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = "https://contract.gt.cn"
OUT = Path(__file__).resolve().parents[2] / ".runtime" / "m0"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")


def session_from_browser() -> requests.Session:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        cookies = browser.contexts[0].cookies()
    s = requests.Session()
    s.trust_env = False
    s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                      "Referer": BASE + "/spa/workflow/static4form/index.html"})
    for c in cookies:
        if c["domain"].endswith("gt.cn"):
            s.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
    return s


def option_name(finfo: dict, value: str) -> str:
    items = ((finfo.get("selectattr") or {}).get("selectitemlist")) or []
    for it in items:
        if str(it.get("selectvalue")) == str(value):
            return it.get("selectname") or ""
    return ""


def flatten_fields(form: dict) -> tuple[list[dict], list[dict]]:
    fmap = ((form.get("tableInfo") or {}).get("main") or {}).get("fieldinfomap") or {}
    maindata = form.get("maindata") or {}
    fields, files = [], []
    for fid, f in fmap.items():
        v = maindata.get(f"field{fid}") or {}
        ht = str(f.get("htmltype"))
        label = (f.get("fieldlabel") or f.get("fieldname") or "").rstrip("：:")
        raw = v.get("value")
        if ht == "6":
            for fd in ((v.get("specialobj") or {}).get("filedatas")) or []:
                files.append({"field": f"field{fid}", "label": label, "filename": fd.get("filename"),
                              "ext": fd.get("fileExtendName"), "size_text": fd.get("filesize"),
                              "fileid": fd.get("fileid"), "imagefileid": fd.get("imagefileid"),
                              "uploaddate": fd.get("uploaddate"), "loadlink": fd.get("loadlink")})
            continue
        display = raw
        if ht == "3":
            objs = v.get("specialobj") or []
            display = "、".join(re.sub(r"<[^>]+>", "", o.get("name") or "") for o in objs) or raw
        elif ht == "5":
            display = option_name(f, raw) or raw
        fields.append({"field": f"field{fid}", "label": label, "htmltype": ht, "value": raw, "display": display})
    return fields, files


def fetch(s: requests.Session, requestid: str) -> dict:
    out = OUT / f"fetch_{requestid}"
    (out / "files").mkdir(parents=True, exist_ok=True)
    timings = {}

    t0 = time.time()
    form = s.post(BASE + "/api/workflow/reqform/loadForm", data={"requestid": requestid}, timeout=60).json()
    if not (form.get("params") or {}).get("workflowid"):
        # 台账授权：以监控方式查看（与台账链接一致）
        form = s.post(BASE + "/api/workflow/reqform/loadForm",
                      data={"requestid": requestid, "ismonitor": "1"}, timeout=60).json()
    timings["loadForm_ms"] = int((time.time() - t0) * 1000)
    params = form.get("params") or {}
    if not params.get("workflowid"):
        raise RuntimeError(f"loadForm 未返回流程信息：{json.dumps(form, ensure_ascii=False)[:300]}")
    (out / "form.json").write_text(json.dumps(form, ensure_ascii=False), encoding="utf-8")

    t0 = time.time()
    log_params = {"isFromWfForm": "1", "requestid": requestid, "requestType": "0",
                  "workflowid": params.get("workflowid"), "nodeid": params.get("nodeid"),
                  "isprint": "0", "submit": "0", "pgnumber": "1", "orderbytype": "1", "wfsignlddtcnt": "100"}
    for key in ("signatureAttributesStr", "signatureSecretKey", "f_weaver_belongto_userid",
                "f_weaver_belongto_usertype", "authStr", "authSignatureStr"):
        if params.get(key) not in (None, ""):
            log_params[key] = params.get(key)
    base_info = s.post(BASE + "/api/workflow/reqform/getRequestLogBaseInfo", data=log_params, timeout=60).json()
    for key in ("viewLogIds", "creatorNodeId", "orderbytype", "wfsignlddtcnt", "isHideInput", "isFormSignature"):
        if base_info.get(key) not in (None, ""):
            log_params[key] = base_info.get(key)
    log_params["wfsignlddtcnt"] = "100"
    log = s.post(BASE + "/api/workflow/reqform/getRequestLogList", data=log_params, timeout=60).json()
    timings["log_ms"] = int((time.time() - t0) * 1000)
    (out / "log.json").write_text(json.dumps(log, ensure_ascii=False), encoding="utf-8")
    logs = [{"date": it.get("log_operatedate"), "time": it.get("log_operatetime"), "node": it.get("log_nodename"),
             "operator": it.get("displayname"), "dept": it.get("displaydepname"), "action": it.get("operationname"),
             "remark": re.sub(r"<[^>]+>", "", it.get("log_remarkHtml") or "").strip()}
            for it in (log.get("loglist") or [])]

    fields, files = flatten_fields(form)
    t0 = time.time()
    for fd in files:
        resp = s.get(BASE + fd.pop("loadlink"), timeout=180)
        body = resp.content
        fd.update({"http": resp.status_code, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
        if resp.status_code == 200 and body:
            (out / "files" / f"{fd['sha256'][:16]}_{fd['filename']}").write_bytes(body)
    timings["files_ms"] = int((time.time() - t0) * 1000)

    summary = {"requestid": requestid, "workflowid": params.get("workflowid"),
               "workflowname": params.get("workflowname"), "requestname": params.get("requestname"),
               "nodename": params.get("nodename"), "fields": fields, "approval_log": logs,
               "files": files, "timings": timings}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def main():
    s = session_from_browser()
    for rid in sys.argv[1:]:
        sm = fetch(s, rid)
        print(f"== {rid} {sm['workflowname']} | {sm['requestname']} | 节点={sm['nodename']} | {sm['timings']}")
        for f in sm["fields"]:
            if f["display"] not in (None, "", "0") and not f["field"].startswith("field-"):
                print(f"   {f['label']}: {str(f['display'])[:60]}")
        print(f"   审批日志 {len(sm['approval_log'])} 条:")
        for lg in sm["approval_log"]:
            print(f"     {lg['date']} {lg['time']} {lg['node']} {lg['operator']}({lg['dept']}) {lg['action']}")
        print(f"   附件 {len(sm['files'])} 份:")
        for fd in sm["files"]:
            print(f"     [{fd['label']}] {fd['filename']} {fd['bytes']}B http={fd['http']} sha={fd['sha256'][:12]}")


if __name__ == "__main__":
    main()
