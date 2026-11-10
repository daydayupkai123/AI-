"""天眼查只读查询：借用调试 Chrome 中已登录的天眼查页面，搜索 → 打开详情，拦截页面背后的 JSON 接口。

接口与字段来自 2026-11-06 的实测记录（.runtime/tyc/），解析函数与网络获取分离，便于离线测试：
  appComIcV4            工商信息（名称、信用代码、法定代表人、注册资本、登记状态）
  dim/staff/announcement 主要人员
  holder/latest/announcement 股东
  ei/get/suspected/list 疑似关系（相同电话/邮箱/地址等）
  actual/controller/list 实际控制人；final/beneficiary/list 最终受益人
风险计数（失信被执行人、被执行人、破产案件、限制消费令、自身风险）从详情页文字读取：有记录时页面导航显示为「失信被执行人3」。
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import quote

from ..config import CDP_URL
from . import ExternalUnavailable

KIND = "tianyancha.profile"
TTL_S = 7 * 24 * 3600

ENDPOINTS = {
    "base": "/details/appComIcV4/",
    "staff": "/dim/staff/announcement",
    "holders": "/holder/latest/announcement",
    "suspected": "/ei/get/suspected/list",
    "controller": "/actual/controller/list",
    "beneficiary": "/final/beneficiary/list",
}
RISK_KEYS = ["失信被执行人", "被执行人", "破产案件", "限制消费令", "终本案件", "股权冻结", "经营异常", "严重违法"]


@dataclass
class CompanyProfile:
    query: str
    name: str = ""
    credit_code: str = ""
    legal_person: str = ""
    reg_status: str = ""
    reg_capital: str = ""
    reg_capital_yuan: float | None = None
    phone: str = ""
    email: str = ""
    address: str = ""
    holders: list = field(default_factory=list)
    staff: list = field(default_factory=list)
    controllers: list = field(default_factory=list)
    beneficiaries: list = field(default_factory=list)
    suspected: list = field(default_factory=list)
    risks: dict = field(default_factory=dict)
    self_risk: int | None = None
    url: str = ""
    fetched_at: float = 0.0

    def people(self) -> set[str]:
        return {p["name"] for p in self.staff + self.holders + self.controllers + self.beneficiaries
                if p.get("name") and p.get("kind", "person") == "person"}

    def to_dict(self) -> dict:
        return asdict(self)


def capital_yuan(text: str) -> float | None:
    """「100万人民币」「5000万元人民币」「1.2亿人民币」→ 元；外币不折算（返回 None）。"""
    m = re.search(r"([\d,.]+)\s*(亿|万)?\s*(元)?\s*(人民币)?", text or "")
    if not m or (text and re.search(r"美元|欧元|港元|日元|英镑", text)):
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v * {"亿": 1e8, "万": 1e4}.get(m.group(2) or "", 1)


def parse_base(d: dict) -> dict:
    b = ((d or {}).get("data") or {}).get("baseInfo") or {}
    return {"name": b.get("name") or "", "credit_code": b.get("creditCode") or "",
            "legal_person": b.get("legalPersonName") or "", "reg_status": b.get("regStatus") or "",
            "reg_capital": b.get("regCapital") or "", "reg_capital_yuan": capital_yuan(b.get("regCapital") or ""),
            "phone": b.get("phoneNumber") or "", "email": b.get("email") or "", "address": b.get("regLocation") or ""}


def parse_staff(d: dict) -> list[dict]:
    rows = ((d or {}).get("data") or {}).get("result") or []
    return [{"name": r.get("name"), "roles": r.get("typeJoin") or [], "percent": r.get("percent"), "kind": "person"}
            for r in rows if r.get("name")]


def parse_holders(d: dict) -> list[dict]:
    rows = ((d or {}).get("data") or {}).get("result") or []
    return [{"name": r.get("shareHolderName"), "percent": r.get("percent"),
             "kind": "person" if r.get("shareHolderType") == 1 or "自然人" in (r.get("shareHolderTypeOnPage") or "")
             else "company", "capital": r.get("totalCapital")} for r in rows if r.get("shareHolderName")]


def parse_suspected(d: dict) -> list[dict]:
    rows = ((d or {}).get("data") or {}).get("list") or []
    out = []
    for r in rows:
        detail = [x.get("email") for x in r.get("emailList") or []] + [x.get("phone") or x.get("phoneNumber")
                                                                        for x in r.get("phoneList") or []]
        detail += [x.get("address") for x in r.get("addressList") or []]
        out.append({"company": r.get("companyName"), "types": r.get("suspectedTypeText") or "",
                    "detail": [x for x in detail if x]})
    return out


def parse_controllers(d: dict) -> list[dict]:
    rows = ((d or {}).get("data") or {}).get("acList") or []
    return [{"name": r.get("name"), "percent": r.get("shareHoldingRatio"), "kind": "person" if r.get("type") == 2
             else "company"} for r in rows if r.get("name")]


def parse_beneficiaries(d: dict) -> list[dict]:
    rows = ((d or {}).get("data") or {}).get("beneficialOwnerList") or []
    return [{"name": r.get("humanName"), "percent": r.get("finalBenefitShare"), "kind": "person"}
            for r in rows if r.get("humanName")]


def parse_risk_text(text: str) -> tuple[dict, int | None]:
    """详情页文字中的风险计数；导航为「法律诉讼…失信被执行人被执行人…」时计数为 0。"""
    t = text or ""
    sr = re.search(r"自身风险\s*(\d+)", t)
    # 「法律诉讼」在概览计数区（法律诉讼\n6\n经营风险\n1）和维度导航中都会出现，取含维度名称的那一段
    m = next((x for x in re.finditer(r"\n法律诉讼\n(.+)\n经营风险\n(.+)\n", t) if "失信被执行人" in x.group(1)), None)
    if not m:
        return {}, int(sr.group(1)) if sr else None  # 页面结构变化：风险计数未知，调用方须转人工复核
    nav = m.group(1) + m.group(2)
    risks = {}
    for key in RISK_KEYS:
        n = 0
        for mm in re.finditer(rf"{re.escape(key)}(\d+)", nav):
            before = nav[max(0, mm.start() - 2):mm.start()]
            if before == "历史" or (key == "被执行人" and before == "失信"):
                continue
            n = int(mm.group(1))
            break
        risks[key] = n
    return risks, int(sr.group(1)) if sr else None


def assemble(query: str, captured: dict[str, dict], detail_text: str, url: str) -> CompanyProfile:
    if "base" not in captured:
        raise ExternalUnavailable(f"天眼查未返回「{query}」的工商信息（可能未登录、触发验证或查无此公司）")
    p = CompanyProfile(query=query, url=url, fetched_at=time.time(), **parse_base(captured["base"]))
    p.staff = parse_staff(captured.get("staff"))
    p.holders = parse_holders(captured.get("holders"))
    p.suspected = parse_suspected(captured.get("suspected"))
    p.controllers = parse_controllers(captured.get("controller"))
    p.beneficiaries = parse_beneficiaries(captured.get("beneficiary"))
    p.risks, p.self_risk = parse_risk_text(detail_text)
    return p


class TianyanchaClient:
    """串行使用（公用账号、页面单实例）；调用方负责缓存与限速。"""

    def __init__(self, cdp_url: str = CDP_URL, wait_ms: int = 6000):
        self.cdp_url = cdp_url
        self.wait_ms = wait_ms

    def profile(self, name: str) -> CompanyProfile:
        from playwright.sync_api import sync_playwright

        captured: dict[str, dict] = {}

        def on_resp(resp):
            if resp.request.resource_type not in ("xhr", "fetch"):
                return
            key = next((k for k, frag in ENDPOINTS.items() if frag in resp.url), None)
            if not key or key in captured:
                return
            try:
                captured[key] = resp.json()
            except Exception:  # noqa: BLE001
                return

        try:
            with sync_playwright() as p:
                ctx = p.chromium.connect_over_cdp(self.cdp_url, timeout=8000).contexts[0]
                page = ctx.new_page()
                try:
                    page.goto("https://www.tianyancha.com/search?key=" + quote(name), wait_until="domcontentloaded",
                              timeout=60000)
                    page.wait_for_timeout(3000)
                    if "login" in page.url:
                        raise ExternalUnavailable("天眼查要求登录")
                    link = page.locator("a[href*='/company/']").first
                    href = link.get_attribute("href") if link.count() else None
                    if not href:
                        raise ExternalUnavailable(f"天眼查未搜索到「{name}」")
                    page.on("response", on_resp)
                    page.goto(href if href.startswith("http") else "https://www.tianyancha.com" + href,
                              wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(self.wait_ms)
                    text = page.evaluate("() => document.body.innerText")
                    url = page.url
                finally:
                    page.close()
        except ExternalUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ExternalUnavailable(f"{type(exc).__name__}: {exc}") from exc
        return assemble(name, captured, text, url)


class CachedTianyancha:
    def __init__(self, store, client: TianyanchaClient | None = None, ttl_s: float = TTL_S):
        self.store = store
        self.client = client or TianyanchaClient()
        self.ttl_s = ttl_s

    def profile(self, name: str) -> dict:
        key = re.sub(r"\s", "", name).replace("（", "(").replace("）", ")")
        hit = self.store.get_external(KIND, key)
        if hit:
            return hit
        body = self.client.profile(name).to_dict()
        if body.get("name") and re.sub(r"[()（）\s]", "", body["name"]) != re.sub(r"[()（）\s]", "", name):
            body["_name_mismatch"] = True
        self.store.put_external(KIND, key, body, self.ttl_s)
        return body
