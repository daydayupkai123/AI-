"""命令行运行财务报销初审数字员工。

  .venv\\Scripts\\python.exe -m employees.reimburse.run DEMO-BX-001 --source local   # 本地事项
  .venv\\Scripts\\python.exe -m employees.reimburse.run <单据编码>                    # 通财云（待摸底打通）
"""
from __future__ import annotations

import sys

from core.cli import main

from .graph import SOURCES, run

if __name__ == "__main__":
    sys.exit(main("财务报销初审", run, SOURCES, sys.argv[1:]))
