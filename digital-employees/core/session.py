"""会话提供方：上层只拿一个带登录态的 requests.Session，不关心登录方式。按 config/accounts.yaml 选择：

- cdp：开发期借用已登录的调试 Chrome（账号密码由人输入，程序不接触）。
  子系统（如合同系统）首次访问需要经统一认证换取本系统会话，warmup() 会在后台标签页自动完成。
- password：部署期用专用服务账号在内网直接登录（客户反馈内网无验证码）。账号密码由运维写在
  config/accounts.yaml（或环境变量 DE_SERVICE_USER / DE_SERVICE_PASSWORD），不入库、不入代码。
  登录交互需在内网用服务账号联调后实现；在此之前选择该模式会明确报错，不会静默回退到 cdp。
"""
from __future__ import annotations

import os
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
                    if on_login and (page.locator("input[type=password]").count() or time.time() - t0 > 8):
                        raise SessionExpired(f"打开 {host} 时停在统一认证登录页（门户未登录）：{page.url[:120]}")
                raise SessionExpired(f"等待 {host} 单点登录超时（{timeout_s}s），最后停留在 {page.url[:120]}")
            finally:
                page.close()


class ServiceAccountNotReady(DEError):
    title = "服务账号登录尚未联调"
    hint = ("config/accounts.yaml 选择了 password 模式，但内网服务账号登录尚未联调实现。"
            "开发期请改回 mode: cdp（借用已登录的调试 Chrome）。")


class PasswordSessionProvider:
    """专用服务账号内网登录（待服务账号到位后在内网联调实现登录交互）。"""

    def __init__(self, username: str, password: str, login_url: str = ""):
        if not username or not password:
            raise ServiceAccountNotReady("config/accounts.yaml 的 password.username / password 为空，"
                                         "也未设置环境变量 DE_SERVICE_USER / DE_SERVICE_PASSWORD")
        self.username, self._password, self.login_url = username, password, login_url

    def session(self) -> requests.Session:
        raise ServiceAccountNotReady(f"服务账号 {self.username} 的内网登录流程尚未联调")

    def warmup(self, host: str) -> None:
        raise ServiceAccountNotReady(f"服务账号 {self.username} 的内网登录流程尚未联调（{host}）")


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
                                       p.get("login_url") or "")
    raise DEError(f"config/accounts.yaml 中的 mode「{mode}」不支持（可选 cdp / password）", title="登录方式配置有误")
