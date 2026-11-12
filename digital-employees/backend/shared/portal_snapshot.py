"""平台页面留档：审查取单后，在后台无界面浏览器中只读打开该单据在客户平台上的详情页，整页截图并记录页面发出的请求。

- 只读：拦截一切形似提交 / 保存 / 审批的非 GET 请求（与 tools/probes/page_capture.py 同一规则），被拦截的请求记入档案。
- 不打开待办：合同系统只在 loadForm 明确返回「只读查看」（isviewonly=1 且非当前处理人）时打开；
  公文系统只定位「我的发起 / 已办 / 已阅」，以 openFrom=listDone 打开；本地事项、离线重放没有平台页面。
- 使用与取数相同的登录态（会话 Cookie 注入独立的无界面浏览器），不占用、不打扰调试 Chrome。
- 截图原样交资料中心保存；同时在页面上定位身份证号 / 手机号 / 银行账号所在位置，前端展示时按位置打码。
"""
from __future__ import annotations

import re
import threading
import time
from urllib.parse import quote, urlparse

from storage_service.desensitize import mask_url, sensitive_spans

# 只读：地址像写操作（提交、保存、审批、写浏览记录等）的非 GET 请求一律拦截；请求体只看「动作」类参数，
# 避免把 submit=0 这类只读参数误判（金蝶云苍穹的按钮动作 bar_submit / audit 写在请求体里）。
WRITE = re.compile(r"(submit|save|delete|remove|agree|disagree|takeback|withdraw|doback|stepback|finish|send|"
                   r"repeal|cancel|lock|update|audit|approve|reject|unaudit|forward|transmit|insert|viewlog|"
                   r"markread|setread|doread|addlog|remarkoperate|track/log)", re.I)
WRITE_BODY = re.compile(r"(bar_(submit|save|audit|unaudit|delete|submitandnew)|"
                        r"(^|[&{,\"])\s*\"?(action|operate|operation|opt|actiontype|src)\"?\s*[:=]\s*\"?"
                        r"(submit|save|delete|agree|approve|reject|audit|send|forward|takeback))", re.I)
MAX_HEIGHT = 12000
VIEW_W = 1440


def target(source: str, req) -> dict:
    """返回 {url, title} 或 {skip: 原因}。"""
    rp = getattr(req, "raw_params", None) or {}
    if source == "contract":
        from .source_adapters.contract import HOST

        from .source_adapters.contract import is_pending

        if is_pending(rp) or str(rp.get("isviewonly")) != "1":
            return {"skip": "该单据是当前账号的待办（或无法确认为只读查看），按约定不打开平台页面"}
        q = f"requestid={req.request_id}" + ("&ismonitor=1" if getattr(req, "via_monitor", False) else "")
        return {"url": f"https://{HOST}/spa/workflow/static4form/index.html#/main/workflow/req?{q}",
                "title": "合同系统 · 审批单据详情（只读查看）"}
    if source == "docflow":
        from .source_adapters.docflow import FINISHED, OA, QUERY

        if rp.get("openFrom") == "formQuery":
            if rp.get("flow_state") != FINISHED or not rp.get("summaryId"):
                return {"skip": "流程未结束的请示可能是他人的待办，按约定不打开平台页面"}
            inner = (f"/seeyon/govdoc/govdoc.do?method=summary&summaryId={rp['summaryId']}&openFrom=formQuery"
                     f"&operationId={QUERY['operationId']}&formId={QUERY['formId']}")
            title = "公文系统 · 内部请示详情（公司数据查询只读视图）"
        else:
            aff = rp.get("affairId")
            if not aff:
                return {"skip": "缺少 affairId，无法定位公文页面"}
            inner = f"/seeyon/govdoc/govdoc.do?method=summary&isFromHome=true&openFrom=listDone&affairId={aff}"
            title = "公文系统 · 内部请示详情（已办 / 已发只读视图）"
        return {"url": f"{OA}/seeyon/tyssj.do?method=access&targetUrl={quote(inner, safe='')}", "title": title}
    return {"skip": "本地事项 / 离线数据，没有客户平台页面"}


def _cookies(session) -> list[dict]:
    out = []
    for c in session.cookies:
        out.append({"name": c.name, "value": c.value, "domain": c.domain or "", "path": c.path or "/",
                    "secure": bool(c.secure), **({"expires": float(c.expires)} if c.expires else {})})
    return out


