from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # 项目根：config/ frontend/ .runtime/ 所在目录
RUNTIME = Path(os.environ.get("DE_RUNTIME", str(ROOT / ".runtime")))
STORE = RUNTIME / "store"
DB_PATH = Path(os.environ.get("DE_DB_PATH", str(STORE / "de.sqlite3")))
RC_DB_PATH = Path(os.environ.get("DE_RC_DB_PATH", str(RUNTIME / "resource" / "resource.sqlite3")))
REPORTS = RUNTIME / "reports"

OCR_WORKERS = int(os.environ.get("DE_OCR_WORKERS", str(max(1, min(8, (os.cpu_count() or 4) // 2)))))
OCR_THREADS_PER_WORKER = int(os.environ.get("DE_OCR_THREADS", "2"))
OCR_DPI = int(os.environ.get("DE_OCR_DPI", "150"))
PDF_TEXT_MIN_CHARS = 30  # 每页文字少于此值即视为扫描页，走 OCR

CDP_URL = os.environ.get("DE_CDP_URL", "http://127.0.0.1:9222")
CONTRACT_BASE = os.environ.get("DE_CONTRACT_BASE", "https://contract.gt.cn")


def hmac_key() -> bytes:
    """完整性签名密钥：生产从环境变量注入；开发期在 .runtime 下生成一次。"""
    env = os.environ.get("DE_HMAC_KEY")
    if env:
        return env.encode("utf-8")
    path = RUNTIME / "secret.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip().encode("utf-8")
