"""工作台账号与登录会话。

账号维护在 DE_USERS_FILE（默认 config/users.local.yaml，不入库），密码只存 PBKDF2 哈希：
  users:
    linxiao: {name: 林晓, role: admin, password: "pbkdf2_sha256$..."}
用 tools/ops/user_admin.py 增改账号。文件不存在或为空时不启用账号登录（沿用访问口令 / 本机开发不设防）。
角色：admin 管理员（全部操作）、reviewer 复核员（复核标注、重新发起、复制意见）、reader 只读人员。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from shared.env_config import ROOT, hmac_key

USERS_PATH = Path(os.environ.get("DE_USERS_FILE", str(ROOT / "config" / "users.local.yaml")))
ROLES = {"admin": "管理员", "reviewer": "复核员", "reader": "只读人员"}
COOKIE = "de_session"
TTL_S = 12 * 3600
MAX_FAILS, LOCK_S = 5, 300

_cache: dict = {"mtime": None, "users": {}}
_fails: dict[str, list[float]] = {}
_lock = threading.Lock()


def hash_password(password: str, iterations: int = 200_000) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode(), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode(), int(n)).hex()
    return hmac.compare_digest(got, digest)


def users() -> dict[str, dict]:
    mtime = USERS_PATH.stat().st_mtime if USERS_PATH.exists() else None
    with _lock:
        if _cache["mtime"] != mtime:
            data = (yaml.safe_load(USERS_PATH.read_text(encoding="utf-8")) or {}) if mtime else {}
            _cache.update(mtime=mtime, users={k: v for k, v in (data.get("users") or {}).items() if v})
        return _cache["users"]


def enabled() -> bool:
    return bool(users())


def _sign(payload: bytes) -> str:
    return hmac.new(hmac_key(), payload, hashlib.sha256).hexdigest()


def issue(username: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"u": username, "exp": time.time() + TTL_S}).encode())
    return payload.decode() + "." + _sign(payload)


def user_of(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(_sign(payload.encode()), sig):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode()))
    except ValueError:
        return None
    u = users().get(data.get("u"))
    if not u or data.get("exp", 0) < time.time():
        return None
    return {"username": data["u"], "name": u.get("name") or data["u"], "role": u.get("role") or "reader"}


def current(request: Request) -> dict:
    """当前登录人；未启用账号登录时视为本机管理员（开发 / 仅访问口令保护的部署）。"""
    if not enabled():
        return {"username": "local", "name": "管理员", "role": "admin", "auth": False}
    u = user_of(request.cookies.get(COOKIE))
    if not u:
        raise HTTPException(401, "未登录或登录已过期")
    return u


def require(request: Request, *roles: str) -> dict:
    u = current(request)
    if roles and u["role"] not in roles:
        raise HTTPException(403, f"当前角色（{ROLES.get(u['role'], u['role'])}）无权执行此操作")
    return u


router = APIRouter()


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/api/auth/login")
def login(body: LoginIn, response: Response):
    name = body.username.strip()
    now = time.time()
    with _lock:
        recent = [t for t in _fails.get(name, []) if now - t < LOCK_S]
        _fails[name] = recent
    if len(recent) >= MAX_FAILS:
        raise HTTPException(429, f"连续登录失败次数过多，请 {int((LOCK_S - (now - recent[0])) // 60) + 1} 分钟后再试")
    u = users().get(name)
    if not u or not verify_password(body.password, u.get("password") or ""):
        with _lock:
            _fails.setdefault(name, []).append(now)
        raise HTTPException(401, "账号或密码不正确")
    with _lock:
        _fails.pop(name, None)
    response.set_cookie(COOKIE, issue(name), max_age=TTL_S, httponly=True, samesite="lax")
    return {"username": name, "name": u.get("name") or name, "role": u.get("role") or "reader"}


@router.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/api/auth/me")
def me(request: Request):
    u = current(request)
    return {**u, "role_name": ROLES.get(u["role"], u["role"]), "auth": enabled()}