_HIDDEN_JS = """() => {
  // 页面内未显示完的高度：文档本身与最大的内部滚动容器（表单常放在随窗口高度变化的滚动区里）
  let extra = Math.max(0, document.documentElement.scrollHeight - innerHeight);
  for (const el of document.querySelectorAll('*')) {
    if (el.clientHeight > 200 && el.scrollHeight > el.clientHeight + 40 && /(auto|scroll)/.test(getComputedStyle(el).overflowY))
      extra = Math.max(extra, el.scrollHeight - el.clientHeight);
  }
  return extra;
}"""
_CONTENT_H_JS = "() => Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)"
# 可见内容底边（忽略被撑高的空布局）；用于控制截图高度，避免大片底部留白
_CONTENT_BOTTOM_JS = """() => {
  let max = 0;
  const body = document.body;
  if (!body) return innerHeight;
  for (const el of body.querySelectorAll('*')) {
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || Number(st.opacity) === 0) continue;
    const t = (el.innerText || '').replace(/\\s+/g, '');
    const hasMedia = el.tagName === 'IMG' || el.tagName === 'CANVAS' || el.tagName === 'SVG'
      || el.tagName === 'TABLE' || el.tagName === 'INPUT' || el.tagName === 'TEXTAREA';
    if (!hasMedia && t.length < 2) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    max = Math.max(max, r.bottom + scrollY);
  }
  return Math.ceil(Math.max(max, Math.min(innerHeight, 900)));
}"""


def _fit_height(page) -> tuple[int, bool]:
    """逐步加高无界面浏览器的窗口直到内容全部露出（只改本地显示，不涉及服务器）；返回高度与是否截断。
    最终高度取「可见内容底边」与滚动需求的较小合理值，避免 SPA 空布局把 scrollHeight 撑到数千像素留白。"""
    height = 900
    for _ in range(4):
        extra = page.evaluate(_HIDDEN_JS)
        if extra < 40:
            break
        if height >= MAX_HEIGHT:
            return height, True
        height = int(min(height + extra + 40, MAX_HEIGHT))
        page.set_viewport_size({"width": VIEW_W, "height": height})
        page.wait_for_timeout(700)
    grown = False
    for f in page.frames[1:]:  # 固定高度的同源 iframe（公文表单）按内容高度撑开
        try:
            el = f.frame_element()
            box = el.bounding_box()
            ch = f.evaluate(_CONTENT_BOTTOM_JS)
            if box and box["height"] > 50 and ch > box["height"] + 40:
                el.evaluate("(e, h) => { e.style.height = h + 'px'; e.style.maxHeight = 'none'; }", ch + 20)
                grown = True
        except Exception:  # noqa: BLE001
            continue
    if grown:
        page.wait_for_timeout(500)
    content_bottom = int(page.evaluate(_CONTENT_BOTTOM_JS) or height)
    # 内容底边 + 边距；同时不超过当前滚动需求，避免截断真实内容
    need = int(min(max(content_bottom + 48, 900), MAX_HEIGHT))
    scroll_need = int(min(page.evaluate(_CONTENT_H_JS) or need, MAX_HEIGHT))
    # 若 scrollHeight 明显虚高（大于内容底边 1.6 倍），按内容底边截
    height = need if scroll_need > need * 1.6 else int(min(max(need, scroll_need), MAX_HEIGHT))
    page.set_viewport_size({"width": VIEW_W, "height": height})
    page.wait_for_timeout(400)
    return height, page.evaluate(_HIDDEN_JS) >= 40

_TEXT_JS = """() => {
  // 收集可见文字节点与输入框的文字及其页面坐标，供定位敏感信息
  const out = [];
  const walker = document.createTreeWalker(document.body || document, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    const t = n.nodeValue;
    if (!t || !/\\d{6,}/.test(t)) continue;
    const r = document.createRange();
    r.selectNodeContents(n);
    const b = r.getBoundingClientRect();
    if (b.width && b.height) out.push({t, x: b.left + scrollX, y: b.top + scrollY, w: b.width, h: b.height});
  }
  for (const el of document.querySelectorAll('input, textarea')) {
    const t = el.value;
    if (!t || !/\\d{6,}/.test(t)) continue;
    const b = el.getBoundingClientRect();
    if (b.width && b.height) out.push({t, x: b.left + scrollX, y: b.top + scrollY, w: b.width, h: b.height});
  }
  return out;
}"""


def _pii_rects(frame, dx: float, dy: float) -> list[list[float]]:
    rects = []
    for it in frame.evaluate(_TEXT_JS):
        t = it["t"]
        for s, e in sensitive_spans(t):
            n = max(len(t), 1)
            x0 = it["x"] + it["w"] * s / n
            x1 = it["x"] + it["w"] * e / n
            rects.append([round(dx + x0 - 3, 1), round(dy + it["y"] - 2, 1), round(dx + x1 + 3, 1),
                          round(dy + it["y"] + it["h"] + 2, 1)])
    return rects


def _launch(p):
    """优先用本机安装的 Chrome（独立的无界面实例，与调试 Chrome 互不影响），没有再用 Playwright 自带浏览器。"""
    try:
        return p.chromium.launch(channel="chrome", headless=True)
    except Exception:  # noqa: BLE001
        return p.chromium.launch(headless=True)


