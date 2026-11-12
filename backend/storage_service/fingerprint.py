"""材料指纹：只依赖表单字段与附件清单（无需下载），资料中心快照与数字员工取单用同一个函数计算。

附件被替换（客户文件 id 或版本变化）或表单字段变化 → 指纹变化 → 触发自动重审。
config/collect.yaml 的 fingerprint.ignore_fields 可排除随审批推进而变化、与审查无关的字段（如审批意见）。
"""
from __future__ import annotations

import hashlib
import re

from shared.signing import canonical


def _ignore_patterns() -> list[str]:
    from . import settings

    return list((settings.collect().get("fingerprint") or {}).get("ignore_fields") or [])


def material_fp(fields: list[dict], attachments: list[dict], ignore: list[str] | None = None) -> str:
    pats = _ignore_patterns() if ignore is None else ignore
    keep = [(str(f.get("label") or ""), str(f.get("display") if f.get("display") is not None else f.get("value") or ""))
            for f in fields if not any(re.search(p, str(f.get("label") or "")) for p in pats)]
    atts = [(str(a.get("field_key") or ""), str(a.get("image_file_id") or ""), str(a.get("version_id") or ""),
             str(a.get("filename") or "")) for a in attachments]
    return hashlib.sha256(canonical([sorted(keep), sorted(atts)])).hexdigest()


def of_request(req) -> str:
    from dataclasses import asdict

    return material_fp(req.fields, [asdict(a) for a in req.attachments])
