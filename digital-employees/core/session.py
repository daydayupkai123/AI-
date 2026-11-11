"""会话提供方：上层只拿一个带登录态的 requests.Session，不关心登录方式。按 config/accounts.yaml 选择：

- cdp：开发期借用已登录的调试 Chrome（账号密码由人输入，程序不接触）。
  子系统（如合同系统）首次访问需要经统一认证换取本系统会话，warmup() 会在后台标签页自动完成。
- password：部署期用专用服务账号在内网登录（内网访问统一认证不要求短信 / 图片验证码）。服务器上常驻一个
  只监听本机的无界面 Chrome（deploy/chrome.sh），单点登录停在统一认证页时由程序填写服务账号提交，
  其余与 cdp 模式相同。账号密码来自环境变量 DE_SERVICE_USER / DE_SERVICE_PASSWORD（或 accounts.yaml），不入库。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import requests
import yaml

from .config import CDP_URL, ROOT
from .errors import BrowserUnavailable, DEError, SessionExpired

ACCOUNTS_PATH = Path(os.environ.get("DE_ACCOUNTS_CONFIG", str(ROOT / "config" / "accounts.yaml")))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")

# 各子系统的单点登录入口：打开后会经统一认证自动跳回并写入本系统会话
WARMUP = {
    "contract.gt.cn": "https://contract.gt.cn/spa/workflow/static/index.html#/main/workflow/listDoing",
    "oa-xc.gt.cn": "https://oa-xc.gt.cn/seeyon/tyssj.do?method=access&targetUrl=%2Fseeyon%2Fmain.do",
}


class SessionProvider(Protocol):
    def session(self) -> requests.Session: ...

    def warmup(self, host: str) -> None: ...


class CdpSessionProvider:
    def __init__(self, cdp_url: str = CDP_URL, domain_suffix: str = "gt.cn"):
        self.cdp_url = cdp_url
        self.domain_suffix = domain_suffix

    def _connect(self, p):
        try:
            return p.chromium.connect_over_cdp(self.cdp_url, timeout=8000)
        except Exception as exc:  # noqa: BLE001
            raise BrowserUnavailable(f"{type(exc).__name__}: {exc}") from exc

    def session(self) -> requests.Session:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            cookies = self._connect(p).contexts[0].cookies()
        s = requests.Session()
        s.trust_env = False
        s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})
        n = 0
        for c in cookies:
            if c["domain"].lstrip(".").endswith(self.domain_suffix):
                s.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
                n += 1
        if n == 0:
            raise SessionExpired("调试 Chrome 中没有 gt.cn 的任何登录信息")
        return s

    def warmup(self, host: str, timeout_s: int = 25) -> None:
        """在调试 Chrome 后台标签页打开子系统入口，等待统一认证跳回并写入该系统会话。"""
        from playwright.sync_api import sync_playwright

        url = WARMUP.get(host)
        if not url:
            return
        with sync_playwright() as p:
            ctx = self._connect(p).contexts[0]
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                t0 = time.time()
                deadline = t0 + timeout_s
                while time.time() < deadline:
                    page.wait_for_timeout(1000)
                    cur = urlparse(page.url).netloc
                    has_cookie = any(c["domain"].lstrip(".").endswith(host) for c in ctx.cookies())
                    if cur.endswith(host) and has_cookie:
                        page.wait_for_timeout(1500)
                        return
                    on_login = cur.startswith("login.")
                    if on_login and (page.locator("input[type=password], #fs86_fspassword").count()
                                     or time.time() - t0 > 8):
                        self._on_login_page(page, host)
                        deadline = max(deadline, time.time() + timeout_s)
                raise SessionExpired(f"等待 {host} 单点登录超时（{timeout_s}s），最后停留在 {page.url[:120]}")
            finally:
                page.close()

    def _on_login_page(self, page, host: str) -> None:
        raise SessionExpired(f"打开 {host} 时停在统一认证登录页（门户未登录）：{page.url[:120]}")


class ServiceAccountNotReady(DEError):
    title = "服务账号未配置"
    hint = "password 模式需要设置环境变量 DE_SERVICE_USER / DE_SERVICE_PASSWORD（或在 config/accounts.yaml 填写）。"


class ServiceLoginFailed(DEError):
    title = "服务账号登录统一认证失败"
    hint = ("请确认服务账号密码正确且未被锁定。为避免连续输错触发验证码或锁号，失败后 10 分钟内不再自动登录；"
            "处理好后重启工作台服务即可立即重试。")


LOGIN_RETRY_AFTER_S = 600


class PasswordSessionProvider(CdpSessionProvider):
    """服务账号模式：使用服务器上常驻的无界面 Chrome，单点登录停在统一认证页时自动填写服务账号登录。"""

    def __init__(self, username: str, password: str, login_url: str = "", cdp_url: str = CDP_URL):
        if not username or not password:
            raise ServiceAccountNotReady("config/accounts.yaml 的 password.username / password 为空，"
                                         "也未设置环境变量 DE_SERVICE_USER / DE_SERVICE_PASSWORD")
        super().__init__(cdp_url)
        self.username, self._password, self.login_url = username, password, login_url
        self._lock = threading.Lock()
        self._failed: tuple[float, str] | None = None

    def session(self) -> requests.Session:
        try:
            return super().session()
        except SessionExpired:
            self.warmup("contract.gt.cn")
            return super().session()

    def _on_login_page(self, page, host: str) -> None:
        with self._lock:
            if self._failed and time.time() - self._failed[0] < LOGIN_RETRY_AFTER_S:
                raise ServiceLoginFailed(f"上次登录失败（{self._failed[1]}），{LOGIN_RETRY_AFTER_S // 60} 分钟内不再自动重试")
            try:
                self._submit(page)
            except ServiceLoginFailed as exc:
                self._failed = (time.time(), exc.detail)
                raise
            self._failed = None

    def _submit(self, page) -> None:
        page.wait_for_selector("#fs86_fsusername", timeout=20000)
        page.wait_for_timeout(800)
        page.fill("#fs86_fsusername", self.username)
        page.locator("#fs86_fsusername").blur()
        page.click("#fs86_fspassword")
        page.fill("#fs86_fspassword", self._password)
        page.wait_for_timeout(1500)  # 用户名失焦后页面异步查询是否需要短信 / 图片验证码
        for box, what in (("#sms86_checkbox", "短信验证码"), ("#sms86_otp", "动态口令"), ("#yzm4Bar1", "图片验证码")):
            if page.locator(box).is_visible():
                raise ServiceLoginFailed(f"统一认证要求{what}（服务器不在免验证网络，或账号输错次数过多）")
        page.click("form#authen86Form1 button.loginBt")
        deadline = time.time() + 30
        while time.time() < deadline:
            page.wait_for_timeout(1000)
            if not urlparse(page.url).netloc.startswith("login."):
                return
            msg = page.evaluate("""() => [...document.querySelectorAll('#authen86Form1 .warningTxt, #errorDivMsg')]
                .map(e => e.innerText.trim()).filter(Boolean).join('；')""")
            if msg:
                raise ServiceLoginFailed(f"统一认证提示：{msg}")
        raise ServiceLoginFailed(f"提交后 30 秒仍停留在统一认证页：{page.url[:120]}")


def accounts_config() -> dict:
    return (yaml.safe_load(ACCOUNTS_PATH.read_text(encoding="utf-8")) or {}) if ACCOUNTS_PATH.exists() else {}


def provider_from_config() -> SessionProvider:
    cfg = accounts_config()
    mode = (os.environ.get("DE_SESSION_MODE") or cfg.get("mode") or "cdp").strip()
    if mode == "cdp":
        return CdpSessionProvider((cfg.get("cdp") or {}).get("url") or CDP_URL)
    if mode == "password":
        p = cfg.get("password") or {}
        return PasswordSessionProvider(os.environ.get("DE_SERVICE_USER") or p.get("username") or "",
                                       os.environ.get("DE_SERVICE_PASSWORD") or p.get("password") or "",
                                       p.get("login_url") or "",
                                       os.environ.get("DE_CDP_URL") or (cfg.get("cdp") or {}).get("url") or CDP_URL)
    raise DEError(f"config/accounts.yaml 中的 mode「{mode}」不支持（可选 cdp / password）", title="登录方式配置有误")