def _kicked(page) -> bool:
    from .source_adapters.docflow import KICKED

    for f in page.frames:
        try:
            if KICKED.search(f.evaluate("() => document.body ? document.body.innerText.slice(0, 3000) : ''")):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def capture(session, url: str, wait_s: float = 4.0, timeout_s: float = 60.0) -> dict:
    """打开页面并截图。返回 {png, width, height, final_url, ops, blocked, pii, error}。"""
    from playwright.sync_api import sync_playwright

    ops, blocked = [], []
    t0 = time.time()
    out = {"png": None, "ops": ops, "blocked": blocked, "pii": [], "error": None}

    def guard(route):
        req = route.request
        u = urlparse(req.url)
        if req.method != "GET" and (WRITE.search(u.path + "?" + (u.query or "")) or WRITE_BODY.search(req.post_data or "")):
            blocked.append({"method": req.method, "url": mask_url(req.url)})
            return route.abort()
        return route.continue_()

    def on_resp(resp):
        rq = resp.request
        if rq.resource_type in ("xhr", "fetch", "document"):
            ops.append({"type": rq.resource_type, "method": rq.method, "url": mask_url(resp.url), "status": resp.status,
                        "at": round(time.time() - t0, 2)})

    with sync_playwright() as p:
        browser = _launch(p)
        try:
            ctx = browser.new_context(viewport={"width": VIEW_W, "height": 900}, locale="zh-CN",
                                      user_agent=session.headers.get("User-Agent"))
            ctx.add_cookies([c for c in _cookies(session) if c["domain"]])
            page = ctx.new_page()
            page.route("**/*", guard)
            page.on("response", on_resp)
            for attempt in (0, 1):
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_s * 1000)
                except Exception:  # noqa: BLE001  页面长连接导致迟迟不 idle 时按已加载内容截图
                    pass
                page.wait_for_timeout(wait_s * 1000)
                if not _kicked(page):
                    break
                if attempt == 1:
                    out["error"] = "平台会话被同一账号在别处的登录挤下线（重试一次仍然如此），未截图"
                    return out
            out["final_url"] = mask_url(page.url)
            if "login.gt.cn" in page.url or "method=login" in page.url:
                out["error"] = "页面跳到了登录页（平台会话失效），未截图"
                return out
            height, truncated = _fit_height(page)
            rects = _pii_rects(page.main_frame, 0, 0)
            for f in page.frames[1:]:
                try:
                    box = f.frame_element().bounding_box()
                    if box:
                        rects += _pii_rects(f, box["x"], box["y"])
                except Exception:  # noqa: BLE001
                    continue
            out["pii"] = rects
            from storage_service.image_trim import trim_bottom_whitespace

            png = page.screenshot(full_page=False)
            png, tw, th = trim_bottom_whitespace(png)
            out["png"] = png
            out["width"], out["height"] = tw or VIEW_W, th or height
            out["truncated"] = truncated
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {exc}"[:500]
        finally:
            browser.close()
    out["ms"] = int((time.time() - t0) * 1000)
    return out


class PageCapture:
    """取单后在后台线程截图，流程结束前取回结果交资料中心入档（不阻塞审查）。"""

    def __init__(self, rt, source: str, req):
        self.rt, self.source, self.req = rt, source, req
        self.tgt = target(source, req)
        self.result: dict | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> "PageCapture":
        if self.tgt.get("skip") or self.rt.sessions is None:
            return self
        session = self.rt.sessions.session()
        self.thread = threading.Thread(target=self._run, args=(session,), daemon=True, name="portal-capture")
        self.thread.start()
        return self

    def _run(self, session) -> None:
        try:
            self.result = capture(session, self.tgt["url"])
        except Exception as exc:  # noqa: BLE001
            self.result = {"png": None, "ops": [], "blocked": [], "pii": [], "error": f"{type(exc).__name__}: {exc}"}

    def finish(self, arc, wait_s: float = 90.0) -> None:
        """把截图与页面请求交资料中心入档；未截图的也写明原因。"""
        if arc is None or not arc.ok:
            return
        meta = {"title": self.tgt.get("title") or "客户平台页面", "url": mask_url(self.tgt.get("url") or ""),
                "skip": self.tgt.get("skip")}
        if self.thread is not None:
            self.thread.join(wait_s)
            r = self.result or {"error": "截图超时", "ops": [], "blocked": [], "pii": []}
            meta.update({k: r.get(k) for k in ("final_url", "ops", "blocked", "error", "width", "height", "truncated",
                                               "ms")})
            if r.get("png"):
                try:
                    meta["page_id"] = self.rt.resources.archive_page(arc.task_id, meta, r["png"], r.get("pii") or [])
                except Exception as exc:  # noqa: BLE001
                    meta["error"] = f"截图入档失败：{type(exc).__name__}: {exc}"
        elif not meta["skip"]:
            meta["skip"] = "没有平台登录会话（离线 / 本地运行）"
        arc.add("page", meta["title"], meta)
        self.rt.on_event({"type": "archive.page", "ok": bool(meta.get("page_id")), "skip": meta.get("skip"),
                          "error": meta.get("error")})
