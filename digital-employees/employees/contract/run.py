"""命令行运行合同审核数字员工。

  .venv\\Scripts\\python.exe -m employees.contract.run <requestid>              # 合同管理系统（需调试 Chrome 已登录门户）
  .venv\\Scripts\\python.exe -m employees.contract.run DEMO-HT-001 --source local   # 本地事项
"""
from __future__ import annotations

import sys

from core.cli import main

from .graph import SOURCES, run

if __name__ == "__main__":
    sys.exit(main("合同审核", run, SOURCES, sys.argv[1:]))
