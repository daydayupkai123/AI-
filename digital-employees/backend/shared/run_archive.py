"""执行档案记录器（工作台侧）：把一次审查的全过程按序写入资料中心的执行档案（入档时脱敏）。

记录：版本信息、表单快照与材料指纹、取数接口报文、资料同步过程、模型调用（完整输入输出、原文校验结果）、
节点、规则结论、报告、证据截图。档案写入失败不中断审查，但会在界面提示。
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict
from pathlib import Path

from .env_config import ROOT

ARCHIVE_EVENTS = {"node.started", "node.completed", "node.failed", "node.note", "sync.notice", "sync.ready",
                  "file.downloaded", "file.parsed", "rule.completed", "run.started"}
API_BODY_MAX = 1_000_000          # 单个响应体最多入档字节
API_RUN_BUDGET = 20_000_000       # 单次审查接口报文入档总量上限，超出后只记元信息
FLUSH_EVERY = 40
SHOT_LIMIT = 30
_code_ver = {"v": None}


def code_version() -> str:
    if _code_ver["v"] is None:
        h = hashlib.sha256()
        for p in sorted((ROOT / "backend").rglob("*.py")):
            h.update(str(p.relative_to(ROOT)).encode())
            h.update(p.read_bytes())
        _code_ver["v"] = h.hexdigest()[:16]
    return _code_ver["v"]


def config_fingerprints() -> dict:
    out = {}
    for p in sorted((ROOT / "config").rglob("*.yaml")):
        if p.name == "accounts.yaml":  # 含服务账号密码，不入档
            continue
        out[str(p.relative_to(ROOT / "config")).replace("\\", "/")] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return out


def versions(rules_version: str | None, resources, employee: str | None = None) -> dict:
    v = {"rules": rules_version, "code": code_version(), "config": config_fingerprints()}
    if employee:
        from . import rule_config

        v["rule_config"] = rule_config.snapshot(employee)  # 当时生效的规则配置（发布序号 + 内容）
    try:
        from .llm import client as llm

        cfg = llm.config()
        v["llm"] = {role: {"provider": name, "model": ((cfg.get("providers") or {}).get(name) or {}).get("model")}
                    for role, name in (cfg.get("roles") or {}).items()}
    except Exception as exc:  # noqa: BLE001
        v["llm"] = {"error": str(exc)}
    try:
        h = resources.health()
        v["ocr"] = {"engine": h.get("ocr_engine"), "params": h.get("ocr_params")}
    except Exception as exc:  # noqa: BLE001
        v["ocr"] = {"error": str(exc)}
    try:
        from .regulation_kb.base import get_base

        v["regulations"] = [{"id": d["id"], "name": d["name"], "state": d["state"]} for d in get_base().documents()]
    except Exception as exc:  # noqa: BLE001
        v["regulations"] = {"error": str(exc)}
    return v


class RunArchive:
    def __init__(self, resources, task: dict, on_warning=None):
        self.rc = resources
        self.task_id = task["task_id"]
        self.on_warning = on_warning or (lambda text: None)
        self.buf: list[dict] = []
        self.lock = threading.Lock()
        self.api_bytes = 0
        self.material_fp: str | None = None
        self.ok = True
        self.warned = False
        try:
            self.rc.archive_start(self.task_id, task["employee"], task.get("source_system") or "",
                                  task.get("request_id") or "", task.get("trigger_by") or "", 
                                  versions(task.get("rules_version"), resources, task["employee"]))
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)

    def _fail(self, exc: Exception) -> None:
        self.ok = False
        if not self.warned:
            self.warned = True
            self.on_warning(f"执行档案写入失败（{type(exc).__name__}: {exc}），本次审查结论不受影响，但过程无法完整追溯。")

    # ------------------------------------------------------------------ 写入
    def add(self, kind: str, title: str, body) -> None:
        if not self.ok:
            return
        with self.lock:
            self.buf.append({"at": time.time(), "kind": kind, "title": title, "body": body})
            full = len(self.buf) >= FLUSH_EVERY
        if full:
            self.flush()

    def flush(self) -> None:
        if not self.ok:
            return
        with self.lock:
            items, self.buf = self.buf, []
        if not items:
            return
        try:
            self.rc.archive_items(self.task_id, json.loads(json.dumps(items, ensure_ascii=False, default=str)))
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)

    def event(self, ev: dict) -> None:
        if ev.get("type") in ARCHIVE_EVENTS:
            self.add("event", ev["type"], ev)

    def snapshot(self, req, material_fp: str) -> None:
        self.material_fp = material_fp
        self.add("snapshot", "表单快照", {"request_id": req.request_id, "workflow_id": req.workflow_id,
                                          "workflow_name": req.workflow_name, "request_name": req.request_name,
                                          "node_name": req.node_name, "fields": req.fields,
                                          "approval_log": req.approval_log,
                                          "attachments": [{k: v for k, v in asdict(a).items() if k != "loadlink"}
                                                          for a in req.attachments],
                                          "material_fp": material_fp})

    def llm(self, trace: dict) -> None:
        self.add("llm", trace.get("purpose") or "模型调用", trace)

    def note(self, title: str, body) -> None:
        self.add("check", title, body)

    def api_hook(self, r, *args, **kwargs):
        """requests 响应钩子：记录取数接口报文（脱敏在资料中心入档时进行；令牌参数此处先去掉）。"""
        from storage_service.desensitize import mask_url

        try:
            req = r.request
            body = req.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            ctype = r.headers.get("content-type", "")
            rec = {"method": req.method, "url": mask_url(r.url), "status": r.status_code,
                   "ms": int(r.elapsed.total_seconds() * 1000) if r.elapsed else None,
                   "request_body": _mask_form(body)[:20000] if body else None, "content_type": ctype,
                   "bytes": len(r.content)}
            textual = any(t in ctype for t in ("json", "html", "text", "xml", "javascript"))
            if textual and self.api_bytes < API_RUN_BUDGET:
                text = r.text[:API_BODY_MAX]
                self.api_bytes += len(text)
                rec["response"] = text
                rec["truncated"] = len(r.content) > API_BODY_MAX
            elif not textual:
                rec["sha256"] = hashlib.sha256(r.content).hexdigest()
            else:
                rec["response"] = None
                rec["omitted"] = "本次审查接口报文已超过入档上限，只记录元信息"
            self.add("api", f"{req.method} {r.url.split('?')[0]}", rec)
        except Exception:  # noqa: BLE001
            pass
        return r

    def finish(self, status: str, verdict: dict | None = None, error: str | None = None) -> None:
        self.flush()
        if not self.ok:
            return
        try:
            self.rc.archive_finish(self.task_id, status, self.material_fp, verdict, error)
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)


def _mask_form(body: str) -> str:
    from urllib.parse import parse_qsl, urlencode

    from storage_service.desensitize import SECRET_PARAMS

    if "=" in body and not body.lstrip().startswith(("{", "[")):
        try:
            pairs = parse_qsl(body, keep_blank_values=True, strict_parsing=True)
            return urlencode([(k, "***" if k.lower() in SECRET_PARAMS else v) for k, v in pairs])
        except ValueError:
            return body
    return body


def shot_items(final: dict, limit: int = SHOT_LIMIT) -> list[dict]:
    """从报告中取「发现问题 / 人工复核 / 命中」规则引用的原文证据，映射到材料签名。"""
    rep = final.get("report") or {}
    mats = final.get("materials") or []
    by_name = {}
    for m in mats:
        for n in {getattr(m, "filename", ""), getattr(m, "name", "") or getattr(m, "filename", "").rsplit("/", 1)[-1]}:
            if n:
                by_name.setdefault(n, m)
    out = []
    for r in rep.get("rules") or []:
        if r.get("code") not in ("issue", "review") and r.get("status") != "命中":
            continue
        for e in r.get("evidence") or []:
            if not isinstance(e, dict) or not e.get("file"):
                continue
            m = by_name.get(e["file"]) or by_name.get(Path(str(e["file"])).name)
            quote = str(e.get("snippet") or e.get("value") or "")
            if not m or len(quote.strip()) < 4:
                continue
            out.append({"sig": m.sig, "filename": getattr(m, "filename", ""), "page": e.get("page"), "quote": quote,
                        "label": e.get("label") or "", "rule_id": r.get("rule_id")})
            if len(out) >= limit:
                return out
    return out
