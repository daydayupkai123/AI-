"""执行档案入档前脱敏（只作用于档案，不影响规则判断）。

- 身份证号：18 位且校验位正确 → 保留前 3 后 4 位
- 手机号：1 开头 11 位（前后不接数字）→ 保留前 3 后 4 位
- 银行卡 / 账号：出现在「卡号、账号、帐号、开户、账户」字样后 20 字内的 12–19 位数字 → 保留前 3 后 4 位
- 地址中的令牌参数（authStr、authSignatureStr、ticket、v、token 等）→ ***
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SECRET_PARAMS = {"authstr", "authsignaturestr", "ticket", "v", "token", "access_token", "signaturesecretkey",
                 "signatureattributesstr", "sessionkey", "password", "pwd", "csrftoken", "_key"}
_W = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
_ID_RE = re.compile(r"(?<![0-9A-Za-z])(\d{17}[\dXx])(?![0-9A-Za-z])")
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_CARD_RE = re.compile(r"((?:卡号|账号|帐号|开户[行账号]*|账户|银行账户)[^\d\n]{0,20})(\d[\d ]{10,22}\d)")


def _keep(s: str, head: int = 3, tail: int = 4) -> str:
    return s[:head] + "*" * max(0, len(s) - head - tail) + s[-tail:]


def _id_ok(s: str) -> bool:
    if not re.fullmatch(r"\d{17}[\dXx]", s):
        return False
    total = sum(int(c) * w for c, w in zip(s[:17], _W))
    return "10X98765432"[total % 11] == s[17].upper()


def mask_text(s: str) -> str:
    if not s or not isinstance(s, str):
        return s
    s = _ID_RE.sub(lambda m: _keep(m.group(1)) if _id_ok(m.group(1)) else m.group(1), s)
    s = _PHONE_RE.sub(lambda m: _keep(m.group(1)), s)

    def card(m):
        digits = m.group(2).replace(" ", "")
        if 12 <= len(digits) <= 19:
            return m.group(1) + _keep(digits)
        return m.group(0)

    return _CARD_RE.sub(card, s)


_LONG_DIGITS_RE = re.compile(r"(?<![\d.,])(\d{15,19})(?![\d.,])")


def sensitive_spans(s: str) -> list[tuple[int, int]]:
    """敏感信息在文本中的位置（截图打码用）：身份证号、手机号、账号字样后的卡号，以及单独出现的 15–19 位数字
    （页面上「银行账号」标签与号码常分处两个元素）。"""
    if not s:
        return []
    spans = [m.span(1) for m in _ID_RE.finditer(s) if _id_ok(m.group(1))]
    spans += [m.span(1) for m in _PHONE_RE.finditer(s)]
    spans += [m.span(2) for m in _CARD_RE.finditer(s) if 12 <= len(m.group(2).replace(" ", "")) <= 19]
    spans += [m.span(1) for m in _LONG_DIGITS_RE.finditer(s)]
    merged: list[list[int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def mask_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    q = [(k, "***" if k.lower() in SECRET_PARAMS else mask_text(v)) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit(parts._replace(query=urlencode(q, safe="*")))


def mask_obj(obj, depth: int = 0):
    """递归脱敏 JSON 结构；键名像密钥的值整体替换。"""
    if depth > 30:
        return obj
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, list):
        return [mask_obj(x, depth + 1) for x in obj]
    if isinstance(obj, dict):
        return {k: ("***" if str(k).lower() in SECRET_PARAMS and isinstance(v, str) and v else mask_obj(v, depth + 1))
                for k, v in obj.items()}
    return obj
