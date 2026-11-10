"""制度知识库：按 config/regulations.yaml 加载已启用制度，解析结果按「文件内容签名 + 解析器版本」缓存。

- documents()：每份制度的状态（已登记 / 文件缺失 / 解析失败 / 已启用）与条款数
- lookup()：按制度 + 部门 + 项号精确定位条款（含各金额档位）
- search()：按事项描述检索（字符二元组 TF-IDF），返回带分数的条款
- refs_in()：从「审批/上会依据」等人工填写文本中识别引用的制度、部门、项号
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import yaml

from ..config import ROOT, RUNTIME
from .regulations import PARSER_VER, PARSERS, Clause

CONFIG = ROOT / "config" / "regulations.yaml"
CACHE = RUNTIME / "knowledge"

ALIASES = {
    "authority_manual": ["权责手册"],
    "major_items": ["重大经营管理事项清单", "重大经营管理事项"],
    "party_items": ["党委决定的重大事项清单", "党委决定的重大事项", "党委会决定事项"],
    "board_authorization": ["董事会授权决策方案", "授权决策方案", "董事会授权方案"],
}
DEPTS = ["综合管理部", "运营管理部", "科技质量部", "财务管理部"]


def _bigrams(s: str) -> list[str]:
    s = re.sub(r"[\s\W_]+", "", s or "")
    return [s[i:i + 2] for i in range(len(s) - 1)]


class RegulationBase:
    def __init__(self, docs: list[dict], clauses: list[Clause]):
        self.docs = docs
        self.clauses = clauses
        self._tf = [Counter(_bigrams(c.text)) for c in clauses]
        df = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = max(1, len(clauses))
        self._idf = {g: math.log((n + 1) / (k + 0.5)) for g, k in df.items()}
        self._norm = [math.sqrt(sum((v * self._idf[g]) ** 2 for g, v in tf.items())) or 1.0 for tf in self._tf]

    # ------------------------------------------------------------ 查询
    def documents(self) -> list[dict]:
        return [{k: d.get(k) for k in ("id", "name", "kind", "enabled", "state", "clauses", "sig", "warnings", "error")}
                for d in self.docs]

    def doc_name(self, doc_id: str) -> str:
        return next((d["name"] for d in self.docs if d["id"] == doc_id), doc_id)

    def lookup(self, doc_id: str | None = None, dept: str | None = None, no: int | None = None) -> list[Clause]:
        return [c for c in self.clauses if (doc_id is None or c.doc_id == doc_id)
                and (dept is None or c.dept == dept) and (no is None or c.no == no)]

    def search(self, query: str, top_k: int = 8, doc_ids: list[str] | None = None) -> list[tuple[float, Clause]]:
        q = Counter(_bigrams(query))
        qn = math.sqrt(sum((v * self._idf.get(g, 0)) ** 2 for g, v in q.items())) or 1.0
        scored = []
        for i, c in enumerate(self.clauses):
            if doc_ids and c.doc_id not in doc_ids:
                continue
            dot = sum(v * self._idf.get(g, 0) * self._tf[i].get(g, 0) * self._idf.get(g, 0) for g, v in q.items())
            if dot > 0:
                scored.append((round(dot / (qn * self._norm[i]), 4), c))
        scored.sort(key=lambda x: -x[0])
        seen, out = set(), []
        for s, c in scored:
            key = (c.doc_id, c.dept, c.no)
            if key in seen:
                continue
            seen.add(key)
            out.append((s, c))
            if len(out) >= top_k:
                break
        return out

    @staticmethod
    def refs_in(text: str) -> list[dict]:
        """识别文本中的制度引用：[{doc_id, dept, no, raw}]；未写明项号的只给 doc_id。"""
        t = re.sub(r"\s+", "", text or "")
        out = []
        for doc_id, names in ALIASES.items():
            for name in names:
                for m in re.finditer(re.escape(name), t):
                    tail = t[m.end():m.end() + 60]
                    dept = next((d for d in DEPTS if d in tail[:30]), None)
                    no = re.search(r"第([0-9]+|[一二三四五六七八九十百]+)[项条]", tail)
                    out.append({"doc_id": doc_id, "dept": dept, "no": _to_int(no.group(1)) if no else None,
                                "raw": t[max(0, m.start() - 4):m.end() + (no.end() if no else 20)]})
                if any(o["doc_id"] == doc_id for o in out):
                    break
        uniq, seen = [], set()
        for o in out:
            k = (o["doc_id"], o["dept"], o["no"])
            if k not in seen:
                seen.add(k)
                uniq.append(o)
        return uniq


def _to_int(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    from ..rules.common import _cn_int  # noqa: PLC0415

    return _cn_int(s) or None


# ------------------------------------------------------------------ 加载与缓存

_lock = threading.Lock()
_loaded: dict = {"key": None, "base": None}


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (ROOT / p).resolve()


def load(config_path: Path = CONFIG, cache_dir: Path = CACHE) -> RegulationBase:
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    docs, clauses = [], []
    cache_dir.mkdir(parents=True, exist_ok=True)
    for d in cfg.get("documents") or []:
        info = {**d, "state": "registered", "clauses": 0, "warnings": [], "error": None, "sig": None}
        docs.append(info)
        path = _resolve(d["path"])
        if not path.exists():
            info.update(state="missing", error=f"文件不存在：{path}")
            continue
        data = path.read_bytes()
        sig = hashlib.sha256(data).hexdigest()
        info["sig"] = sig[:16]
        cache = cache_dir / f"{d['id']}-{sig[:16]}-v{PARSER_VER}.json"
        try:
            if cache.exists():
                body = json.loads(cache.read_text(encoding="utf-8"))
            else:
                parsed, warns = PARSERS[d["kind"]](data, d["id"], d["name"])
                body = {"clauses": [asdict(c) for c in parsed], "warnings": warns}
                cache.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            info.update(state="failed", error=f"{type(exc).__name__}: {exc}")
            continue
        items = [Clause(**c) for c in body["clauses"]]
        info.update(state="enabled" if d.get("enabled", True) else "disabled", clauses=len(items),
                    warnings=body.get("warnings", [])[:20])
        if d.get("enabled", True):
            clauses.extend(items)
    return RegulationBase(docs, clauses)


def get_base() -> RegulationBase:
    """进程内复用；配置文件或任一制度文件变化后自动重新加载。"""
    cfg_text = CONFIG.read_text(encoding="utf-8")
    cfg = yaml.safe_load(cfg_text) or {}
    stamps = [cfg_text]
    for d in cfg.get("documents") or []:
        p = _resolve(d["path"])
        stamps.append(f"{p}:{p.stat().st_mtime if p.exists() else 0}")
    key = hashlib.sha256("|".join(stamps).encode("utf-8")).hexdigest()
    with _lock:
        if _loaded["key"] != key:
            _loaded["base"], _loaded["key"] = load(), key
        return _loaded["base"]
