"""清空运行数据，重新开始端到端验证（先备份，不直接删除）。

  .venv\\Scripts\\python.exe tools/reset_runtime.py [--yes]

移入 .runtime/backup/reset-<时间>/：任务与审查记录（store/）、资料中心（resource/）、审查报告（reports/）、
规则配置（rules/）、本地事项（cases/ 与真实材料底稿 cases_src/）。
保留：天眼查查询缓存（共享账号，额度有限；迁回新库的 external_cache）、法规知识库索引（knowledge/）、
完整性签名密钥（secret.key）、调试 Chrome 配置与摸底产物。
工作台（8090）与资料中心（8091）必须先停止。
"""
from __future__ import annotations

import shutil
import socket
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import DB_PATH, RC_DB_PATH, REPORTS, RUNTIME, STORE  # noqa: E402

MOVE = [STORE, RC_DB_PATH.parent, REPORTS, RUNTIME / "rules", RUNTIME / "cases", RUNTIME / "cases_src"]


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main(yes: bool) -> int:
    busy = [p for p in (8090, 8091) if _listening(p)]
    if busy:
        print(f"端口 {busy} 仍在监听，请先停止工作台 / 资料中心服务")
        return 1
    dest = RUNTIME / "backup" / time.strftime("reset-%Y%m%d-%H%M%S")
    todo = [p for p in MOVE if p.exists()]
    print("将移入", dest)
    for p in todo:
        print("  ", p.relative_to(RUNTIME))
    if not yes and input("确认？[y/N] ").strip().lower() != "y":
        return 1
    cache = []
    for path in (DB_PATH, RC_DB_PATH):
        if not path.exists():
            continue
        db = sqlite3.connect(str(path))
        try:
            if path == DB_PATH and db.execute("SELECT 1 FROM sqlite_master WHERE name='external_cache'").fetchone():
                cols = [r[1] for r in db.execute("PRAGMA table_info(external_cache)")]
                cache = [cols, db.execute("SELECT * FROM external_cache").fetchall()]
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            db.close()  # 连接未关闭时 Windows 不允许移动所在目录
    dest.mkdir(parents=True)
    for p in todo:
        p.rename(dest / p.relative_to(RUNTIME))
    if cache and cache[1]:
        from core.storage import Store

        Store(DB_PATH)._db.close()  # 建新库
        db = sqlite3.connect(str(DB_PATH))
        try:
            with db:
                db.executemany(f"INSERT OR REPLACE INTO external_cache ({','.join(cache[0])}) "
                               f"VALUES ({','.join('?' * len(cache[0]))})", cache[1])
        finally:
            db.close()
    print(f"完成：已备份到 {dest}；迁回天眼查缓存 {len(cache[1]) if cache else 0} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--yes" in sys.argv))
