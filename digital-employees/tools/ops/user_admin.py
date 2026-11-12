"""工作台账号管理（写到 config/users.local.yaml，不入库）。

  .venv\\Scripts\\python.exe tools/ops/user_admin.py list
  .venv\\Scripts\\python.exe tools/ops/user_admin.py set <用户名> <姓名> <角色> <密码>
      角色：admin / reviewer / reader
  .venv\\Scripts\\python.exe tools/ops/user_admin.py remove <用户名>
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from workbench_service.auth import ROLES, USERS_PATH, hash_password  # noqa: E402


def load() -> dict:
    return (yaml.safe_load(USERS_PATH.read_text(encoding="utf-8")) or {}) if USERS_PATH.exists() else {}


def save(data: dict) -> None:
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    USERS_PATH.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"已写入 {USERS_PATH}")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("list", "set", "remove"):
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    data = load()
    users = data.setdefault("users", {})
    if cmd == "list":
        if not users:
            print("(空)")
            return
        for name, u in users.items():
            print(f"{name}\t{u.get('name')}\t{u.get('role')}\t{ROLES.get(u.get('role'), '')}")
        return
    if cmd == "remove":
        users.pop(sys.argv[2], None)
        save(data)
        return
    if len(sys.argv) != 6:
        raise SystemExit(__doc__)
    username, name, role, password = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
    if role not in ROLES:
        raise SystemExit(f"角色只能是 {', '.join(ROLES)}")
    users[username] = {"name": name, "role": role, "password": hash_password(password)}
    save(data)


if __name__ == "__main__":
    main()
